#!/usr/bin/env python3
"""
ECM Registro
Execute: python3 app.py
Acesse:  http://localhost:8080
"""

import io
import json
import os
from datetime import datetime

from flask import (Flask, request, send_file, render_template,
                   redirect, url_for, flash, jsonify, session)
from werkzeug.security import generate_password_hash, check_password_hash

from db import init_db, salvar_ficha, atualizar_ficha, get_ficha, listar_fichas, excluir_ficha
from db import listar_clausulas, salvar_clausula, excluir_clausula
from db import listar_modelos, salvar_modelo
from db import get_config, set_config
from db import get_user_by_email, get_user_by_id, list_users, create_user, update_user, inativar_user
from gerar_contrato import gerar_contrato
from gerar_alteracao import gerar_alteracao
from extrator_docx import extrair_dados_contrato
import leads as leads_module
from leads import db as leads_db

app = Flask(__name__)
app.secret_key = "contratos-societarios-2026"
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB

import json as _json
@app.template_filter('fromjson')
def fromjson_filter(s):
    try:
        return _json.loads(s or '{}')
    except Exception:
        return {}

leads_module.register(app)


@app.context_processor
def inject_organ_types():
    """Makes organ lead types available in all templates for sidebar rendering."""
    try:
        return {"organ_lead_types": leads_db.list_organ_lead_types()}
    except Exception:
        return {"organ_lead_types": []}


@app.before_request
def require_login():
    public_paths = {"/login", "/logout"}
    if request.path in public_paths or request.path.startswith("/static"):
        return
    # Public approval pages
    if request.path.startswith("/leads/aprovacao/"):
        return
    # Public approval resolve API
    if request.path.startswith("/api/leads/approval/"):
        return
    # Public client portal
    if request.path.startswith("/processo/"):
        return
    if not session.get("user_id"):
        return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        user = get_user_by_email(email)
        if user and check_password_hash(user["password_hash"], senha):
            session["user_id"]   = user["id"]
            session["user_name"] = user["name"]
            session["profile"]   = user["profile"]
            return redirect(url_for("dashboard"))
        flash("E-mail ou senha inválidos.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin/usuarios", methods=["GET", "POST"])
def admin_usuarios():
    if session.get("profile") != "admin":
        flash("Acesso negado.", "danger")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name       = request.form.get("name", "").strip()
        email      = request.form.get("email", "").strip().lower()
        senha      = request.form.get("password", "")
        profile    = request.form.get("profile", "operacional")
        can_review = 1 if request.form.get("can_review") else 0
        if not name or not email or not senha:
            flash("Todos os campos são obrigatórios.", "danger")
        else:
            try:
                uid = create_user(name, email, generate_password_hash(senha, method="pbkdf2:sha256"), profile)
                # Update can_review if needed
                if can_review:
                    from db import get_db as _get_db
                    conn = _get_db()
                    conn.execute("UPDATE users SET can_review=? WHERE email=?", (can_review, email))
                    conn.commit()
                    conn.close()
                flash(f"Usuário '{name}' criado com sucesso.", "success")
            except Exception as e:
                flash(f"Erro ao criar usuário: {e}", "danger")
        return redirect(url_for("admin_usuarios"))
    return render_template("admin_usuarios.html", users=list_users())


@app.route("/admin/usuarios/<uid>/editar", methods=["GET", "POST"])
def admin_usuario_editar(uid):
    if session.get("profile") != "admin":
        flash("Acesso negado.", "danger")
        return redirect(url_for("dashboard"))
    user = get_user_by_id(uid)
    if not user:
        flash("Usuário não encontrado.", "danger")
        return redirect(url_for("admin_usuarios"))
    if request.method == "POST":
        name       = request.form.get("name", "").strip()
        email      = request.form.get("email", "").strip().lower()
        profile    = request.form.get("profile", "operacional")
        active     = int(request.form.get("active", 1))
        can_review = 1 if request.form.get("can_review") else 0
        update_user(uid, name, email, profile, active)
        from db import get_db as _get_db
        conn = _get_db()
        conn.execute("UPDATE users SET can_review=? WHERE id=?", (can_review, uid))
        nova_senha = request.form.get("senha", "").strip()
        if nova_senha:
            conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                         (generate_password_hash(nova_senha, method="pbkdf2:sha256"), uid))
        conn.commit()
        conn.close()
        flash("Usuário atualizado.", "success")
        return redirect(url_for("admin_usuarios"))
    return render_template("admin_usuario_editar.html", user=user)


