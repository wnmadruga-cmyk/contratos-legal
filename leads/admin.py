"""
Rotas de administração do módulo de Leads.

- /admin/leads/tipos          — CRUD de tipos + macrofases + etapas + reordenar
- /admin/leads/formularios    — editor de campos de formulário por tipo
- /admin/leads/prioridades    — CRUD de prioridades
- /admin/leads/status         — CRUD de status
- /admin/leads/etiquetas      — CRUD de tags
"""
from __future__ import annotations

import json
import sqlite3

from flask import flash, jsonify, redirect, render_template, request, url_for

from . import db, leads_admin_bp
from .db import db_cursor, new_id


# ---------------------------------------------------------------------------
# /admin/leads/tipos — Tipos + workflow + macrofases + etapas
# ---------------------------------------------------------------------------

@leads_admin_bp.route("/tipos")
def tipos():
    types = db.list_lead_types(active_only=False)
    selected_id = request.args.get("id") or (types[0]["id"] if types else None)
    selected = None
    workflow = None
    macrophases = []
    stages = []
    checklists_by_stage = {}
    if selected_id:
        selected = db.get_lead_type(selected_id)
        workflow = db.get_default_workflow(selected_id)
        if workflow:
            macrophases = db.list_macrophases(workflow["id"])
            stages = db.list_stages(workflow["id"])
            for st in stages:
                checklists_by_stage[st["id"]] = db.list_stage_checklist_templates(st["id"])
    checklist_templates = db.list_checklist_templates()
    return render_template(
        "leads/admin/tipos.html",
        types=types,
        selected=selected,
        workflow=workflow,
        macrophases=macrophases,
        stages=stages,
        checklists_by_stage=checklists_by_stage,
        checklist_templates=checklist_templates,
    )


@leads_admin_bp.route("/tipos/salvar", methods=["POST"])
def tipos_salvar():
    type_id = request.form.get("id")
    name = (request.form.get("name") or "").strip()
    color = request.form.get("color") or "#64748b"
    active = 1 if request.form.get("active") else 0
    copy_from_type_id = request.form.get("copy_from_type_id")
    
    if not name:
        flash("Nome é obrigatório.", "warning")
        return redirect(url_for("leads_admin.tipos"))
    with db_cursor() as conn:
        if type_id:
            conn.execute(
                "UPDATE lead_types SET name=?,color=?,active=? WHERE id=?",
                (name, color, active, type_id),
            )
        else:
            type_id = new_id()
            conn.execute(
                "INSERT INTO lead_types (id,name,color,active) VALUES (?,?,?,?)",
                (type_id, name, color, active),
            )
            # --- COPY FORM FIELDS LOGIC ---
            if copy_from_type_id:
                fields = conn.execute(
                    "SELECT * FROM lead_form_fields WHERE lead_type_id=?",
                    (copy_from_type_id,)
                ).fetchall()
                for f in fields:
                    conn.execute(
                        "INSERT INTO lead_form_fields (id,lead_type_id,field_key,label,field_type,options,required,section,position,help_text) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (new_id(), type_id, f["field_key"], f["label"], f["field_type"], f["options"], f["required"], f["section"], f["position"], f["help_text"])
                    )
            # -------------------

    flash("Tipo salvo.", "success")
    return redirect(url_for("leads_admin.tipos", id=type_id))


@leads_admin_bp.route("/tipos/<type_id>/excluir", methods=["POST"])
def tipos_excluir(type_id):
    with db_cursor() as conn:
        conn.execute("DELETE FROM lead_types WHERE id=?", (type_id,))
    flash("Tipo excluído.", "info")
    return redirect(url_for("leads_admin.tipos"))


