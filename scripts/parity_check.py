"""
parity_check.py — Fase 2 (teste de paridade Sheets vs Supabase).

Roda carregar_dados() forçando cada fonte e compara os DataFrames resultantes
APÓS a tipagem do loader (mesma transformação p/ ambas). Acusa divergências
de shape, colunas, nulos e agregados-chave antes do corte definitivo.

Uso:
    python scripts/parity_check.py

Pré-requisitos: blocos [supabase] e sheet_id/[gcp_service_account] em
.streamlit/secrets.toml. Descartável após a migração.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from etl.loader import carregar_dados  # noqa: E402

# (df_key, coluna numérica p/ somar, coluna de ID p/ comparar conjunto)
CHECKS = [
    ("pedidos", "Total Venda", "ID"),
    ("itens", "Quantidade", "ID_pedido"),
    ("produtos", "preco_custo", "ID"),
    ("produtos_todos", "preco_custo", "ID"),
    ("estoque", "saldoFisico", "ID_produto"),
    ("detalhes", None, "ID_produto"),
    ("vendedores", None, "ID"),
    ("lojas", None, "ID"),
    ("situacoes", None, "ID"),
    ("depositos", None, "ID"),
]


def _resumo(df: pd.DataFrame, num_col, id_col):
    soma = None
    if num_col and num_col in df.columns:
        soma = round(float(pd.to_numeric(df[num_col], errors="coerce").sum()), 2)
    ids = set(df[id_col].astype(str)) if id_col in df.columns else set()
    return df.shape, sorted(map(str, df.columns)), soma, ids


def main():
    print("Carregando fonte=sheets ...")
    a = carregar_dados(fonte="sheets")
    print("Carregando fonte=supabase ...")
    b = carregar_dados(fonte="supabase")

    for nome, d in (("sheets", a), ("supabase", b)):
        v = d.get("validacao", {})
        if not v.get("ok", False):
            print(f"❌ {nome} falhou na validação: {v.get('erros')}")
            return

    print("\n=== PARIDADE ===")
    ok_geral = True
    for key, num_col, id_col in CHECKS:
        if key not in a or key not in b:
            print(f"⚠ {key}: ausente em uma das fontes")
            ok_geral = False
            continue

        sa, ca, soma_a, ids_a = _resumo(a[key], num_col, id_col)
        sb, cb, soma_b, ids_b = _resumo(b[key], num_col, id_col)

        problemas = []
        if sa[0] != sb[0]:
            problemas.append(f"linhas {sa[0]} vs {sb[0]}")
        if ca != cb:
            so_a = set(ca) - set(cb)
            so_b = set(cb) - set(ca)
            problemas.append(f"colunas divergem (só sheets={so_a}, só supabase={so_b})")
        if soma_a is not None and soma_a != soma_b:
            problemas.append(f"soma {num_col}: {soma_a} vs {soma_b}")
        if ids_a != ids_b:
            problemas.append(
                f"IDs divergem (só sheets={len(ids_a - ids_b)}, "
                f"só supabase={len(ids_b - ids_a)})"
            )

        if problemas:
            ok_geral = False
            print(f"❌ {key}: " + " | ".join(problemas))
        else:
            print(f"✅ {key}: {sa[0]} linhas, paridade OK")

    print("\n" + ("✅ PARIDADE TOTAL — pode cortar p/ Supabase"
                   if ok_geral else "❌ Há divergências — ajustar antes do corte"))


if __name__ == "__main__":
    main()