@app.route("/admin/usuarios/<uid>/inativar", methods=["POST"])
def admin_usuario_inativar(uid):
    if session.get("profile") != "admin":
        return jsonify({"erro": "Acesso negado"}), 403
    inativar_user(uid)
    flash("Usuário inativado.", "success")
    return redirect(url_for("admin_usuarios"))

# Carrega .env se existir (OPENAI_API_KEY etc.)
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

init_db()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    constituicoes = listar_fichas("constituicao")
    alteracoes    = listar_fichas("alteracao")
    return render_template("dashboard.html", constituicoes=constituicoes, alteracoes=alteracoes)


# ---------------------------------------------------------------------------
# Constituição
# ---------------------------------------------------------------------------

@app.route("/constituicao/nova")
def constituicao_nova():
    return render_template("form_constituicao.html", ficha=None, ficha_id=None)


@app.route("/constituicao/salvar", methods=["POST"])
def constituicao_salvar():
    dados_json = request.form.get("dados_json", "")
    try:
        dados = json.loads(dados_json)
    except Exception:
        flash("Erro ao processar os dados do formulário.", "danger")
        return redirect(url_for("constituicao_nova"))

    empresa = dados.get("empresa", {})
    socios = empresa.get("socios", [])
    subtipo = "ltda_unipessoal" if len(socios) == 1 else "ltda"
    razao = empresa.get("razaoSocial", "Sem Nome")

    # Adiciona timestamp
    dados["timestamp"] = datetime.now().isoformat()

    # Calcula resumo
    capital = float(empresa.get("capitalSocial", 0))
    total_cotas = sum(int(s.get("quantidadeCotas", 0)) for s in socios)
    percentuais = []
    for s in socios:
        qtd = int(s.get("quantidadeCotas", 0))
        pct = (qtd / total_cotas * 100) if total_cotas else 0
        val = qtd * float(s.get("valorUnitarioCota", 1))
        percentuais.append({
            "nome": s.get("nome", ""),
            "cpf": s.get("cpf", ""),
            "capitalInvestido": val,
            "percentual": f"{pct:.2f}"
        })
    dados["resumo"] = {
        "totalSocios": len(socios),
        "capitalSocial": capital,
        "atividadesEconomicas": len(empresa.get("atividades", [])),
        "percentualPorSocio": percentuais
    }

    lead_id_param = request.form.get("lead_id") or None
    ficha_id = request.form.get("ficha_id")
    if ficha_id:
        atualizar_ficha(int(ficha_id), subtipo, razao, dados)
        flash(f"Ficha '{razao}' atualizada com sucesso!", "success")
    else:
        ficha_id = salvar_ficha("constituicao", subtipo, razao, dados)
        flash(f"Ficha '{razao}' salva com sucesso!", "success")

    if lead_id_param:
        leads_db.link_ficha(lead_id_param, str(ficha_id))
        leads_db.sync_sem_atividade_tag(lead_id_param, dados)
        return redirect(f"/leads/{lead_id_param}")

    return redirect(url_for("dashboard"))


@app.route("/constituicao/<int:fid>/editar")
def constituicao_editar(fid):
    ficha = get_ficha(fid)
    if not ficha:
        flash("Ficha não encontrada.", "danger")
        return redirect(url_for("dashboard"))
    return render_template("form_constituicao.html", ficha=ficha["dados"], ficha_id=fid)


@app.route("/constituicao/<int:fid>/preparar")
def constituicao_preparar(fid):
    """Tela intermediária para selecionar cláusulas antes de gerar."""
    ficha = get_ficha(fid)
    if not ficha:
        flash("Ficha não encontrada.", "danger")
        return redirect(url_for("dashboard"))
    subtipo = ficha.get("subtipo", "ltda")
    clausulas = listar_clausulas(subtipo)
    return render_template("gerar_contrato.html",
                           ficha=ficha["dados"], ficha_id=fid, clausulas=clausulas)


