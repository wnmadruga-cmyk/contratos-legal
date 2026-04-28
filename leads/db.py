"""
Camada de banco do módulo de Leads.

- Reusa o mesmo arquivo SQLite do projeto principal (`contratos.db`).
- Toda conexão tem `PRAGMA foreign_keys = ON` (caso contrário ON DELETE CASCADE é no-op).
- UUIDs gerados em Python (TEXT canonical com hifens).
- Timestamps ISO-8601 UTC com sufixo Z.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "contratos.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


# ---------------------------------------------------------------------------
# Conexão
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_cursor():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Init + seed
# ---------------------------------------------------------------------------

def init_db() -> None:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = f.read()
    with db_cursor() as conn:
        conn.executescript(schema)
    # Migrations: add columns if missing
    with db_cursor() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()]
        new_cols = {
            "ficha_id":              "TEXT",
            "op_baixo_risco":        "TEXT",
            "op_alvara":             "TEXT",
            "op_bombeiro":           "TEXT",
            "op_vigilancia":         "TEXT",
            "op_conselho":           "TEXT",
            "op_url_junta":               "TEXT",
            "op_link_assinatura_junta":   "TEXT",
            "op_organs_data":             "TEXT",
            "parent_lead_id":        "TEXT",
            "organ_type":            "TEXT",
            "client_token":          "TEXT",
            "client_access_code":    "TEXT",
            "due_date_junta":        "TEXT",
            "due_date_nf":           "TEXT",
        }
        for col, ctype in new_cols.items():
            if col not in cols:
                conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {ctype}")
    # Users migration: can_review
    with db_cursor() as conn:
        user_cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "can_review" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN can_review INTEGER DEFAULT 0")
    # New tables for approvals and guard events
    # Checklist templates (named groups)
    with db_cursor() as conn:
        conn.executescript("""
          CREATE TABLE IF NOT EXISTS checklist_templates (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            code        TEXT UNIQUE NOT NULL,
            description TEXT,
            is_default  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
          );
          CREATE TABLE IF NOT EXISTS checklist_template_items (
            id          TEXT PRIMARY KEY,
            template_id TEXT NOT NULL REFERENCES checklist_templates(id) ON DELETE CASCADE,
            label       TEXT NOT NULL,
            required    INTEGER NOT NULL DEFAULT 0,
            position    INTEGER NOT NULL DEFAULT 0
          );
        """)
    # Stage checklist_template_id column
    with db_cursor() as conn:
        stage_cols = [r[1] for r in conn.execute("PRAGMA table_info(lead_stages)").fetchall()]
        if "checklist_template_id" not in stage_cols:
            conn.execute("ALTER TABLE lead_stages ADD COLUMN checklist_template_id TEXT")
    # lead_checklist_items.required column (for stage completion guard)
    with db_cursor() as conn:
        chk_cols = [r[1] for r in conn.execute("PRAGMA table_info(lead_checklist_items)").fetchall()]
        if "required" not in chk_cols:
            conn.execute("ALTER TABLE lead_checklist_items ADD COLUMN required INTEGER NOT NULL DEFAULT 0")
    # lead_types.code column
    with db_cursor() as conn:
        lt_cols = [r[1] for r in conn.execute("PRAGMA table_info(lead_types)").fetchall()]
        if "code" not in lt_cols:
            conn.execute("ALTER TABLE lead_types ADD COLUMN code TEXT")
    # Notifications table migration
    with db_cursor() as conn:
        conn.executescript("""
          CREATE TABLE IF NOT EXISTS lead_notifications (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            lead_id     TEXT REFERENCES leads(id) ON DELETE CASCADE,
            type        TEXT NOT NULL,
            message     TEXT NOT NULL,
            actor_name  TEXT,
            read        INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
          );
          CREATE INDEX IF NOT EXISTS idx_notif_user ON lead_notifications(user_id, read, created_at DESC);
        """)
    with db_cursor() as conn:
        conn.executescript("""
          CREATE TABLE IF NOT EXISTS lead_approvals (
            id              TEXT PRIMARY KEY,
            lead_id         TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
            approval_type   TEXT NOT NULL,
            token           TEXT UNIQUE,
            access_code     TEXT DEFAULT '1234',
            status          TEXT NOT NULL DEFAULT 'pending',
            justification   TEXT,
            return_stage_id TEXT,
            resolved_by     TEXT,
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            resolved_at     TEXT
          );
          CREATE TABLE IF NOT EXISTS lead_guard_events (
            id            TEXT PRIMARY KEY,
            lead_id       TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
            event_type    TEXT NOT NULL,
            stage_from    TEXT,
            stage_to      TEXT,
            actor_name    TEXT,
            justification TEXT,
            created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
          );
          CREATE TABLE IF NOT EXISTS lead_stage_checklist_templates (
            id         TEXT PRIMARY KEY,
            stage_id   TEXT NOT NULL REFERENCES lead_stages(id) ON DELETE CASCADE,
            label      TEXT NOT NULL,
            position   INTEGER NOT NULL DEFAULT 0,
            required   INTEGER NOT NULL DEFAULT 0
          );
        """)
    # State signature manuals repository
    with db_cursor() as conn:
        conn.executescript("""
          CREATE TABLE IF NOT EXISTS lead_state_manuals (
            id          TEXT PRIMARY KEY,
            state_code  TEXT NOT NULL,
            name        TEXT NOT NULL,
            filename    TEXT NOT NULL,
            storage_key TEXT NOT NULL,
            size_bytes  INTEGER,
            created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
          );
          CREATE UNIQUE INDEX IF NOT EXISTS idx_state_manuals_code
            ON lead_state_manuals(state_code);
        """)
    _seed_defaults()
    # Recalculate deadlines for existing leads that are missing junta/nf dates
    with db_cursor() as conn:
        needs_recalc = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE due_date_junta IS NULL AND (parent_lead_id IS NULL OR parent_lead_id='')"
        ).fetchone()[0]
    if needs_recalc > 0:
        recalculate_all_deadlines()
    # Remove incorrect "Pedido de Nota Fiscal" lead type (it was a stage, not a service type)
    with db_cursor() as conn:
        conn.execute(
            "DELETE FROM lead_types WHERE name='Pedido de Nota Fiscal' AND id NOT IN (SELECT DISTINCT lead_type_id FROM leads WHERE lead_type_id IS NOT NULL)"
        )


def _seed_defaults() -> None:
    """Cria prioridades, status e um tipo de lead default se vazio."""
    with db_cursor() as conn:
        # Prioridades
        if conn.execute("SELECT COUNT(*) FROM lead_priorities").fetchone()[0] == 0:
            for pos, (name, color) in enumerate([
                ("Baixa",   "#94a3b8"),
                ("Normal",  "#3b82f6"),
                ("Alta",    "#f59e0b"),
                ("Urgente", "#ef4444"),
            ]):
                conn.execute(
                    "INSERT INTO lead_priorities (id,name,color,position) VALUES (?,?,?,?)",
                    (new_id(), name, color, pos),
                )

        # Status
        if conn.execute("SELECT COUNT(*) FROM lead_statuses").fetchone()[0] == 0:
            for pos, (name, color) in enumerate([
                ("Aberto",                 "#3b82f6"),
                ("Em andamento",           "#f59e0b"),
                ("Concluído",              "#10b981"),
                ("Cancelado",              "#6b7280"),
                ("Inativo Pedido Cliente", "#dc2626"),
            ]):
                conn.execute(
                    "INSERT INTO lead_statuses (id,name,color,position) VALUES (?,?,?,?)",
                    (new_id(), name, color, pos),
                )
        # Ensure "Inativo Pedido Cliente" exists (migration for existing DBs)
        if conn.execute("SELECT COUNT(*) FROM lead_statuses WHERE name='Inativo Pedido Cliente'").fetchone()[0] == 0:
            pos = conn.execute("SELECT COALESCE(MAX(position),0)+1 FROM lead_statuses").fetchone()[0]
            conn.execute(
                "INSERT INTO lead_statuses (id,name,color,position) VALUES (?,?,?,?)",
                (new_id(), "Inativo Pedido Cliente", "#dc2626", pos),
            )
        # Ensure pause statuses exist
        for _sname, _scolor in [("Aguardando Cliente", "#f59e0b"), ("Aguardando Órgão Público", "#8b5cf6")]:
            if conn.execute("SELECT COUNT(*) FROM lead_statuses WHERE name=?", (_sname,)).fetchone()[0] == 0:
                _pos = conn.execute("SELECT COALESCE(MAX(position),0)+1 FROM lead_statuses").fetchone()[0]
                conn.execute(
                    "INSERT INTO lead_statuses (id,name,color,position) VALUES (?,?,?,?)",
                    (new_id(), _sname, _scolor, _pos),
                )

        # Tipos + workflow + macrofases + etapas (default)
        if conn.execute("SELECT COUNT(*) FROM lead_types").fetchone()[0] == 0:
            ab_id = new_id()
            const_id = new_id()
            conn.execute(
                "INSERT INTO lead_types (id,name,color,active) VALUES (?,?,?,1)",
                (ab_id, "Abertura de Empresa", "#2456a4"),
            )
            conn.execute(
                "INSERT INTO lead_types (id,name,color,active) VALUES (?,?,?,1)",
                (const_id, "Constituição", "#10b981"),
            )
            wf_id = new_id()
            conn.execute(
                "INSERT INTO lead_workflows (id,lead_type_id,name,is_default) VALUES (?,?,?,1)",
                (wf_id, ab_id, "Padrão"),
            )
            mp_specs = [
                ("TRIAGEM E VIABILIDADE", 15, [
                    ("1. Coleta de Informações", 3),
                    ("2. Pedido de Viabilidade", 5),
                    ("3. Análise da Prefeitura", 7),
                ]),
                ("PRODUÇÃO E APROVAÇÃO", 16, [
                    ("4. Elaboração FCN e DBE", 3),
                    ("5. Redação de Contrato", 3),
                    ("6. Conferência Interna", 2),
                    ("7. Validação e Pagamento", 3),
                    ("8. Assinatura do Cliente", 5),
                ]),
                ("TRÂMITE JUNTA", 7, [
                    ("9. Protocolo na Junta", 2),
                    ("10. Em Exigência (Correções)", 5),
                ]),
                ("FINALIZAÇÃO", 21, [
                    ("11. Inscrições Fiscais", 5),
                    ("12. Licenças e Alvarás", 10),
                    ("13. Setup Contábil", 3),
                    ("14. Arquivo de Documentos", 2),
                    ("15. Comunicado de Conclusão", 1),
                ]),
            ]
            stage_pos = 0
            for mp_pos, (mp_name, mp_sla, stages) in enumerate(mp_specs):
                mp_id = new_id()
                conn.execute(
                    "INSERT INTO lead_macrophases (id,workflow_id,name,position,sla_days) VALUES (?,?,?,?,?)",
                    (mp_id, wf_id, mp_name, mp_pos, mp_sla),
                )
                for st_name, st_sla in stages:
                    conn.execute(
                        "INSERT INTO lead_stages (id,workflow_id,macrophase_id,name,position,sla_days) "
                        "VALUES (?,?,?,?,?,?)",
                        (new_id(), wf_id, mp_id, st_name, stage_pos, st_sla),
                    )
                    stage_pos += 1


# ---------------------------------------------------------------------------
# Deadline computation (CNPJ, Nota Fiscal, Total)
# ---------------------------------------------------------------------------

def compute_lead_deadlines(workflow_id: str, created_at: str) -> dict:
    """
    Returns {'due_date', 'due_date_junta', 'due_date_nf'} computed from the
    workflow SLAs and the creation date.

    Logic (based on standard 5-macrophase structure):
    - due_date       = created + sum(ALL stage SLAs)
    - due_date_junta = created + sum(stages in macrophases 0, 1, 2)
                       → the date CNPJ is expected to be issued
    - due_date_nf    = due_date_junta + FINALIZAÇÃO SLA + stages in LICENÇAS up to
                       the stage whose name contains "Liberação" and "Nota"
                       → when the Nota Fiscal should be available
    """
    import datetime as _dt
    try:
        created_date = _dt.datetime.fromisoformat(created_at.replace("Z", "+00:00")).date()
    except Exception:
        created_date = _dt.date.today()

    with db_cursor() as conn:
        macrophases = [dict(r) for r in conn.execute(
            "SELECT * FROM lead_macrophases WHERE workflow_id=? ORDER BY position",
            (workflow_id,)
        ).fetchall()]
        stages = [dict(r) for r in conn.execute(
            "SELECT * FROM lead_stages WHERE workflow_id=? ORDER BY position",
            (workflow_id,)
        ).fetchall()]

    if not stages:
        return {"due_date": None, "due_date_junta": None, "due_date_nf": None}

    # Map macrophase position → id
    mp_by_pos = {mp["position"]: mp["id"] for mp in macrophases}

    # Stages grouped by macrophase position
    stage_by_mp_pos: dict[int, list] = {}
    mp_pos_by_id = {mp["id"]: mp["position"] for mp in macrophases}
    for st in stages:
        mp_pos = mp_pos_by_id.get(st.get("macrophase_id"), 99)
        stage_by_mp_pos.setdefault(mp_pos, []).append(st)

    # due_date = sum of all SLAs
    total_sla = sum(s.get("sla_days") or 0 for s in stages)
    due_date = (created_date + _dt.timedelta(days=total_sla)).isoformat() if total_sla else None

    # due_date_junta = sum of stages in macrophases at positions 0, 1, 2
    # (Triagem + Produção + Trâmite Junta) — when CNPJ is issued
    junta_sla = sum(
        s.get("sla_days") or 0
        for pos in (0, 1, 2)
        for s in stage_by_mp_pos.get(pos, [])
    )
    due_date_junta = (created_date + _dt.timedelta(days=junta_sla)).isoformat() if junta_sla else None

    # due_date_nf: junta_sla + FINALIZAÇÃO stages (pos 3) + LICENÇAS stages up to
    # "Liberação de Nota Fiscal" (find by name, fallback to first 3 stages of LICENÇAS pos 4)
    finalizacao_sla = sum(s.get("sla_days") or 0 for s in stage_by_mp_pos.get(3, []))

    # Find NF stage in LICENÇAS (pos 4)
    licencas_stages = sorted(stage_by_mp_pos.get(4, []), key=lambda s: s.get("position", 0))
    nf_extra_sla = 0
    for st in licencas_stages:
        nf_extra_sla += st.get("sla_days") or 0
        name_upper = (st.get("name") or "").upper()
        if "LIBERA" in name_upper and ("NOTA" in name_upper or "NF" in name_upper or "FISCAL" in name_upper):
            break  # Stop accumulating after Liberação de Nota Fiscal
    else:
        # Fallback: first 3 stages of LICENÇAS
        nf_extra_sla = sum((s.get("sla_days") or 0) for s in licencas_stages[:3])

    nf_sla = junta_sla + finalizacao_sla + nf_extra_sla
    due_date_nf = (created_date + _dt.timedelta(days=nf_sla)).isoformat() if nf_sla else None

    return {
        "due_date": due_date,
        "due_date_junta": due_date_junta,
        "due_date_nf": due_date_nf,
    }


def recalculate_all_deadlines() -> int:
    """Recalculates due_date, due_date_junta, due_date_nf for all non-closed leads.
    Returns the number of leads updated."""
    with db_cursor() as conn:
        leads = [dict(r) for r in conn.execute(
            "SELECT id, workflow_id, created_at FROM leads WHERE parent_lead_id IS NULL OR parent_lead_id=''"
        ).fetchall()]
    updated = 0
    for lead in leads:
        try:
            dates = compute_lead_deadlines(lead["workflow_id"], lead["created_at"])
            with db_cursor() as conn:
                conn.execute(
                    "UPDATE leads SET due_date=?, due_date_junta=?, due_date_nf=? WHERE id=?",
                    (dates["due_date"], dates["due_date_junta"], dates["due_date_nf"], lead["id"])
                )
            updated += 1
        except Exception:
            pass
    return updated


# ---------------------------------------------------------------------------
# Helpers de leitura
# ---------------------------------------------------------------------------

def list_lead_types(active_only: bool = True) -> list[dict]:
    with db_cursor() as conn:
        sql = "SELECT * FROM lead_types"
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY name"
        return [dict(r) for r in conn.execute(sql).fetchall()]


def get_lead_type(type_id: str) -> Optional[dict]:
    with db_cursor() as conn:
        r = conn.execute("SELECT * FROM lead_types WHERE id=?", (type_id,)).fetchone()
        return dict(r) if r else None


def get_default_workflow(type_id: str = "") -> Optional[dict]:
    """Retorna o workflow global unificado para todos os seriços."""
    with db_cursor() as conn:
        r = conn.execute(
            "SELECT * FROM lead_workflows ORDER BY is_default DESC, name LIMIT 1"
        ).fetchone()
        return dict(r) if r else None


def list_workflows(type_id: str) -> list[dict]:
    with db_cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM lead_workflows WHERE lead_type_id=? ORDER BY name",
            (type_id,),
        ).fetchall()]


def list_macrophases(workflow_id: str) -> list[dict]:
    with db_cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM lead_macrophases WHERE workflow_id=? ORDER BY position",
            (workflow_id,),
        ).fetchall()]


def list_stages(workflow_id: str) -> list[dict]:
    with db_cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM lead_stages WHERE workflow_id=? ORDER BY position",
            (workflow_id,),
        ).fetchall()]


def get_stage(stage_id: str) -> Optional[dict]:
    with db_cursor() as conn:
        r = conn.execute("SELECT * FROM lead_stages WHERE id=?", (stage_id,)).fetchone()
        return dict(r) if r else None


def list_priorities() -> list[dict]:
    with db_cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM lead_priorities ORDER BY position"
        ).fetchall()]


def list_statuses() -> list[dict]:
    with db_cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM lead_statuses ORDER BY position"
        ).fetchall()]


def list_tags() -> list[dict]:
    with db_cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM lead_tags ORDER BY name"
        ).fetchall()]


def list_offices() -> list[dict]:
    with db_cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM lead_offices ORDER BY position"
        ).fetchall()]


# ---------------------------------------------------------------------------
# Leads — CRUD principal
# ---------------------------------------------------------------------------

def list_leads(filters: dict | None = None) -> list[dict]:
    """Lista leads com tags + nome de etapa/tipo/macrofase já agregados."""
    filters = filters or {}
    where = []
    params: list[Any] = []
    for key, col in [
        ("type",        "l.lead_type_id"),
        ("stage",       "l.current_stage_id"),
        ("priority",    "l.priority"),
        ("status",      "l.status"),
        ("responsible", "l.responsible_name"),
        ("office",      "l.office_id"),
    ]:
        v = filters.get(key)
        if v:
            where.append(f"{col} = ?")
            params.append(v)
    if filters.get("tag"):
        where.append("l.id IN (SELECT lead_id FROM lead_tag_assignments WHERE tag_id = ?)")
        params.append(filters["tag"])

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
      SELECT
        l.*,
        lt.name  AS type_name,  lt.color AS type_color,
        s.name   AS stage_name, s.position AS stage_position, s.sla_days AS stage_sla,
        s.macrophase_id AS macrophase_id,
        mp.name  AS macrophase_name,
        o.name   AS office_name, o.color AS office_color
      FROM leads l
      LEFT JOIN lead_types       lt ON lt.id = l.lead_type_id
      LEFT JOIN lead_stages      s  ON s.id  = l.current_stage_id
      LEFT JOIN lead_macrophases mp ON mp.id = s.macrophase_id
      LEFT JOIN lead_offices     o  ON o.id  = l.office_id
      {where_clause}
      ORDER BY l.created_at DESC
    """
    with db_cursor() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        # carrega tags do lead
        if rows:
            ids = [r["id"] for r in rows]
            placeholders = ",".join("?" * len(ids))
            tag_rows = conn.execute(
                f"""SELECT lta.lead_id, t.id, t.name, t.color
                    FROM lead_tag_assignments lta
                    JOIN lead_tags t ON t.id = lta.tag_id
                    WHERE lta.lead_id IN ({placeholders})""",
                ids,
            ).fetchall()
            by_lead: dict[str, list] = {}
            for tr in tag_rows:
                by_lead.setdefault(tr["lead_id"], []).append(
                    {"id": tr["id"], "name": tr["name"], "color": tr["color"]}
                )
            for r in rows:
                r["tags"] = by_lead.get(r["id"], [])
        return rows


