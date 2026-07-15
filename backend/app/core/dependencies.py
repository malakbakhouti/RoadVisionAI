"""Central dependency-injection wiring (SAD §5 — layered architecture).

Convention: routers depend ONLY on services; services depend on
repositories; repositories depend on the AsyncSession. Each layer is
provided here as an annotated FastAPI dependency so endpoints stay thin.

Step 1 wires the infrastructure dependencies (settings, db session).
Step 2 adds security dependencies (get_current_user, RBAC).
Steps 3+ add service/repository providers as modules are implemented.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db

# --- Infrastructure ---------------------------------------------------------
SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db)]
