"""年度目标相关API"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models import get_db, AnnualGoal

router = APIRouter()


@router.get("/goals")
def list_goals(year: int = 2026, db: Session = Depends(get_db)):
    goals = db.query(AnnualGoal).filter(AnnualGoal.year == year).all()
    return [
        {
            "id": g.id, "name": g.name, "weight": g.weight,
            "category": g.category, "kpis": g.kpis, "year": g.year
        }
        for g in goals
    ]
