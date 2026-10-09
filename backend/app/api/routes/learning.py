from fastapi import APIRouter

from app.api.deps import LearningEngineDep
from app.schemas.learning import LearningReport

router = APIRouter(prefix="/learning", tags=["learning"])


@router.get("/report", response_model=LearningReport)
def recorded_learning_report(engine: LearningEngineDep) -> LearningReport:
    """RECORDED-only insights from the stored synthetic dataset. Read-only and deterministic; simulated
    outcomes are never mixed in (see GET /requests/{request_code}/learning for those)."""
    return engine.recorded_report()
