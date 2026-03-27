import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import SessionLocal, get_db
from app.models import CollectionJob, Membership, Project, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])

_SSE_MAX_ITERATIONS = 90  # 90 * 2s = 3 мин


def _extract_token(request: Request) -> str:
    """Extract JWT from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    raise HTTPException(status_code=401, detail="Токен не предоставлен")


@router.get("/subscribe")
async def subscribe_jobs(
    request: Request,
    project_id: str = Query(...),
    org_id: str = Query(...),
    db: Session = Depends(get_db),
):
    token = _extract_token(request)
    try:
        payload = decode_token(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Неверный токен") from exc
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Неверный тип токена")
    user = db.get(User, payload.get("sub"))
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    membership = db.execute(
        select(Membership).where(Membership.user_id == user.id, Membership.organization_id == org_id)
    ).scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Нет доступа к организации")
    project = db.get(Project, project_id)
    if not project or str(project.organization_id) != org_id:
        raise HTTPException(status_code=404, detail="Проект не найден")

    project_uuid = project.id

    async def event_generator():
        sse_db = SessionLocal()
        try:
            for _ in range(_SSE_MAX_ITERATIONS):
                try:
                    sse_db.expire_all()
                    jobs = (
                        sse_db.execute(
                            select(CollectionJob)
                            .where(CollectionJob.project_id == project_uuid)
                            .order_by(CollectionJob.created_at.desc())
                            .limit(20)
                        )
                        .scalars()
                        .all()
                    )
                    data = [
                        {
                            "id": str(j.id),
                            "kind": j.kind,
                            "status": j.status.value,
                            "requested_limit": j.requested_limit,
                            "found_count": j.found_count,
                            "added_count": j.added_count,
                            "enriched_count": j.enriched_count,
                            "error": j.error,
                        }
                        for j in jobs
                    ]
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except Exception:
                    logger.exception("SSE job fetch error for project %s", project_uuid)
                    yield "data: []\n\n"
                await asyncio.sleep(2)
            yield "data: {\"close\":true}\n\n"
        finally:
            sse_db.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