def get_lead(lead_id: str) -> Optional[dict]:
    with db_cursor() as conn:
        r = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not r:
            return None
        lead = dict(r)
        lead["tags"] = [dict(t) for t in conn.execute(
            "SELECT t.* FROM lead_tag_assignments lta "
            "JOIN lead_tags t ON t.id = lta.tag_id WHERE lta.lead_id=?",
            (lead_id,),
        ).fetchall()]
        form = conn.execute(
            "SELECT data FROM lead_forms WHERE lead_id=?", (lead_id,)
        ).fetchone()
        lead["form_data"] = json.loads(form["data"]) if form else {}
        return lead


def create_lead(*, lead_type_id: str, name: str, priority: str = "Normal",
                status: str = "Aberto", description: str | None = None,
                responsible_name: str | None = None,
                due_date: str | None = None, office_id: str | None = None) -> str:
    import datetime as _dt
    wf = get_default_workflow(lead_type_id)
    if not wf:
        raise ValueError("Tipo de lead sem workflow configurado.")
    stages = list_stages(wf["id"])
    first_stage = stages[0]["id"] if stages else None
    created_now = now_iso()
    # Auto-compute all deadlines
    dates = compute_lead_deadlines(wf["id"], created_now)
    if not due_date:
        due_date = dates.get("due_date")
    due_date_junta = dates.get("due_date_junta")
    due_date_nf    = dates.get("due_date_nf")
    lead_id = new_id()
    with db_cursor() as conn:
        conn.execute(
            """INSERT INTO leads (id,lead_type_id,workflow_id,current_stage_id,
                                  name,responsible_name,status,priority,description,
                                  due_date,due_date_junta,due_date_nf,office_id,created_at,stage_entered_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (lead_id, lead_type_id, wf["id"], first_stage, name,
             responsible_name, status, priority, description,
             due_date, due_date_junta, due_date_nf, office_id, created_now, created_now),
        )
        conn.execute(
            "INSERT INTO lead_forms (id,lead_id,data) VALUES (?,?,'{}')",
            (new_id(), lead_id),
        )
    # Apply default checklist template to new lead
    default_tpl = get_default_checklist_template()
    if default_tpl:
        apply_checklist_template_to_lead(lead_id, default_tpl["id"])
    # Apply first stage template if any
    if first_stage:
        apply_stage_checklist_templates(lead_id, first_stage)
    return lead_id


def update_lead_fields(lead_id: str, fields: dict, actor: str | None = None) -> None:
    """Atualiza campos do lead e registra histórico campo a campo."""
    if not fields:
        return
    with db_cursor() as conn:
        current = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not current:
            raise ValueError("Lead não encontrado.")
        sets, params = [], []
        for k, v in fields.items():
            if k not in {
                "name", "responsible_name", "status", "priority",
                "description", "due_date", "due_date_junta", "due_date_nf",
                "current_stage_id", "office_id",
                "op_baixo_risco", "op_alvara", "op_bombeiro",
                "op_vigilancia", "op_conselho", "op_url_junta",
                "op_link_assinatura_junta",
                "op_organs_data", "parent_lead_id", "organ_type",
            }:
                continue
            old = current[k]
            if str(old or "") != str(v or ""):
                sets.append(f"{k}=?")
                params.append(v)
                conn.execute(
                    "INSERT INTO lead_history (id,lead_id,actor_name,field,old_value,new_value) "
                    "VALUES (?,?,?,?,?,?)",
                    (new_id(), lead_id, actor, k, str(old) if old else None,
                     str(v) if v else None),
                )
        if "current_stage_id" in fields:
            sets.append("stage_entered_at=?")
            params.append(now_iso())
        if sets:
            params.append(lead_id)
            conn.execute(f"UPDATE leads SET {', '.join(sets)} WHERE id=?", params)


def link_ficha(lead_id: str, ficha_id: str) -> None:
    with db_cursor() as conn:
        conn.execute("UPDATE leads SET ficha_id=? WHERE id=?", (ficha_id, lead_id))


def delete_lead(lead_id: str) -> None:
    with db_cursor() as conn:
        conn.execute("DELETE FROM leads WHERE id=?", (lead_id,))


def set_lead_tags(lead_id: str, tag_ids: Iterable[str]) -> None:
    with db_cursor() as conn:
        conn.execute("DELETE FROM lead_tag_assignments WHERE lead_id=?", (lead_id,))
        for tid in tag_ids:
            conn.execute(
                "INSERT OR IGNORE INTO lead_tag_assignments (lead_id,tag_id) VALUES (?,?)",
                (lead_id, tid),
            )


# ---------------------------------------------------------------------------
# Form / comments / history / files / checklist
# ---------------------------------------------------------------------------

def get_form_fields(type_id: str) -> list[dict]:
    with db_cursor() as conn:
        rows = conn.execute(
            "SELECT * FROM lead_form_fields WHERE lead_type_id=? "
            "ORDER BY position",
            (type_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["options"] = json.loads(d["options"]) if d.get("options") else None
            d["required"] = bool(d.get("required"))
            out.append(d)
        return out


def save_form_data(lead_id: str, data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    with db_cursor() as conn:
        existing = conn.execute(
            "SELECT id FROM lead_forms WHERE lead_id=?", (lead_id,)
        ).fetchone()
        if existing:
            conn.execute("UPDATE lead_forms SET data=? WHERE lead_id=?", (payload, lead_id))
        else:
            conn.execute(
                "INSERT INTO lead_forms (id,lead_id,data) VALUES (?,?,?)",
                (new_id(), lead_id, payload),
            )


def list_comments(lead_id: str) -> list[dict]:
    with db_cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM lead_comments WHERE lead_id=? ORDER BY created_at DESC",
            (lead_id,),
        ).fetchall()]


def add_comment(lead_id: str, body: str, author: str | None = None,
                attachment_key: str | None = None, attachment_name: str | None = None,
                attachment_mime: str | None = None) -> str:
    cid = new_id()
    ts = now_iso()
    with db_cursor() as conn:
        conn.execute(
            "INSERT INTO lead_comments "
            "(id,lead_id,author_name,body,attachment_key,attachment_name,attachment_mime,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (cid, lead_id, author, body, attachment_key, attachment_name, attachment_mime, ts),
        )
    return cid


def list_history(lead_id: str) -> list[dict]:
    with db_cursor() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM lead_history WHERE lead_id=? ORDER BY created_at DESC",
            (lead_id,),
        ).fetchall()]
        
        stage_ids = set()
        for r in rows:
            if r["field"] == "current_stage_id":
                if r["old_value"]: stage_ids.add(r["old_value"])
                if r["new_value"]: stage_ids.add(r["new_value"])
                
        if stage_ids:
            placeholders = ",".join("?" * len(stage_ids))
            stages = conn.execute(f"SELECT id, name FROM lead_stages WHERE id IN ({placeholders})", list(stage_ids)).fetchall()
            st_map = {st["id"]: st["name"] for st in stages}
            for r in rows:
                if r["field"] == "current_stage_id":
                    r["old_value_name"] = st_map.get(r["old_value"], r["old_value"]) if r["old_value"] else ""
                    r["new_value_name"] = st_map.get(r["new_value"], r["new_value"]) if r["new_value"] else ""
                    
        return rows


def list_files(lead_id: str) -> list[dict]:
    with db_cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM lead_files WHERE lead_id=? ORDER BY uploaded_at DESC",
            (lead_id,),
        ).fetchall()]


def add_file(lead_id: str, *, filename: str, storage_key: str,
             size_bytes: int | None, mime_type: str | None) -> str:
    fid = new_id()
    with db_cursor() as conn:
        conn.execute(
            """INSERT INTO lead_files
               (id,lead_id,filename,storage_key,size_bytes,mime_type)
               VALUES (?,?,?,?,?,?)""",
            (fid, lead_id, filename, storage_key, size_bytes, mime_type),
        )
    return fid


def get_file(file_id: str) -> Optional[dict]:
    with db_cursor() as conn:
        r = conn.execute("SELECT * FROM lead_files WHERE id=?", (file_id,)).fetchone()
        return dict(r) if r else None


def delete_file(file_id: str) -> Optional[dict]:
    """Remove o registro e retorna o dict (para o caller apagar do storage)."""
    rec = get_file(file_id)
    if rec:
        with db_cursor() as conn:
            conn.execute("DELETE FROM lead_files WHERE id=?", (file_id,))
    return rec


def list_checklist(lead_id: str) -> list[dict]:
    with db_cursor() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT ci.*, s.name AS stage_name FROM lead_checklist_items ci
               LEFT JOIN lead_stages s ON s.id = ci.stage_id
               WHERE ci.lead_id=? ORDER BY ci.position, ci.created_at""",
            (lead_id,),
        ).fetchall()]


