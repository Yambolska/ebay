DATABASE_URL="postgresql+psycopg2://ebayuser:ebaypass@localhost:5432/ebaydb"
engine = create_engine(DATABASE_URL, echo=False)

with engine.begin() as conn:
        conn.execute(text(DDL))
        conn.execute(text("""
            select * from ebay_items
        """))