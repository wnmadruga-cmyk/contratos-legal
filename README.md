# Contratos Legal — Sistema de Contratos Societários LTDA

Sistema web em Flask para geração de contratos sociais e alterações contratuais de Sociedades Limitadas (LTDA), com suporte à geração de documentos DOCX prontos para registro na Junta Comercial.

## Funcionalidades

- Constituição de LTDA e LTDA Unipessoal
- Alterações contratuais com consolidação automática (ingresso/retirada de sócios, capital social, administração, endereço, objeto social, nome empresarial)
- Cláusula de aumento de capital com integralização dividida (dinheiro, bens móveis, bens imóveis)
- Suporte a menor/incapaz com representante legal
- Verificação e sugestão de razão social (firma ou denominação) via IA
- Extração automática de dados de contratos existentes (DOCX/PDF) via IA
- Banco de cláusulas editáveis
- Painel de eventos FCN/Viabilidade por alteração
- Configuração de respostas padrão da FCN

## Pré-requisitos

- Python 3.10 ou superior
- pip

## Instalação

```bash
# Clone o repositório
git clone https://github.com/wnmadruga-cmyk/contratos-legal.git
cd contratos-legal

# Crie e ative um ambiente virtual (recomendado)
python3 -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows

# Instale as dependências
pip install -r requirements.txt
```

## Configuração

Crie um arquivo `.env` na raiz do projeto com a chave da API OpenAI:

```
OPENAI_API_KEY=sk-...sua-chave-aqui...
```

> A chave é necessária para as funções de IA (extração de contratos, verificação de razão social, geração de objeto social). O sistema funciona sem ela, mas essas funções ficam desabilitadas.

## Como executar

```bash
python3 app.py
```

Acesse em: **http://localhost:8080**

O banco de dados SQLite (`contratos.db`) é criado automaticamente na primeira execução.

## Estrutura do projeto

```
├── app.py                  # Servidor Flask — rotas e endpoints
├── db.py                   # Banco de dados SQLite (fichas, cláusulas, configurações)
├── gerar_contrato.py       # Gerador de contrato social (constituição)
├── gerar_alteracao.py      # Gerador de alteração contratual + consolidado
├── extrator_docx.py        # Extrator de dados de contratos via IA
├── requirements.txt        # Dependências Python
├── templates/              # Templates HTML (Jinja2 + Bootstrap 5)
│   ├── base.html
│   ├── dashboard.html
│   ├── form_constituicao.html
│   ├── form_alteracao.html
│   ├── fcn_config.html
│   └── ...
└── .env                    # NÃO versionar — variáveis de ambiente locais
```

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| OPENAI_API_KEY | Não | Chave da API OpenAI para funções de IA |
