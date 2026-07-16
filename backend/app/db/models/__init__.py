"""ORM models registry — importing everything registers all 24 tables on Base.metadata."""

from app.db.models.ai_model import AiModel
from app.db.models.audit import AuditLog
from app.db.models.dashboard import DamageTypeStat, DashboardSnapshot, PciTrend
from app.db.models.enums import (
    DamageCategory,
    DocType,
    InspectionStatus,
    MaintenanceStrategy,
    ModelFramework,
    ModelStatus,
    NotifType,
    PlanStatus,
    PriorityLevel,
    RecStatus,
    RoadType,
    SeverityLevel,
    TrendDirection,
)
from app.db.models.inspection import (
    AnalysisResult,
    DamageDetection,
    Inspection,
    InspectionReport,
    PciScore,
    XaiExplanation,
)
from app.db.models.knowledge import Embedding, KnowledgeDocument
from app.db.models.maintenance import MaintenancePlan, MaintenanceRecommendation, Rule
from app.db.models.notification import Notification
from app.db.models.road import DamageType, GisLocation, RoadImage, RoadSection
from app.db.models.user import Role, User, UserRole, UserRoleLink

__all__ = [
    "AiModel",
    "AnalysisResult",
    "AuditLog",
    "DamageCategory",
    "DamageDetection",
    "DamageType",
    "DamageTypeStat",
    "DashboardSnapshot",
    "DocType",
    "Embedding",
    "GisLocation",
    "Inspection",
    "InspectionReport",
    "InspectionStatus",
    "KnowledgeDocument",
    "MaintenancePlan",
    "MaintenanceRecommendation",
    "MaintenanceStrategy",
    "ModelFramework",
    "ModelStatus",
    "NotifType",
    "Notification",
    "PciScore",
    "PciTrend",
    "PlanStatus",
    "PriorityLevel",
    "RecStatus",
    "Role",
    "RoadImage",
    "RoadSection",
    "RoadType",
    "Rule",
    "SeverityLevel",
    "TrendDirection",
    "User",
    "UserRole",
    "UserRoleLink",
    "XaiExplanation",
]