@app.route("/constituicao/<int:fid>/gerar")
def constituicao_gerar(fid):
    ficha = get_ficha(fid)
    if not ficha:
        flash("Ficha não encontrada.", "danger")
        return redirect(url_for("dashboard"))

    dados = ficha["dados"]

    # Cláusulas do banco de cláusulas selecionadas
    extras = []
    clausulas_ids = request.args.getlist("clausula")
    for cid in clausulas_ids:
        from db import get_db as _get_db
        conn = _get_db()
        row = conn.execute("SELECT * FROM clausulas_banco WHERE id=?", (cid,)).fetchone()
        conn.close()
        if row:
            extras.append({"titulo": row["titulo"], "corpo": row["corpo"]})

    # Cláusulas geradas via IA (passadas como pares ia_titulo_N / ia_corpo_N)
    i = 0
    while True:
        titulo = request.args.get(f"ia_titulo_{i}")
        corpo  = request.args.get(f"ia_corpo_{i}")
        if not titulo:
            break
        extras.append({"titulo": titulo, "corpo": corpo or ""})
        i += 1

    if extras:
        dados = dict(dados)
        dados["clausulas_extras"] = extras

    razao = dados.get("empresa", {}).get("razaoSocial", "contrato")
    slug = "".join(c if c.isalnum() or c in " -" else "" for c in razao)
    slug = slug.strip().replace(" ", "_")[:50]
    nome_saida = f"Contrato_{slug}.docx"

    buf = io.BytesIO()
    try:
        gerar_contrato(dados, buf)
    except Exception as e:
        flash(f"Erro ao gerar contrato: {e}", "danger")
        return redirect(url_for("dashboard"))

    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=nome_saida,
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.route("/constituicao/<int:fid>/excluir", methods=["POST"])
def constituicao_excluir(fid):
    ficha = get_ficha(fid)
    if ficha:
        excluir_ficha(fid)
        flash(f"Ficha excluída.", "success")
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Alteração Contratual
# ---------------------------------------------------------------------------

@app.route("/alteracao/nova")
def alteracao_nova():
    openai_ok = bool(os.environ.get("OPENAI_API_KEY"))
    return render_template("form_alteracao.html", ficha=None, ficha_id=None,
                           openai_ok=openai_ok,
                           clausulas_banco=listar_clausulas(),
                           modelos_clausulas=listar_modelos())


@app.route("/alteracao/salvar", methods=["POST"])
def alteracao_salvar():
    dados_json = request.form.get("dados_json", "")
    try:
        dados = json.loads(dados_json)
    except Exception:
        flash("Erro ao processar os dados.", "danger")
        return redirect(url_for("alteracao_nova"))

    razao = dados.get("empresa_atual", {}).get("razaoSocial", "Sem Nome")
    lead_id_param = request.form.get("lead_id") or None
    ficha_id = request.form.get("ficha_id")
    if ficha_id:
        atualizar_ficha(int(ficha_id), "alteracao", razao, dados)
        flash(f"Alteração '{razao}' atualizada!", "success")
    else:
        ficha_id = salvar_ficha("alteracao", "alteracao", razao, dados)
        flash(f"Alteração '{razao}' salva!", "success")

    if lead_id_param:
        leads_db.link_ficha(lead_id_param, str(ficha_id))
        # For alterations: atividades may be under empresa_atual.atividades
        _dados_sync = {"empresa": dados.get("empresa_atual", dados.get("empresa", {}))}
        leads_db.sync_sem_atividade_tag(lead_id_param, _dados_sync)
        return redirect(f"/leads/{lead_id_param}")

    return redirect(url_for("dashboard"))


@app.route("/alteracao/<int:fid>/editar")
def alteracao_editar(fid):
    ficha = get_ficha(fid)
    if not ficha:
        flash("Ficha não encontrada.", "danger")
        return redirect(url_for("dashboard"))
    openai_ok = bool(os.environ.get("OPENAI_API_KEY"))
    return render_template("form_alteracao.html",
                           ficha=ficha["dados"], ficha_id=fid, openai_ok=openai_ok,
                           clausulas_banco=listar_clausulas(),
                           modelos_clausulas=listar_modelos())


