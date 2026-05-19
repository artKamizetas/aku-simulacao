"""
_supabase_conf.py — helper compartilhado pelos scripts de migração (Fase 0/2).

Lê o bloco [supabase] de .streamlit/secrets.toml e cria uma engine SQLAlchemy.
Descartável — usado só durante a migração Google Sheets → Supabase.
"""

from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # fallback (pip install tomli)

from sqlalchemy import create_engine
from sqlalchemy.engine import URL

RAIZ = Path(__file__).resolve().parent.parent
SECRETS = RAIZ / ".streamlit" / "secrets.toml"


def carregar_secrets() -> dict:
    if not SECRETS.exists():
        raise FileNotFoundError(f"secrets.toml não encontrado: {SECRETS}")
    with open(SECRETS, "rb") as f:
        return tomllib.load(f)


def criar_engine():
    """Engine SQLAlchemy a partir de st.secrets['supabase']."""
    cfg = carregar_secrets().get("supabase")
    if not cfg:
        raise KeyError("Bloco [supabase] ausente em secrets.toml")

    url = URL.create(
        "postgresql+psycopg2",
        username=cfg["user"],
        password=cfg["password"],
        host=cfg["host"],
        port=int(cfg.get("port", 5432)),
        database=cfg["dbname"],
    )
    return create_engine(url, pool_pre_ping=True), cfg.get("schema", "public")
