from fastapi import APIRouter

from app.api.routes import admin, auth, billing, jobs, leads, organizations, plans, projects, search

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(projects.router)
api_router.include_router(leads.router)
api_router.include_router(jobs.router)
api_router.include_router(plans.router)
api_router.include_router(billing.router)
api_router.include_router(admin.router)
api_router.include_router(search.router)
