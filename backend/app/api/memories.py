from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.memory.base import MemoryItem, MemoryProvider
from app.memory.factory import get_memory_provider
from app.memory.sensitive import check_sensitive
from app.models import User
from app.repositories.messages import MessageRepository

router = APIRouter(prefix="/api/memories", tags=["memories"])


class MemoryOut(BaseModel):
    id: str
    text: str
    score: float | None = None
    created_at: str | None = None
    updated_at: str | None = None
    category: str | None = None
    importance: float | None = None
    status: str | None = None
    superseded_by: str | None = None
    supersedes: str | None = None


class VersionOut(BaseModel):
    content: str
    reason: str
    created_at: str


class MemoryEdit(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class DeleteAll(BaseModel):
    confirm: str  # must be exactly "DELETE"; a guard against accidental calls


def _out(m: MemoryItem) -> MemoryOut:
    return MemoryOut(id=m.id, text=m.text, score=m.score, created_at=m.created_at, updated_at=m.updated_at,
                     category=m.category, importance=m.importance, status=m.status,
                     superseded_by=m.superseded_by, supersedes=m.supersedes)


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    q: str | None = Query(None, min_length=1, max_length=200), limit: int = Query(50, ge=1, le=100),
    status: Literal["active", "pending", "superseded"] = "active",
    user: User = Depends(get_current_user), memory: MemoryProvider = Depends(get_memory_provider),
) -> list[MemoryOut]:
    uid = str(user.id)
    if status == "pending":
        return [_out(m) for m in await memory.list_pending(uid, limit=limit)]
    if status == "superseded":
        return [_out(m) for m in await memory.list_superseded(uid, limit=limit)]
    items = await memory.search(uid, q, top_k=limit) if q else await memory.list_all(uid, limit=limit)
    return [_out(m) for m in items]


@router.patch("/{memory_id}", response_model=MemoryOut)
async def edit_memory(memory_id: str, body: MemoryEdit, user: User = Depends(get_current_user),
                      memory: MemoryProvider = Depends(get_memory_provider)) -> MemoryOut:
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "Memory text can't be empty")
    if (reason := check_sensitive(text)) is not None:
        raise HTTPException(422, f"That looks like {reason}. MemoryAI doesn't store passwords, keys or ID numbers.")
    updated = await memory.update(str(user.id), memory_id, text)
    if updated is None:  # also what other users' IDs look like: 404, not 403
        raise HTTPException(404, "Memory not found")
    return _out(updated)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(memory_id: str, user: User = Depends(get_current_user),
                        memory: MemoryProvider = Depends(get_memory_provider),
                        session: AsyncSession = Depends(get_session)) -> None:
    if not await memory.delete(str(user.id), memory_id):
        raise HTTPException(404, "Memory not found")
    await MessageRepository(session).scrub_memories_used(user.id, {memory_id})


@router.post("/delete-all")
async def delete_all(body: DeleteAll, user: User = Depends(get_current_user),
                     memory: MemoryProvider = Depends(get_memory_provider),
                     session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    if body.confirm != "DELETE":
        raise HTTPException(422, 'Type "DELETE" to confirm')
    deleted = await memory.delete_all(str(user.id))
    await MessageRepository(session).scrub_memories_used(user.id, None)
    return {"deleted": deleted}


@router.post("/{memory_id}/approve", response_model=MemoryOut)
async def approve_memory(memory_id: str, user: User = Depends(get_current_user),
                         memory: MemoryProvider = Depends(get_memory_provider)) -> MemoryOut:
    approved = await memory.approve(str(user.id), memory_id)
    if approved is None:
        raise HTTPException(404, "Suggestion not found")
    return _out(approved)


@router.post("/{memory_id}/reject", status_code=204)
async def reject_memory(memory_id: str, user: User = Depends(get_current_user),
                        memory: MemoryProvider = Depends(get_memory_provider)) -> None:
    if not await memory.reject(str(user.id), memory_id):
        raise HTTPException(404, "Suggestion not found")


@router.post("/{memory_id}/restore", response_model=MemoryOut)
async def restore_memory(memory_id: str, user: User = Depends(get_current_user),
                         memory: MemoryProvider = Depends(get_memory_provider)) -> MemoryOut:
    restored = await memory.restore(str(user.id), memory_id)
    if restored is None:
        raise HTTPException(404, "Superseded memory not found")
    return _out(restored)


@router.get("/{memory_id}/versions", response_model=list[VersionOut])
async def memory_versions(memory_id: str, user: User = Depends(get_current_user),
                          memory: MemoryProvider = Depends(get_memory_provider)) -> list[VersionOut]:
    rows = await memory.versions(str(user.id), memory_id)
    if rows is None:
        raise HTTPException(404, "Memory not found")
    return [VersionOut(content=v.content, reason=v.reason, created_at=v.created_at) for v in rows]