@app.route("/alteracao/<int:fid>/gerar")
def alteracao_gerar(fid):
    ficha = get_ficha(fid)
    if not ficha:
        flash("Ficha não encontrada.", "danger")
        return redirect(url_for("dashboard"))

    dados = ficha["dados"]
    razao = dados.get("empresa_atual", {}).get("razaoSocial", "alteracao")
    num   = dados.get("numero_alteracao", 1)
    slug  = "".join(c if c.isalnum() or c in " -" else "" for c in razao)
    slug  = slug.strip().replace(" ", "_")[:50]
    nome_saida = f"Alteracao_{num}_{slug}.docx"

    buf = io.BytesIO()
    try:
        gerar_alteracao(dados, buf)
    except Exception as e:
        flash(f"Erro ao gerar alteração: {e}", "danger")
        return redirect(url_for("dashboard"))

    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=nome_saida,
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.route("/alteracao/<int:fid>/excluir", methods=["POST"])
def alteracao_excluir(fid):
    excluir_ficha(fid)
    flash("Ficha de alteração excluída.", "success")
    return redirect(url_for("dashboard"))


@app.route("/api/extrair-contrato", methods=["POST"])
def api_extrair_contrato():
    arquivo = request.files.get("arquivo")
    if not arquivo:
        return jsonify({"erro": "Nenhum arquivo enviado."}), 400

    nome = arquivo.filename or ""
    ext  = os.path.splitext(nome)[1].lower()
    if ext not in (".docx", ".pdf"):
        return jsonify({"erro": "Envie um arquivo .docx ou .pdf"}), 400

    try:
        dados = extrair_dados_contrato(arquivo, nome)
        dados["_modo"] = "gpt" if os.environ.get("OPENAI_API_KEY") else "local"
        return jsonify(dados)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# ---------------------------------------------------------------------------
# Banco de Cláusulas
# ---------------------------------------------------------------------------

@app.route("/clausulas")
def banco_clausulas():
    clausulas = listar_clausulas()
    return render_template("banco_clausulas.html", clausulas=clausulas)


@app.route("/clausulas/salvar", methods=["POST"])
def clausula_salvar():
    titulo = request.form.get("titulo", "").strip()
    corpo = request.form.get("corpo", "").strip()
    tipo = request.form.get("tipo_contrato", "todos")
    if not titulo or not corpo:
        flash("Título e texto são obrigatórios.", "danger")
        return redirect(url_for("banco_clausulas"))
    salvar_clausula(titulo, corpo, tipo)
    flash("Cláusula adicionada ao banco.", "success")
    return redirect(url_for("banco_clausulas"))


@app.route("/clausulas/<int:cid>/excluir", methods=["POST"])
def clausula_excluir(cid):
    excluir_clausula(cid)
    flash("Cláusula removida.", "success")
    return redirect(url_for("banco_clausulas"))


# ---------------------------------------------------------------------------
# Modelos de Contrato
# ---------------------------------------------------------------------------

@app.route("/modelos")
def modelos():
    clausulas = listar_modelos()
    return render_template("modelos.html", clausulas=clausulas)


@app.route("/modelos/salvar", methods=["POST"])
def modelos_salvar():
    dados = request.json or {}
    codigo        = dados.get("codigo", "").strip()
    tipo_contrato = dados.get("tipo_contrato", "ltda").strip()
    titulo        = dados.get("titulo", "").strip()
    corpo         = dados.get("corpo", "").strip()
    if not codigo:
        return jsonify({"erro": "Código inválido."}), 400
    salvar_modelo(codigo, tipo_contrato, titulo, corpo)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API: sugestão de cláusula via IA (OpenAI)
# ---------------------------------------------------------------------------

@app.route("/api/sugerir-clausula", methods=["POST"])
def sugerir_clausula():
    dados = request.json or {}
    descricao = dados.get("descricao", "").strip()
    contexto = dados.get("contexto", "")

    if not descricao:
        return jsonify({"erro": "Informe uma descrição para a cláusula."}), 400

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return jsonify({"erro": "OPENAI_API_KEY não configurada no ambiente."}), 500

    try:
        import urllib.request
        payload = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": (
                    "Você é um especialista em direito empresarial brasileiro. "
                    "Redija cláusulas para contratos sociais de sociedades limitadas. "
                    "Seja objetivo, formal e juridicamente preciso. "
                    "Retorne APENAS o texto da cláusula, sem numeração e sem título."
                )},
                {"role": "user", "content": (
                    f"Redija uma cláusula contratual sobre: {descricao}.\n"
                    f"Contexto da empresa: {contexto}" if contexto else
                    f"Redija uma cláusula contratual sobre: {descricao}."
                )}
            ],
            "max_tokens": 500,
            "temperature": 0.4
        }).encode()

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resultado = json.loads(resp.read())
            texto = resultado["choices"][0]["message"]["content"].strip()
            return jsonify({"clausula": texto})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/extrair-documento-socio", methods=["POST"])
