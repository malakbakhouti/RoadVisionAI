"""ORM models — generated from the LIVE schema v4.2 database (sqlacodegen),
then reviewed and organised by domain. The database remains the single source
of truth; do not edit columns here without a schema-level ADR.
"""

import datetime
import decimal
import uuid
from typing import TYPE_CHECKING, Any, Optional

from geoalchemy2.types import Geometry
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.dashboard import PciTrend
    from app.db.models.inspection import DamageDetection, Inspection

from app.db.models.enums import (
    DamageCategory,
    RoadType,
)


class DamageType(Base):
    __tablename__ = "damage_types"
    __table_args__ = (
        CheckConstraint("TRIM(BOTH FROM code) <> ''::text", name="chk_damage_type_code"),
        CheckConstraint("TRIM(BOTH FROM name) <> ''::text", name="chk_damage_type_name"),
        CheckConstraint(
            "pci_weight >= 0::numeric AND pci_weight <= 1::numeric",
            name="damage_types_pci_weight_check",
        ),
        PrimaryKeyConstraint("id", name="damage_types_pkey"),
        UniqueConstraint("code", name="uq_damage_type_code"),
        {
            "comment": "Reference table for the 8 YOLO damage classes (Pothole, "
            "Alligator, etc.) with PCI weights."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    pci_weight: Mapped[decimal.Decimal] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        server_default=text("0.0"),
        comment="Weight applied in PCI formula (ASTM D6433). Range [0,1].",
    )
    category: Mapped[DamageCategory] = mapped_column(
        Enum(
            DamageCategory,
            values_callable=lambda cls: [member.value for member in cls],
            name="damage_category",
        ),
        nullable=False,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    description: Mapped[str | None] = mapped_column(Text)

    damage_detections: Mapped[list["DamageDetection"]] = relationship(
        "DamageDetection", back_populates="damage_type"
    )


class GisLocation(Base):
    __tablename__ = "gis_locations"
    __table_args__ = (
        CheckConstraint(
            "latitude >= '-90'::integer::numeric AND latitude <= 90::numeric", name="chk_latitude"
        ),
        CheckConstraint(
            "longitude >= '-180'::integer::numeric AND longitude <= 180::numeric",
            name="chk_longitude",
        ),
        CheckConstraint("updated_at >= created_at", name="chk_gis_updated_at"),
        PrimaryKeyConstraint("id", name="gis_locations_pkey"),
        Index("idx_gis_locations_geom", "geometry", postgresql_using="gist"),
        {"comment": "PostGIS-backed spatial table. geometry column uses SRID 4326 (WGS84)."},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    latitude: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    geometry: Mapped[Any] = mapped_column(
        Geometry("POINT", 4326, 2, from_text="ST_GeomFromEWKT", name="geometry", nullable=False),
        nullable=False,
        comment="GEOMETRY(Point,4326). Auto-derived from latitude/longitude via trigger.",
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    altitude: Mapped[decimal.Decimal | None] = mapped_column(Numeric(8, 2))
    address: Mapped[str | None] = mapped_column(Text)

    road_sections: Mapped[list["RoadSection"]] = relationship(
        "RoadSection", back_populates="gis_location"
    )


class RoadSection(Base):
    __tablename__ = "road_sections"
    __table_args__ = (
        CheckConstraint("TRIM(BOTH FROM road_name) <> ''::text", name="chk_road_name_nonempty"),
        CheckConstraint(
            "TRIM(BOTH FROM section_code) <> ''::text", name="chk_section_code_nonempty"
        ),
        CheckConstraint(
            "deleted_at IS NULL OR deleted_at >= created_at", name="chk_sections_deleted_at"
        ),
        CheckConstraint("updated_at >= created_at", name="chk_sections_updated_at"),
        ForeignKeyConstraint(
            ["gis_location_id"],
            ["gis_locations.id"],
            ondelete="SET NULL",
            name="road_sections_gis_location_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="road_sections_pkey"),
        UniqueConstraint("section_code", name="uq_road_section_code"),
        Index("idx_road_sections_deleted", "deleted_at", postgresql_where="(deleted_at IS NULL)"),
        Index("idx_road_sections_province", "province"),
        Index("idx_road_sections_region", "region"),
        Index("idx_road_sections_type", "road_type"),
        {"comment": "Road section master data. Each section has one GIS location (PostGIS)."},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    section_code: Mapped[str] = mapped_column(String(50), nullable=False)
    road_name: Mapped[str] = mapped_column(String(200), nullable=False)
    road_type: Mapped[RoadType] = mapped_column(
        Enum(
            RoadType, values_callable=lambda cls: [member.value for member in cls], name="road_type"
        ),
        nullable=False,
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    kilometric: Mapped[decimal.Decimal | None] = mapped_column(Numeric(10, 3))
    province: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    length_km: Mapped[decimal.Decimal | None] = mapped_column(Numeric(8, 3))
    gis_location_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(True), comment="Soft delete — NULL means active."
    )

    gis_location: Mapped[Optional["GisLocation"]] = relationship(
        "GisLocation", back_populates="road_sections"
    )
    inspections: Mapped[list["Inspection"]] = relationship(
        "Inspection", back_populates="road_section"
    )
    pci_trends: Mapped[list["PciTrend"]] = relationship("PciTrend", back_populates="road_section")


class RoadImage(Base):
    __tablename__ = "road_images"
    __table_args__ = (
        CheckConstraint("TRIM(BOTH FROM filename) <> ''::text", name="chk_image_filename"),
        CheckConstraint("TRIM(BOTH FROM storage_path) <> ''::text", name="chk_image_storage"),
        CheckConstraint("file_size >= 0", name="road_images_file_size_check"),
        CheckConstraint(
            "gps_lat IS NULL OR gps_lat >= '-90'::integer::numeric AND gps_lat <= 90::numeric",
            name="chk_image_gps_lat",
        ),
        CheckConstraint(
            "gps_lng IS NULL OR gps_lng >= '-180'::integer::numeric AND gps_lng <= 180::numeric",
            name="chk_image_gps_lng",
        ),
        CheckConstraint("height > 0", name="road_images_height_check"),
        CheckConstraint("width > 0", name="road_images_width_check"),
        ForeignKeyConstraint(
            ["inspection_id"],
            ["inspections.id"],
            ondelete="CASCADE",
            name="road_images_inspection_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="road_images_pkey"),
        Index("idx_road_images_captured", "captured_at"),
        Index("idx_road_images_inspection", "inspection_id"),
        {"comment": "Images captured during an inspection. Stored in MinIO; path persisted here."},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    inspection_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="MinIO object path. Format: inspections/{inspection_id}/{filename}.",
    )
    mime_type: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default=text("'image/jpeg'::character varying")
    )
    sequence_num: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
        comment="Order of the image within the inspection session.",
    )
    captured_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    gps_lat: Mapped[decimal.Decimal | None] = mapped_column(Numeric(10, 7))
    gps_lng: Mapped[decimal.Decimal | None] = mapped_column(Numeric(10, 7))

    inspection: Mapped["Inspection"] = relationship("Inspection", back_populates="road_images")
    damage_detections: Mapped[list["DamageDetection"]] = relationship(
        "DamageDetection", back_populates="road_image"
    )
