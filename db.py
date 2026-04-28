import sqlite3
import json
import os

# Resolução do caminho do banco:
#   VERCEL=1  → /tmp/contratos.db  (filesystem serverless é read-only)
#   DB_PATH   → caminho configurado via env (ex: volume persistente no Railway)
#   padrão    → contratos.db ao lado do app.py (desenvolvimento local / Railway sem volume)
_local_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contratos.db")
if os.environ.get("VERCEL"):
    DB_PATH = "/tmp/contratos.db"
elif os.environ.get("DB_PATH"):
    DB_PATH = os.environ["DB_PATH"]
else:
    DB_PATH = _local_db


def get_db():
    _dir = os.path.dirname(DB_PATH)
    if _dir:
        os.makedirs(_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Textos padrão para as cláusulas fixas (fallback quando não há registro no DB)
# ---------------------------------------------------------------------------
_CLAUSULAS_PADRAO = [
    # (codigo, tipo_contrato, titulo, corpo)
    # VII – idêntico para ambos
    ("vii", "ambos",
     "CLÁUSULA VII - DO BALANÇO PATRIMONIAL (art. 1.065, CC)",
     "Ao término de cada exercício, em 31 de Dezembro, o administrador prestará contas "
     "justificadas de sua administração, procedendo à elaboração do inventário, do balanço "
     "patrimonial e do balanço de resultado econômico."),
    # VIII – LTDA
    ("viii", "ltda",
     "CLÁUSULA VIII - DECLARAÇÃO DE DESIMPEDIMENTO DE ADMINISTRADOR "
     "(art. 1.011, § 1° CC e art. 37, II da Lei n° 8.934 de 1994)",
     "Os Administradores declaram, sob as penas da lei, de que não estão impedidos de exercer "
     "a administração da empresa, por lei especial, ou em virtude de condenação criminal, ou "
     "se encontrar sob os efeitos dela, a pena que vede, ainda que temporariamente, o acesso "
     "a cargos públicos; ou por crime falimentar, de prevaricação, peita ou suborno, "
     "concussão, peculato, ou contra a economia popular, contra o sistema financeiro nacional, "
     "contra as normas de defesa da concorrência, contra as relações de consumo, a fé pública "
     "ou a propriedade."),
    # VIII – Unipessoal
    ("viii", "unipessoal",
     "CLÁUSULA VIII - DECLARAÇÃO DE DESIMPEDIMENTO DE ADMINISTRADOR "
     "(art. 1.011, § 1° CC e art. 37, II da Lei n° 8.934 de 1994)",
     "O Administrador declara, sob as penas da lei, de que não está impedido de exercer "
     "a administração da empresa, por lei especial, ou em virtude de condenação criminal, ou "
     "se encontrar sob os efeitos dela, a pena que vede, ainda que temporariamente, o acesso "
     "a cargos públicos; ou por crime falimentar, de prevaricação, peita ou suborno, "
     "concussão, peculato, ou contra a economia popular, contra o sistema financeiro nacional, "
     "contra as normas de defesa da concorrência, contra as relações de consumo, a fé pública "
     "ou a propriedade."),
    # IX – LTDA
    ("ix", "ltda",
     "CLÁUSULA IX - DO PRÓ-LABORE",
     "Os sócios poderão, de comum acordo, fixar uma retirada mensal, a título de pró-labore "
     "para os sócios e/ou administradores, observadas as disposições regulamentares pertinentes."),
    # IX – Unipessoal
    ("ix", "unipessoal",
     "CLÁUSULA IX - DO PRÓ-LABORE",
     "O sócio poderá fixar uma retirada mensal, a título de pró-labore para si e/ou para o "
     "administrador, observadas as disposições regulamentares pertinentes."),
    # X corpo – idêntico
    ("x_corpo", "ambos",
     "CLÁUSULA X - DISTRIBUIÇÃO DE LUCROS",
     "A sociedade poderá levantar balanços intermediários ou intercalares e distribuir os "
     "lucros evidenciados nos mesmos."),
    # X §1 – LTDA
    ("x_p1", "ltda",
     "Parágrafo Primeiro",
     "Os eventuais lucros serão distribuídos entre os sócios, total ou parcialmente, "
     "podendo ser desproporcional aos percentuais de participação societária, conforme "
     "deliberação dos sócios."),
    # X §1 – Unipessoal
    ("x_p1", "unipessoal",
     "Parágrafo Primeiro",
     "Os lucros apurados poderão ser distribuídos ao sócio, total ou parcialmente, "
     "conforme sua deliberação."),
    # X §2 – LTDA
    ("x_p2", "ltda",
     "Parágrafo Segundo",
     "Os prejuízos porventura havidos serão transferidos aos exercícios seguintes, "
     "observadas as disposições legais, e suportados pelos sócios na proporção de suas quotas."),
    # X §2 – Unipessoal
    ("x_p2", "unipessoal",
     "Parágrafo Segundo",
     "Os prejuízos porventura havidos serão transferidos aos exercícios seguintes, "
     "observadas as disposições legais, e suportados pelo sócio na proporção de sua quota."),
    # XI – LTDA
    ("xi", "ltda",
     "CLÁUSULA XI - DA RETIRADA OU FALECIMENTO DE SÓCIO",
     "Retirando-se, falecendo ou interditado qualquer sócio, a sociedade continuará suas "
     "atividades com os herdeiros, sucessores e o incapaz, desde que autorizados pelo(s) "
     "outro(s) sócio(s). Não sendo possível ou desejável, a sociedade dissolverá com relação "
     "ao sócio, procedendo-se ao levantamento do balanço especial na data da ocorrência do fato."),
    # XI – Unipessoal
    ("xi", "unipessoal",
     "CLÁUSULA XI - DA RETIRADA OU FALECIMENTO DE SÓCIO",
     "No caso de falecimento ou incapacidade do sócio, a sociedade poderá continuar com seus "
     "herdeiros ou sucessores, mediante a aprovação dos mesmos e desde que não exista disposição "
     "em contrário neste contrato."),
    # XI §único – LTDA
    ("xi_pu", "ltda",
     "Parágrafo único",
     "O mesmo procedimento será adotado em outros casos em que a sociedade se resolva em "
     "relação a seu sócio."),
    # XI §único – Unipessoal (sem parágrafo único)
    ("xi_pu", "unipessoal", "", ""),
    # XII – LTDA
    ("xii", "ltda",
     "CLÁUSULA XII - DA CESSÃO DE QUOTAS",
     "As quotas são indivisíveis e não poderão ser cedidas ou transferidas a terceiros sem o "
     "consentimento do outro sócio, a quem fica assegurado, em igualdade de condições e preço, "
     "direito de preferência, devendo o cedente comunicar sua intenção ao cessionário, que "
     "terá o prazo de trinta dias para manifestar-se, decorrido o qual, sem manifestação, "
     "entender-se-á que o sócio renunciou ao direito de preferência, ensejando, após a "
     "cessão delas, a alteração contratual pertinente."),
    # XII – Unipessoal
    ("xii", "unipessoal",
     "CLÁUSULA XII - DA CESSÃO DE QUOTAS",
     "As quotas são indivisíveis em relação à sociedade. O sócio único poderá ceder ou "
     "transferir, total ou parcialmente, suas quotas a terceiros ou a herdeiros, desde que "
     "o contrato social seja alterado para ingresso de novo sócio."),
    # XIII – LTDA
    ("xiii", "ltda",
     "CLÁUSULA XIII - DA RESPONSABILIDADE",
     "A responsabilidade de cada sócio é restrita ao valor das suas quotas, mas todos "
     "respondem solidariamente pela integralização do capital social."),
    # XIII – Unipessoal
    ("xiii", "unipessoal",
     "CLÁUSULA XIII - DA RESPONSABILIDADE",
     "A responsabilidade do sócio é restrita ao valor das suas quotas, mas responde "
     "solidariamente pela integralização do capital social."),
    # XIV ME – LTDA
    ("xiv_me", "ltda",
     "CLÁUSULA XIV - PORTE EMPRESARIAL",
     "Os sócios declaram que a sociedade se enquadra como Microempresa - ME, nos termos da "
     "Lei Complementar nº 123, de 14 de dezembro de 2006, e que não se enquadra em qualquer "
     "das hipóteses de exclusão do tratamento favorecido da mesma lei."),
    # XIV ME – Unipessoal
    ("xiv_me", "unipessoal",
     "CLÁUSULA XIV - PORTE EMPRESARIAL",
     "O sócio declara que a sociedade se enquadra como Microempresa - ME, nos termos da "
     "Lei Complementar nº 123, de 14 de dezembro de 2006, e que não se enquadra em qualquer "
     "das hipóteses de exclusão do tratamento favorecido da mesma lei."),

    # ===== ALTERAÇÃO CONTRATUAL =====
    # Preâmbulo — resolve
    ("alt_preambulo_resolve", "alteracao",
     "Preâmbulo — Cláusula de Resolução",
     "resolvem alterar e consolidar o contrato social primitivo e demais alterações, "
     "mediante as condições estabelecidas nas cláusulas seguintes:"),

    # Ingresso
    ("alt_ingresso_texto", "alteracao",
     "Ingresso de Sócio — Texto",
     "Ingressa na sociedade {ARTIGO} {NOME}, {QUALIFICACAO}."),

    # Retirada
    ("alt_retirada_texto", "alteracao",
     "Retirada de Sócio — Texto",
     "cedendo e transferindo suas quotas conforme deliberado pelos sócios remanescentes."),

    # Quitação
    ("alt_quitacao_texto", "alteracao",
     "Declaração de Conhecimento e Quitação — Texto",
     "declara, neste ato, ter pleno e irrestrito conhecimento da situação econômica, "
     "financeira e contábil da sociedade, dando plena, geral, irrevogável e irretratável "
     "quitação de suas quotas ao(s) sócio(s) remanescente(s) e à sociedade, nada mais tendo "
     "a reclamar a qualquer título, seja judicial ou extrajudicialmente."),

    # Capital — parágrafo único
    ("alt_capital_pu", "alteracao",
     "Capital Social — Parágrafo Único",
     "O capital encontra-se subscrito e integralizado em moeda corrente nacional "
     "pelos sócios, distribuídos da seguinte forma:"),

    # Administração — complemento
    ("alt_adm_complemento", "alteracao",
     "Administração — Complemento",
     "que representará legalmente a sociedade {MODO} e poderá praticar todo e qualquer ato "
     "de gestão pertinente ao objeto social."),

    # Desimpedimento
    ("alt_desimpedimento", "alteracao",
     "Declaração de Desimpedimento — Texto",
     "O(s) Administrador(es) declara(m), sob as penas da lei, de que não está(ão) "
     "impedido(s) de exercer a administração da empresa, por lei especial, ou em virtude "
     "de condenação criminal, ou se encontrar sob os efeitos dela, a pena que vede, ainda "
     "que temporariamente, o acesso a cargos públicos; ou por crime falimentar, de "
     "prevaricação, peita ou suborno, concussão, peculato, ou contra a economia popular, "
     "contra o sistema financeiro nacional, contra as normas de defesa da concorrência, "
     "contra as relações de consumo, a fé pública ou a propriedade."),

    # Permanecem inalteradas
    ("alt_permanece", "alteracao",
     "Cláusula — Permanecem Inalteradas",
     "Permanecem inalteradas as demais cláusulas vigentes que não colidirem com as "
     "disposições do presente instrumento."),

    # Da Consolidação
    ("alt_consolidacao", "alteracao",
     "Cláusula — Da Consolidação",
     "A vista das modificações ora ajustadas consolida-se o contrato social, que passa a ter "
     "a seguinte redação:"),

    # Fecho do consolidado
    ("alt_fecho", "alteracao",
     "Fecho do Contrato Consolidado",
     "E por estarem em perfeito acordo, em tudo que neste instrumento particular foi lavrado, "
     "obrigam-se a cumprir o presente instrumento, e o assina em uma única via que será "
     "destinada ao registro e arquivamento na Junta Comercial do {ESTADO}."),
]


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS fichas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            subtipo TEXT,
            razao_social TEXT,
            dados TEXT NOT NULL,
            criado_em TEXT DEFAULT (datetime('now', 'localtime')),
            atualizado_em TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS clausulas_banco (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            corpo TEXT NOT NULL,
            tipo_contrato TEXT DEFAULT 'todos',
            ativo INTEGER DEFAULT 1,
            criado_em TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS modelos_clausulas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL,
            tipo_contrato TEXT NOT NULL DEFAULT 'ltda',
            titulo TEXT NOT NULL,
            corpo TEXT NOT NULL,
            UNIQUE(codigo, tipo_contrato)
        );

        CREATE TABLE IF NOT EXISTS configuracoes (
            chave TEXT PRIMARY KEY,
            valor TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            profile       TEXT NOT NULL DEFAULT 'operacional',
            active        INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );
    """)
    # Bootstrap: cria admin padrão se não existir nenhum usuário
    import uuid as _uuid
    from werkzeug.security import generate_password_hash as _gph
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO users (id, name, email, password_hash, profile) VALUES (?,?,?,?,?)",
            (str(_uuid.uuid4()), "Administrador", "admin@contratos.com",
             _gph("admin123", method="pbkdf2:sha256"), "admin")
        )

    # Popula defaults na primeira execução
    for codigo, tipo, titulo, corpo in _CLAUSULAS_PADRAO:
        conn.execute(
            "INSERT OR IGNORE INTO modelos_clausulas (codigo, tipo_contrato, titulo, corpo) "
            "VALUES (?, ?, ?, ?)",
            (codigo, tipo, titulo, corpo)
        )
    conn.commit()
    conn.close()


def salvar_ficha(tipo, subtipo, razao_social, dados):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO fichas (tipo, subtipo, razao_social, dados) VALUES (?, ?, ?, ?)",
        (tipo, subtipo, razao_social, json.dumps(dados, ensure_ascii=False))
    )
    conn.commit()
    fid = cur.lastrowid
    conn.close()
    return fid


def atualizar_ficha(fid, subtipo, razao_social, dados):
    conn = get_db()
    conn.execute(
        "UPDATE fichas SET subtipo=?, razao_social=?, dados=?, "
        "atualizado_em=datetime('now','localtime') WHERE id=?",
        (subtipo, razao_social, json.dumps(dados, ensure_ascii=False), fid)
    )
    conn.commit()
    conn.close()


def get_ficha(fid):
    conn = get_db()
    row = conn.execute("SELECT * FROM fichas WHERE id=?", (fid,)).fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["dados"] = json.loads(d["dados"])
        return d
    return None


def listar_fichas(tipo=None):
    conn = get_db()
    if tipo:
        rows = conn.execute(
            "SELECT * FROM fichas WHERE tipo=? ORDER BY atualizado_em DESC", (tipo,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM fichas ORDER BY atualizado_em DESC"
        ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["dados"] = json.loads(d["dados"])
        result.append(d)
    return result


def excluir_ficha(fid):
    conn = get_db()
    conn.execute("DELETE FROM fichas WHERE id=?", (fid,))
    conn.commit()
    conn.close()


def listar_clausulas(tipo_contrato=None):
    conn = get_db()
    if tipo_contrato:
        rows = conn.execute(
            "SELECT * FROM clausulas_banco WHERE ativo=1 "
            "AND (tipo_contrato=? OR tipo_contrato='todos') ORDER BY titulo",
            (tipo_contrato,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM clausulas_banco WHERE ativo=1 ORDER BY titulo"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def salvar_clausula(titulo, corpo, tipo_contrato="todos"):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO clausulas_banco (titulo, corpo, tipo_contrato) VALUES (?, ?, ?)",
        (titulo, corpo, tipo_contrato)
    )
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return cid


def excluir_clausula(cid):
    conn = get_db()
    conn.execute("UPDATE clausulas_banco SET ativo=0 WHERE id=?", (cid,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Modelos de cláusulas (editáveis)
# ---------------------------------------------------------------------------

def listar_modelos():
    """Retorna todos os modelos de cláusulas agrupados por código."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM modelos_clausulas ORDER BY codigo, tipo_contrato"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_modelo(codigo: str, tipo_contrato: str) -> dict:
    """Retorna o modelo de uma cláusula específica."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM modelos_clausulas WHERE codigo=? AND tipo_contrato=?",
        (codigo, tipo_contrato)
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


def salvar_modelo(codigo: str, tipo_contrato: str, titulo: str, corpo: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO modelos_clausulas (codigo, tipo_contrato, titulo, corpo) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(codigo, tipo_contrato) DO UPDATE SET titulo=excluded.titulo, corpo=excluded.corpo",
        (codigo, tipo_contrato, titulo, corpo)
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Configurações (chave/valor JSON)
# ---------------------------------------------------------------------------

def get_config(chave: str, default=None):
    conn = get_db()
    row = conn.execute("SELECT valor FROM configuracoes WHERE chave=?", (chave,)).fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row["valor"])
        except Exception:
            return row["valor"]
    return default


def set_config(chave: str, valor):
    conn = get_db()
    conn.execute(
        "INSERT INTO configuracoes (chave, valor) VALUES (?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
        (chave, json.dumps(valor, ensure_ascii=False))
    )
    conn.commit()
    conn.close()


def get_clausula_texto(codigo: str, is_unipessoal: bool = False) -> tuple:
    """
    Retorna (titulo, corpo) lendo do DB.
    Prioridade: tipo_contrato específico > 'ambos'.
    """
    tipo = "unipessoal" if is_unipessoal else "ltda"
    conn = get_db()
    row = conn.execute(
        "SELECT titulo, corpo FROM modelos_clausulas "
        "WHERE codigo=? AND tipo_contrato IN (?, 'ambos') "
        "ORDER BY CASE tipo_contrato WHEN ? THEN 0 ELSE 1 END LIMIT 1",
        (codigo, tipo, tipo)
    ).fetchone()
    conn.close()
    if row:
        return row["titulo"], row["corpo"]
    return "", ""


def get_texto_alteracao(codigo: str) -> str:
    """Retorna o corpo de um modelo de cláusula de alteração contratual."""
    conn = get_db()
    row = conn.execute(
        "SELECT corpo FROM modelos_clausulas WHERE codigo=? AND tipo_contrato='alteracao' LIMIT 1",
        (codigo,)
    ).fetchone()
    conn.close()
    return row["corpo"] if row else ""


# ---------------------------------------------------------------------------
# Usuários
# ---------------------------------------------------------------------------

def get_user_by_email(email: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email=? AND active=1", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(uid: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_users():
    conn = get_db()
    rows = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_user(name, email, password_hash, profile="operacional"):
    import uuid
    uid = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        "INSERT INTO users (id, name, email, password_hash, profile) VALUES (?,?,?,?,?)",
        (uid, name, email, password_hash, profile)
    )
    conn.commit()
    conn.close()
    return uid


def update_user(uid, name, email, profile, active):
    conn = get_db()
    conn.execute(
        "UPDATE users SET name=?, email=?, profile=?, active=? WHERE id=?",
        (name, email, profile, int(active), uid)
    )
    conn.commit()
    conn.close()


def inativar_user(uid):
    conn = get_db()
    conn.execute("UPDATE users SET active=0 WHERE id=?", (uid,))
    conn.commit()
    conn.close()