def extrair_documento_socio():
    arquivo = request.files.get("arquivo")
    if not arquivo:
        return jsonify({"erro": "Nenhum arquivo enviado."}), 400

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return jsonify({"erro": "OPENAI_API_KEY não configurada."}), 500

    nome = arquivo.filename or ""
    ext  = os.path.splitext(nome)[1].lower()

    _PROMPT_SISTEMA = (
        "Você é um especialista em leitura de documentos pessoais brasileiros "
        "(RG, CNH, CPF, Passaporte, RNE, CTPS). "
        "Extraia os dados com precisão e retorne apenas JSON válido, sem markdown."
    )
    _PROMPT_EXTRACAO = (
        'Extraia os dados do documento e retorne APENAS este JSON:\n'
        '{\n'
        '  "nome": "NOME COMPLETO CONFORME O DOCUMENTO",\n'
        '  "cpf": "000.000.000-00",\n'
        '  "dataNascimento": "YYYY-MM-DD",\n'
        '  "doc_tipo": "rg",\n'
        '  "doc_numero": "número do documento",\n'
        '  "doc_orgaoExpedidor": "SSP/PR",\n'
        '  "doc_dataExpedicao": "YYYY-MM-DD"\n'
        '}\n'
        'Regras obrigatórias:\n'
        '- doc_tipo: "cnh" para Carteira de Habilitação, "rg" para Cédula de Identidade, '
        '"passaporte", "rne" para estrangeiros\n'
        '- doc_orgaoExpedidor para CNH: "DETRAN/" + sigla do estado emissor '
        '(ex: "DETRAN/PR", "DETRAN/SP")\n'
        '- doc_orgaoExpedidor para RG: se o órgão for SSP, SESP, PC, Polícia Civil ou similar '
        '→ "SSP/" + sigla do estado (ex: "SSP/PR"); '
        'se for outra organização, use o nome abreviado + "/" + sigla do estado\n'
        '- Sigla do estado: 2 letras maiúsculas (PR, SP, RS, etc.)\n'
        '- Datas: formato YYYY-MM-DD\n'
        '- CPF: formato 000.000.000-00\n'
        '- Se um campo não for encontrado: string vazia ""\n'
        '- Retorne SOMENTE o JSON, sem texto adicional'
    )

    try:
        import urllib.request, base64

        if ext in (".jpg", ".jpeg", ".png", ".webp"):
            # GPT-4o Vision
            conteudo   = arquivo.read()
            b64        = base64.b64encode(conteudo).decode()
            media_type = "image/jpeg" if ext in (".jpg", ".jpeg") else f"image/{ext[1:]}"

            payload = json.dumps({
                "model": "gpt-4o",
                "messages": [
                    {"role": "system", "content": _PROMPT_SISTEMA},
                    {"role": "user", "content": [
                        {"type": "text",       "text": _PROMPT_EXTRACAO},
                        {"type": "image_url",  "image_url": {
                            "url": f"data:{media_type};base64,{b64}",
                            "detail": "high"
                        }}
                    ]}
                ],
                "max_tokens": 600,
                "temperature": 0.1,
                "response_format": {"type": "json_object"}
            }).encode()

        elif ext == ".pdf":
            # Tenta extrair texto; se falhar, converte página para imagem
            import pdfplumber, io as _io
            conteudo = arquivo.read()
            texto_pdf = ""
            with pdfplumber.open(_io.BytesIO(conteudo)) as pdf:
                for page in pdf.pages[:2]:
                    t = page.extract_text()
                    if t:
                        texto_pdf += t + "\n"

            if texto_pdf.strip():
                # PDF com texto — usa GPT texto
                payload = json.dumps({
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": _PROMPT_SISTEMA},
                        {"role": "user",   "content": _PROMPT_EXTRACAO + "\n\nTexto do documento:\n" + texto_pdf[:4000]}
                    ],
                    "max_tokens": 600,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"}
                }).encode()
            else:
                # PDF digitalizado (sem texto) — tenta converter para imagem
                try:
                    from pdf2image import convert_from_bytes
                    imgs = convert_from_bytes(conteudo, dpi=200, first_page=1, last_page=1)
                    img_bytes = _io.BytesIO()
                    imgs[0].save(img_bytes, format="JPEG", quality=90)
                    b64 = base64.b64encode(img_bytes.getvalue()).decode()
                    payload = json.dumps({
                        "model": "gpt-4o",
                        "messages": [
                            {"role": "system", "content": _PROMPT_SISTEMA},
                            {"role": "user", "content": [
                                {"type": "text",      "text": _PROMPT_EXTRACAO},
                                {"type": "image_url", "image_url": {
                                    "url": f"data:image/jpeg;base64,{b64}",
                                    "detail": "high"
                                }}
                            ]}
                        ],
                        "max_tokens": 600,
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"}
                    }).encode()
                except ImportError:
                    return jsonify({"erro": "PDF digitalizado detectado. Envie como imagem JPG ou PNG."}), 400
        else:
            return jsonify({"erro": "Formato não suportado. Use JPG, PNG, WEBP ou PDF."}), 400

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            resultado = json.loads(resp.read())
            dados     = json.loads(resultado["choices"][0]["message"]["content"])
            return jsonify(dados)

    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/sugerir-objeto-cnae", methods=["POST"])
