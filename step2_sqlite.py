from sqlalchemy import create_engine, text

engine = create_engine("sqlite:///workshop.db", echo=False)

# Tablo (sku birincil anahtar)
ddl = """
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    title TEXT,
    price REAL
);
"""
with engine.begin() as conn:
    conn.execute(text(ddl))

# Upsert SQL (SQLite ve Postgres'te çalışır)
upsert_sql = """
INSERT INTO products (sku, title, price) VALUES (:sku, :title, :price)
ON CONFLICT(sku) DO UPDATE SET
    title=excluded.title,
    price=excluded.price;
"""

with engine.begin() as conn:
    # İlk ekleme
    conn.execute(text(upsert_sql), {"sku": "A1", "title": "Kulaklık", "price": 100})
    # Aynı anahtarla güncelleme
    conn.execute(text(upsert_sql), {"sku": "A1", "title": "Kulaklık PRO", "price": 120})

# Kontrol
with engine.begin() as conn:
    row = conn.execute(text("SELECT * FROM products WHERE sku='A1'")).mappings().first()
    print(dict(row))