def add_checklist_item(lead_id: str, label: str, stage_id: str | None = None,
                       required: bool = False) -> str:
    cid = new_id()
    with db_cursor() as conn:
        pos = conn.execute(
            "SELECT COALESCE(MAX(position),-1)+1 FROM lead_checklist_items WHERE lead_id=?",
            (lead_id,),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO lead_checklist_items (id,lead_id,stage_id,label,position,required)
               VALUES (?,?,?,?,?,?)""",
            (cid, lead_id, stage_id, label, pos, 1 if required else 0),
        )
    return cid


def toggle_checklist_item(item_id: str, done: bool) -> None:
    with db_cursor() as conn:
        conn.execute("UPDATE lead_checklist_items SET done=? WHERE id=?",
                     (1 if done else 0, item_id))


def delete_checklist_item(item_id: str) -> None:
    with db_cursor() as conn:
        conn.execute("DELETE FROM lead_checklist_items WHERE id=?", (item_id,))


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------

def create_approval(lead_id: str, approval_type: str, token: str | None = None,
                    access_code: str = '1234') -> str:
    aid = new_id()
    if token is None:
        token = str(uuid.uuid4()).replace('-', '')
    with db_cursor() as conn:
        conn.execute(
            """INSERT INTO lead_approvals (id, lead_id, approval_type, token, access_code, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
            (aid, lead_id, approval_type, token, access_code, now_iso()),
        )
    return aid


def get_approval(approval_id: str) -> Optional[dict]:
    with db_cursor() as conn:
        r = conn.execute("SELECT * FROM lead_approvals WHERE id=?", (approval_id,)).fetchone()
        return dict(r) if r else None


def get_approval_by_token(token: str) -> Optional[dict]:
    with db_cursor() as conn:
        r = conn.execute("SELECT * FROM lead_approvals WHERE token=?", (token,)).fetchone()
        return dict(r) if r else None


def get_lead_approval(lead_id: str, approval_type: str) -> Optional[dict]:
    """Returns the latest approval of a given type for a lead."""
    with db_cursor() as conn:
        r = conn.execute(
            "SELECT * FROM lead_approvals WHERE lead_id=? AND approval_type=? "
            "ORDER BY created_at DESC LIMIT 1",
            (lead_id, approval_type),
        ).fetchone()
        return dict(r) if r else None


def resolve_approval(approval_id: str, status: str, justification: str | None = None,
                     return_stage_id: str | None = None, resolved_by: str | None = None) -> None:
    with db_cursor() as conn:
        conn.execute(
            """UPDATE lead_approvals
               SET status=?, justification=?, return_stage_id=?, resolved_by=?, resolved_at=?
               WHERE id=?""",
            (status, justification, return_stage_id, resolved_by, now_iso(), approval_id),
        )


# ---------------------------------------------------------------------------
# Guard events
# ---------------------------------------------------------------------------

def log_guard_event(lead_id: str, event_type: str, stage_from: str | None,
                    stage_to: str | None, actor_name: str | None,
                    justification: str | None) -> str:
    eid = new_id()
    with db_cursor() as conn:
        conn.execute(
            """INSERT INTO lead_guard_events
               (id, lead_id, event_type, stage_from, stage_to, actor_name, justification, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (eid, lead_id, event_type, stage_from, stage_to, actor_name, justification, now_iso()),
        )
    return eid


def list_guard_events(lead_id: str | None = None) -> list[dict]:
    with db_cursor() as conn:
        if lead_id:
            rows = conn.execute(
                "SELECT ge.*, l.name AS lead_name FROM lead_guard_events ge "
                "LEFT JOIN leads l ON l.id = ge.lead_id "
                "WHERE ge.lead_id=? ORDER BY ge.created_at DESC",
                (lead_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT ge.*, l.name AS lead_name FROM lead_guard_events ge "
                "LEFT JOIN leads l ON l.id = ge.lead_id "
                "ORDER BY ge.created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Organ leads
# ---------------------------------------------------------------------------

def create_organ_lead(*, parent_lead_id: str, organ_type: str, name: str,
                      lead_type_id: str, responsible_name: str | None = None,
                      office_id: str | None = None) -> str:
    # Prefer the organ type's own workflow; fallback to global default
    organ_workflows = list_workflows(lead_type_id)
    wf = organ_workflows[0] if organ_workflows else None
    if not wf:
        wf = get_default_workflow()
    if not wf:
        with db_cursor() as conn:
            wf_row = conn.execute("SELECT * FROM lead_workflows LIMIT 1").fetchone()
            if wf_row:
                wf = dict(wf_row)
    stages = list_stages(wf["id"]) if wf else []

    # Try to find the first stage for this specific organ type inside the "LICENÇAS E ALVARÁS" macrophase
    # Stage names follow the pattern "<OrganLabel> — Protocolo do Pedido"
    ORGAN_LABEL_MAP = {
        "bombeiro":   "Bombeiro",
        "vigilancia": "Vigilância Sanitária",
        "conselho":   "Conselho de Classe",
        "alvara":     "Alvará",
    }
    first_stage = None
    if wf:
        organ_label = ORGAN_LABEL_MAP.get(organ_type, "")
        with db_cursor() as conn:
            mp_row = conn.execute(
                "SELECT id FROM lead_macrophases WHERE workflow_id=? AND "
                "(UPPER(name) LIKE '%LICEN%' OR UPPER(name) LIKE '%ALVAR%') "
                "ORDER BY position LIMIT 1",
                (wf["id"],),
            ).fetchone()
            if mp_row and organ_label:
                # First stage whose name starts with the organ label
                st_row = conn.execute(
                    "SELECT id FROM lead_stages WHERE workflow_id=? AND macrophase_id=? "
                    "AND name LIKE ? ORDER BY position LIMIT 1",
                    (wf["id"], mp_row["id"], f"{organ_label}%"),
                ).fetchone()
                if st_row:
                    first_stage = st_row["id"]
            # Fallback: first stage of the macrophase
            if not first_stage and mp_row:
                st_row = conn.execute(
                    "SELECT id FROM lead_stages WHERE workflow_id=? AND macrophase_id=? ORDER BY position LIMIT 1",
                    (wf["id"], mp_row["id"]),
                ).fetchone()
                if st_row:
                    first_stage = st_row["id"]

    # Fallback: first stage of whole workflow
    if not first_stage:
        first_stage = stages[0]["id"] if stages else None

    lead_id = new_id()
    with db_cursor() as conn:
        conn.execute(
            """INSERT INTO leads (id, lead_type_id, workflow_id, current_stage_id,
                                  name, responsible_name, status, priority,
                                  parent_lead_id, organ_type, office_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (lead_id, lead_type_id, wf["id"] if wf else "", first_stage, name,
             responsible_name, "Aberto", "Normal", parent_lead_id, organ_type, office_id),
        )
    return lead_id


# ---------------------------------------------------------------------------
# Stage checklist templates
# ---------------------------------------------------------------------------

def list_stage_checklist_templates(stage_id: str) -> list[dict]:
    with db_cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM lead_stage_checklist_templates WHERE stage_id=? ORDER BY position",
            (stage_id,),
        ).fetchall()]


