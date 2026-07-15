-- ================================================================
-- RoadVisionAI — Reference seed data v1.0
-- Source of truth: CDC v5.0 (8 damage classes, pci_weight table)
-- Idempotent: safe to re-run (ON CONFLICT DO NOTHING)
-- ================================================================

-- ----------------------------------------------------------------
-- 1. Damage types — the 8 official classes with CDC pci_weight
-- ----------------------------------------------------------------
INSERT INTO damage_types (code, name, description, pci_weight, category) VALUES
('POTHOLE',            'Pothole',            'Nid-de-poule : cavité dans la couche de roulement',            0.350, 'DEFORMATION'),
('ALLIGATOR_CRACK',    'Alligator Crack',    'Réseau de fissures en mosaïque (faïençage)',                    0.300, 'FISSURE'),
('RUTTING',            'Rutting',            'Orniérage : déformation longitudinale permanente',              0.280, 'DEFORMATION'),
('RAVELLING',          'Ravelling',          'Désagrégation granulaire de la surface',                        0.250, 'DEGRADATION_SURFACE'),
('LONGITUDINAL_CRACK', 'Longitudinal Crack', 'Fissure parallèle à l''axe de la route',                        0.150, 'FISSURE'),
('LATERAL_CRACK',      'Lateral Crack',      'Fissure perpendiculaire à l''axe (transversale)',               0.150, 'FISSURE'),
('EDGE_CRACKING',      'Edge Cracking',      'Fissure de rive, en bordure de chaussée',                       0.120, 'FISSURE'),
('STRIPING',           'Striping',           'Dégradation du marquage au sol',                                0.050, 'MARQUAGE')
ON CONFLICT (code) DO NOTHING;

-- ----------------------------------------------------------------
-- 2. Roles (RBAC catalogue — UC0/UC3)
-- ----------------------------------------------------------------
INSERT INTO roles (name, permissions, description) VALUES
('ADMINISTRATOR',
 '["users:manage","models:manage","rules:manage","knowledge:manage","dashboard:read"]'::jsonb,
 'Administrateur système DGR : gestion des utilisateurs, modèles IA, règles et base de connaissances'),
('ROAD_ENGINEER',
 '["inspections:read","recommendations:validate","recommendations:reject","plans:manage","reports:read","dashboard:read"]'::jsonb,
 'Ingénieur routier : validation Human-in-the-Loop des recommandations, pilotage des plans de maintenance'),
('INSPECTION_AGENT',
 '["inspections:create","inspections:read","images:upload"]'::jsonb,
 'Agent d''inspection terrain : création des inspections et téléversement des images géolocalisées')
ON CONFLICT DO NOTHING;

-- ----------------------------------------------------------------
-- 3. Initial administrator
--    Password: Admin@2026!  (Argon2id) — MUST be changed at first login
-- ----------------------------------------------------------------
INSERT INTO users (username, email, password_hash, role,
                   can_manage_users, can_manage_models, can_configure_ai)
VALUES ('admin', 'admin@dgr.gov.ma',
        '$argon2id$v=19$m=65536,t=3,p=4$PLWszW5NUDurUqrRxbvhNw$5REvd2haL3l1PtfK1HCo9tsB9PqdohPLgM+bWmbVvAw',
        'ADMINISTRATOR', TRUE, TRUE, TRUE)
ON CONFLICT DO NOTHING;
