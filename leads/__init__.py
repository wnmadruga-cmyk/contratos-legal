"""
Módulo de Leads / Kanban / CRM.

Isolado em Blueprint para não poluir o app principal de contratos.
Tabelas no mesmo SQLite, prefixadas com `lead_`.
"""
from flask import Blueprint

from . import db  # noqa: F401  (registra init no import)

leads_bp = Blueprint(
    "leads",
    __name__,
    url_prefix="/leads",
    template_folder="../templates/leads",
)

leads_admin_bp = Blueprint(
    "leads_admin",
    __name__,
    url_prefix="/admin/leads",
    template_folder="../templates/leads/admin",
)

leads_api_bp = Blueprint(
    "leads_api",
    __name__,
    url_prefix="/api/leads",
)

# Importa rotas para registrá-las nos blueprints (após criação dos BPs).
from . import routes      # noqa: E402,F401
from . import admin       # noqa: E402,F401
from . import api         # noqa: E402,F401


def register(app):
    """Registra os blueprints no app Flask e inicializa o schema."""
    db.init_db()
    app.register_blueprint(leads_bp)
    app.register_blueprint(leads_admin_bp)
    app.register_blueprint(leads_api_bp)
