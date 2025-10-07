import os, time, re, json, requests
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
import google.generativeai as genai

# ------------------- Yüklemeler ve ortam -------------------
load_dotenv()
margin_rate=0 # fark yuzdesi
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("Uyarı: GEMINI_API_KEY yok; AI tahmini atlanacak.", flush=True)

DATABASE_URL = os.getenv("DATABASE_URL")
assert DATABASE_URL, "DATABASE_URL boş!"
engine = create_engine(DATABASE_URL, echo=False)
B=os.getenv('TEST_TOKEN')
EBAY_MARKETPLACE_ID = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_GB")
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")
assert EBAY_CLIENT_ID and EBAY_CLIENT_SECRET, "EBAY kimlik bilgileri eksik!"

# Telegram bilgileri
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or ""
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID") or ""

def _mask(s: str, keep: int = 6) -> str:
    if not s:
        return "<empty>"
    return s[:keep] + "…" if len(s) > keep else s

print(f"[Env] TELEGRAM_BOT_TOKEN={_mask(TELEGRAM_BOT_TOKEN)}", flush=True)
print(f"[Env] TELEGRAM_CHAT_ID={TELEGRAM_CHAT_ID or '<empty>'}", flush=True)


def send_telegram_message(text: str):
    """Basit Telegram gönderici."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] token veya chat_id yok, mesaj atlanıyor.", flush=True)
        return
    if not TELEGRAM_CHAT_ID:
        print("[Telegram] TELEGRAM_CHAT_ID yok! Mesaj atlanıyor.", flush=True)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"[Telegram] hata: {r.text}", flush=True)
    except Exception as e:
        print(f"[Telegram] gönderim hatası: {e}", flush=True)

# ------------------- DB yapısı -------------------
DDL = """
CREATE TABLE IF NOT EXISTS public.ebay_items (
  item_id TEXT PRIMARY KEY,
  title TEXT,
  price_value NUMERIC,
  price_currency TEXT,
  item_href TEXT,
  seller_username TEXT,
  condition_display_name TEXT,
  category_id TEXT,
  category_name TEXT,
  brand TEXT,
  last_seen_utc TIMESTAMP,
  ai_price_estimate NUMERIC
);
"""

UPSERT_SQL = """
INSERT INTO public.ebay_items (
  item_id, title, price_value, price_currency, item_href, seller_username,
  condition_display_name, category_id, category_name, brand, last_seen_utc,
  ai_price_estimate
) VALUES (
  :item_id, :title, :price_value, :price_currency, :item_href, :seller_username,
  :condition_display_name, :category_id, :category_name, :brand, :last_seen_utc,
  :ai_price_estimate
)
ON CONFLICT (item_id) DO UPDATE SET
  title = EXCLUDED.title,
  price_value = EXCLUDED.price_value,
  price_currency = EXCLUDED.price_currency,
  item_href = EXCLUDED.item_href,
  seller_username = EXCLUDED.seller_username,
  condition_display_name = EXCLUDED.condition_display_name,
  category_id = EXCLUDED.category_id,
  category_name = EXCLUDED.category_name,
  brand = EXCLUDED.brand,
  last_seen_utc = EXCLUDED.last_seen_utc,
  ai_price_estimate = EXCLUDED.ai_price_estimate;