def add_stage_checklist_template(stage_id: str, label: str, required: bool = False) -> str:
    tid = new_id()
    with db_cursor() as conn:
        pos = (conn.execute(
            "SELECT COALESCE(MAX(position),0)+1 FROM lead_stage_checklist_templates WHERE stage_id=?",
            (stage_id,)
        ).fetchone()[0])
        conn.execute(
            "INSERT INTO lead_stage_checklist_templates (id,stage_id,label,position,required) VALUES (?,?,?,?,?)",
            (tid, stage_id, label, pos, 1 if required else 0),
        )
    return tid


def delete_stage_checklist_template(tid: str) -> None:
    with db_cursor() as conn:
        conn.execute("DELETE FROM lead_stage_checklist_templates WHERE id=?", (tid,))


def apply_stage_checklist_templates(lead_id: str, stage_id: str) -> None:
    """When a lead enters a stage, auto-create checklist items from:
       1) Per-stage direct items (legacy)
       2) The linked checklist_template_id on the stage (new)
    """
    # 1. Per-stage direct items (existing behaviour)
    templates = list_stage_checklist_templates(stage_id)
    if templates:
        with db_cursor() as conn:
            existing_labels = {r[0] for r in conn.execute(
                "SELECT label FROM lead_checklist_items WHERE lead_id=? AND stage_id=?",
                (lead_id, stage_id),
            ).fetchall()}
            for t in templates:
                if t["label"] not in existing_labels:
                    conn.execute(
                        "INSERT INTO lead_checklist_items (id,lead_id,stage_id,label,done,required,position) VALUES (?,?,?,?,0,?,?)",
                        (new_id(), lead_id, stage_id, t["label"], 1 if t.get("required") else 0, t["position"]),
                    )
    # 2. Linked template
    with db_cursor() as conn:
        row = conn.execute(
            "SELECT checklist_template_id FROM lead_stages WHERE id=?", (stage_id,)
        ).fetchone()
    if row and row[0]:
        apply_checklist_template_to_lead(lead_id, row[0], stage_id=stage_id)


