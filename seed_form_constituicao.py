import sqlite3
import json
import uuid

# ID do serviço Constituicao
TYPE_ID = "5bfb2671-6416-468e-b347-33d171788b1b"
DB_PATH = "/Users/luizborges/contratos-legal/contratos.db"

def new_id():
    return str(uuid.uuid4())

fields = [
    # ---- SÓCIOS ----
    {
        "section": "SÓCIOS",
        "label": "Sócios",
        "field_key": "socios",
        "field_type": "repeater",
        "required": 1,
        "help_text": None,
        "options": [
            {"key": "nome_completo", "label": "Nome completo", "field_type": "text"},
            {"key": "socio_admin", "label": "Sócio administrador", "field_type": "radio", "options": [{"key": "Sim", "label": "Sim"}, {"key": "Não", "label": "Não"}]},
            {"key": "func_publico", "label": "Funcionário público", "field_type": "radio", "options": [{"key": "Sim", "label": "Sim"}, {"key": "Não", "label": "Não"}]},
            {"key": "telefone", "label": "Telefone", "field_type": "text"},
            {"key": "email", "label": "E-mail (AR Internet, SEFA-PR, CNPJ)", "field_type": "text"},
            {"key": "profissao", "label": "Profissão", "field_type": "text"},
            {"key": "estado_civil", "label": "Estado civil", "field_type": "select", "options": [{"key": "Solteiro(a)", "label": "Solteiro(a)"}, {"key": "Casado(a)", "label": "Casado(a)"}, {"key": "Divorciado(a)", "label": "Divorciado(a)"}, {"key": "Viúvo(a)", "label": "Viúvo(a)"}]},
            {"key": "regime_bens", "label": "Regime de bens", "field_type": "select", "options": [{"key": "Nenhum", "label": "Nenhum (Solteiro)"}, {"key": "Comunhão Parcial", "label": "Comunhão Parcial"}, {"key": "Comunhão Universal", "label": "Comunhão Universal"}, {"key": "Separação Total", "label": "Separação Total"}, {"key": "Participação Final", "label": "Participação Final"}]},
            {"key": "logradouro", "label": "Logradouro", "field_type": "text"},
            {"key": "bairro", "label": "Bairro", "field_type": "text"},
            {"key": "complemento", "label": "Complemento", "field_type": "text"},
            {"key": "socio_cep", "label": "CEP", "field_type": "text"},
            {"key": "socio_estado", "label": "Estado (UF)", "field_type": "text"},
            {"key": "socio_cidade", "label": "Cidade", "field_type": "text"},
            {"key": "qtd_quotas_integ", "label": "Qtd. quotas integralizadas", "field_type": "number"},
            {"key": "qtd_quotas_nao_integ", "label": "Qtd. quotas não integralizadas", "field_type": "number"},
            {"key": "valor_quota", "label": "Valor unitário da quota (R$)", "field_type": "number"},
            {"key": "forma_integ", "label": "Forma de integralização", "field_type": "select", "options": [{"key": "Dinheiro", "label": "Dinheiro"}, {"key": "Bens Movéis", "label": "Bens Móveis"}, {"key": "Bens Imóveis", "label": "Bens Imóveis"}]}
        ]
    },
    
    # ---- EMPRESA ----
    {
        "section": "EMPRESA", "label": "Razão social", "field_key": "razao_social", "field_type": "text", "required": 1
    },
    {
        "section": "EMPRESA", "label": "Nome fantasia", "field_key": "nome_fantasia", "field_type": "text", "required": 0
    },
    {
        "section": "EMPRESA", "label": "Natureza jurídica", "field_key": "natureza_juridica", "field_type": "select", "required": 1,
        "options": ["Sociedade Limitada (LTDA)", "Sociedade Anônima (S/A)", "Sociedade Limitada Unipessoal (SLU)", "Empresário Individual (EI)"]
    },
    {
        "section": "EMPRESA", "label": "Objeto social", "field_key": "objeto_social", "field_type": "textarea", "required": 1
    },

    # ---- ATIVIDADES ----
    {
        "section": "ATIVIDADES", "label": "CNAE principal", "field_key": "cnae_principal", "field_type": "select_cnae", "required": 1
    },
    {
        "section": "ATIVIDADES", "label": "Exercida no local:", "field_key": "exercida_local", "field_type": "radio", "required": 0, "options": ["Sim", "Não"]
    },
    {
        "section": "ATIVIDADES", "label": "CNAEs secundários", "field_key": "cnaes_secundarios", "field_type": "repeater", "required": 0,
        "options": [{"key": "cnae", "label": "CNAE secundário", "field_type": "select_cnae"}]
    },

    # ---- ENDEREÇO EMPRESA ----
    { "section": "ENDEREÇO EMPRESA", "label": "Logradouro", "field_key": "empresa_logradouro", "field_type": "text", "required": 1 },
    { "section": "ENDEREÇO EMPRESA", "label": "Bairro", "field_key": "empresa_bairro", "field_type": "text", "required": 1 },
    { "section": "ENDEREÇO EMPRESA", "label": "Complemento", "field_key": "empresa_complemento", "field_type": "text", "required": 1 },
    { "section": "ENDEREÇO EMPRESA", "label": "CEP", "field_key": "empresa_cep", "field_type": "text", "required": 0 },
    { "section": "ENDEREÇO EMPRESA", "label": "Estado (UF)", "field_key": "empresa_estado", "field_type": "text", "required": 0 },
    { "section": "ENDEREÇO EMPRESA", "label": "Cidade", "field_key": "empresa_cidade", "field_type": "text", "required": 0 },
    { "section": "ENDEREÇO EMPRESA", "label": "Tipo de imóvel", "field_key": "tipo_imovel", "field_type": "select", "required": 0, "options": ["Comercial", "Residencial", "Misto"] },
    { "section": "ENDEREÇO EMPRESA", "label": "Inscrição imobiliária", "field_key": "inscricao_imobiliaria", "field_type": "text", "required": 0 },
    { "section": "ENDEREÇO EMPRESA", "label": "Lote", "field_key": "lote", "field_type": "text", "required": 0 },
    { "section": "ENDEREÇO EMPRESA", "label": "Quadra", "field_key": "quadra", "field_type": "text", "required": 0 },
    { "section": "ENDEREÇO EMPRESA", "label": "Metragem (m²)", "field_key": "metragem", "field_type": "text", "required": 0 },

    # ---- CONTATO EMPRESA ----
    { "section": "CONTATO EMPRESA", "label": "Telefone", "field_key": "empresa_telefone", "field_type": "text", "required": 1 },
    { "section": "CONTATO EMPRESA", "label": "E-mail", "field_key": "empresa_email", "field_type": "text", "required": 1 },

    # ---- IDENTIFICAÇÃO ----
    { "section": "IDENTIFICAÇÃO", "label": "CNPJ", "field_key": "cnpj", "field_type": "text", "required": 0 },
    { "section": "IDENTIFICAÇÃO", "label": "Inscrição Estadual (IE)", "field_key": "ie", "field_type": "text", "required": 0 },
    { "section": "IDENTIFICAÇÃO", "label": "Inscrição Municipal (IM)", "field_key": "im", "field_type": "text", "required": 0 },
    { "section": "IDENTIFICAÇÃO", "label": "Regime tributário", "field_key": "regime_tributario", "field_type": "select", "required": 0, "options": ["Simples Nacional", "Lucro Presumido", "Lucro Real", "MEI"] },
]

def run():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM lead_form_fields WHERE lead_type_id=?", (TYPE_ID,))
    
    for pos, f in enumerate(fields):
        opt = json.dumps(f.get("options")) if f.get("options") else None
        cur.execute(
            """INSERT INTO lead_form_fields (id, lead_type_id, field_key, label, field_type, options, required, section, position, help_text) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (new_id(), TYPE_ID, f["field_key"], f["label"], f.get("field_type", "text"), opt, f.get("required", 0), f.get("section", "Geral"), pos, f.get("help_text"))
        )
    
    conn.commit()
    print("Banco atualizado com formulário 'Constituição'!")

if __name__ == "__main__":
    run()
