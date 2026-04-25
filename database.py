"""
database.py — SQLAlchemy models and DB session management.

Supports:
  - SQLite   (local dev, zero-config, default)
  - PostgreSQL (Docker / production, set DATABASE_URL env var)

Resume claim: "PostgreSQL for persistent usage and cost data"
"""

import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

# Default to SQLite for frictionless local development.
# In Docker, DATABASE_URL is set to postgresql://... via docker-compose.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./gateway.db"
)

# SQLite needs check_same_thread=False; PostgreSQL does not support that arg.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────

class TokenUsage(Base):
    """Persists every LLM call with tokens consumed and estimated cost."""
    __tablename__ = "token_usage"

    id = Column(Integer, primary_key=True, index=True)
    department = Column(String, index=True)
    model = Column(String)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    estimated_cost = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=datetime.utcnow)


class APIKey(Base):
    """Maps API keys to departments with budget limits."""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    department = Column(String)
    role = Column(String, default="standard")
    budget_limit = Column(Float, default=5.0)


# Create tables on startup (idempotent)
Base.metadata.create_all(bind=engine)


# ─────────────────────────────────────────────────────────────────────────────
# Seed Data
# ─────────────────────────────────────────────────────────────────────────────

def seed_db():
    """Insert default API keys if the table is empty."""
    db = SessionLocal()
    try:
        if db.query(APIKey).count() == 0:
            db.add_all([
                APIKey(key="sk-eng-1234",  department="Engineering", role="admin",    budget_limit=5.0),
                APIKey(key="sk-eng-1235",  department="Engineering", role="standard", budget_limit=5.0),
                APIKey(key="sk-mkt-5678",  department="Marketing",   role="standard", budget_limit=5.0),
                APIKey(key="sk-hr-9999",   department="HR",          role="standard", budget_limit=2.0),
                APIKey(key="sk-fin-4321",  department="Finance",     role="admin",    budget_limit=10.0),
            ])
            db.commit()
            print("[DB] Seeded default API keys for Engineering, Marketing, HR, Finance.")
    finally:
        db.close()


seed_db()


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI Dependency
# ─────────────────────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