"""

def ensure_schema():
    with engine.begin() as conn:
        conn.execute(text(DDL))


# ------------------- eBay API -------------------
def get_access_token() -> str:
    url = "https://api.ebay.com/identity/v1/oauth2/token"
    data = {"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = requests.post(url, data=data, auth=(EBAY_CLIENT_ID, EBAY_CLIENT_SECRET), headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]

def flatten_item(it: dict) -> dict:
    price = it.get("price") or {}
    seller = it.get("seller") or {}
    cats = it.get("categories") or []
    first_c = cats[0] if cats else {}
    cond = it.get("conditionDisplayName") or it.get("condition")
    return {
        "item_id": it.get("itemId"),
        "title": it.get("title"),
        "price_value": (price.get("value") if isinstance(price, dict) else None),
        "price_currency": (price.get("currency") if isinstance(price, dict) else None),
        "item_href": it.get("itemHref"),
        "seller_username": seller.get("username"),
        "condition_display_name": cond if isinstance(cond, str) else None,
        "category_id": first_c.get("categoryId"),
        "category_name": first_c.get("categoryName"),
        "brand": it.get("brand"),
        "last_seen_utc": datetime.now(timezone.utc).replace(tzinfo=None),
        "ai_price_estimate": None,
    }

def upsert_items(rows: list[dict]):
    if not rows:
        return
    with engine.begin() as conn:
        for r in rows:
            conn.execute(text(UPSERT_SQL), r)

def search_items(access_token: str, query: dict) -> list[dict]:
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID
    }
    r = requests.get(url, headers=headers, params=query, timeout=30)
    r.raise_for_status()
    return r.json().get("itemSummaries", []) or []


# ------------------- Gemini fiyat tahmini -------------------
def predict_prices_with_gemini(items: list[dict]) -> list[float | None]:
    if not GEMINI_API_KEY or not items:
        return [None] * len(items)

    prompt = "Aşağıdaki ürünler için piyasa fiyat tahmini yap.\n" \
             "Sadece rakam yaz ve her tahmini '||' ile ayır. Başka hiçbir şey yazma.\n"
    for it in items:
        title = it.get("title")
        pv = it.get("price_value")
        pc = it.get("price_currency")
        prompt += f"- {title} (mevcut: {pv} {pc})\n"

    model = genai.GenerativeModel("models/gemini-2.5-flash")
    resp = model.generate_content(prompt)
    raw = (getattr(resp, "text", "") or "").strip()

    cands = raw.split("||") if "||" in raw else re.findall(r"[-+]?\d+(?:[.,]\d+)?", raw)
    preds: list[float | None] = []
    for s in cands:
        s = s.strip().replace(",", ".")
        try:
            preds.append(float(s))
        except ValueError:
            preds.append(None)

    if len(preds) < len(items):
        preds += [None] * (len(items) - len(preds))
    return preds[:len(items)]


# ------------------- İşler -------------------
def job_ingest_ebay():
    print("[Ingest] started", flush=True)
    ensure_schema()
    token = get_access_token()

    with open("queries.json", "r", encoding="utf-8") as f:
        queries = json.load(f)

    total = 0
    for q in queries:
        try:
            print(f"Arama: {q}", flush=True)
            items = search_items(token, q)
            rows = [flatten_item(it) for it in items if it.get("itemId")]
            upsert_items(rows)
            print(f"Kaydedilen: {len(rows)}", flush=True)
            total += len(rows)
            time.sleep(0.5)
        except Exception as e:
            print(f"[Ingest] hata: {e}", flush=True)
    print(f"[Ingest] done, upsert={total}", flush=True)


def job_predict_prices():
    if not GEMINI_API_KEY:
        print("[AI] GEMINI_API_KEY yok; atlandı.", flush=True)
        return

    print("[AI] started", flush=True)
    batch = 20
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT item_id, title, price_value, price_currency, item_href, seller_username,
                   condition_display_name, category_id, category_name, brand, last_seen_utc,
                   ai_price_estimate
            FROM public.ebay_items
            ORDER BY (ai_price_estimate IS NULL) DESC, last_seen_utc DESC
            LIMIT 200
        """)).mappings().all()

    for i in range(0, len(rows), batch):
        subset = [dict(r) for r in rows[i:i+batch]]
        preds = predict_prices_with_gemini(subset)
        for r, p in zip(subset, preds):
            r["ai_price_estimate"] = p
        try:
            upsert_items(subset)
            print(f"[AI] upsert {len(subset)} kayıt", flush=True)

            # --- Telegram uyarısı kontrolü ---
            for r in subset:
                pv = r.get("price_value")
                ai = r.get("ai_price_estimate")
                if pv and ai:
                    try:
                        pv = float(pv)
                        ai = float(ai)
                        if ai >= pv * margin_rate:
                            fark = (ai / pv - 1) * 100
                            msg = (
                                f"🔥 <b>Fiyat Uyarısı</b>\n\n"
                                f"<b>{r.get('title')}</b>\n"
                                f"Gerçek fiyat: <b>{pv:.2f}</b>\n"
                                f"Tahmini değer: <b>{ai:.2f}</b>\n"
                                f"Fark: <b>{fark:.1f}%</b>\n"
                                f"🔗 <a href='{r.get('item_href')}'>Ürünü Gör</a>"
                            )
                            send_telegram_message(msg)
                    except Exception as e:
                        print(f"[WarnCheck] hata: {e}", flush=True)

        except Exception as e:
            print(f"[AI] upsert hata: {e}", flush=True)
        time.sleep(1)

    print("[AI] done", flush=True)


def main():
    ensure_schema()
    send_telegram_message("🧪 Bot bağlandı: başlangıç testi")

    sched = BlockingScheduler(timezone="UTC")

    sched.add_job(job_ingest_ebay, "interval", minutes=30, id="ingest")
    sched.add_job(job_predict_prices, "interval", minutes=30, id="ai")

    job_ingest_ebay()
    job_predict_prices()

    print("[Scheduler] running (every 30 min)", flush=True)
    sched.start()


if __name__ == "__main__":
    main()

