import json
from datetime import datetime, timezone
from sqlalchemy import create_engine, text

engine = create_engine("sqlite:///workshop.db", echo=False)

# 1) Tabloyu oluştur (yoksa)
ddl = """
CREATE TABLE IF NOT EXISTS ebay_items (
    item_id TEXT PRIMARY KEY,
    title TEXT,
    price_value REAL,
    price_currency TEXT,
    item_href TEXT,
    seller_username TEXT,
    condition_display_name TEXT,
    category_id TEXT,
    category_name TEXT,
    brand TEXT,
    last_seen_utc TEXT
);
"""
with engine.begin() as conn:
    conn.execute(text(ddl))

# 2) JSON'u oku
with open("items_sample.json", "r", encoding="utf-8") as f:
    items = json.load(f)

# 3) Düzleştirme (nested -> flat)
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
        "last_seen_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }

rows = [flatten_item(it) for it in items]

# 4) Upsert
upsert_sql = """
INSERT INTO ebay_items (
    item_id, title, price_value, price_currency, item_href, seller_username,
    condition_display_name, category_id, category_name, brand, last_seen_utc
) VALUES (
    :item_id, :title, :price_value, :price_currency, :item_href, :seller_username,
    :condition_display_name, :category_id, :category_name, :brand, :last_seen_utc
)
ON CONFLICT(item_id) DO UPDATE SET
    title=excluded.title,
    price_value=excluded.price_value,
    price_currency=excluded.price_currency,
    item_href=excluded.item_href,
    seller_username=excluded.seller_username,
    condition_display_name=excluded.condition_display_name,
    category_id=excluded.category_id,
    category_name=excluded.category_name,
    brand=excluded.brand,
    last_seen_utc=excluded.last_seen_utc;
"""
with engine.begin() as conn:
    for r in rows:
        conn.execute(text(upsert_sql), r)

# 5) Kontrol için oku
with engine.begin() as conn:
    res = conn.execute(text("SELECT item_id, title, price_value FROM ebay_items ORDER BY item_id"))
    for row in res.mappings():
        print(dict(row))
