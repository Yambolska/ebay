import os
import json
import time
import requests
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from datetime import datetime, timezone
import re
import google.generativeai as genai
from sqlalchemy.orm import declarative_base

Base = declarative_base()

# tablo sınıfların buraya (ör: EbayItem)




load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("Uyarı: GEMINI_API_KEY yok, AI tahmini yapılmayacak.")

DATABASE_URL = os.getenv("DATABASE_URL")
EBAY_MARKETPLACE_ID = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_GB")
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")

assert DATABASE_URL, "DATABASE_URL boş!"
assert EBAY_CLIENT_ID and EBAY_CLIENT_SECRET, "EBAY kimlik bilgileri eksik!"

engine = create_engine(DATABASE_URL, echo=False)

def predict_prices_with_gemini(items: list[dict]) -> list[float]:
    """
    items: flatten edilmiş satırlar (title, price_value, price_currency alanları var)
    dönüş: her item için 1 float tahmin (uzunluk uyuşmazsa eksik olanlar None döner)
    """
    if not GEMINI_API_KEY:
        return [None] * len(items)

    # Prompt: tek satırda ayrıştırılabilir çıktı iste
    prompt = (
        "Aşağıdaki ürünler için piyasa fiyat tahmini yap. "
        "Sadece sayıları yaz ve her tahmini '||' ile AYIR. Başka hiçbir şey yazma.\n"
        "Örnek: 320||28.5||290\n\n"
    )
    for it in items:
        title = it.get("title")
        pv = it.get("price_value")
        pc = it.get("price_currency")
        prompt += f"- {title} (mevcut: {pv} {pc})\n"

    # model adı senin testinde çalıştığı gibi olsun:
    model = genai.GenerativeModel("models/gemini-2.5-flash")
    resp = model.generate_content(prompt)
    raw = (resp.text or "").strip()

    # Önce '||' ile böl, olmazsa regex fallback
    parts = [p.strip() for p in raw.split("||")] if "||" in raw else re.findall(r"[\d.,]+", raw)
    preds: list[float] = []
    for p in parts:
        p = p.replace(",", ".")
        try:
            preds.append(float(p))
        except ValueError:
            pass

    # uzunluk eşitle (fazlaysa kırp, azsa None ile doldur)
    if len(preds) < len(items):
        preds += [None] * (len(items) - len(preds))
    return preds[:len(items)]

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

def get_access_token() -> str:
    url = "https://api.ebay.com/identity/v1/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(url, data=data, auth=(EBAY_CLIENT_ID, EBAY_CLIENT_SECRET), headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def flatten_item(it: dict) -> dict:
    price = it.get("price") or {}
    seller = it.get("seller") or {}
    cats = it.get("categories") or []
    first_cat = cats[0] if cats else {}
    cond = it.get("conditionDisplayName") or it.get("condition")
    return {
        "item_id": it.get("itemId"),
        "title": it.get("title"),
        "price_value": price.get("value"),
        "price_currency": price.get("currency"),
        "item_href": it.get("itemHref"),
        "seller_username": seller.get("username"),
        "condition_display_name": cond if isinstance(cond, str) else None,
        "category_id": first_cat.get("categoryId"),
        "category_name": first_cat.get("categoryName"),
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

def run_once():
    """Tek seferlik: tabloyu hazırla → eBay'den çek → (opsiyonel) Gemini tahmini → DB'ye yaz."""
    # 2) Access token al
    try:
        token = get_access_token()
    except Exception as e:
        print(f"Token alınamadı: {e}", flush=True)
        return

    # 3) Sorguları yükle
    try:
        with open("queries.json", "r", encoding="utf-8") as f:
            queries = json.load(f)
    except Exception as e:
        print(f"queries.json okunamadı: {e}", flush=True)
        return

    total = 0
    batch_size = 20  # Gemini çağrıları için güvenli paket boyutu

    # 4) Her sorgu için çek → düzleştir → önce ham upsert (gerçek fiyatlar)
    for q in queries:
        print("Arama:", q, flush=True)

        try:
            items = search_items(token, q)
        except Exception as e:
            print(f"eBay API hatası: {e}", flush=True)
            continue

        rows = [flatten_item(it) for it in items if it.get("itemId")]

        if not rows:
            print("Bu sorguda item çıkmadı.", flush=True)
            continue

        # önce gerçek veriyi yaz (ai_price_estimate şimdilik None)
        try:
            upsert_items(rows)
            print("Kaydedilen:", len(rows), flush=True)
            total += len(rows)
        except Exception as e:
            print(f"DB upsert hatası (ham): {e}", flush=True)

        time.sleep(1)  # nazik bekleme

        # 5) GEMINI_API_KEY varsa tahminleri üret ve partiler halinde tekrar upsert et
        if GEMINI_API_KEY:
            for i in range(0, len(rows), batch_size):
                subset = rows[i:i + batch_size]
                try:
                    preds = predict_prices_with_gemini(subset)
                except Exception as e:
                    print(f"Gemini tahmin hatası: {e}", flush=True)
                    continue

                for r, p in zip(subset, preds):
                    r["ai_price_estimate"] = p

                try:
                    upsert_items(subset)
                except Exception as e:
                    print(f"DB upsert hatası (AI): {e}", flush=True)

                time.sleep(1)  # nazik bekleme

    print("Toplam upsert:", total, flush=True)



if __name__ == "__main__":
    run_once()
