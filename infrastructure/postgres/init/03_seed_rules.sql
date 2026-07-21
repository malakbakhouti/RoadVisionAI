-- RoadVisionAI — Seed du référentiel de règles de maintenance (Semaine 4, SD05)
-- Idempotent : ON CONFLICT (code) DO NOTHING.
-- Sémantique : priorité croissante = évaluée en premier ; première règle
-- correspondante appliquée. Conditions/actions au format DSL JSON documenté
-- dans app/ai/engines/rule_engine.py. Montants en MAD, indicatifs (à calibrer
-- avec la DGR) ; les références normatives seront ancrées par le RAG.

INSERT INTO rules (code, name, condition, action, priority) VALUES

-- ============ PCI < 40 : état critique ============
('R010_CRITIQUE_RECONSTRUCTION',
 'Reconstruction — section critique',
 '{"pci_max": 40}',
 '{"strategy": "RECONSTRUCTION", "estimated_days": 90, "deadline_days": 30,
   "cost_min_mad": 1500000, "cost_max_mad": 4000000,
   "justification": "PCI de {pci} (priorité {priority}) : la chaussée a atteint un niveau de ruine structurelle. Une reconstruction complète du corps de chaussée est requise ; intervention à engager sous 30 jours."}',
 10),

-- ============ 40 <= PCI < 55 : état grave ============
('R020_GRAVE_STRUCTUREL_REHABILITATION',
 'Réhabilitation — dégradations structurelles dominantes',
 '{"pci_min": 40, "pci_max": 55, "dominant_type_in": ["POTHOLE", "ALLIGATOR_CRACK", "RUTTING"]}',
 '{"strategy": "REHABILITATION", "estimated_days": 45, "deadline_days": 60,
   "cost_min_mad": 400000, "cost_max_mad": 1200000,
   "justification": "PCI de {pci} avec dominance {dominant} : les désordres touchent la structure de la chaussée. Réhabilitation (reprise des couches de surface et purges localisées) sous 60 jours."}',
 20),

('R021_GRAVE_DEFAUT_RESURFACAGE',
 'Resurfaçage — état grave, dégradations de surface',
 '{"pci_min": 40, "pci_max": 55}',
 '{"strategy": "RESURFACAGE", "estimated_days": 30, "deadline_days": 90,
   "cost_min_mad": 250000, "cost_max_mad": 700000,
   "justification": "PCI de {pci} ({detections} détection(s), dominante {dominant}) : dégradation généralisée de la couche de roulement sans ruine structurelle avérée. Resurfaçage programmé sous 90 jours."}',
 25),

-- ============ 55 <= PCI < 70 : état modéré ============
('R030_MODERE_SURFACE_RESURFACAGE',
 'Resurfaçage — usure de surface dominante',
 '{"pci_min": 55, "pci_max": 70, "dominant_type_in": ["RAVELLING", "RUTTING"]}',
 '{"strategy": "RESURFACAGE", "estimated_days": 21, "deadline_days": 180,
   "cost_min_mad": 150000, "cost_max_mad": 450000,
   "justification": "PCI de {pci} avec dominance {dominant} : usure de la couche de roulement (arrachements/orniérage). Resurfaçage préventif à planifier sous 6 mois avant aggravation."}',
 30),

('R031_MODERE_FISSURES_COLMATAGE',
 'Colmatage — fissuration dominante, état modéré',
 '{"pci_min": 55, "pci_max": 70, "dominant_type_in": ["LONGITUDINAL_CRACK", "LATERAL_CRACK", "EDGE_CRACKING", "ALLIGATOR_CRACK"]}',
 '{"strategy": "COLMATAGE", "estimated_days": 10, "deadline_days": 120,
   "cost_min_mad": 60000, "cost_max_mad": 180000,
   "justification": "PCI de {pci} avec dominance {dominant} : fissuration active. Colmatage des fissures sous 120 jours pour prévenir les infiltrations d''eau et la dégradation accélérée du corps de chaussée."}',
 35),

('R032_MODERE_DEFAUT_COLMATAGE',
 'Colmatage — état modéré (règle générale)',
 '{"pci_min": 55, "pci_max": 70}',
 '{"strategy": "COLMATAGE", "estimated_days": 10, "deadline_days": 180,
   "cost_min_mad": 50000, "cost_max_mad": 150000,
   "justification": "PCI de {pci} : dégradations modérées diffuses. Entretien curatif localisé (colmatage) à programmer sous 6 mois."}',
 39),

-- ============ 70 <= PCI < 85 : bon état, entretien préventif ============
('R040_BON_FISSURES_COLMATAGE_PREVENTIF',
 'Colmatage préventif — fissuration naissante',
 '{"pci_min": 70, "pci_max": 85, "min_detections": 1, "dominant_type_in": ["LONGITUDINAL_CRACK", "LATERAL_CRACK", "EDGE_CRACKING"]}',
 '{"strategy": "COLMATAGE", "estimated_days": 5, "deadline_days": 365,
   "cost_min_mad": 20000, "cost_max_mad": 80000,
   "justification": "PCI de {pci} avec fissuration naissante ({dominant}) : colmatage préventif à intégrer au programme annuel d''entretien — coût minime aujourd''hui contre réhabilitation coûteuse demain."}',
 40),

('R041_BON_SURVEILLANCE',
 'Surveillance renforcée — bon état',
 '{"pci_min": 70, "pci_max": 85}',
 '{"strategy": "SURVEILLANCE", "estimated_days": 1, "deadline_days": 365,
   "justification": "PCI de {pci} : section en bon état. Surveillance renforcée avec ré-inspection sous 12 mois."}',
 45),

-- ============ PCI >= 85 : excellent état ============
('R050_EXCELLENT_SURVEILLANCE',
 'Surveillance de routine — excellent état',
 '{"pci_min": 85}',
 '{"strategy": "SURVEILLANCE", "estimated_days": 1, "deadline_days": 730,
   "justification": "PCI de {pci} ({detections} détection(s)) : chaussée en excellent état. Surveillance de routine, prochaine inspection sous 24 mois."}',
 50)

ON CONFLICT (code) DO NOTHING;
