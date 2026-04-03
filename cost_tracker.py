from sqlalchemy.orm import Session
from database import TokenUsage

def log_usage(db: Session, department: str, model: str, prompt_tokens: int, completion_tokens: int, total_tokens: int, estimated_cost: float):
    if not department:
        department = "Unknown"
        
    usage_entry = TokenUsage(
        department=department,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost=estimated_cost
    )
    db.add(usage_entry)
    db.commit()
    db.refresh(usage_entry)
    return usage_entry

def get_department_stats(db: Session):
    from sqlalchemy import func
    stats = db.query(
        TokenUsage.department,
        func.sum(TokenUsage.total_tokens).label('total_tokens'),
        func.sum(TokenUsage.estimated_cost).label('total_cost')
    ).group_by(TokenUsage.department).all()
    
    return [
        {
            "department": s.department, 
            "total_tokens": s.total_tokens, 
            "total_cost": round(s.total_cost, 6) if s.total_cost else 0.0
        }
        for s in stats
    ]

def check_budget_exceeded(db: Session, department: str, limit: float) -> bool:
    from sqlalchemy import func
    total_cost = db.query(func.sum(TokenUsage.estimated_cost)).filter(TokenUsage.department == department).scalar()
    if total_cost is None:
        total_cost = 0.0
    return total_cost >= limit