def sugerir_objeto_cnae():
    dados = request.json or {}
    descricao = dados.get("descricao", "").strip()
    if not descricao:
        return jsonify({"erro": "Informe uma descrição das atividades."}), 400

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return jsonify({"erro": "OPENAI_API_KEY não configurada."}), 500

    try:
        import urllib.request
        prompt_sistema = (
            "Você é um advogado especializado em direito empresarial brasileiro com amplo "
            "conhecimento nos procedimentos da Junta Comercial e do DNRC. "
            "Redija textos formais para registro de empresas com precisão jurídica."
        )
        prompt_usuario = (
            f"Com base nas seguintes atividades descritas pelo cliente, execute duas tarefas:\n\n"
            f"Atividades: {descricao}\n\n"
            f"1. Redija um OBJETO SOCIAL formal para o contrato social de uma sociedade limitada, "
            f"nos padrões aceitos pela Junta Comercial. O texto deve ser formal, em caixa alta, "
            f"completo e juridicamente adequado para registro. "
            f"IMPORTANTE: NUNCA utilize termos vagos como 'correlatas', 'afins', 'similares', "
            f"'outras atividades', 'demais atividades', 'e outras' — o objeto social deve ser "
            f"completamente específico e detalhado, descrevendo cada atividade de forma individualizada, "
            f"sob pena de indeferimento pela Junta Comercial. "
            f"Retorne apenas o texto do objeto social, sem prefixo.\n\n"
            f"2. Sugira de 1 a 6 códigos CNAE (subclasses) mais adequados para essas atividades, "
            f"indicando qual deve ser o principal.\n\n"
            f"Retorne SOMENTE este JSON válido (sem markdown):\n"
            f'{{"objetoSocial": "...", '
            f'"cnaes": [{{"cnae": "0000-0/00", "descricao": "...", "principal": true}}, ...]}}'
        )

        payload = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": prompt_sistema},
                {"role": "user",   "content": prompt_usuario}
            ],
            "max_tokens": 800,
            "temperature": 0.3,
            "response_format": {"type": "json_object"}
        }).encode()

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            resultado = json.loads(resp.read())
            conteudo  = json.loads(resultado["choices"][0]["message"]["content"])
            return jsonify(conteudo)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/verificar-razao-social", methods=["POST"])
