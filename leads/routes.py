"""Rotas web do módulo de Leads."""
from __future__ import annotations

import datetime

from flask import render_template, request, redirect, url_for, flash, abort, jsonify, session

from . import db, leads_bp


def _add_progress(leads_list: list[dict]) -> None:
    """Adds `_progress` (0–100 int) to each lead dict, based on stage position."""
    wf_max: dict[str, int] = {}
    for lead in leads_list:
        wid = lead.get("workflow_id")
        if wid and wid not in wf_max:
            stgs = db.list_stages(wid)
            wf_max[wid] = max((s["position"] for s in stgs), default=1) if stgs else 1
        max_pos = wf_max.get(wid or "", 1) or 1
        pos = lead.get("stage_position") or 0
        lead["_progress"] = round(pos / max_pos * 100)


@leads_bp.route("")
def index():
    view = request.args.get("view", "list")
    filters = {
        "type":        request.args.get("type") or None,
        "stage":       request.args.get("stage") or None,
        "priority":    request.args.get("priority") or None,
        "status":      request.args.get("status") or None,
        "responsible": request.args.get("responsible") or None,
        "tag":         request.args.get("tag") or None,
    }
    leads = db.list_leads(filters)
    _add_progress(leads)
    types = db.list_lead_types(active_only=True)
    priorities = db.list_priorities()
    statuses = db.list_statuses()
    tags = db.list_tags()

    # Para Kanban: renderizar apenas 1 workflow unificado absoluto
    selected_type = filters["type"] or None
    
    workflows_data = []
    if view == "kanban":
        # Puxa o workflow mestre único
        wf = db.get_default_workflow()
        if wf:
            wf_macrophases = db.list_macrophases(wf["id"])
            wf_stages_by_macro = {}
            for st in db.list_stages(wf["id"]):
                wf_stages_by_macro.setdefault(st["macrophase_id"], []).append(st)
            
            # Filtra os leads, se houver um selected_type
            if selected_type:
                wf_leads = [l for l in leads if l.get("lead_type_id") == selected_type]
            else:
                wf_leads = leads
            
            # Devolvemos apenas UM item no array para renderizar um único board mestre
            workflows_data.append({
                "type": {"name": "Todos os Serviços"} if not selected_type else [t for t in types if t["id"] == selected_type][0],
                "workflow": wf,
                "macrophases": wf_macrophases,
                "stages_by_macro": wf_stages_by_macro,
                "leads": wf_leads
            })

    # workflow para o header do kanban
    kanban_workflow = workflows_data[0]["workflow"] if workflows_data else None

    template = "leads/kanban.html" if view == "kanban" else "leads/list.html"
    from db import list_users as _list_users
    return render_template(
        template,
        leads=leads,
        types=types,
        priorities=priorities,
        statuses=statuses,
        tags=tags,
        filters=filters,
        selected_type=selected_type,
        workflows_data=workflows_data,
        workflow=kanban_workflow,
        users=_list_users(),
    )


