from sqlalchemy.orm import Session

from app.models import ActionLog


def log_action(
    db: Session,
    *,
    user_id: str,
    organization_id: str,
    action: str,
    meta: dict | None = None,
) -> None:
    db.add(
        ActionLog(
            user_id=user_id,
            organization_id=organization_id,
            action=action,
            meta=meta or {},
        )
    )
