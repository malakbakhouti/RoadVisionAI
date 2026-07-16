"""ReportService — report generation & retrieval (SD06, APISpec).

Step 5 scope: real ReportLab PDF with the OFFICIAL 12-section structure of
CDC §PDF-spec, populated with placeholders where the AI pipeline is not yet
wired. The TechnicalReportAgent (AI step) will later fill sections 3-11 with
real content; the storage/DB integration built here will not change.

Rules honoured: one report per plan (uq_report_plan -> 409), PDF stored in
MinIO `reports/` bucket, file_path/file_size persisted, audit trail.
"""

import io
import uuid
from datetime import UTC, datetime

import anyio
import structlog
from fastapi import HTTPException, status
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models.inspection import InspectionReport
from app.db.models.user import User
from app.repositories.audit_repository import AuditRepository
from app.repositories.report_repository import ReportRepository
from app.services.storage_service import StorageService

log = structlog.get_logger("app.services.report")

# CDC v5.0 — the official 12 sections of the inspection report
REPORT_SECTIONS = [
    "1. Page de garde",
    "2. Résumé exécutif",
    "3. Contexte de l'inspection",
    "4. Évaluation des dégradations",
    "5. Analyse PCI (ASTM D6433)",
    "6. Classement des priorités",
    "7. Recommandations de maintenance",
    "8. Budget estimatif",
    "9. Planification des interventions",
    "10. Analyse des risques",
    "11. Justification XAI",
    "12. Références normatives",
]

PLACEHOLDER = (
    "Section générée automatiquement — le contenu détaillé sera produit par le "
    "pipeline IA (TechnicalReportAgent) lors de l'analyse complète."
)


def _build_pdf(title: str, executive_summary: str | None) -> bytes:
    """Synchronous ReportLab build — executed in a worker thread."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=title,
        author="RoadVisionAI — DGR Maroc",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("RoadVisionAI — Rapport d'inspection routière", styles["Title"]),
        Paragraph("Direction Générale des Routes — Royaume du Maroc", styles["Heading3"]),
        Spacer(1, 12),
        Paragraph(title, styles["Heading1"]),
        Paragraph(
            f"Généré le {datetime.now(UTC).strftime('%d/%m/%Y %H:%M UTC')}",
            styles["Normal"],
        ),
        PageBreak(),
    ]
    for section in REPORT_SECTIONS:
        story.append(Paragraph(section, styles["Heading2"]))
        if section.startswith("2.") and executive_summary:
            story.append(Paragraph(executive_summary, styles["Normal"]))
        else:
            story.append(Paragraph(PLACEHOLDER, styles["Italic"]))
        story.append(Spacer(1, 16))
    doc.build(story)
    return buffer.getvalue()


class ReportService:
    def __init__(self, session: AsyncSession, settings: Settings, storage: StorageService) -> None:
        self._session = session
        self._settings = settings
        self._storage = storage
        self._repo = ReportRepository(session)
        self._audit = AuditRepository(session)

    async def generate_for_plan(
        self, plan_id: uuid.UUID, title: str, executive_summary: str | None, actor: User
    ) -> InspectionReport:
        if not await self._repo.plan_exists(plan_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Maintenance plan {plan_id} not found")
        if await self._repo.get_by_plan(plan_id) is not None:
            # uq_report_plan: exactly one report per plan
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"A report already exists for plan {plan_id}",
            )

        pdf_bytes = await anyio.to_thread.run_sync(_build_pdf, title, executive_summary)

        bucket = self._settings.minio_bucket_reports
        object_name = f"{plan_id}/{uuid.uuid4().hex}_rapport.pdf"
        await self._storage.put_object(
            bucket=bucket,
            object_name=object_name,
            data=pdf_bytes,
            content_type="application/pdf",
        )

        report = InspectionReport(
            plan_id=plan_id,
            title=title,
            executive_summary=executive_summary,
            file_path=f"{bucket}/{object_name}",
            file_size=len(pdf_bytes),
        )
        self._session.add(report)
        await self._session.flush()
        await self._audit.log(
            action="REPORT_GENERATED",
            entity_type="inspection_reports",
            entity_id=report.id,
            user_id=actor.id,
            new_value={"plan_id": str(plan_id), "file_size": len(pdf_bytes)},
        )
        await self._session.commit()
        await self._session.refresh(report)
        log.info("report_generated", report_id=str(report.id), size=len(pdf_bytes))
        return report

    async def get(self, report_id: uuid.UUID) -> InspectionReport:
        return await self._repo.get_or_404(report_id)

    async def list(self, *, limit: int, offset: int):
        return await self._repo.list(limit=limit, offset=offset)

    async def download_url(self, report_id: uuid.UUID) -> str:
        report = await self._repo.get_or_404(report_id)
        if not report.file_path:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Report has no PDF file")
        bucket, _, object_name = report.file_path.partition("/")
        return await self._storage.presigned_get_url(bucket, object_name)