@leads_bp.route("/organ/<organ_code>")
def organ_index(organ_code):
    """Dedicated kanban/list view for an organ lead type (bombeiro/vigilancia/conselho)."""
    if organ_code not in db.ORGAN_TYPE_CODES:
        abort(404)
    view = request.args.get("view", "kanban")
    organ_type = db.get_lead_type_by_code(organ_code)
    if not organ_type:
        abort(404)

    filters = {
        "type":        organ_type["id"],
        "stage":       request.args.get("stage") or None,
        "priority":    request.args.get("priority") or None,
        "status":      request.args.get("status") or None,
        "responsible": request.args.get("responsible") or None,
        "tag":         request.args.get("tag") or None,
    }
    leads_list = db.list_leads(filters)
    _add_progress(leads_list)
    priorities = db.list_priorities()
    statuses = db.list_statuses()
    tags = db.list_tags()
    types = db.list_lead_types(active_only=True)

    workflows_data = []
    organ_workflows = db.list_workflows(organ_type["id"])
    wf = organ_workflows[0] if organ_workflows else None
    if wf:
        wf_macrophases = db.list_macrophases(wf["id"])
        wf_stages_by_macro = {}
        for st in db.list_stages(wf["id"]):
            wf_stages_by_macro.setdefault(st["macrophase_id"], []).append(st)
        workflows_data.append({
            "type": organ_type,
            "workflow": wf,
            "macrophases": wf_macrophases,
            "stages_by_macro": wf_stages_by_macro,
            "leads": leads_list,
        })

    kanban_workflow = workflows_data[0]["workflow"] if workflows_data else None
    template = "leads/kanban.html" if view == "kanban" else "leads/list.html"
    from db import list_users as _list_users
    return render_template(
        template,
        leads=leads_list,
        types=types,
        priorities=priorities,
        statuses=statuses,
        tags=tags,
        filters=filters,
        selected_type=organ_type["id"],
        workflows_data=workflows_data,
        workflow=kanban_workflow,
        organ_code=organ_code,
        organ_type=organ_type,
        users=_list_users(),
    )


# ---------------------------------------------------------------------------
# Painel Analítico
# ---------------------------------------------------------------------------

@leads_bp.route("/painel")
def painel():
    today = datetime.date.today()
    try:
        month = int(request.args.get("mes", today.month))
        year  = int(request.args.get("ano", today.year))
    except (ValueError, TypeError):
        month, year = today.month, today.year
    month = max(1, min(12, month))
    data = db.get_analytics_data(month, year)
    months = [
        {"value": f"{m:02d}", "label": ["Jan","Fev","Mar","Abr","Mai","Jun",
                                         "Jul","Ago","Set","Out","Nov","Dez"][m-1]}
        for m in range(1, 13)
    ]
    years = list(range(today.year - 3, today.year + 1))
    return render_template(
        "analytics.html",
        data=data,
        months=months,
        years=years,
        sel_month=month,
        sel_year=year,
        today=today,
    )


@leads_bp.route("/painel/api")
def painel_api():
    today = datetime.date.today()
    try:
        month = int(request.args.get("mes", today.month))
        year  = int(request.args.get("ano", today.year))
    except (ValueError, TypeError):
        month, year = today.month, today.year
    return jsonify(db.get_analytics_data(month, year))


@leads_bp.route("/<lead_id>/gerar-link-cliente", methods=["POST"])
def gerar_link_cliente(lead_id):
    lead = db.get_lead(lead_id)
    if not lead:
        return jsonify({"erro": "Lead não encontrado"}), 404
    token, code = db.get_or_create_client_token(lead_id)
    return jsonify({"token": token, "code": code})


@leads_bp.route("/<lead_id>/resetar-link-cliente", methods=["POST"])
def resetar_link_cliente(lead_id):
    """Forces a new token+code for the lead."""
    import secrets as _sec
    lead = db.get_lead(lead_id)
    if not lead:
        return jsonify({"erro": "Lead não encontrado"}), 404
    from . import db as ldb
    from .db import db_cursor, now_iso
    token = _sec.token_urlsafe(20)
    code  = str(_sec.randbelow(9000) + 1000)
    from .db import db_cursor as _dc
    with _dc() as conn:
        conn.execute(
            "UPDATE leads SET client_token=?, client_access_code=? WHERE id=?",
            (token, code, lead_id)
        )
    return jsonify({"token": token, "code": code})


@leads_bp.route("/novo", methods=["POST"])
def create():
    type_id = request.form.get("lead_type_id")
    name = (request.form.get("name") or "").strip()
    return_url = (request.form.get("return_url") or "").strip()
    if not type_id or not name:
        flash("Tipo e nome são obrigatórios.", "warning")
        return redirect(url_for("leads.index"))
    lead_id = db.create_lead(
        lead_type_id=type_id,
        name=name,
        priority=request.form.get("priority") or "Normal",
        status=request.form.get("status") or "Aberto",
        responsible_name=(request.form.get("responsible_name") or "").strip() or None,
        description=(request.form.get("description") or "").strip() or None,
        due_date=request.form.get("due_date") or None,
    )
    base = return_url if return_url else url_for("leads.index")
    return redirect(f"{base}?card={lead_id}")