def verificar_razao_social():
    dados      = request.json or {}
    nome       = dados.get("nome", "").strip()
    socios     = dados.get("socios", [])
    ativs      = dados.get("atividades", [])
    modo       = dados.get("modo", "verificar")       # "verificar" | "sugerir"
    tipo_nome  = dados.get("tipo_nome", "denominacao") # "firma" | "denominacao"

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return jsonify({"erro": "OPENAI_API_KEY não configurada."}), 500

    nomes_socios = ", ".join(s.get("nome", "") for s in socios if s.get("nome"))
    ativ_desc    = ", ".join(a.get("descricao", "") for a in ativs[:4] if a.get("descricao"))

    REGRAS = """Regras do DREI para nome empresarial de Sociedade Limitada (LTDA):
1. Pode usar FIRMA (contém nome civil de sócio(s)) ou DENOMINAÇÃO (qualquer palavra).
2. Deve terminar com "LIMITADA" ou "LTDA" por extenso ou abreviado.
3. Se firma com mais de 1 sócio e não individualiza todos, deve incluir pelo menos 1 nome + "e Companhia" ou "& Cia." + LTDA.
4. Denominação pode ser em língua nacional ou estrangeira.
5. Proibido: idêntico/semelhante a nome já registrado na mesma Junta; palavras atentatórias à moral; siglas de órgãos públicos ou internacionais sem autorização; designação de atividade não prevista no objeto; indicação de porte (ME/EPP) no nome.
6. ESC (Empresa Simples de Crédito) deve conter "Empresa Simples de Crédito" antes do tipo societário, sem a palavra "banco".
7. SPE pode agregar "SPE" antes de "LTDA".
8. Em liquidação: adicionar "em liquidação" ao final após anotação no registro.
9. Em recuperação judicial: acrescentar "em recuperação judicial" após o nome.
10. Nome civil: deve figurar completo; prenomes podem ser abreviados; FILHO, JÚNIOR, NETO, SOBRINHO etc. não podem ser abreviados nem excluídos; último sobrenome não pode ser abreviado."""

    try:
        import urllib.request

        tipo_label = "firma (deve conter sobrenome de pelo menos um sócio)" if tipo_nome == "firma" else "denominação (nome livre, não precisa usar nome dos sócios)"

        if modo == "sugerir":
            prompt_user = (
                f"Sugira 5 opções criativas de nome empresarial (razão social) para uma sociedade limitada (LTDA).\n"
                f"Tipo escolhido pelo usuário: {tipo_label}.\n"
                f"{'Se firma: todas as sugestões devem conter sobrenome de ao menos um sócio.' if tipo_nome == 'firma' else 'Se denominação: sugestões devem ser nomes criativos/descritivos sem necessariamente usar nomes dos sócios.'}\n"
                f"Sócios: {nomes_socios or 'não informados'}\n"
                f"Atividades: {ativ_desc or 'não informadas'}\n\n"
                f"Regras obrigatórias:\n{REGRAS}\n\n"
                f"Retorne SOMENTE este JSON: {{\"sugestoes\": [\"Nome 1 LTDA\", \"Nome 2 LTDA\", ...]}} com 5 opções."
            )
        else:
            if not nome:
                return jsonify({"erro": "Informe um nome para verificar."}), 400
            prompt_user = (
                f"Analise se o nome empresarial abaixo está em conformidade com as regras do DREI para LTDA.\n\n"
                f"Nome proposto: \"{nome}\"\n"
                f"Tipo de nome escolhido pelo usuário: {tipo_label}.\n"
                f"{'Para FIRMA: verifique se contém sobrenome de ao menos um dos sócios listados.' if tipo_nome == 'firma' else 'Para DENOMINAÇÃO: não exigir nome de sócio — verificar apenas regras gerais (LTDA no final, palavras proibidas, etc.).'}\n"
                f"Sócios: {nomes_socios or 'não informados'}\n"
                f"Atividades: {ativ_desc or 'não informadas'}\n\n"
                f"Regras:\n{REGRAS}\n\n"
                f"Retorne SOMENTE este JSON:\n"
                f"{{\"ok\": true_ou_false, \"mensagem\": \"explicação em 1-2 frases\", "
                f"\"sugestoes\": [\"alternativa1 LTDA\", \"alternativa2 LTDA\"]}}\n"
                f"Se ok=true, sugestoes pode ser []. Se ok=false, forneça 2 alternativas válidas do mesmo tipo ({tipo_nome})."
            )

        payload = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": (
                    "Você é um advogado e contador especialista em direito empresarial brasileiro "
                    "e nos procedimentos de registro na Junta Comercial (DREI). "
                    "Responda sempre em JSON válido conforme o formato solicitado."
                )},
                {"role": "user", "content": prompt_user}
            ],
            "max_tokens": 400,
            "temperature": 0.3,
            "response_format": {"type": "json_object"}
        }).encode()

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resultado = json.loads(resp.read())
            conteudo  = json.loads(resultado["choices"][0]["message"]["content"])
            return jsonify(conteudo)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# ---------------------------------------------------------------------------
