import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///./gateway.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class TokenUsage(Base):
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
    __tablename__ = "api_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    department = Column(String)
    role = Column(String, default="standard")
    budget_limit = Column(Float, default=5.0)

Base.metadata.create_all(bind=engine)

def seed_db():
    db = SessionLocal()
    try:
        if db.query(APIKey).count() == 0:
            db.add_all([
                APIKey(key="sk-eng-1234", department="Engineering", role="admin", budget_limit=5.0),
                APIKey(key="sk-eng-1235", department="Marketing", role="admin", budget_limit=5.0),
                APIKey(key="sk-mkt-5678", department="Marketing", role="standard", budget_limit=5.0)
            ])
            db.commit()
    finally:
        db.close()

seed_db()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
