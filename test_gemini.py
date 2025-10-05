import os
import re
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()  # .env'yi oku

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise SystemExit("GEMINI_API_KEY .env içinde yok!")

genai.configure(api_key=API_KEY)

def predict_prices_with_gemini(items):
    # Çıktıyı makinece okunur yapıyoruz: sadece sayılar ve '||' ayraç
    prompt = (
        "Aşağıdaki ürünler için piyasa fiyat tahmini yap.\n"
        "Sadece sayıları yaz ve her tahmini '||' ile AYIR. Başka hiçbir şey yazma.\n"
        "Örnek çıktı: 320||28.5||290\n\n"
    )
    for it in items:
        prompt += f"- {it['title']} (mevcut: {it['price_value']} {it['price_currency']})\n"

    model = genai.GenerativeModel("gemini-2.5-flash")
    resp = model.generate_content(prompt)

    raw = (resp.text or "").strip()
    print("LLM cevabı ham:", raw)

    # 1) Tercihen '||' ile böl
    parts = [p.strip() for p in raw.split("||")] if "||" in raw else []

    # 2) Güvenli parse: sayı dışı karakterleri ayıkla, nokta/virgül normalize et
    preds = []
    source = parts if parts else re.findall(r"[\d.,]+", raw)
    for p in source:
        p = p.replace(",", ".")  # 28,5 -> 28.5
        try:
            preds.append(float(p))
        except ValueError:
            pass
    return preds

if __name__ == "__main__":
    sample_items = [
        {"title": "iPhone 13", "price_value": 300, "price_currency": "USD"},
        {"title": "LEGO Star Wars Set", "price_value": 25, "price_currency": "USD"},
        {"title": "Sony WH-1000XM4 Headphones", "price_value": 280, "price_currency": "USD"},
    ]
    predictions = predict_prices_with_gemini(sample_items)
    print("Tahminler:", predictions)