# FCN Config
# ---------------------------------------------------------------------------

# Perguntas complementares padrão da FCN para LTDA
_FCN_PERGUNTAS_PADRAO = [
    {"id": "num_empregados",       "pergunta": "Número de empregados (incluindo sócios que trabalham na empresa)", "resposta": ""},
    {"id": "horario_func",         "pergunta": "Horário de funcionamento", "resposta": "08:00 às 18:00, de segunda a sexta-feira"},
    {"id": "area_total",           "pergunta": "Área total do estabelecimento (m²)", "resposta": ""},
    {"id": "area_util",            "pergunta": "Área útil utilizada para a atividade (m²)", "resposta": ""},
    {"id": "contato_responsavel",  "pergunta": "Nome e telefone do responsável para contato", "resposta": ""},
    {"id": "email_contato",        "pergunta": "E-mail para contato da empresa", "resposta": ""},
    {"id": "inscricao_estadual",   "pergunta": "Possui inscrição estadual?", "resposta": "Não"},
    {"id": "inscricao_municipal",  "pergunta": "Possui inscrição municipal / alvará?", "resposta": "Não"},
    {"id": "socios_exterior",      "pergunta": "Possui sócios residentes no exterior?", "resposta": "Não"},
    {"id": "tipo_imovel",          "pergunta": "O imóvel utilizado é próprio, alugado ou cedido?", "resposta": "Alugado"},
    {"id": "faturamento_previsto", "pergunta": "Faturamento anual previsto (R$)", "resposta": ""},
    {"id": "possui_filial",        "pergunta": "Possui filial ou estabelecimento secundário?", "resposta": "Não"},
    {"id": "obs_gerais",           "pergunta": "Observações gerais / informações adicionais", "resposta": ""},
]


@app.route("/fcn-config", methods=["GET", "POST"])
def fcn_config():
    if request.method == "POST":
        perguntas = get_config("fcn_perguntas", _FCN_PERGUNTAS_PADRAO)
        dados_form = request.form
        for perg in perguntas:
            perg["resposta"] = dados_form.get(f"resp_{perg['id']}", "")
        set_config("fcn_perguntas", perguntas)
        flash("Configurações FCN salvas com sucesso.", "success")
        return redirect(url_for("fcn_config"))

    perguntas = get_config("fcn_perguntas", _FCN_PERGUNTAS_PADRAO)
    return render_template("fcn_config.html", perguntas=perguntas)


# ---------------------------------------------------------------------------
# Portal do Cliente (público)
# ---------------------------------------------------------------------------

@app.route("/processo/<token>")
def portal_cliente(token):
    """Portal público de acompanhamento — acesso direto pelo link, sem senha."""
    from datetime import date as _date
    lead = leads_db.get_lead_by_client_token(token)
    if not lead:
        return render_template("leads/portal_404.html"), 404
    portal_data = leads_db.get_client_portal_data(lead["id"])

    # Detect the lead's UF to find the relevant state manual
    state_manual = None
    if lead.get("op_link_assinatura_junta"):
        lead_uf = None
        if lead.get("ficha_id"):
            try:
                ficha = get_ficha(int(lead["ficha_id"]))
                if ficha:
                    dados = ficha.get("dados") or {}
                    empresa = dados.get("empresa") or dados.get("empresa_atual") or {}
                    lead_uf = (empresa.get("estado") or empresa.get("estadoSede") or "").strip().upper()
            except Exception:
                pass
        if lead_uf:
            state_manual = leads_db.get_state_manual(lead_uf)

    return render_template("leads/portal_cliente.html", token=token,
                           portal=portal_data, today=_date.today(),
                           state_manual=state_manual)


if __name__ == "__main__":
    print("Acesse: http://localhost:8080")
    app.run(debug=True, port=8080)
