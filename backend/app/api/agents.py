from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.llm.base import LLMProvider
from app.llm.factory import get_provider
from app.memory.base import MemoryProvider
from app.memory.factory import get_memory_provider
from app.models import User

router = APIRouter(prefix="/api/agents", tags=["agents"])


class StudyPlanIn(BaseModel):
    goal: str = Field(min_length=3, max_length=1000)


@router.post("/study-plan")
async def study_plan(body: StudyPlanIn, user: User = Depends(get_current_user), llm: LLMProvider = Depends(get_provider), memory: MemoryProvider = Depends(get_memory_provider)) -> dict[str, object]:
    try:
        from app.agents.study_plan import build_study_plan_graph
        result = await build_study_plan_graph(llm, memory).ainvoke({"user_id": str(user.id), "goal": body.goal, "memories": [], "plan": ""})
    except Exception:
        raise HTTPException(503, "The planning assistant is unavailable. Please try again.") from None
    return {"plan": result["plan"], "memory_count": len(result["memories"])}
