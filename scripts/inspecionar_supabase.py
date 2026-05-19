"""
inspecionar_supabase.py — Fase 0 (introspecção / debug).

Conecta no Supabase e lista tabelas + colunas reais do schema, depois tenta
casar cada tabela com as abas esperadas pelo SCHEMA do loader, sugerindo o
mapa TABELAS_SUPABASE.

Uso:
    python scripts/inspecionar_supabase.py

Pré-requisito: bloco [supabase] preenchido em .streamlit/secrets.toml.
Descartável após a migração.
"""

import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text  # noqa: E402

from scripts._supabase_conf import criar_engine  # noqa: E402
from etl.loader import SCHEMA  # noqa: E402


def _norm(s: str) -> str:
    """remove acento, lower, sem espaço/underscore — p/ casar nomes."""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().replace("_", "").replace(" ", "")


def main():
    engine, schema = criar_engine()
    insp = inspect(engine)

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print(f"✅ Conectado ao Supabase (schema='{schema}')\n")

    tabelas = insp.get_table_names(schema=schema)
    print(f"Tabelas encontradas ({len(tabelas)}):")
    for t in sorted(tabelas):
        cols = [c["name"] for c in insp.get_columns(t, schema=schema)]
        print(f"  • {t}  ({len(cols)} cols): {', '.join(cols)}")

    print("\n--- Mapa sugerido SCHEMA → tabela Supabase ---")
    tab_norm = {_norm(t): t for t in tabelas}
    faltando = []
    print("TABELAS_SUPABASE = {")
    for aba, cols_req in SCHEMA.items():
        cand = tab_norm.get(_norm(aba))
        if cand:
            real_cols = {c["name"] for c in insp.get_columns(cand, schema=schema)}
            ausentes = [c for c in cols_req if c not in real_cols]
            obs = "" if not ausentes else f"  # ⚠ colunas ausentes: {ausentes}"
            print(f'    "{aba}": "{cand}",{obs}')
        else:
            faltando.append(aba)
            print(f'    "{aba}": None,  # ❌ NÃO ENCONTRADA — preencher manual')
    print("}")

    if faltando:
        print(f"\n⚠ Abas sem tabela correspondente: {faltando}")
        print("  Ajuste TABELAS_SUPABASE manualmente em etl/loader.py")
    else:
        print("\n✅ Todas as abas do SCHEMA têm tabela candidata.")


if __name__ == "__main__":
    main()
