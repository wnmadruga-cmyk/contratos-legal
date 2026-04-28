-- Schema do módulo de Leads.
-- Todas as tabelas prefixadas com lead_ para evitar colisão futura.
-- UUIDs são TEXT (canonical, com hifens). JSONB → TEXT (json.loads no Python).
-- Timestamps são TEXT em ISO-8601 UTC (com sufixo Z).

CREATE TABLE IF NOT EXISTS lead_types (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  color       TEXT NOT NULL DEFAULT '#64748b',
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS lead_workflows (
  id           TEXT PRIMARY KEY,
  lead_type_id TEXT NOT NULL REFERENCES lead_types(id) ON DELETE CASCADE,
  name         TEXT NOT NULL,
  is_default   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS lead_macrophases (
  id          TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL REFERENCES lead_workflows(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  position    INTEGER NOT NULL DEFAULT 0,
  sla_days    INTEGER
);

CREATE TABLE IF NOT EXISTS lead_stages (
  id            TEXT PRIMARY KEY,
  workflow_id   TEXT NOT NULL REFERENCES lead_workflows(id) ON DELETE CASCADE,
  macrophase_id TEXT REFERENCES lead_macrophases(id) ON DELETE SET NULL,
  name          TEXT NOT NULL,
  position      INTEGER NOT NULL DEFAULT 0,
  sla_days      INTEGER
);

CREATE TABLE IF NOT EXISTS lead_tags (
  id    TEXT PRIMARY KEY,
  name  TEXT NOT NULL UNIQUE,
  color TEXT NOT NULL DEFAULT '#6b7280'
);

CREATE TABLE IF NOT EXISTS lead_priorities (
  id       TEXT PRIMARY KEY,
  name     TEXT NOT NULL UNIQUE,
  color    TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS lead_statuses (
  id       TEXT PRIMARY KEY,
  name     TEXT NOT NULL UNIQUE,
  color    TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS lead_form_fields (
  id           TEXT PRIMARY KEY,
  lead_type_id TEXT NOT NULL REFERENCES lead_types(id) ON DELETE CASCADE,
  field_key    TEXT NOT NULL,
  label        TEXT NOT NULL,
  field_type   TEXT NOT NULL,        -- text|number|date|textarea|select|radio|repeater|select_cnae
  options      TEXT,                 -- JSON
  required     INTEGER DEFAULT 0,
  section      TEXT NOT NULL DEFAULT 'Geral',
  position     INTEGER NOT NULL DEFAULT 0,
  help_text    TEXT,
  UNIQUE(lead_type_id, field_key)
);

CREATE TABLE IF NOT EXISTS lead_offices (
  id       TEXT PRIMARY KEY,
  name     TEXT NOT NULL UNIQUE,
  color    TEXT NOT NULL DEFAULT '#64748b',
  position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS leads (
  id                TEXT PRIMARY KEY,
  lead_type_id      TEXT NOT NULL REFERENCES lead_types(id),
  workflow_id       TEXT NOT NULL REFERENCES lead_workflows(id),
  current_stage_id  TEXT REFERENCES lead_stages(id) ON DELETE SET NULL,
  name              TEXT,
  responsible_name  TEXT,                            -- texto livre (sem auth ainda)
  status            TEXT NOT NULL DEFAULT 'Aberto',
  priority          TEXT NOT NULL DEFAULT 'Normal',
  description       TEXT,
  due_date          TEXT,                            -- ISO date (YYYY-MM-DD)
  office_id         TEXT REFERENCES lead_offices(id) ON DELETE SET NULL,
  ficha_id          TEXT,
  stage_entered_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(current_stage_id);
CREATE INDEX IF NOT EXISTS idx_leads_type  ON leads(lead_type_id);

CREATE TABLE IF NOT EXISTS lead_tag_assignments (
  lead_id TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  tag_id  TEXT NOT NULL REFERENCES lead_tags(id) ON DELETE CASCADE,
  PRIMARY KEY (lead_id, tag_id)
);

CREATE TABLE IF NOT EXISTS lead_forms (
  id      TEXT PRIMARY KEY,
  lead_id TEXT NOT NULL UNIQUE REFERENCES leads(id) ON DELETE CASCADE,
  data    TEXT NOT NULL DEFAULT '{}'           -- JSON
);

CREATE TABLE IF NOT EXISTS lead_comments (
  id               TEXT PRIMARY KEY,
  lead_id          TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  author_name      TEXT,
  body             TEXT NOT NULL,
  attachment_key   TEXT,
  attachment_name  TEXT,
  attachment_mime  TEXT,
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS lead_history (
  id          TEXT PRIMARY KEY,
  lead_id     TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  actor_name  TEXT,
  field       TEXT NOT NULL,
  old_value   TEXT,
  new_value   TEXT,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS lead_files (
  id           TEXT PRIMARY KEY,
  lead_id      TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  filename     TEXT NOT NULL,
  storage_key  TEXT NOT NULL,                  -- caminho no driver de storage
  size_bytes   INTEGER,
  mime_type    TEXT,
  uploaded_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS lead_checklist_items (
  id          TEXT PRIMARY KEY,
  lead_id     TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  stage_id    TEXT REFERENCES lead_stages(id) ON DELETE SET NULL,
  label       TEXT NOT NULL,
  done        INTEGER NOT NULL DEFAULT 0,
  position    INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