@leads_admin_bp.route("/macrofases/salvar", methods=["POST"])
def macrofases_salvar():
    mp_id = request.form.get("id")
    workflow_id = request.form.get("workflow_id")
    name = (request.form.get("name") or "").strip()
    sla_days = request.form.get("sla_days") or None
    type_id = request.form.get("type_id")
    if not workflow_id or not name:
        flash("Workflow e nome obrigatórios.", "warning")
        return redirect(url_for("leads_admin.tipos", id=type_id))
    with db_cursor() as conn:
        if mp_id:
            conn.execute(
                "UPDATE lead_macrophases SET name=?,sla_days=? WHERE id=?",
                (name, sla_days, mp_id),
            )
        else:
            pos = conn.execute(
                "SELECT COALESCE(MAX(position),-1)+1 FROM lead_macrophases WHERE workflow_id=?",
                (workflow_id,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO lead_macrophases (id,workflow_id,name,position,sla_days)
                   VALUES (?,?,?,?,?)""",
                (new_id(), workflow_id, name, pos, sla_days),
            )
    return redirect(url_for("leads_admin.tipos", id=type_id))


@leads_admin_bp.route("/macrofases/<mp_id>/excluir", methods=["POST"])
def macrofases_excluir(mp_id):
    type_id = request.form.get("type_id")
    with db_cursor() as conn:
        conn.execute("DELETE FROM lead_macrophases WHERE id=?", (mp_id,))
    return redirect(url_for("leads_admin.tipos", id=type_id))


@leads_admin_bp.route("/etapas/salvar", methods=["POST"])
def etapas_salvar():
    st_id = request.form.get("id")
    workflow_id = request.form.get("workflow_id")
    macrophase_id = request.form.get("macrophase_id") or None
    name = (request.form.get("name") or "").strip()
    sla_days = request.form.get("sla_days") or None
    type_id = request.form.get("type_id")
    if not workflow_id or not name:
        flash("Workflow e nome obrigatórios.", "warning")
        return redirect(url_for("leads_admin.tipos", id=type_id))
    with db_cursor() as conn:
        if st_id:
            conn.execute(
                """UPDATE lead_stages SET name=?, macrophase_id=?, sla_days=?
                   WHERE id=?""",
                (name, macrophase_id, sla_days, st_id),
            )
        else:
            pos = conn.execute(
                "SELECT COALESCE(MAX(position),-1)+1 FROM lead_stages WHERE workflow_id=?",
                (workflow_id,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO lead_stages (id,workflow_id,macrophase_id,name,position,sla_days)
                   VALUES (?,?,?,?,?,?)""",
                (new_id(), workflow_id, macrophase_id, name, pos, sla_days),
            )
    return redirect(url_for("leads_admin.tipos", id=type_id))


@leads_admin_bp.route("/etapas/<st_id>/excluir", methods=["POST"])
def etapas_excluir(st_id):
    type_id = request.form.get("type_id")
    with db_cursor() as conn:
        conn.execute("DELETE FROM lead_stages WHERE id=?", (st_id,))
    return redirect(url_for("leads_admin.tipos", id=type_id))


@leads_admin_bp.route("/etapas/reordenar", methods=["POST"])
def etapas_reordenar():
    """Recebe JSON: {ordered_ids: [stage_id, ...]} e atualiza positions."""
    data = request.get_json(silent=True) or {}
    ids = data.get("ordered_ids") or []
    with db_cursor() as conn:
        for pos, sid in enumerate(ids):
            conn.execute("UPDATE lead_stages SET position=? WHERE id=?", (pos, sid))
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Admin genérico: prioridades / status / etiquetas (NamedColorAdmin)
# ---------------------------------------------------------------------------

NAMED_TABLES = {
    "prioridades": ("lead_priorities", True,  "Prioridade"),  # has position
    "status":      ("lead_statuses",   True,  "Status"),
    "etiquetas":   ("lead_tags",       False, "Etiqueta"),    # sem position
    "escritorios": ("lead_offices",    True,  "Escritório"),  # has position
}


def _list_named(slug: str) -> list[dict]:
    table, has_pos, _ = NAMED_TABLES[slug]
    order = "position" if has_pos else "name"
    with db_cursor() as conn:
        return [dict(r) for r in conn.execute(
            f"SELECT * FROM {table} ORDER BY {order}"
        ).fetchall()]


@leads_admin_bp.route("/<slug>")
def named_admin(slug):
    if slug not in NAMED_TABLES:
        return ("Não encontrado", 404)
    items = _list_named(slug)
    table, has_pos, label = NAMED_TABLES[slug]
    return render_template(
        "leads/admin/named.html",
        slug=slug, items=items, label=label, has_position=has_pos,
    )


@leads_admin_bp.route("/<slug>/salvar", methods=["POST"])
def named_salvar(slug):
    if slug not in NAMED_TABLES:
        return ("Não encontrado", 404)
    table, has_pos, _ = NAMED_TABLES[slug]
    item_id = request.form.get("id")
    name = (request.form.get("name") or "").strip()
    color = request.form.get("color") or "#64748b"
    if not name:
        flash("Nome é obrigatório.", "warning")
        return redirect(url_for("leads_admin.named_admin", slug=slug))
    with db_cursor() as conn:
        if item_id:
            conn.execute(
                f"UPDATE {table} SET name=?,color=? WHERE id=?",
                (name, color, item_id),
            )
        else:
            if has_pos:
                pos = conn.execute(
                    f"SELECT COALESCE(MAX(position),-1)+1 FROM {table}"
                ).fetchone()[0]
                conn.execute(
                    f"INSERT INTO {table} (id,name,color,position) VALUES (?,?,?,?)",
                    (new_id(), name, color, pos),
                )
            else:
                conn.execute(
                    f"INSERT INTO {table} (id,name,color) VALUES (?,?,?)",
                    (new_id(), name, color),
                )
    flash("Salvo.", "success")
    return redirect(url_for("leads_admin.named_admin", slug=slug))


@leads_admin_bp.route("/<slug>/<item_id>/excluir", methods=["POST"])
def named_excluir(slug, item_id):
    if slug not in NAMED_TABLES:
        return ("Não encontrado", 404)
    table, _, _ = NAMED_TABLES[slug]
    with db_cursor() as conn:
        conn.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
    return redirect(url_for("leads_admin.named_admin", slug=slug))


# ---------------------------------------------------------------------------
# Checklist Template Groups (modelos reutilizáveis)
# ---------------------------------------------------------------------------

@leads_admin_bp.route("/checklists")
def checklists():
    templates = db.list_checklist_templates()
    return render_template("leads/admin/checklists.html", templates=templates)


@leads_admin_bp.route("/checklists/salvar", methods=["POST"])
def checklists_salvar():
    tpl_id     = request.form.get("id") or None
    name       = (request.form.get("name") or "").strip()
    code       = (request.form.get("code") or "").strip().upper()
    desc       = (request.form.get("description") or "").strip()
    is_def     = bool(request.form.get("is_default"))
    items_json = request.form.get("items_json") or "[]"
    if not name or not code:
        flash("Nome e código são obrigatórios.", "warning")
        return redirect(url_for("leads_admin.checklists"))
    try:
        inline_items = json.loads(items_json)
        if not isinstance(inline_items, list):
            inline_items = []
    except Exception:
        inline_items = []

    try:
        if tpl_id:
            db.update_checklist_template(tpl_id, name, code, desc, is_def)
            flash("Modelo atualizado.", "success")
        else:
            tpl_id = db.create_checklist_template(name, code, desc, is_def)
            # Save inline items submitted with the creation form
            for item in inline_items:
                label = (item.get("label") or "").strip()
                required = bool(item.get("required"))
                if label:
                    db.add_checklist_template_item(tpl_id, label, required)
            flash("Modelo criado.", "success")
    except sqlite3.IntegrityError as e:
        if "code" in str(e).lower() or "unique" in str(e).lower():
            flash(
                f"O código '{code}' já está em uso por outro modelo. Escolha um código diferente.",
                "danger",
            )
        else:
            flash(f"Erro ao salvar: {e}", "danger")
        return redirect(url_for("leads_admin.checklists"))
    return redirect(url_for("leads_admin.checklists") + f"#{tpl_id}")


@leads_admin_bp.route("/checklists/<tpl_id>/excluir", methods=["POST"])
def checklists_excluir(tpl_id):
    db.delete_checklist_template(tpl_id)
    flash("Modelo excluído.", "info")
    return redirect(url_for("leads_admin.checklists"))


@leads_admin_bp.route("/checklists/<tpl_id>/items/add", methods=["POST"])
def checklists_item_add(tpl_id):
    label    = (request.form.get("label") or "").strip()
    required = bool(request.form.get("required"))
    if label:
        db.add_checklist_template_item(tpl_id, label, required)
    return redirect(url_for("leads_admin.checklists") + f"#{tpl_id}")


@leads_admin_bp.route("/checklists/items/<item_id>/excluir", methods=["POST"])
def checklists_item_excluir(item_id):
    tpl_id = request.form.get("tpl_id")
    db.delete_checklist_template_item(item_id)
    return redirect(url_for("leads_admin.checklists") + f"#{tpl_id}")


@leads_admin_bp.route("/etapas/<st_id>/link-checklist", methods=["POST"])
def etapas_link_checklist(st_id):
    """Links or unlinks a checklist template to a stage."""
    tpl_id  = request.form.get("checklist_template_id") or None
    type_id = request.form.get("type_id")
    db.link_stage_checklist_template(st_id, tpl_id)
    return redirect(url_for("leads_admin.tipos", id=type_id))


# ---------------------------------------------------------------------------
# Checklist templates por etapa
# ---------------------------------------------------------------------------

@leads_admin_bp.route("/stage-checklist/add", methods=["POST"])
def stage_checklist_add():
    stage_id = request.form.get("stage_id")
    type_id = request.form.get("type_id")
    label = (request.form.get("label") or "").strip()
    required = bool(request.form.get("required"))
    if stage_id and label:
        db.add_stage_checklist_template(stage_id, label, required)
    return redirect(url_for("leads_admin.tipos", id=type_id) + f"#chk-panel-{stage_id}")


@leads_admin_bp.route("/stage-checklist/<tpl_id>/excluir", methods=["POST"])
def stage_checklist_excluir(tpl_id):
    type_id = request.form.get("type_id")
    stage_id = request.form.get("stage_id")
    db.delete_stage_checklist_template(tpl_id)
    return redirect(url_for("leads_admin.tipos", id=type_id) + f"#chk-panel-{stage_id}")


# ---------------------------------------------------------------------------
# Editor de Formulários (campos por tipo)
# ---------------------------------------------------------------------------

@leads_admin_bp.route("/formularios")
def formularios():
    types = db.list_lead_types(active_only=False)
    selected_id = request.args.get("id") or (types[0]["id"] if types else None)
    fields = db.get_form_fields(selected_id) if selected_id else []
    return render_template(
        "leads/admin/formularios.html",
        types=types,
        selected_id=selected_id,
        fields=fields,
    )


@leads_admin_bp.route("/formularios/salvar", methods=["POST"])
def formularios_salvar():
    """Salva todos os campos do formulário de um tipo (substitui o conjunto)."""
    type_id = request.form.get("type_id")
    payload = request.form.get("fields_json") or "[]"
    try:
        fields = json.loads(payload)
    except json.JSONDecodeError:
        flash("Payload inválido.", "danger")
        return redirect(url_for("leads_admin.formularios", id=type_id))
    with db_cursor() as conn:
        conn.execute("DELETE FROM lead_form_fields WHERE lead_type_id=?", (type_id,))
        for pos, f in enumerate(fields):
            conn.execute(
                """INSERT INTO lead_form_fields
                   (id,lead_type_id,field_key,label,field_type,options,
                    required,section,position,help_text)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    new_id(), type_id,
                    (f.get("field_key") or "").strip(),
                    (f.get("label") or "").strip(),
                    f.get("field_type") or "text",
                    json.dumps(f.get("options")) if f.get("options") else None,
                    1 if f.get("required") else 0,
                    (f.get("section") or "Geral").strip(),
                    pos,
                    (f.get("help_text") or None),
                ),
            )
    flash("Formulário salvo.", "success")
    return redirect(url_for("leads_admin.formularios", id=type_id))


@leads_admin_bp.route("/formularios/copiar", methods=["POST"])
def formularios_copiar():
    target_type_id = request.form.get("target_type_id")
    source_type_id = request.form.get("source_type_id")
    if not target_type_id or not source_type_id:
        flash("Selecione um serviço origem e destino.", "warning")
        return redirect(url_for("leads_admin.formularios", id=target_type_id))
        
    with db_cursor() as conn:
        conn.execute("DELETE FROM lead_form_fields WHERE lead_type_id=?", (target_type_id,))
        fields = conn.execute(
            "SELECT * FROM lead_form_fields WHERE lead_type_id=?",
            (source_type_id,)
        ).fetchall()
        
        for f in fields:
            conn.execute(
                """INSERT INTO lead_form_fields
                   (id,lead_type_id,field_key,label,field_type,options,
                    required,section,position,help_text)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    new_id(), target_type_id, f["field_key"], f["label"],
                    f["field_type"], f["options"], f["required"],
                    f["section"], f["position"], f["help_text"]
                )
            )
    flash("Formulário copiado com sucesso.", "success")
    return redirect(url_for("leads_admin.formularios", id=target_type_id))


