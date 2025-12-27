# db.py
import psycopg2
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME

Base = declarative_base()

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:5432/{DB_NAME}?sslmode=require"

engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,       
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def connect_postgres():
    try:
        cnx = psycopg2.connect(
            user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=5432, database=DB_NAME, sslmode="require"
        )
        print("Connected to PostgreSQL successfully!")
        cursor = cnx.cursor()
        cursor.execute("SELECT version();")
        print("Database version:", cursor.fetchone()[0])
        cursor.close()
        return cnx
    except Exception as e:
        print(f"PostgreSQL connection error: {e}")
        raise