# ---------------------------------------------------------------------------
# Helpers extras
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Checklist template groups (named/reusable)
# ---------------------------------------------------------------------------

def list_checklist_templates() -> list[dict]:
    with db_cursor() as conn:
        rows = conn.execute(
            "SELECT * FROM checklist_templates ORDER BY name"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["items"] = [dict(i) for i in conn.execute(
                "SELECT * FROM checklist_template_items WHERE template_id=? ORDER BY position",
                (d["id"],),
            ).fetchall()]
            d["stages_using"] = [dict(s) for s in conn.execute(
                "SELECT id, name FROM lead_stages WHERE checklist_template_id=?",
                (d["id"],),
            ).fetchall()]
            result.append(d)
        return result


def get_checklist_template(tpl_id: str) -> Optional[dict]:
    with db_cursor() as conn:
        r = conn.execute("SELECT * FROM checklist_templates WHERE id=?", (tpl_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["items"] = [dict(i) for i in conn.execute(
            "SELECT * FROM checklist_template_items WHERE template_id=? ORDER BY position",
            (tpl_id,),
        ).fetchall()]
        return d


def create_checklist_template(name: str, code: str, description: str = "",
                               is_default: bool = False) -> str:
    tid = new_id()
    if is_default:
        # Only one default at a time
        with db_cursor() as conn:
            conn.execute("UPDATE checklist_templates SET is_default=0")
    with db_cursor() as conn:
        conn.execute(
            "INSERT INTO checklist_templates (id,name,code,description,is_default,created_at) VALUES (?,?,?,?,?,?)",
            (tid, name, code, description, 1 if is_default else 0, now_iso()),
        )
    return tid


def update_checklist_template(tpl_id: str, name: str, code: str,
                               description: str = "", is_default: bool = False) -> None:
    with db_cursor() as conn:
        if is_default:
            conn.execute("UPDATE checklist_templates SET is_default=0 WHERE id!=?", (tpl_id,))
        conn.execute(
            "UPDATE checklist_templates SET name=?,code=?,description=?,is_default=? WHERE id=?",
            (name, code, description, 1 if is_default else 0, tpl_id),
        )


def delete_checklist_template(tpl_id: str) -> None:
    with db_cursor() as conn:
        # Unlink stages
        conn.execute("UPDATE lead_stages SET checklist_template_id=NULL WHERE checklist_template_id=?", (tpl_id,))
        conn.execute("DELETE FROM checklist_templates WHERE id=?", (tpl_id,))


def add_checklist_template_item(template_id: str, label: str, required: bool = False) -> str:
    iid = new_id()
    with db_cursor() as conn:
        pos = conn.execute(
            "SELECT COALESCE(MAX(position),0)+1 FROM checklist_template_items WHERE template_id=?",
            (template_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO checklist_template_items (id,template_id,label,required,position) VALUES (?,?,?,?,?)",
            (iid, template_id, label, 1 if required else 0, pos),
        )
    return iid


def delete_checklist_template_item(item_id: str) -> None:
    with db_cursor() as conn:
        conn.execute("DELETE FROM checklist_template_items WHERE id=?", (item_id,))


def link_stage_checklist_template(stage_id: str, template_id: Optional[str]) -> None:
    with db_cursor() as conn:
        conn.execute(
            "UPDATE lead_stages SET checklist_template_id=? WHERE id=?",
            (template_id, stage_id),
        )


def apply_checklist_template_to_lead(lead_id: str, template_id: str,
                                      stage_id: Optional[str] = None) -> None:
    """Apply all items of a template to a lead (skip duplicates by label)."""
    tpl = get_checklist_template(template_id)
    if not tpl or not tpl["items"]:
        return
    with db_cursor() as conn:
        existing = {r[0] for r in conn.execute(
            "SELECT label FROM lead_checklist_items WHERE lead_id=?", (lead_id,)
        ).fetchall()}
        for item in tpl["items"]:
            if item["label"] not in existing:
                pos = conn.execute(
                    "SELECT COALESCE(MAX(position),-1)+1 FROM lead_checklist_items WHERE lead_id=?",
                    (lead_id,),
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO lead_checklist_items (id,lead_id,stage_id,label,done,required,position) VALUES (?,?,?,?,0,?,?)",
                    (new_id(), lead_id, stage_id, item["label"], 1 if item.get("required") else 0, pos),
                )


def check_stage_checklist_complete(lead_id: str, stage_id: str) -> tuple[bool, list[str]]:
    """Returns (is_complete, list_of_pending_required_labels) for a stage's checklist.
    Only checks items that are required=1 and done=0 for this specific stage."""
    with db_cursor() as conn:
        rows = conn.execute(
            "SELECT label FROM lead_checklist_items WHERE lead_id=? AND stage_id=? AND required=1 AND done=0",
            (lead_id, stage_id),
        ).fetchall()
    missing = [r[0] for r in rows]
    return len(missing) == 0, missing


def get_default_checklist_template() -> Optional[dict]:
    with db_cursor() as conn:
        r = conn.execute(
            "SELECT * FROM checklist_templates WHERE is_default=1 LIMIT 1"
        ).fetchone()
        return dict(r) if r else None


def get_stage_with_template(stage_id: str) -> Optional[dict]:
    with db_cursor() as conn:
        r = conn.execute("SELECT * FROM lead_stages WHERE id=?", (stage_id,)).fetchone()
        return dict(r) if r else None


ORGAN_TYPE_CODES = ("bombeiro", "vigilancia", "conselho")


def list_organ_lead_types() -> list[dict]:
    """Returns the 3 organ lead types in fixed order: Vigilância → Bombeiro → Conselho."""
    _order = {"vigilancia": 0, "bombeiro": 1, "conselho": 2}
    with db_cursor() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM lead_types WHERE code IN ('bombeiro','vigilancia','conselho')"
        ).fetchall()]
    rows.sort(key=lambda x: _order.get(x.get("code", ""), 99))
    return rows


def get_lead_type_by_code(code: str) -> Optional[dict]:
    with db_cursor() as conn:
        r = conn.execute("SELECT * FROM lead_types WHERE code=?", (code,)).fetchone()
        return dict(r) if r else None


def get_lead_children(lead_id: str) -> list[dict]:
    """Returns child organ leads with current stage name."""
    with db_cursor() as conn:
        rows = conn.execute(
            """SELECT l.*, lt.name AS type_name, lt.color AS type_color,
                      s.name AS stage_name, s.position AS stage_position
               FROM leads l
               LEFT JOIN lead_types  lt ON lt.id = l.lead_type_id
               LEFT JOIN lead_stages s  ON s.id  = l.current_stage_id
               WHERE l.parent_lead_id = ?
               ORDER BY l.created_at""",
            (lead_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_lead_parent(lead_id: str) -> Optional[dict]:
    """Returns the parent lead if this is a child organ card."""
    with db_cursor() as conn:
        child = conn.execute("SELECT parent_lead_id FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not child or not child["parent_lead_id"]:
            return None
        r = conn.execute(
            "SELECT l.*, lt.name AS type_name FROM leads l "
            "LEFT JOIN lead_types lt ON lt.id = l.lead_type_id "
            "WHERE l.id=?", (child["parent_lead_id"],)
        ).fetchone()
        return dict(r) if r else None


def get_last_stage(workflow_id: str) -> Optional[dict]:
    """Returns the highest-position stage in a workflow (used for auto-move on close)."""
    with db_cursor() as conn:
        r = conn.execute(
            "SELECT * FROM lead_stages WHERE workflow_id=? ORDER BY position DESC LIMIT 1",
            (workflow_id,),
        ).fetchone()
        return dict(r) if r else None


def ensure_tag(name: str, color: str = "#64748b") -> str:
    """Returns existing tag id or creates the tag. Thread-safe via INSERT OR IGNORE."""
    with db_cursor() as conn:
        row = conn.execute("SELECT id FROM lead_tags WHERE name=?", (name,)).fetchone()
        if row:
            return row[0]
        tid = new_id()
        conn.execute(
            "INSERT OR IGNORE INTO lead_tags (id, name, color) VALUES (?, ?, ?)",
            (tid, name, color),
        )
        row2 = conn.execute("SELECT id FROM lead_tags WHERE name=?", (name,)).fetchone()
        return row2[0] if row2 else tid


def apply_tag_to_lead(lead_id: str, tag_name: str, color: str = "#64748b") -> None:
    """Ensures a tag exists and assigns it to the lead (idempotent)."""
    tag_id = ensure_tag(tag_name, color)
    with db_cursor() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO lead_tag_assignments (lead_id, tag_id) VALUES (?, ?)",
            (lead_id, tag_id),
        )


def remove_tag_from_lead(lead_id: str, tag_name: str) -> None:
    """Removes a named tag from a lead if it exists."""
    with db_cursor() as conn:
        row = conn.execute("SELECT id FROM lead_tags WHERE name=?", (tag_name,)).fetchone()
        if row:
            conn.execute(
                "DELETE FROM lead_tag_assignments WHERE lead_id=? AND tag_id=?",
                (lead_id, row[0]),
            )


def sync_sem_atividade_tag(lead_id: str, ficha_dados: dict) -> None:
    """Applies or removes 'Sem atividade no local' tag based on all activities in ficha."""
    empresa = ficha_dados.get("empresa", {})
    atividades = empresa.get("atividades", [])
    if not atividades:
        return
    all_sem = all(not ativ.get("desenvolvidaNoLocal", True) for ativ in atividades if ativ.get("cnae"))
    if all_sem:
        apply_tag_to_lead(lead_id, "Sem atividade no local", "#f59e0b")
    else:
        remove_tag_from_lead(lead_id, "Sem atividade no local")


def list_users() -> list[dict]:
    """Returns all users (delegates to main DB)."""
    with db_cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, name, email, profile FROM users ORDER BY name"
        ).fetchall()]


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

CLOSED_STATUS_NAMES = {"Cancelado", "Inativo Pedido Cliente"}
# Statuses that require a comment/justification (superset of CLOSED — includes pause statuses)
COMMENT_REQUIRED_STATUS_NAMES = {"Cancelado", "Inativo Pedido Cliente",
                                  "Aguardando Cliente", "Aguardando Órgão Público"}


def create_notification(user_id: str, lead_id: str, notif_type: str,
                        message: str, actor_name: str | None = None) -> str:
    nid = new_id()
    with db_cursor() as conn:
        conn.execute(
            """INSERT INTO lead_notifications (id,user_id,lead_id,type,message,actor_name,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (nid, user_id, lead_id, notif_type, message, actor_name, now_iso()),
        )
    return nid


def list_notifications(user_id: str, limit: int = 30) -> list[dict]:
    with db_cursor() as conn:
        rows = conn.execute(
            """SELECT n.*, l.name AS lead_name
               FROM lead_notifications n
               LEFT JOIN leads l ON l.id = n.lead_id
               WHERE n.user_id = ?
               ORDER BY n.created_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def count_unread_notifications(user_id: str) -> int:
    with db_cursor() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM lead_notifications WHERE user_id=? AND read=0",
            (user_id,),
        ).fetchone()[0]


def mark_notification_read(notif_id: str) -> None:
    with db_cursor() as conn:
        conn.execute("UPDATE lead_notifications SET read=1 WHERE id=?", (notif_id,))


def mark_all_notifications_read(user_id: str) -> None:
    with db_cursor() as conn:
        conn.execute("UPDATE lead_notifications SET read=1 WHERE user_id=?", (user_id,))


# ---------------------------------------------------------------------------
# Analytics Dashboard
# ---------------------------------------------------------------------------

def get_analytics_data(month: int, year: int) -> dict:
    """Returns complete analytics data for the given month/year."""
    import datetime as _dt
    today = _dt.date.today()
    today_str = today.isoformat()

    month_start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        month_end = f"{year + 1:04d}-01-01"
    else:
        month_end = f"{year:04d}-{month + 1:02d}-01"

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    prev_start = f"{prev_year:04d}-{prev_month:02d}-01"
    prev_end = month_start

    ROOT = "(l.parent_lead_id IS NULL OR l.parent_lead_id = '')"

    with db_cursor() as conn:
        def q(sql, params=()):
            return conn.execute(sql, params).fetchall()

        created_mes = q(
            f"SELECT COUNT(*) FROM leads l WHERE l.created_at >= ? AND l.created_at < ? AND {ROOT}",
            (month_start, month_end)
        )[0][0]

        created_prev = q(
            f"SELECT COUNT(*) FROM leads l WHERE l.created_at >= ? AND l.created_at < ? AND {ROOT}",
            (prev_start, prev_end)
        )[0][0]

        finalizados_mes = q(
            """SELECT COUNT(DISTINCT lead_id) FROM lead_history
               WHERE field='status' AND new_value='Concluído'
               AND created_at >= ? AND created_at < ?""",
            (month_start, month_end)
        )[0][0]

        finalizados_prev = q(
            """SELECT COUNT(DISTINCT lead_id) FROM lead_history
               WHERE field='status' AND new_value='Concluído'
               AND created_at >= ? AND created_at < ?""",
            (prev_start, prev_end)
        )[0][0]

        total_ativos = q(
            f"""SELECT COUNT(*) FROM leads l
               WHERE l.status NOT IN ('Concluído','Cancelado','Inativo Pedido Cliente') AND {ROOT}"""
        )[0][0]

        total_concluidos_all = q(
            f"SELECT COUNT(*) FROM leads l WHERE l.status='Concluído' AND {ROOT}"
        )[0][0]

        total_cancelados_all = q(
            f"""SELECT COUNT(*) FROM leads l
               WHERE l.status IN ('Cancelado','Inativo Pedido Cliente') AND {ROOT}"""
        )[0][0]

        total_all = q(f"SELECT COUNT(*) FROM leads l WHERE {ROOT}")[0][0]

        total_atrasados = q(
            f"""SELECT COUNT(*) FROM leads l
               WHERE l.due_date < ? AND l.status NOT IN ('Concluído','Cancelado','Inativo Pedido Cliente')
               AND {ROOT}""",
            (today_str,)
        )[0][0]

        total_atrasados_cnpj = q(
            f"""SELECT COUNT(*) FROM leads l
               WHERE l.due_date_junta IS NOT NULL AND l.due_date_junta < ?
               AND l.status NOT IN ('Concluído','Cancelado','Inativo Pedido Cliente') AND {ROOT}""",
            (today_str,)
        )[0][0]

        total_atrasados_nf = q(
            f"""SELECT COUNT(*) FROM leads l
               WHERE l.due_date_nf IS NOT NULL AND l.due_date_nf < ?
               AND l.status NOT IN ('Concluído','Cancelado','Inativo Pedido Cliente') AND {ROOT}""",
            (today_str,)
        )[0][0]

        total_urgentes = q(
            f"""SELECT COUNT(*) FROM leads l
               WHERE l.priority='Urgente' AND l.status NOT IN ('Concluído','Cancelado','Inativo Pedido Cliente')
               AND {ROOT}"""
        )[0][0]

        # Detailed lists
        atrasados_list = [dict(r) for r in q(
            f"""SELECT l.id, l.name, l.responsible_name,
                       l.due_date, l.due_date_junta, l.due_date_nf,
                       l.priority, l.status,
                       lt.name as type_name, lt.color as type_color,
                       s.name as stage_name, mp.name as macrophase_name,
                       CAST(julianday('now') - julianday(l.due_date) AS INTEGER) as dias_atraso,
                       CASE WHEN l.due_date_junta < '{today_str}' THEN CAST(julianday('now') - julianday(l.due_date_junta) AS INTEGER) ELSE NULL END as dias_atraso_cnpj,
                       CASE WHEN l.due_date_nf < '{today_str}' THEN CAST(julianday('now') - julianday(l.due_date_nf) AS INTEGER) ELSE NULL END as dias_atraso_nf
               FROM leads l
               LEFT JOIN lead_types lt ON lt.id = l.lead_type_id
               LEFT JOIN lead_stages s ON s.id = l.current_stage_id
               LEFT JOIN lead_macrophases mp ON mp.id = s.macrophase_id
               WHERE (l.due_date < ? OR l.due_date_junta < ? OR l.due_date_nf < ?)
               AND l.status NOT IN ('Concluído','Cancelado','Inativo Pedido Cliente')
               AND {ROOT}
               ORDER BY l.due_date ASC LIMIT 25""",
            (today_str, today_str, today_str)
        )]

        mais_antigos_list = [dict(r) for r in q(
            f"""SELECT l.id, l.name, l.responsible_name, l.created_at, l.due_date, l.priority, l.status,
                       lt.name as type_name, lt.color as type_color,
                       s.name as stage_name, mp.name as macrophase_name,
                       CAST(julianday('now') - julianday(l.created_at) AS INTEGER) as dias_aberto
               FROM leads l
               LEFT JOIN lead_types lt ON lt.id = l.lead_type_id
               LEFT JOIN lead_stages s ON s.id = l.current_stage_id
               LEFT JOIN lead_macrophases mp ON mp.id = s.macrophase_id
               WHERE l.status NOT IN ('Concluído','Cancelado','Inativo Pedido Cliente') AND {ROOT}
               ORDER BY l.created_at ASC LIMIT 15"""
        )]

        parados_list = [dict(r) for r in q(
            f"""SELECT l.id, l.name, l.responsible_name, l.stage_entered_at, l.priority, l.status,
                       lt.name as type_name, lt.color as type_color,
                       s.name as stage_name, s.sla_days as stage_sla,
                       mp.name as macrophase_name,
                       CAST(julianday('now') - julianday(l.stage_entered_at) AS INTEGER) as dias_na_etapa
               FROM leads l
               LEFT JOIN lead_types lt ON lt.id = l.lead_type_id
               LEFT JOIN lead_stages s ON s.id = l.current_stage_id
               LEFT JOIN lead_macrophases mp ON mp.id = s.macrophase_id
               WHERE l.status NOT IN ('Concluído','Cancelado','Inativo Pedido Cliente') AND {ROOT}
               ORDER BY l.stage_entered_at ASC LIMIT 15"""
        )]

        sem_retorno_list = [dict(r) for r in q(
            f"""SELECT l.id, l.name, l.responsible_name, l.stage_entered_at, l.priority, l.status,
                       lt.name as type_name, lt.color as type_color,
                       s.name as stage_name, mp.name as macrophase_name,
                       CAST(julianday('now') - julianday(l.stage_entered_at) AS INTEGER) as dias_aguardando
               FROM leads l
               LEFT JOIN lead_types lt ON lt.id = l.lead_type_id
               LEFT JOIN lead_stages s ON s.id = l.current_stage_id
               LEFT JOIN lead_macrophases mp ON mp.id = s.macrophase_id
               WHERE l.status NOT IN ('Concluído','Cancelado','Inativo Pedido Cliente') AND {ROOT}
               AND (UPPER(s.name) LIKE '%CLIENTE%' OR UPPER(s.name) LIKE '%ASSINATURA%'
                    OR UPPER(s.name) LIKE '%APROVAÇÃO%' OR UPPER(s.name) LIKE '%APROVACAO%'
                    OR UPPER(s.name) LIKE '%VALIDAÇÃO%' OR UPPER(s.name) LIKE '%VALIDACAO%')
               AND julianday('now') - julianday(l.stage_entered_at) > 2
               ORDER BY dias_aguardando DESC LIMIT 15"""
        )]

        rework_list = [dict(r) for r in q(
            f"""SELECT ge.lead_id, l.name, l.responsible_name,
                       lt.name as type_name, lt.color as type_color,
                       s.name as stage_name, mp.name as macrophase_name,
                       COUNT(*) as rework_count,
                       MAX(ge.created_at) as last_rework,
                       ge.justification as ultima_justificativa
               FROM lead_guard_events ge
               JOIN leads l ON l.id = ge.lead_id
               LEFT JOIN lead_types lt ON lt.id = l.lead_type_id
               LEFT JOIN lead_stages s ON s.id = l.current_stage_id
               LEFT JOIN lead_macrophases mp ON mp.id = s.macrophase_id
               WHERE ge.event_type IN ('rejected', 'backward', 'returned', 'review_rejected')
               GROUP BY ge.lead_id
               ORDER BY rework_count DESC, last_rework DESC LIMIT 10"""
        )]

        reprovados_list = [dict(r) for r in q(
            f"""SELECT la.lead_id, l.name, l.responsible_name,
                       lt.name as type_name, lt.color as type_color,
                       s.name as stage_name, mp.name as macrophase_name,
                       COUNT(*) as reject_count,
                       MAX(la.resolved_at) as last_reject,
                       la.justification as ultima_justificativa
               FROM lead_approvals la
               JOIN leads l ON l.id = la.lead_id
               LEFT JOIN lead_types lt ON lt.id = l.lead_type_id
               LEFT JOIN lead_stages s ON s.id = l.current_stage_id
               LEFT JOIN lead_macrophases mp ON mp.id = s.macrophase_id
               WHERE la.status = 'rejected' AND {ROOT.replace('l.', 'l.')}
               GROUP BY la.lead_id
               ORDER BY reject_count DESC LIMIT 10"""
        )]

        by_type = [dict(r) for r in q(
            f"""SELECT lt.name, lt.color, COUNT(*) as cnt
               FROM leads l JOIN lead_types lt ON lt.id = l.lead_type_id
               WHERE {ROOT}
               GROUP BY lt.id ORDER BY cnt DESC"""
        )]

        by_type_active = [dict(r) for r in q(
            f"""SELECT lt.name, lt.color, COUNT(*) as cnt
               FROM leads l JOIN lead_types lt ON lt.id = l.lead_type_id
               WHERE l.status NOT IN ('Concluído','Cancelado','Inativo Pedido Cliente') AND {ROOT}
               GROUP BY lt.id ORDER BY cnt DESC"""
        )]

        by_macrophase = [dict(r) for r in q(
            f"""SELECT COALESCE(mp.name,'Sem etapa') as name, COUNT(*) as cnt
               FROM leads l
               LEFT JOIN lead_stages s ON s.id = l.current_stage_id
               LEFT JOIN lead_macrophases mp ON mp.id = s.macrophase_id
               WHERE l.status NOT IN ('Concluído','Cancelado','Inativo Pedido Cliente') AND {ROOT}
               GROUP BY mp.name ORDER BY cnt DESC"""
        )]

        by_responsible = [dict(r) for r in q(
            f"""SELECT COALESCE(l.responsible_name,'Não atribuído') as name,
                       COUNT(*) as cnt,
                       SUM(CASE WHEN l.due_date < '{today_str}' THEN 1 ELSE 0 END) as atrasados
               FROM leads l
               WHERE l.status NOT IN ('Concluído','Cancelado','Inativo Pedido Cliente') AND {ROOT}
               GROUP BY l.responsible_name ORDER BY cnt DESC LIMIT 12"""
        )]

        # 12-month trend
        trend = []
        for i in range(11, -1, -1):
            m_date = _dt.date(today.year, today.month, 1)
            m_m = today.month - i
            m_y = today.year
            while m_m <= 0:
                m_m += 12
                m_y -= 1
            m_start = f"{m_y:04d}-{m_m:02d}-01"
            if m_m == 12:
                m_end = f"{m_y + 1:04d}-01-01"
            else:
                m_end = f"{m_y:04d}-{m_m + 1:02d}-01"
            opened = q(
                f"SELECT COUNT(*) FROM leads l WHERE l.created_at >= ? AND l.created_at < ? AND {ROOT}",
                (m_start, m_end)
            )[0][0]
            closed = q(
                """SELECT COUNT(DISTINCT lead_id) FROM lead_history
                   WHERE field='status' AND new_value='Concluído'
                   AND created_at >= ? AND created_at < ?""",
                (m_start, m_end)
            )[0][0]
            trend.append({"label": f"{m_m:02d}/{m_y}", "abertos": opened, "concluidos": closed})

        return {
            "month": month, "year": year,
            "month_label": f"{month:02d}/{year}",
            "created_mes": created_mes,
            "created_prev": created_prev,
            "finalizados_mes": finalizados_mes,
            "finalizados_prev": finalizados_prev,
            "total_ativos": total_ativos,
            "total_concluidos_all": total_concluidos_all,
            "total_cancelados_all": total_cancelados_all,
            "total_all": total_all,
            "total_atrasados": total_atrasados,
            "total_atrasados_cnpj": total_atrasados_cnpj,
            "total_atrasados_nf": total_atrasados_nf,
            "total_urgentes": total_urgentes,
            "atrasados_list": atrasados_list,
            "mais_antigos_list": mais_antigos_list,
            "parados_list": parados_list,
            "sem_retorno_list": sem_retorno_list,
            "rework_list": rework_list,
            "reprovados_list": reprovados_list,
            "by_type": by_type,
            "by_type_active": by_type_active,
            "by_macrophase": by_macrophase,
            "by_responsible": by_responsible,
            "trend": trend,
        }


# ---------------------------------------------------------------------------
# Client Portal (Token)
# ---------------------------------------------------------------------------

def get_or_create_client_token(lead_id: str) -> tuple:
    """Returns (token, access_code) for a lead's client portal. Creates if missing."""
    import secrets as _sec
    with db_cursor() as conn:
        row = conn.execute(
            "SELECT client_token, client_access_code FROM leads WHERE id=?", (lead_id,)
        ).fetchone()
        if row and row[0]:
            return row[0], row[1] or "1234"
    token = _sec.token_urlsafe(20)
    code = str(_sec.randbelow(9000) + 1000)
    with db_cursor() as conn:
        conn.execute(
            "UPDATE leads SET client_token=?, client_access_code=? WHERE id=?",
            (token, code, lead_id)
        )
    return token, code


def get_lead_by_client_token(token: str) -> Optional[dict]:
    with db_cursor() as conn:
        r = conn.execute(
            """SELECT l.*, lt.name as type_name, lt.color as type_color,
                      s.name as stage_name, s.position as stage_position, s.sla_days as stage_sla,
                      s.macrophase_id as stage_macrophase_id,
                      mp.name as macrophase_name, mp.position as macrophase_position, mp.sla_days as macrophase_sla
               FROM leads l
               LEFT JOIN lead_types lt ON lt.id = l.lead_type_id
               LEFT JOIN lead_stages s ON s.id = l.current_stage_id
               LEFT JOIN lead_macrophases mp ON mp.id = s.macrophase_id
               WHERE l.client_token=?""",
            (token,)
        ).fetchone()
        return dict(r) if r else None


def get_client_portal_data(lead_id: str) -> Optional[dict]:
    """Returns full data for the client portal page (compute phase info)."""
    import datetime as _dt
    today = _dt.date.today()

    with db_cursor() as conn:
        lead = conn.execute(
            """SELECT l.*, lt.name as type_name, lt.color as type_color,
                      s.name as stage_name, s.position as stage_position, s.sla_days as stage_sla,
                      s.macrophase_id as stage_macrophase_id,
                      mp.name as macrophase_name, mp.position as macrophase_position, mp.sla_days as macrophase_sla
               FROM leads l
               LEFT JOIN lead_types lt ON lt.id = l.lead_type_id
               LEFT JOIN lead_stages s ON s.id = l.current_stage_id
               LEFT JOIN lead_macrophases mp ON mp.id = s.macrophase_id
               WHERE l.id=?""",
            (lead_id,)
        ).fetchone()
        if not lead:
            return None
        lead = dict(lead)

        wf_id = lead.get("workflow_id", "")
        all_stages = [dict(r) for r in conn.execute(
            "SELECT * FROM lead_stages WHERE workflow_id=? ORDER BY position",
            (wf_id,)
        ).fetchall()]
        all_macrophases = [dict(r) for r in conn.execute(
            "SELECT * FROM lead_macrophases WHERE workflow_id=? ORDER BY position",
            (wf_id,)
        ).fetchall()]

        # History of stage changes (to detect macrophase entry times)
        stage_history = [dict(r) for r in conn.execute(
            """SELECT lh.new_value as stage_id, lh.created_at,
                      ls.macrophase_id
               FROM lead_history lh
               LEFT JOIN lead_stages ls ON ls.id = lh.new_value
               WHERE lh.lead_id=? AND lh.field='current_stage_id'
               ORDER BY lh.created_at ASC""",
            (lead_id,)
        ).fetchall()]

    # Build macrophase entry times from history
    mp_entry = {}
    for h in stage_history:
        mp_id = h.get("macrophase_id")
        if mp_id and mp_id not in mp_entry:
            mp_entry[mp_id] = h["created_at"]

    # Include current macrophase if not seen in history
    cur_mp_id = lead.get("stage_macrophase_id")
    if cur_mp_id and cur_mp_id not in mp_entry:
        mp_entry[cur_mp_id] = lead.get("stage_entered_at") or lead.get("created_at")

    # 5 client-visible phases (map DB macrophases → client phases)
    # If the DB has >= 4 macrophases, we split the first one into Triagem + Viabilidade
    # by treating the first 2 stages of macrophase[0] as "Triagem" and the rest as "Viabilidade"

    CLIENT_PHASES = [
        {"key": "triagem",    "label": "Triagem",              "icon": "bi-clipboard-check",
         "desc": "Coleta de informações e pedido de viabilidade"},
        {"key": "viabilidade","label": "Viabilidade",           "icon": "bi-building-check",
         "desc": "Análise técnica e parecer da prefeitura"},
        {"key": "producao",   "label": "Produção e Aprovação",  "icon": "bi-file-earmark-check",
         "desc": "Elaboração dos documentos e aprovação"},
        {"key": "junta",      "label": "Trâmite na Junta",      "icon": "bi-bank",
         "desc": "Registro na Junta Comercial"},
        {"key": "cadastros",  "label": "Cadastros",             "icon": "bi-patch-check",
         "desc": "Inscrições fiscais e registros municipais"},
        {"key": "licencas",   "label": "Licenças e Alvarás",    "icon": "bi-shield-check",
         "desc": "Obtenção de alvarás, licenças e liberação de nota fiscal"},
    ]

    # Assign stage positions to client phases
    # Phase 0 (Triagem) = stages 0..N where N = int(len(mp0_stages)/2) - special split
    # Phase 1 (Viabilidade) = remaining stages in macrophase 0
    # Phases 2–4 = macrophases 1–3
    stages_by_mp = {}
    for st in all_stages:
        stages_by_mp.setdefault(st.get("macrophase_id", ""), []).append(st)

    mp0_stages = stages_by_mp.get(all_macrophases[0]["id"], []) if all_macrophases else []
    split = max(1, len(mp0_stages) - 1)  # last stage of mp0 = "Análise da Prefeitura" → viabilidade

    # Assign each stage a client_phase_key
    stage_phase_map = {}
    for st in mp0_stages[:split]:
        stage_phase_map[st["id"]] = "triagem"
    for st in mp0_stages[split:]:
        stage_phase_map[st["id"]] = "viabilidade"

    if len(all_macrophases) > 1:
        for st in stages_by_mp.get(all_macrophases[1]["id"], []):
            stage_phase_map[st["id"]] = "producao"
    if len(all_macrophases) > 2:
        for st in stages_by_mp.get(all_macrophases[2]["id"], []):
            stage_phase_map[st["id"]] = "junta"
    if len(all_macrophases) > 3:
        for st in stages_by_mp.get(all_macrophases[3]["id"], []):
            stage_phase_map[st["id"]] = "cadastros"
    if len(all_macrophases) > 4:
        for st in stages_by_mp.get(all_macrophases[4]["id"], []):
            stage_phase_map[st["id"]] = "licencas"

    # Compute SLA per client phase
    phase_sla = {p["key"]: 0 for p in CLIENT_PHASES}
    for st in all_stages:
        pk = stage_phase_map.get(st["id"])
        if pk and st.get("sla_days"):
            phase_sla[pk] += st["sla_days"]

    # Current stage's client phase
    cur_stage_id = lead.get("current_stage_id", "")
    cur_phase_key = stage_phase_map.get(cur_stage_id, "triagem")

    # Phases completed = all client phases before current
    phase_keys = [p["key"] for p in CLIENT_PHASES]
    cur_idx = phase_keys.index(cur_phase_key) if cur_phase_key in phase_keys else 0

    # Days in current client phase
    # Look at when first stage of this phase was entered via history
    phase_stage_ids = [sid for sid, pk in stage_phase_map.items() if pk == cur_phase_key]
    phase_entry_time = None
    for h in stage_history:
        if h["stage_id"] in phase_stage_ids:
            phase_entry_time = h["created_at"]
            break
    if not phase_entry_time:
        phase_entry_time = lead.get("stage_entered_at") or lead.get("created_at", "")

    import datetime as _dt2
    try:
        entry_dt = _dt2.datetime.fromisoformat(phase_entry_time.replace("Z", "+00:00"))
        days_in_phase = max(0, (_dt2.datetime.now(_dt2.timezone.utc) - entry_dt).days)
    except Exception:
        days_in_phase = 0

    # Total remaining SLA (from current stage to end)
    cur_pos = lead.get("stage_position") or 0
    remaining_sla = sum(
        st.get("sla_days") or 0
        for st in all_stages
        if (st.get("position") or 0) >= cur_pos
    )
    proj_date = (today + _dt2.timedelta(days=remaining_sla)).isoformat() if remaining_sla else None

    # Time with client: sum days the lead spent in "client-facing" stages
    client_stage_ids = [
        st["id"] for st in all_stages
        if any(kw in st["name"].upper() for kw in ["CLIENTE", "ASSINATURA", "APROVAÇÃO", "APROVACAO", "VALIDAÇÃO", "VALIDACAO"])
    ]
    total_client_days = 0
    cur_in_client = cur_stage_id in client_stage_ids
    if cur_in_client:
        total_client_days += days_in_phase

    # From history: count days between stage_enter and stage_exit for each client stage
    prev_entry = None
    prev_stage = None
    for h in stage_history:
        if prev_stage and prev_stage in client_stage_ids and prev_entry:
            try:
                t_from = _dt2.datetime.fromisoformat(prev_entry.replace("Z", "+00:00"))
                t_to   = _dt2.datetime.fromisoformat(h["created_at"].replace("Z", "+00:00"))
                total_client_days += max(0, (t_to - t_from).days)
            except Exception:
                pass
        prev_stage = h["stage_id"]
        prev_entry = h["created_at"]

    is_delayed = bool(lead.get("due_date") and lead["due_date"] < today.isoformat()
                      and lead.get("status") not in ("Concluído", "Cancelado", "Inativo Pedido Cliente"))

    phases_data = []
    for i, p in enumerate(CLIENT_PHASES):
        phases_data.append({
            **p,
            "sla_days": phase_sla[p["key"]],
            "status": "done" if i < cur_idx else ("active" if i == cur_idx else "pending"),
            "days_in_phase": days_in_phase if i == cur_idx else None,
        })

    return {
        "lead": lead,
        "phases": phases_data,
        "cur_phase_idx": cur_idx,
        "days_in_phase": days_in_phase,
        "cur_phase_sla": phase_sla.get(cur_phase_key, 0),
        "is_delayed": is_delayed,
        "proj_date": proj_date,
        "remaining_sla": remaining_sla,
        "total_client_days": total_client_days,
        "cur_in_client_stage": cur_in_client,
        "cur_stage_name": lead.get("stage_name", ""),
        "due_date_junta": lead.get("due_date_junta"),
        "due_date_nf": lead.get("due_date_nf"),
        "due_date": lead.get("due_date"),
        "total_stages": len(all_stages),
    }


# ---------------------------------------------------------------------------
# State signature manuals repository
# ---------------------------------------------------------------------------

def list_state_manuals() -> list[dict]:
    with db_cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM lead_state_manuals ORDER BY state_code"
        ).fetchall()]