# ---------------------------------------------------------------------------
# /admin/leads/manuais — Repositório de manuais de assinatura por estado (UF)
# ---------------------------------------------------------------------------

@leads_admin_bp.route("/manuais")
def manuais():
    from flask import session, abort as _abort
    if session.get("profile") not in ("admin", "gerente"):
        _abort(403)
    manuals = db.list_state_manuals()
    return render_template("leads/admin/manuais.html", manuals=manuals)


@leads_admin_bp.route("/manuais/upload", methods=["POST"])
def manuais_upload():
    from flask import session, abort as _abort
    if session.get("profile") not in ("admin", "gerente"):
        _abort(403)
    state_code = (request.form.get("state_code") or "").strip().upper()
    name = (request.form.get("name") or "").strip()
    if not state_code or len(state_code) != 2:
        flash("UF inválida (use 2 letras, ex: PR).", "danger")
        return redirect(url_for("leads_admin.manuais"))
    if not name:
        name = f"Manual de Assinatura — {state_code}"
    if "file" not in request.files or not request.files["file"].filename:
        flash("Selecione um arquivo.", "danger")
        return redirect(url_for("leads_admin.manuais"))
    f = request.files["file"]
    from .storage import get_storage as _get_storage
    storage = _get_storage()
    storage_key, size = storage.save(
        f"state_manuals", f"manual_{state_code.lower()}{_ext(f.filename)}", f.stream, f.mimetype
    )
    db.upsert_state_manual(state_code, name, f.filename, storage_key, size)
    flash(f"Manual do estado {state_code} salvo.", "success")
    return redirect(url_for("leads_admin.manuais"))


@leads_admin_bp.route("/manuais/<state_code>/excluir", methods=["POST"])
def manuais_excluir(state_code):
    from flask import session, abort as _abort
    if session.get("profile") not in ("admin", "gerente"):
        _abort(403)
    rec = db.delete_state_manual(state_code)
    if rec:
        try:
            from .storage import get_storage as _get_storage
            _get_storage().delete(rec["storage_key"])
        except Exception:
            pass
    flash(f"Manual do estado {state_code.upper()} removido.", "info")
    return redirect(url_for("leads_admin.manuais"))


def _ext(filename: str) -> str:
    """Return file extension including dot, or empty string."""
    import os
    _, ext = os.path.splitext(filename or "")
    return ext or ""
