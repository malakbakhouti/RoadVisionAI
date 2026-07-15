-- ================================================================
-- RoadVisionAI Production Schema v4.2
-- PostgreSQL 17 + PostGIS
-- v4.2 — Final Production Release
-- ================================================================

-- ================================================================
-- EXTENSIONS
-- ================================================================

CREATE EXTENSION IF NOT EXISTS "postgis";       -- Geospatial support (PostGIS)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";      -- gen_random_uuid() + cryptographic functions
CREATE EXTENSION IF NOT EXISTS "pg_trgm";       -- Trigram similarity for FTS (title search)
CREATE EXTENSION IF NOT EXISTS "citext";        -- Case-insensitive text type (email)

-- ================================================================
-- ENUM TYPES
-- ================================================================

CREATE TYPE road_type AS ENUM (
    'NATIONALE',
    'REGIONALE',
    'PROVINCIALE',
    'RURALE'
);

CREATE TYPE severity_level AS ENUM (
    'FAIBLE',
    'MODERE',
    'GRAVE',
    'CRITIQUE'
);

CREATE TYPE priority_level AS ENUM (
    'P0_CRITIQUE',
    'P1_URGENT',
    'P2_PLANIFIE',
    'P3_SURVEILLANCE',
    'P4_EXCELLENT'
);

CREATE TYPE inspection_status AS ENUM (
    'EN_ATTENTE',
    'EN_COURS',
    'TERMINEE',
    'ANNULEE',
    'VALIDEE',
    'ERREUR'
);

CREATE TYPE maintenance_strategy AS ENUM (
    'COLMATAGE',
    'RESURFACAGE',
    'RECONSTRUCTION',
    'REHABILITATION',
    'SURVEILLANCE'
);

CREATE TYPE damage_category AS ENUM (
    'FISSURE',
    'DEFORMATION',
    'DEGRADATION_SURFACE',
    'MARQUAGE'
);

CREATE TYPE plan_status AS ENUM (
    'BROUILLON',
    'SOUMIS',
    'VALIDE',
    'REJETE',
    'EN_COURS',
    'TERMINE'
);

CREATE TYPE rec_status AS ENUM (
    'EN_ATTENTE',
    'VALIDEE',
    'MODIFIEE',
    'REJETEE'
);

CREATE TYPE doc_type AS ENUM (
    'NORME_DGR',
    'GUIDE_TECHNIQUE',
    'PCI_MANUAL',
    'AASHTO',
    'ASTM',
    'HISTORIQUE',
    'BONNE_PRATIQUE'
);

CREATE TYPE notif_type AS ENUM (
    'ALERTE_CRITIQUE',
    'VALIDATION_REQUISE',
    'RAPPORT_PRET',
    'MISE_A_JOUR_MODELE',
    'INFO'
);

CREATE TYPE trend_direction AS ENUM (
    'AMELIORATION',
    'STABLE',
    'DEGRADATION'
);

CREATE TYPE user_role AS ENUM (
    'ADMINISTRATOR',
    'ROAD_ENGINEER',
    'INSPECTION_AGENT'
);

-- ================================================================
-- PACKAGE 1 — USER MANAGEMENT
-- ================================================================