def get_state_manual(state_code: str) -> Optional[dict]:
    with db_cursor() as conn:
        r = conn.execute(
            "SELECT * FROM lead_state_manuals WHERE state_code=?",
            (state_code.upper(),)
        ).fetchone()
        return dict(r) if r else None


def upsert_state_manual(state_code: str, name: str, filename: str,
                        storage_key: str, size_bytes: int | None) -> str:
    """Insert or replace a manual for the given UF."""
    state_code = state_code.upper()
    with db_cursor() as conn:
        existing = conn.execute(
            "SELECT id FROM lead_state_manuals WHERE state_code=?", (state_code,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE lead_state_manuals SET name=?,filename=?,storage_key=?,size_bytes=? WHERE state_code=?",
                (name, filename, storage_key, size_bytes, state_code),
            )
            return existing[0]
        mid = new_id()
        conn.execute(
            "INSERT INTO lead_state_manuals (id,state_code,name,filename,storage_key,size_bytes) VALUES (?,?,?,?,?,?)",
            (mid, state_code, name, filename, storage_key, size_bytes),
        )
        return mid


def delete_state_manual(state_code: str) -> Optional[dict]:
    """Delete manual and return its record (for storage cleanup)."""
    state_code = state_code.upper()
    with db_cursor() as conn:
        r = conn.execute(
            "SELECT * FROM lead_state_manuals WHERE state_code=?", (state_code,)
        ).fetchone()
        if r:
            conn.execute("DELETE FROM lead_state_manuals WHERE state_code=?", (state_code,))
            return dict(r)
    return None