@leads_bp.route("/<lead_id>")
def detail(lead_id):
    lead = db.get_lead(lead_id)
    if not lead:
        abort(404)
    type_data = db.get_lead_type(lead["lead_type_id"])
    stages = db.list_stages(lead["workflow_id"])
    macrophases = db.list_macrophases(lead["workflow_id"])
    ficha_data = None
    if lead.get("ficha_id"):
        from db import get_ficha as _get_ficha
        ficha_data = _get_ficha(int(lead["ficha_id"]))
    from db import list_users as _list_users
    return render_template(
        "leads/card_full.html",
        lead=lead,
        type_data=type_data,
        stages=stages,
        macrophases=macrophases,
        priorities=db.list_priorities(),
        statuses=db.list_statuses(),
        tags=db.list_tags(),
        offices=db.list_offices(),
        ficha_data=ficha_data,
        comments=db.list_comments(lead_id),
        history=db.list_history(lead_id),
        files=db.list_files(lead_id),
        checklist=db.list_checklist(lead_id),
        form_fields=db.get_form_fields(lead["lead_type_id"]),
        users=_list_users(),
    )

@leads_bp.route("/<lead_id>/formulario")
def form_view(lead_id):
    lead = db.get_lead(lead_id)
    if not lead:
        abort(404)
    type_data = db.get_lead_type(lead["lead_type_id"])
    form_fields = db.get_form_fields(lead["lead_type_id"])
    return render_template(
        "leads/form_full.html",
        lead=lead,
        type_data=type_data,
        form_fields=form_fields,
    )


@leads_bp.route("/<lead_id>/formulario-resumo")
def form_resumo(lead_id):
    """Print-friendly form summary for a lead's ficha."""
    lead = db.get_lead(lead_id)
    if not lead:
        abort(404)
    type_data = db.get_lead_type(lead["lead_type_id"])
    ficha_data = None
    if lead.get("ficha_id"):
        from db import get_ficha as _get_ficha
        ficha_data = _get_ficha(int(lead["ficha_id"]))
    return render_template(
        "leads/formulario_resumo.html",
        lead=lead,
        type_data=type_data,
        ficha_data=ficha_data,
    )


@leads_bp.route("/aprovacao/<token>")
def client_approval(token):
    approval = db.get_approval_by_token(token)
    if not approval:
        abort(404)
    lead = db.get_lead(approval["lead_id"])
    if not lead:
        abort(404)
    stages = db.list_stages(lead["workflow_id"])
    type_data = db.get_lead_type(lead["lead_type_id"])
    ficha_data = None
    if lead.get("ficha_id"):
        from db import get_ficha as _get_ficha
        ficha_data = _get_ficha(int(lead["ficha_id"]))
    return render_template(
        "leads/aprovacao.html",
        approval=approval,
        lead=lead,
        stages=stages,
        type_data=type_data,
        ficha_data=ficha_data,
    )


@leads_bp.route("/admin/justificativas")
def justificativas():
    from flask import session, abort as _abort
    if session.get("profile") not in ("admin", "gerente"):
        _abort(403)
    events = db.list_guard_events()
    # Resolve stage names
    stage_cache = {}
    for ev in events:
        for sf in ("stage_from", "stage_to"):
            sid = ev.get(sf)
            if sid and sid not in stage_cache:
                st = db.get_stage(sid)
                stage_cache[sid] = st["name"] if st else sid
            ev[sf + "_name"] = stage_cache.get(sid, "") if sid else ""
    return render_template("leads/justificativas.html", events=events)
