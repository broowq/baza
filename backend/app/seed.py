from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Membership, Organization, PlanType, Project, User
from app.services.quota import apply_plan_limits


def run() -> None:
    db = SessionLocal()
    try:
        demo_email = "demo@baza.app"
        legacy_demo_email = "demo@baza.local"
        demo_org_name = "БАЗА Демо"

        user = db.execute(select(User).where(User.email == demo_email)).scalar_one_or_none()
        legacy_user = db.execute(select(User).where(User.email == legacy_demo_email)).scalar_one_or_none()
        organization = db.execute(select(Organization).where(Organization.name == demo_org_name)).scalar_one_or_none()

        if not user and legacy_user:
            legacy_user.email = demo_email
            user = legacy_user

        if not organization:
            organization = Organization(name=demo_org_name, plan=PlanType.pro)
            apply_plan_limits(organization)
            db.add(organization)
            db.flush()

        if not user:
            user = User(
                email=demo_email,
                full_name="Demo Owner",
                hashed_password=hash_password("password123"),
                email_verified=True,
                is_admin=True,
            )
            db.add(user)
            db.flush()
        elif not user.email_verified:
            user.email_verified = True

        membership = db.execute(
            select(Membership).where(Membership.organization_id == organization.id, Membership.user_id == user.id)
        ).scalar_one_or_none()
        if not membership:
            db.add(Membership(organization_id=organization.id, user_id=user.id, role="owner"))

        project = db.execute(
            select(Project).where(Project.organization_id == organization.id, Project.name == "Демо лиды БАЗА")
        ).scalar_one_or_none()
        if not project:
            db.add(
                Project(
                    organization_id=organization.id,
                    name="Демо лиды БАЗА",
                    niche="b2b saas",
                    geography="europe",
                    segments=["sales", "founders"],
                    cron_schedule="0 9 * * 1",
                    auto_collection_enabled=False,
                )
            )

        db.commit()
        print("Seed complete. Login: demo@baza.app / password123")
    finally:
        db.close()


if __name__ == "__main__":
    run()