-- users (base table, all roles)
CREATE TABLE users (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    username        VARCHAR(100)    NOT NULL,
    email           CITEXT          NOT NULL,
    password_hash   VARCHAR(255)    NOT NULL,
    role            user_role       NOT NULL,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    specialization  VARCHAR(200),               -- RoadEngineer only
    region          VARCHAR(200),               -- RoadEngineer only
    vehicle_id      VARCHAR(100),               -- InspectionAgent only
    equipment_id    VARCHAR(100),               -- InspectionAgent only
    can_manage_users  BOOLEAN       DEFAULT FALSE, -- Administrator only
    can_manage_models BOOLEAN       DEFAULT FALSE,
    can_configure_ai  BOOLEAN       DEFAULT FALSE,
    last_login      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    version         INTEGER         NOT NULL DEFAULT 1,
    CONSTRAINT chk_users_email      CHECK (email ~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'),
    CONSTRAINT chk_users_username   CHECK (trim(username) <> ''),
    CONSTRAINT chk_users_updated_at CHECK (updated_at >= created_at),
    CONSTRAINT chk_users_deleted_at CHECK (deleted_at IS NULL OR deleted_at >= created_at)
);

COMMENT ON TABLE  users IS 'Unified user table. Discriminated by role column (Administrator, RoadEngineer, InspectionAgent).';
COMMENT ON COLUMN users.password_hash IS 'bcrypt hash — plaintext never stored.';
COMMENT ON COLUMN users.version       IS 'Optimistic locking version counter.';
COMMENT ON COLUMN users.deleted_at    IS 'Soft delete — NULL means active. Set to NOW() to deactivate.';

-- Partial unique indexes: allow re-registration after soft-delete
CREATE UNIQUE INDEX uq_users_email_active    ON users(email)    WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_users_username_active ON users(username) WHERE deleted_at IS NULL;

-- roles
CREATE TABLE roles (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(100) NOT NULL,
    permissions JSONB        NOT NULL DEFAULT '[]'
                             CHECK (jsonb_typeof(permissions) = 'array'),
    description TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_roles_name       UNIQUE (name),
    CONSTRAINT chk_roles_updated_at CHECK (updated_at >= created_at)
);

COMMENT ON TABLE  roles IS 'Role definitions with JSON permission lists.';
COMMENT ON COLUMN roles.permissions IS 'JSON array of permission strings granted to this role.';

-- user_roles (junction: User M-N Role)
CREATE TABLE user_roles (
    user_id     UUID    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id     UUID    NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);

COMMENT ON TABLE  user_roles IS 'Junction table for M:N relationship between users and roles.';
COMMENT ON COLUMN user_roles.assigned_at IS 'Timestamp when the role was assigned to the user.';

-- notifications
CREATE TABLE notifications (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type        notif_type  NOT NULL,
    title       VARCHAR(255) NOT NULL,
    message     TEXT        NOT NULL,
    is_read     BOOLEAN     NOT NULL DEFAULT FALSE,
    priority    VARCHAR(20)  NOT NULL DEFAULT 'NORMAL'
                             CHECK (priority IN ('LOW','NORMAL','HIGH','CRITICAL')),
    entity_type VARCHAR(100),   -- optional: 'Inspection', 'MaintenancePlan'...
    entity_id   UUID,           -- FK-less reference to any entity
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at     TIMESTAMPTZ,
    CONSTRAINT chk_notif_read_at CHECK (read_at IS NULL OR read_at >= created_at)
);

COMMENT ON TABLE  notifications IS 'User notifications. entity_type/entity_id provide loose coupling to source entity.';
COMMENT ON COLUMN notifications.entity_type IS 'Discriminator for the source entity (e.g. ''Inspection'', ''MaintenancePlan'').';
COMMENT ON COLUMN notifications.entity_id   IS 'UUID of the source entity. No FK — loose coupling by design.';
COMMENT ON COLUMN notifications.read_at     IS 'Timestamp when the user read the notification. NULL means unread.';

-- audit_logs
CREATE TABLE audit_logs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        REFERENCES users(id) ON DELETE SET NULL,
    action      VARCHAR(100) NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    entity_id   UUID        NOT NULL,
    old_value   JSONB,
    new_value   JSONB,
    ip_address  INET,
    user_agent  TEXT,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  audit_logs IS 'Immutable audit trail. All business mutations recorded here.';
COMMENT ON COLUMN audit_logs.entity_type IS 'Name of the affected table or aggregate (e.g. ''inspections'', ''maintenance_plans'').';
COMMENT ON COLUMN audit_logs.old_value   IS 'JSONB snapshot of the row before the mutation.';
COMMENT ON COLUMN audit_logs.new_value   IS 'JSONB snapshot of the row after the mutation.';

-- ================================================================
-- PACKAGE 2 — INSPECTION DOMAIN
-- ================================================================

-- gis_locations (PostGIS)
CREATE TABLE gis_locations (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    latitude    NUMERIC(10,7) NOT NULL,
    longitude   NUMERIC(10,7) NOT NULL,
    altitude    NUMERIC(8,2),
    geometry    GEOMETRY(Point, 4326) NOT NULL,
    address     TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_latitude       CHECK (latitude  BETWEEN -90  AND 90),
    CONSTRAINT chk_longitude      CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT chk_gis_updated_at CHECK (updated_at >= created_at)
);

COMMENT ON TABLE  gis_locations IS 'PostGIS-backed spatial table. geometry column uses SRID 4326 (WGS84).';
COMMENT ON COLUMN gis_locations.geometry IS 'GEOMETRY(Point,4326). Auto-derived from latitude/longitude via trigger.';

-- road_sections
CREATE TABLE road_sections (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    section_code    VARCHAR(50) NOT NULL,
    road_name       VARCHAR(200) NOT NULL,
    road_type       road_type   NOT NULL,
    kilometric      NUMERIC(10,3),
    province        VARCHAR(100),
    region          VARCHAR(100),
    length_km       NUMERIC(8,3),
    gis_location_id UUID        REFERENCES gis_locations(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    version         INTEGER     NOT NULL DEFAULT 1,
    CONSTRAINT uq_road_section_code       UNIQUE (section_code),
    CONSTRAINT chk_section_code_nonempty  CHECK (trim(section_code) <> ''),
    CONSTRAINT chk_road_name_nonempty     CHECK (trim(road_name) <> ''),
    CONSTRAINT chk_sections_updated_at    CHECK (updated_at >= created_at),
    CONSTRAINT chk_sections_deleted_at    CHECK (deleted_at IS NULL OR deleted_at >= created_at)
);

COMMENT ON TABLE  road_sections IS 'Road section master data. Each section has one GIS location (PostGIS).';
COMMENT ON COLUMN road_sections.deleted_at IS 'Soft delete — NULL means active.';

-- damage_types (reference/lookup table)
CREATE TABLE damage_types (
    id          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    code        VARCHAR(50)     NOT NULL,
    name        VARCHAR(200)    NOT NULL,
    description TEXT,
    pci_weight  NUMERIC(4,3)    NOT NULL DEFAULT 0.0
                                CHECK (pci_weight BETWEEN 0 AND 1),
    category    damage_category NOT NULL,
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_damage_type_code       UNIQUE (code),
    CONSTRAINT chk_damage_type_code      CHECK (trim(code) <> ''),
    CONSTRAINT chk_damage_type_name      CHECK (trim(name) <> '')
);

COMMENT ON TABLE  damage_types IS 'Reference table for the 8 YOLO damage classes (Pothole, Alligator, etc.) with PCI weights.';
COMMENT ON COLUMN damage_types.pci_weight IS 'Weight applied in PCI formula (ASTM D6433). Range [0,1].';

-- inspections
CREATE TABLE inspections (
    id              UUID                PRIMARY KEY DEFAULT gen_random_uuid(),
    road_section_id UUID                NOT NULL REFERENCES road_sections(id) ON DELETE RESTRICT,
    created_by      UUID                NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    validated_by    UUID                REFERENCES users(id) ON DELETE SET NULL,
    status          inspection_status   NOT NULL DEFAULT 'EN_ATTENTE',
    inspection_date TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    weather_cond    VARCHAR(100),
    notes           TEXT,
    created_at      TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    version         INTEGER             NOT NULL DEFAULT 1,
    CONSTRAINT chk_inspections_updated_at CHECK (updated_at >= created_at),
    CONSTRAINT chk_inspections_deleted_at CHECK (deleted_at IS NULL OR deleted_at >= created_at)
);

COMMENT ON TABLE  inspections IS 'Core inspection entity. Links road section, agent (created_by) and engineer (validated_by).';
COMMENT ON COLUMN inspections.deleted_at IS 'Soft delete — NULL means active.';

-- road_images
CREATE TABLE road_images (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    inspection_id   UUID        NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    filename        VARCHAR(255) NOT NULL,
    storage_path    VARCHAR(500) NOT NULL,
    file_size       BIGINT      CHECK (file_size >= 0),
    mime_type       VARCHAR(100) NOT NULL DEFAULT 'image/jpeg',
    width           INTEGER     CHECK (width > 0),
    height          INTEGER     CHECK (height > 0),
    gps_lat         NUMERIC(10,7),
    gps_lng         NUMERIC(10,7),
    sequence_num    INTEGER     NOT NULL DEFAULT 1,
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_image_gps_lat    CHECK (gps_lat IS NULL OR gps_lat BETWEEN -90  AND 90),
    CONSTRAINT chk_image_gps_lng    CHECK (gps_lng IS NULL OR gps_lng BETWEEN -180 AND 180),
    CONSTRAINT chk_image_filename   CHECK (trim(filename) <> ''),
    CONSTRAINT chk_image_storage    CHECK (trim(storage_path) <> '')
);

COMMENT ON TABLE  road_images IS 'Images captured during an inspection. Stored in MinIO; path persisted here.';
COMMENT ON COLUMN road_images.storage_path IS 'MinIO object path. Format: inspections/{inspection_id}/{filename}.';
COMMENT ON COLUMN road_images.sequence_num IS 'Order of the image within the inspection session.';

-- damage_detections
CREATE TABLE damage_detections (
    id               UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    road_image_id    UUID            NOT NULL REFERENCES road_images(id) ON DELETE CASCADE,
    damage_type_id   UUID            NOT NULL REFERENCES damage_types(id) ON DELETE RESTRICT,
    bbox_x           NUMERIC(8,4)    NOT NULL CHECK (bbox_x >= 0),
    bbox_y           NUMERIC(8,4)    NOT NULL CHECK (bbox_y >= 0),
    bbox_width       NUMERIC(8,4)    NOT NULL CHECK (bbox_width > 0),
    bbox_height      NUMERIC(8,4)    NOT NULL CHECK (bbox_height > 0),
    confidence_score NUMERIC(5,4)    NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
    severity_score   NUMERIC(5,4)    NOT NULL CHECK (severity_score BETWEEN 0 AND 1),
    area_m2          NUMERIC(10,4),
    detected_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  damage_detections IS 'YOLOv11 detection output. One row per detected damage per image.';
COMMENT ON COLUMN damage_detections.confidence_score IS 'YOLOv11 detection confidence score. Range [0,1].';
COMMENT ON COLUMN damage_detections.severity_score   IS 'Computed severity score derived from type weight and area. Range [0,1].';
COMMENT ON COLUMN damage_detections.area_m2          IS 'Estimated damage area in square metres, derived from bounding box and GPS scale.';

-- analysis_results
CREATE TABLE analysis_results (
    id                          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    inspection_id               UUID            NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    total_detections            INTEGER         NOT NULL DEFAULT 0 CHECK (total_detections >= 0),
    dominant_damage_type        VARCHAR(200),
    overall_severity            severity_level,
    recommendation_confidence   NUMERIC(5,4)    CHECK (recommendation_confidence BETWEEN 0 AND 1),
    processing_time_ms          BIGINT          CHECK (processing_time_ms >= 0),
    created_at                  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_analysis_inspection UNIQUE (inspection_id)
);

COMMENT ON TABLE  analysis_results IS '1:1 with Inspection. Aggregated output of the full AI pipeline per inspection.';
COMMENT ON COLUMN analysis_results.recommendation_confidence IS 'Overall AI confidence in the generated maintenance recommendation. Range [0,1].';
COMMENT ON COLUMN analysis_results.processing_time_ms        IS 'Total AI pipeline processing time in milliseconds.';

-- ================================================================
-- PACKAGE 4 — KNOWLEDGE BASE
-- ================================================================

-- knowledge_documents
CREATE TABLE knowledge_documents (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    title       VARCHAR(500) NOT NULL,
    source      VARCHAR(500),
    doc_type    doc_type    NOT NULL,
    language    VARCHAR(10)  NOT NULL DEFAULT 'fr',
    version     VARCHAR(50),
    content     TEXT        NOT NULL,
    page_count  INTEGER     CHECK (page_count > 0),
    status      VARCHAR(50)  NOT NULL DEFAULT 'PENDING'
                             CHECK (status IN ('PENDING','INDEXING','INDEXED','ERROR')),
    embedding_count INTEGER  NOT NULL DEFAULT 0,
    uploaded_by UUID        REFERENCES users(id) ON DELETE SET NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at  TIMESTAMPTZ,
    lock_version INTEGER     NOT NULL DEFAULT 1,
    CONSTRAINT chk_docs_embedding_count CHECK (embedding_count >= 0),
    CONSTRAINT chk_docs_updated_at      CHECK (updated_at >= uploaded_at),
    CONSTRAINT chk_docs_deleted_at      CHECK (deleted_at IS NULL OR deleted_at >= uploaded_at)
);

COMMENT ON TABLE  knowledge_documents IS 'Normative documents (DGR, ASTM, AASHTO, PCI Manual). Source for RAG pipeline.';
COMMENT ON COLUMN knowledge_documents.status          IS 'Indexing lifecycle: PENDING → INDEXING → INDEXED | ERROR.';
COMMENT ON COLUMN knowledge_documents.embedding_count IS 'Number of chunks indexed into ChromaDB. Updated after successful indexing.';
COMMENT ON COLUMN knowledge_documents.deleted_at      IS 'Soft delete — NULL means active.';
COMMENT ON COLUMN knowledge_documents.lock_version    IS 'Optimistic locking counter. Prevents concurrent update conflicts between admin UI and background indexing job.';

-- embeddings
CREATE TABLE embeddings (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID        NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    chunk_text      TEXT        NOT NULL,
    chunk_index     INTEGER     NOT NULL CHECK (chunk_index >= 0),
    token_count     INTEGER     CHECK (token_count > 0),
    chroma_id       VARCHAR(500),   -- ChromaDB internal ID for sync
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_embedding_doc_chunk UNIQUE (document_id, chunk_index)
);

COMMENT ON TABLE  embeddings IS 'Chunk metadata persisted in PostgreSQL. Actual vectors live in ChromaDB; chroma_id enables sync.';
COMMENT ON COLUMN embeddings.chunk_index IS 'Zero-based position of this chunk within the parent document.';
COMMENT ON COLUMN embeddings.chroma_id   IS 'ChromaDB internal record ID. Used to synchronise updates and deletions.';

-- rules
CREATE TABLE rules (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    code        VARCHAR(50) NOT NULL,
    name        VARCHAR(200) NOT NULL,
    condition   TEXT        NOT NULL,
    action      TEXT        NOT NULL,
    priority    INTEGER     NOT NULL DEFAULT 10 CHECK (priority > 0),
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    created_by  UUID        REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_rule_code         UNIQUE (code),
    CONSTRAINT chk_rule_code        CHECK (trim(code) <> ''),
    CONSTRAINT chk_rule_name        CHECK (trim(name) <> ''),
    CONSTRAINT chk_rules_updated_at CHECK (updated_at >= created_at)
);

COMMENT ON TABLE  rules IS 'Business rules evaluated by RuleEngine (e.g. PCI<40 -> P1_URGENT). Configurable by Administrator.';
COMMENT ON COLUMN rules.condition IS 'Rule condition expression evaluated by the RuleEngine service.';
COMMENT ON COLUMN rules.action    IS 'Action triggered when condition evaluates to true.';
COMMENT ON COLUMN rules.priority  IS 'Evaluation order — lower value means higher priority.';

-- ================================================================
-- PACKAGE 5 — MAINTENANCE
-- ================================================================

-- pci_scores
CREATE TABLE pci_scores (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    inspection_id   UUID            NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
    score           NUMERIC(5,2)    NOT NULL CHECK (score BETWEEN 0 AND 100),
    severity_level  severity_level  NOT NULL,
    priority_level  priority_level  NOT NULL,
    priority_score  NUMERIC(5,4)    CHECK (priority_score BETWEEN 0 AND 1),
    computed_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_pci_inspection UNIQUE (inspection_id)
);

COMMENT ON TABLE  pci_scores IS '1:1 with Inspection. PCI computed by PCIEngine using ASTM D6433.';
COMMENT ON COLUMN pci_scores.priority_score IS 'Multicriteria priority score combining PCI, traffic volume, road type and history. Range [0,1].';

-- maintenance_recommendations
CREATE TABLE maintenance_recommendations (
    id                  UUID                    PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_result_id  UUID                    NOT NULL REFERENCES analysis_results(id) ON DELETE CASCADE,
    strategy            maintenance_strategy    NOT NULL,
    estimated_cost_min  NUMERIC(12,2)           CHECK (estimated_cost_min >= 0),
    estimated_cost_max  NUMERIC(12,2)           CHECK (
                                estimated_cost_max IS NULL
                                OR estimated_cost_min IS NULL
                                OR estimated_cost_max >= estimated_cost_min
                            ),
    estimated_days      INTEGER                 CHECK (estimated_days > 0),
    deadline            DATE,
    justification       TEXT,
    normative_refs      JSONB                   DEFAULT '[]'
                                                CHECK (normative_refs IS NULL OR jsonb_typeof(normative_refs) = 'array'),
    confidence          NUMERIC(5,4)            CHECK (confidence BETWEEN 0 AND 1),
    status              rec_status              NOT NULL DEFAULT 'EN_ATTENTE',
    validated_by        UUID                    REFERENCES users(id) ON DELETE SET NULL,
    validated_at        TIMESTAMPTZ,
    rejection_reason    TEXT,
    rejected_by         UUID                    REFERENCES users(id) ON DELETE SET NULL,
    rejected_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ             NOT NULL DEFAULT NOW(),
    version             INTEGER                 NOT NULL DEFAULT 1,
    CONSTRAINT uq_rec_analysis      UNIQUE (analysis_result_id),
    CONSTRAINT chk_rec_validation CHECK (
        (status = 'VALIDEE'  AND validated_by IS NOT NULL AND validated_at IS NOT NULL) OR
        (status = 'REJETEE'  AND rejected_by  IS NOT NULL AND rejected_at  IS NOT NULL) OR
        (status NOT IN ('VALIDEE','REJETEE'))
    ),
    CONSTRAINT chk_rec_updated_at    CHECK (updated_at   >= created_at),
    CONSTRAINT chk_rec_validated_at  CHECK (validated_at IS NULL OR validated_at >= created_at),
    CONSTRAINT chk_rec_rejected_at   CHECK (rejected_at  IS NULL OR rejected_at  >= created_at)
);

COMMENT ON TABLE  maintenance_recommendations IS '1:1 with AnalysisResult. Generated by PlanningAgent, validated by RoadEngineer.';
COMMENT ON COLUMN maintenance_recommendations.normative_refs IS 'JSON array of normative references cited by the RAG pipeline (e.g. ["ASTM D6433 §4.2", "DGR Art.7.3"]).';

-- maintenance_plans
CREATE TABLE maintenance_plans (
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    recommendation_id   UUID            NOT NULL REFERENCES maintenance_recommendations(id) ON DELETE CASCADE,
    total_budget        NUMERIC(14,2)   CHECK (total_budget >= 0),
    start_date          DATE,
    end_date            DATE,
    priority            priority_level  NOT NULL,
    status              plan_status     NOT NULL DEFAULT 'BROUILLON',
    validated_by        UUID            REFERENCES users(id) ON DELETE SET NULL,
    validated_at        TIMESTAMPTZ,
    engineer_notes      TEXT,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    version             INTEGER         NOT NULL DEFAULT 1,
    CONSTRAINT uq_plan_recommendation  UNIQUE (recommendation_id),
    CONSTRAINT chk_plan_dates          CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date),
    CONSTRAINT chk_plan_updated_at     CHECK (updated_at   >= created_at),
    CONSTRAINT chk_plan_validated_at   CHECK (validated_at IS NULL OR validated_at >= created_at)
);

COMMENT ON TABLE  maintenance_plans IS '1:1 with MaintenanceRecommendation. Operational schedule and budget.';
COMMENT ON COLUMN maintenance_plans.engineer_notes IS 'Free-text notes added by the Road Engineer during validation or modification.';

-- ================================================================
-- PACKAGE 6 — REPORTING
-- ================================================================

-- xai_explanations
CREATE TABLE xai_explanations (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    rules_applied           JSONB       DEFAULT '[]'
                                        CHECK (jsonb_typeof(rules_applied)    = 'array'),
    normative_refs          JSONB       DEFAULT '[]'
                                        CHECK (jsonb_typeof(normative_refs)   = 'array'),
    priority_breakdown      JSONB       DEFAULT '{}'
                                        CHECK (jsonb_typeof(priority_breakdown) = 'object'),
    confidence_score        NUMERIC(5,4) CHECK (confidence_score BETWEEN 0 AND 1),
    severity_justification  TEXT,
    strategy_justification  TEXT,
    agents_involved         JSONB       DEFAULT '[]'
                                        CHECK (jsonb_typeof(agents_involved)  = 'array'),
    generated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  xai_explanations IS 'XAI output: rules, normative refs, priority decomposition. Generated by XAIService.';
COMMENT ON COLUMN xai_explanations.rules_applied        IS 'JSON array of Rule codes activated by the RuleEngine for this inspection.';
COMMENT ON COLUMN xai_explanations.normative_refs        IS 'JSON array of normative document references retrieved via RAG.';
COMMENT ON COLUMN xai_explanations.priority_breakdown    IS 'JSON object decomposing the Priority Score by factor (PCI, traffic, road_type, history, climate).';
COMMENT ON COLUMN xai_explanations.agents_involved       IS 'JSON array of LangGraph agent names that contributed to the decision.';

-- inspection_reports
CREATE TABLE inspection_reports (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id             UUID        NOT NULL REFERENCES maintenance_plans(id) ON DELETE CASCADE,
    xai_explanation_id  UUID        REFERENCES xai_explanations(id) ON DELETE SET NULL,
    title               VARCHAR(500) NOT NULL,
    executive_summary   TEXT,
    damage_assessment   TEXT,
    pci_analysis        TEXT,
    priority_ranking    TEXT,
    recommendations     TEXT,
    estimated_budget    NUMERIC(14,2),
    estimated_duration  INTEGER     CHECK (estimated_duration IS NULL OR estimated_duration > 0),
    risk_analysis       TEXT,
    xai_justification   TEXT,
    normative_refs      JSONB       DEFAULT '[]'
                                    CHECK (normative_refs IS NULL OR jsonb_typeof(normative_refs) = 'array'),
    file_path           VARCHAR(500),
    file_size           BIGINT,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_report_plan          UNIQUE (plan_id),
    CONSTRAINT chk_report_title        CHECK (trim(title) <> ''),
    CONSTRAINT chk_report_generated_at CHECK (generated_at >= created_at),
    CONSTRAINT chk_report_file_size    CHECK (file_size IS NULL OR file_size >= 0)
);

COMMENT ON TABLE  inspection_reports IS '1:1 with MaintenancePlan. PDF report generated by ReportAgent + ReportLab.';
COMMENT ON COLUMN inspection_reports.file_path  IS 'MinIO object path to the generated PDF file.';
COMMENT ON COLUMN inspection_reports.file_size  IS 'Size of the generated PDF file in bytes.';



-- ================================================================
-- PACKAGE 7 — DASHBOARD (persisted KPI snapshots)
-- ================================================================

-- dashboard_snapshots
CREATE TABLE dashboard_snapshots (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_date       DATE        NOT NULL DEFAULT CURRENT_DATE,
    total_inspections   INTEGER     NOT NULL DEFAULT 0,
    total_detections    INTEGER     NOT NULL DEFAULT 0,
    avg_pci_score       NUMERIC(5,2),
    critical_sections   INTEGER     NOT NULL DEFAULT 0,
    total_budget        NUMERIC(16,2),
    coverage_rate       NUMERIC(5,2) CHECK (coverage_rate BETWEEN 0 AND 100),
    region              VARCHAR(100),
    province            VARCHAR(100),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_snapshot_date_region    UNIQUE (snapshot_date, region, province),
    CONSTRAINT chk_snapshot_inspections   CHECK (total_inspections >= 0),
    CONSTRAINT chk_snapshot_detections    CHECK (total_detections  >= 0),
    CONSTRAINT chk_snapshot_critical      CHECK (critical_sections >= 0),
    CONSTRAINT chk_snapshot_avg_pci       CHECK (avg_pci_score IS NULL OR avg_pci_score BETWEEN 0 AND 100)
);

COMMENT ON TABLE  dashboard_snapshots IS 'Daily KPI snapshots for the Dashboard. Computed by a background job. Not real-time.';
COMMENT ON COLUMN dashboard_snapshots.coverage_rate IS 'Percentage of the road network covered by at least one inspection. Range [0,100].';
COMMENT ON COLUMN dashboard_snapshots.region        IS 'Administrative region filter. NULL means national aggregate.';
COMMENT ON COLUMN dashboard_snapshots.province      IS 'Administrative province filter. NULL means regional aggregate.';

-- damage_type_stats
CREATE TABLE damage_type_stats (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id     UUID        NOT NULL REFERENCES dashboard_snapshots(id) ON DELETE CASCADE,
    damage_type     VARCHAR(200) NOT NULL,
    count           INTEGER     NOT NULL DEFAULT 0,
    percentage      NUMERIC(5,2) CHECK (percentage BETWEEN 0 AND 100),
    avg_severity    NUMERIC(5,4) CHECK (avg_severity IS NULL OR avg_severity BETWEEN 0 AND 1),
    period          VARCHAR(50),
    CONSTRAINT chk_dts_count CHECK (count >= 0)
);

COMMENT ON TABLE  damage_type_stats IS 'Aggregated damage detection counts per type per dashboard snapshot.';
COMMENT ON COLUMN damage_type_stats.damage_type  IS 'Damage type name (denormalised from damage_types.name for snapshot stability).';
COMMENT ON COLUMN damage_type_stats.avg_severity IS 'Average severity score for this damage type in the snapshot period. Range [0,1].';

-- pci_trends
CREATE TABLE pci_trends (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    road_section_id UUID            NOT NULL REFERENCES road_sections(id) ON DELETE CASCADE,
    snapshot_id     UUID            NOT NULL REFERENCES dashboard_snapshots(id) ON DELETE CASCADE,
    pci_value       NUMERIC(5,2)    NOT NULL CHECK (pci_value BETWEEN 0 AND 100),
    recorded_date   DATE            NOT NULL DEFAULT CURRENT_DATE,
    trend           trend_direction,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  pci_trends IS 'Historical PCI values per road section. Feeds the predictive maintenance module.';
COMMENT ON COLUMN pci_trends.trend IS 'PCI evolution direction compared to previous snapshot for this road section.';

-- ================================================================
-- TRIGGERS
-- ================================================================

-- Auto-update updated_at (only when row actually changed)
CREATE OR REPLACE FUNCTION fn_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW IS DISTINCT FROM OLD THEN
        NEW.updated_at = NOW();
    END IF;
    RETURN NEW;
END;
$$;

-- Increment optimistic locking version (only when row actually changed)
CREATE OR REPLACE FUNCTION fn_increment_version()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.*) IS DISTINCT FROM ROW(OLD.*) THEN
        NEW.version = OLD.version + 1;
    END IF;
    RETURN NEW;
END;
$$;

-- Increment lock_version for knowledge_documents (dedicated function — avoids
-- conflict with the business column version VARCHAR(50) on that table)
CREATE OR REPLACE FUNCTION fn_increment_lock_version()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.*) IS DISTINCT FROM ROW(OLD.*) THEN
        NEW.lock_version = OLD.lock_version + 1;
    END IF;
    RETURN NEW;
END;
$$;

-- Auto-populate geometry from lat/lng
CREATE OR REPLACE FUNCTION fn_sync_geometry()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT'
       OR NEW.latitude  IS DISTINCT FROM OLD.latitude
       OR NEW.longitude IS DISTINCT FROM OLD.longitude THEN
        NEW.geometry = ST_SetSRID(
            ST_MakePoint(NEW.longitude, NEW.latitude), 4326
        );
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gis_locations_geom
    BEFORE INSERT OR UPDATE
    ON gis_locations
    FOR EACH ROW EXECUTE FUNCTION fn_sync_geometry();

-- updated_at triggers
CREATE TRIGGER trg_gis_locations_updated_at
    BEFORE UPDATE ON gis_locations
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_roles_updated_at
    BEFORE UPDATE ON roles
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_road_sections_updated_at
    BEFORE UPDATE ON road_sections
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_inspections_updated_at
    BEFORE UPDATE ON inspections
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_knowledge_docs_updated_at
    BEFORE UPDATE ON knowledge_documents
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_rec_updated_at
    BEFORE UPDATE ON maintenance_recommendations
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

CREATE TRIGGER trg_plan_updated_at
    BEFORE UPDATE ON maintenance_plans
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

-- version increment triggers
CREATE TRIGGER trg_road_sections_version
    BEFORE UPDATE ON road_sections
    FOR EACH ROW EXECUTE FUNCTION fn_increment_version();

CREATE TRIGGER trg_users_version
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION fn_increment_version();

CREATE TRIGGER trg_rec_version
    BEFORE UPDATE ON maintenance_recommendations
    FOR EACH ROW EXECUTE FUNCTION fn_increment_version();

CREATE TRIGGER trg_plan_version
    BEFORE UPDATE ON maintenance_plans
    FOR EACH ROW EXECUTE FUNCTION fn_increment_version();

CREATE TRIGGER trg_inspections_version
    BEFORE UPDATE ON inspections
    FOR EACH ROW
    EXECUTE FUNCTION fn_increment_version();

CREATE TRIGGER trg_knowledge_docs_lock_version
    BEFORE UPDATE ON knowledge_documents
    FOR EACH ROW EXECUTE FUNCTION fn_increment_lock_version();

-- ================================================================
-- INDEXES
-- ================================================================

-- users
CREATE INDEX idx_users_role       ON users(role);
CREATE INDEX idx_users_is_active  ON users(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_users_deleted_at ON users(deleted_at) WHERE deleted_at IS NULL;

-- road_sections
CREATE INDEX idx_road_sections_type     ON road_sections(road_type);
CREATE INDEX idx_road_sections_region   ON road_sections(region);
CREATE INDEX idx_road_sections_province ON road_sections(province);
CREATE INDEX idx_road_sections_deleted  ON road_sections(deleted_at) WHERE deleted_at IS NULL;

-- gis_locations (PostGIS GiST)
CREATE INDEX idx_gis_locations_geom ON gis_locations USING GIST(geometry);

-- road_images
CREATE INDEX idx_road_images_inspection ON road_images(inspection_id);
CREATE INDEX idx_road_images_captured   ON road_images(captured_at DESC);

-- damage_detections
CREATE INDEX idx_detections_image       ON damage_detections(road_image_id);
CREATE INDEX idx_detections_type        ON damage_detections(damage_type_id);
CREATE INDEX idx_detections_severity    ON damage_detections(severity_score DESC);
CREATE INDEX idx_detections_confidence  ON damage_detections(confidence_score DESC);

-- pci_scores
CREATE INDEX idx_pci_score        ON pci_scores(score ASC);
CREATE INDEX idx_pci_priority     ON pci_scores(priority_level);
CREATE INDEX idx_pci_severity     ON pci_scores(severity_level);

-- maintenance_recommendations
CREATE INDEX idx_rec_status_strategy ON maintenance_recommendations(status, strategy); -- composite replaces two separate
CREATE INDEX idx_rec_created_at      ON maintenance_recommendations(created_at DESC);

-- maintenance_plans
CREATE INDEX idx_plan_status_priority ON maintenance_plans(status, priority); -- composite replaces two separate
CREATE INDEX idx_plan_start_date   ON maintenance_plans(start_date);

-- knowledge_documents
CREATE INDEX idx_doc_type          ON knowledge_documents(doc_type);
CREATE INDEX idx_doc_status        ON knowledge_documents(status);
CREATE INDEX idx_doc_deleted       ON knowledge_documents(deleted_at) WHERE deleted_at IS NULL;
CREATE INDEX idx_doc_content_fts   ON knowledge_documents USING GIN(to_tsvector('french', content));
CREATE INDEX idx_doc_title_trgm    ON knowledge_documents USING GIN(title gin_trgm_ops);

-- embeddings
CREATE INDEX idx_emb_document     ON embeddings(document_id);
CREATE INDEX idx_emb_chroma_id    ON embeddings(chroma_id);

-- rules
CREATE INDEX idx_rules_active     ON rules(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_rules_priority   ON rules(priority ASC);

-- audit_logs
CREATE INDEX idx_audit_user        ON audit_logs(user_id);
CREATE INDEX idx_audit_entity      ON audit_logs(entity_type, entity_id);
CREATE INDEX idx_audit_timestamp   ON audit_logs(timestamp DESC);

-- notifications
CREATE INDEX idx_notif_user_created ON notifications(user_id, created_at DESC); -- composite: most frequent query pattern
CREATE INDEX idx_notif_is_read      ON notifications(is_read) WHERE is_read = FALSE;

-- inspections
CREATE INDEX idx_inspections_section_date ON inspections(road_section_id, inspection_date DESC); -- composite
CREATE INDEX idx_inspections_created_by   ON inspections(created_by);
CREATE INDEX idx_inspections_status       ON inspections(status);
CREATE INDEX idx_inspections_deleted      ON inspections(deleted_at) WHERE deleted_at IS NULL;

-- pci_trends
CREATE INDEX idx_pci_trend_section   ON pci_trends(road_section_id);
CREATE INDEX idx_pci_trend_date      ON pci_trends(recorded_date DESC);

-- analysis_results
CREATE INDEX idx_analysis_severity   ON analysis_results(overall_severity);

-- dashboard_snapshots
CREATE INDEX idx_snapshot_date     ON dashboard_snapshots(snapshot_date DESC);
CREATE INDEX idx_snapshot_region   ON dashboard_snapshots(region, province);

-- ================================================================
-- PARTIAL INDEXES (high-selectivity status filters)
-- ================================================================
CREATE INDEX idx_inspections_pending   ON inspections(road_section_id, created_at) WHERE status = 'EN_ATTENTE';
CREATE INDEX idx_inspections_in_cours  ON inspections(created_by, updated_at)      WHERE status = 'EN_COURS';
CREATE INDEX idx_rec_pending           ON maintenance_recommendations(created_at)   WHERE status = 'EN_ATTENTE';
CREATE INDEX idx_plan_brouillon        ON maintenance_plans(created_at)             WHERE status = 'BROUILLON';
CREATE INDEX idx_plan_valide           ON maintenance_plans(validated_at DESC)      WHERE status = 'VALIDE';
CREATE INDEX idx_doc_indexed           ON knowledge_documents(doc_type)             WHERE status = 'INDEXED';
CREATE INDEX idx_doc_pending_idx       ON knowledge_documents(uploaded_at)          WHERE status = 'PENDING';

-- damage_type_stats
CREATE INDEX idx_dts_snapshot      ON damage_type_stats(snapshot_id);

-- pci_trends
CREATE INDEX idx_pci_trends_snapshot ON pci_trends(snapshot_id);

-- inspection_reports
CREATE INDEX idx_reports_xai          ON inspection_reports(xai_explanation_id) WHERE xai_explanation_id IS NOT NULL;
CREATE INDEX idx_reports_generated_at ON inspection_reports(generated_at DESC);

-- maintenance_recommendations (FK columns used in validation queries)
CREATE INDEX idx_rec_validated_by  ON maintenance_recommendations(validated_by) WHERE validated_by IS NOT NULL;
CREATE INDEX idx_rec_rejected_by   ON maintenance_recommendations(rejected_by)  WHERE rejected_by  IS NOT NULL;

-- maintenance_plans (FK used in engineer validation queries)
CREATE INDEX idx_plan_validated_by ON maintenance_plans(validated_by) WHERE validated_by IS NOT NULL;

-- knowledge_documents (FK uploaded_by used in admin queries)
CREATE INDEX idx_doc_uploaded_by   ON knowledge_documents(uploaded_by) WHERE uploaded_by IS NOT NULL;

-- xai_explanations (frequently queried by generated_at for reporting)
CREATE INDEX idx_xai_generated_at  ON xai_explanations(generated_at DESC);


-- ================================================================
-- AI MODEL REGISTRY
-- ================================================================

CREATE TYPE model_framework AS ENUM (
    'YOLOV11',
    'YOLOV8',
    'PYTORCH',
    'TENSORFLOW',
    'ONNX',
    'OTHER'
);

CREATE TYPE model_status AS ENUM (
    'TRAINING',
    'VALIDATING',
    'STAGING',
    'PRODUCTION',
    'DEPRECATED',
    'FAILED'
);

CREATE TABLE ai_models (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(200)    NOT NULL,
    version         VARCHAR(50)     NOT NULL,
    framework       model_framework NOT NULL DEFAULT 'YOLOV11',
    description     TEXT,
    -- Dataset
    dataset_name    VARCHAR(200),
    dataset_version VARCHAR(50),
    dataset_size    INTEGER         CHECK (dataset_size > 0),   -- nb images
    num_classes     INTEGER         CHECK (num_classes > 0),
    -- Training config
    epochs          INTEGER         CHECK (epochs > 0),
    batch_size      INTEGER         CHECK (batch_size > 0),
    image_size      INTEGER         CHECK (image_size > 0),
    learning_rate   NUMERIC(8,6),
    -- Performance metrics
    map50           NUMERIC(5,4)    CHECK (map50 BETWEEN 0 AND 1),
    map50_95        NUMERIC(5,4)    CHECK (map50_95 BETWEEN 0 AND 1),
    precision_score NUMERIC(5,4)    CHECK (precision_score BETWEEN 0 AND 1),
    recall_score    NUMERIC(5,4)    CHECK (recall_score BETWEEN 0 AND 1),
    f1_score        NUMERIC(5,4)    CHECK (f1_score BETWEEN 0 AND 1),
    inference_ms    NUMERIC(8,2)    CHECK (inference_ms > 0),
    -- Storage
    weights_path    VARCHAR(500),
    model_size_mb   NUMERIC(8,2)    CHECK (model_size_mb >= 0),
    -- Lifecycle
    status          model_status    NOT NULL DEFAULT 'STAGING',
    is_active       BOOLEAN         NOT NULL DEFAULT FALSE,
    trained_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    deployed_at     TIMESTAMPTZ,
    deprecated_at   TIMESTAMPTZ,
    trained_by      UUID            REFERENCES users(id) ON DELETE SET NULL,
    notes           TEXT,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_model_name_version    UNIQUE (name, version),
    CONSTRAINT chk_model_name           CHECK (trim(name) <> ''),
    CONSTRAINT chk_model_weights_path   CHECK (weights_path IS NULL OR trim(weights_path) <> ''),
    CONSTRAINT chk_model_learning_rate  CHECK (learning_rate IS NULL OR learning_rate > 0),
    CONSTRAINT chk_model_deployed_at    CHECK (deployed_at    IS NULL OR deployed_at    >= trained_at),
    CONSTRAINT chk_model_deprecated_at  CHECK (deprecated_at  IS NULL OR deprecated_at  >= trained_at),
    CONSTRAINT chk_model_updated_at     CHECK (updated_at >= created_at)
);

COMMENT ON TABLE  ai_models IS 'AI model registry. Tracks all YOLOv11 versions, metrics and lifecycle status.';
COMMENT ON COLUMN ai_models.is_active     IS 'Only one model can be active at a time. Enforced at database level by the partial unique index uq_one_active_model.';
COMMENT ON COLUMN ai_models.map50         IS 'Mean Average Precision at IoU threshold 0.50.';
COMMENT ON COLUMN ai_models.map50_95      IS 'Mean Average Precision averaged over IoU thresholds 0.50 to 0.95.';
COMMENT ON COLUMN ai_models.precision_score IS 'TP / (TP + FP) — ratio of correct detections.';
COMMENT ON COLUMN ai_models.recall_score    IS 'TP / (TP + FN) — ratio of detected real damages.';
COMMENT ON COLUMN ai_models.weights_path  IS 'Path to .pt weights file in MinIO or local storage.';

-- Link detections to the model version that produced them
ALTER TABLE damage_detections
    ADD COLUMN model_id UUID REFERENCES ai_models(id) ON DELETE SET NULL;

COMMENT ON COLUMN damage_detections.model_id IS 'Which AI model version produced this detection. Enables per-model performance tracking.';

-- Trigger: updated_at
CREATE TRIGGER trg_ai_models_updated_at
    BEFORE UPDATE ON ai_models
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();

-- Indexes
CREATE INDEX        idx_ai_models_status    ON ai_models(status);
CREATE INDEX        idx_ai_models_is_active ON ai_models(is_active) WHERE is_active = TRUE;
CREATE INDEX        idx_ai_models_trained   ON ai_models(trained_at DESC);
CREATE INDEX        idx_ai_models_map50     ON ai_models(map50 DESC);
CREATE INDEX        idx_detections_model    ON damage_detections(model_id);
-- Enforce at DB level: only one model can be active at a time
CREATE UNIQUE INDEX uq_one_active_model     ON ai_models(is_active) WHERE is_active = TRUE;

