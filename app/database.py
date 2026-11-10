
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:password@localhost:5432/kanko_db"
)

engine = create_engine(DATABASE_URL)

# 実際に使用しているDB接続先をログに表示
# パスワードは表示しない
print(
    "WITHLOG DB CONNECTION:",
    "host=", engine.url.host,
    "database=", engine.url.database,
    flush=True
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
