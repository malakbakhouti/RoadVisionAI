"""API v1 router aggregation.

Each business module (Steps 2-6) registers its APIRouter here, mapped
1:1 onto APISpec v1.0 resource groups:
  Step 2 -> /auth          (APISpec §3, SD01)
  Step 4 -> /inspections   (APISpec §6.2, SD02/SD03)
  Step 5 -> /reports       (APISpec §6.x, SD06)
  Step 6 -> /dashboard     (APISpec §6.5, SD08)
"""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, dashboard, health, inspections, reports

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(inspections.router)
api_router.include_router(reports.router)
api_router.include_router(dashboard.router)
