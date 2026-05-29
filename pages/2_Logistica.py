"""
Página: Dashboard Logístico (Reposição de Loja)
VM Dinâmico + Pulmão. Sugestão baseada em VM+Pulmão − Estoque.
"""

import streamlit as st
from auth import exigir_login
exigir_login()
import plotly.express as px
import pandas as pd
from etl.logistica import processar_logistica
from etl.vm_dinamico import carregar_parametros_vm, calcular_vm_por_sku

import yaml
from pathlib import Path
from etl.loader import carregar_dados


def _carregar():
    caminho_config = Path(__file__).parent.parent / "config.yaml"
    with open(caminho_config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    dados = carregar_dados()

    caminho_params = Path(__file__).parent.parent / "data" / "Parametros_VM.xlsx"
    params_vm = carregar_parametros_vm(str(caminho_params))

    return dados, config, params_vm


with st.spinner("Carregando dados..."):
    dados, config, params_vm = _carregar()

if not dados["validacao"]["ok"]:
    st.error("Dados inválidos. Verifique a página principal.")
    st.stop()


@st.cache_data
def _processar(_dados, _config, _params_vm):
    vm_map = None
    if _params_vm["ok"]:
        vm_map = calcular_vm_por_sku(_dados, _params_vm)
    return processar_logistica(_dados, _config, vm_map), _params_vm


with st.spinner("Processando logística..."):
    df, params_info = _processar(dados, config, params_vm)

st.title("📦 Logística — Reposição de Loja")

# Info sobre VM
if params_info["ok"]:
    g = params_info["globais"]
    st.caption(
        f"VM Dinâmico ativo — "
        f"Cobertura: {int(g['dias_cobertura'])}d | "
        f"Alta: {int(g['inicio_alta'])}-{int(g['fim_alta'])} | "
        f"Mult. PA: {g['mult_pa']}x | "
        f"LT: {int(g['lead_time'])}d | "
        f"Colégios: {len(params_info['colegios'])} | "
        f"SKUs c/ correção: {len(params_info['skus'])}"
    )
    if params_info["avisos"]:
        for av in params_info["avisos"]:
            st.warning(av)
else:
    st.warning("⚠️ Parametros_VM.xlsx não encontrado em data/. Usando VM fixo do config.yaml.")

# =================================================================
# FILTROS
# =================================================================
col_f1, col_f2, col_f3 = st.columns(3)

with col_f1:
    lojas = ["Todas"] + sorted(df["Loja"].unique().tolist())
    filtro_loja = st.selectbox("Loja", lojas)

with col_f2:
    ordem_acoes = ["🚫 Estoque Negativo", "🚨 Ruptura", "✨ Repor", "🔵 Sem Venda", "✅ OK"]
    acoes_existentes = [a for a in ordem_acoes if a in df["Acao"].values]
    filtro_acao = st.selectbox("Ação", ["Todas"] + acoes_existentes)

with col_f3:
    cats = df["Categoria"].dropna().astype(str)
    cats = cats[cats.ne("") & cats.ne("nan")]
    categorias = ["Todas"] + sorted(cats.unique().tolist())
    filtro_cat = st.selectbox("Categoria", categorias)

col_f4, col_f5 = st.columns(2)

with col_f4:
    colegios = df["Colegio"].dropna().astype(str)
    colegios = colegios[colegios.ne("") & colegios.ne("nan")]
    colegios_disp = ["Todos"] + sorted(colegios.unique().tolist())
    filtro_colegio = st.selectbox("Colégio", colegios_disp)

with col_f5:
    filtro_texto = st.text_input("🔍 Buscar SKU ou Produto", placeholder="Digite para filtrar...")

df_filtrado = df.copy()
if filtro_loja != "Todas":
    df_filtrado = df_filtrado[df_filtrado["Loja"] == filtro_loja]
if filtro_acao != "Todas":
    df_filtrado = df_filtrado[df_filtrado["Acao"] == filtro_acao]
if filtro_cat != "Todas":
    df_filtrado = df_filtrado[df_filtrado["Categoria"] == filtro_cat]
if filtro_colegio != "Todos":
    df_filtrado = df_filtrado[df_filtrado["Colegio"] == filtro_colegio]
if filtro_texto.strip():
    termo = filtro_texto.strip().lower()
    df_filtrado = df_filtrado[
        df_filtrado["SKU"].str.lower().str.contains(termo, na=False) |
        df_filtrado["Produto"].str.lower().str.contains(termo, na=False)
    ]

# =================================================================
# KPIs
# =================================================================
st.subheader("Resumo")

c1, c2, c3, c4 = st.columns(4)

repor = df_filtrado[df_filtrado["Acao"] == "✨ Repor"]
ruptura = df_filtrado[df_filtrado["Acao"] == "🚨 Ruptura"]
negativo = df_filtrado[df_filtrado["Acao"] == "🚫 Estoque Negativo"]
ok = df_filtrado[df_filtrado["Acao"] == "✅ OK"]

c1.metric("✨ Repor", f"{len(repor)} SKUs", f"{repor['SugestaoQtd'].sum():.0f} pçs")
c2.metric("🚨 Ruptura", f"{len(ruptura)} SKUs")
c3.metric("🚫 Negativo", f"{len(negativo)} SKUs")
c4.metric("✅ OK", f"{len(ok)} SKUs")

# =================================================================
# TABELA PRINCIPAL
# =================================================================
st.subheader("Detalhamento por SKU")

colunas_principais = [
    "Loja", "SKU", "Produto", "Colegio", "Categoria", "Tamanho",
    "EstoqueCentral", "EstoqueLoja", "VM", "Pulmao", "Total",
    "SugestaoQtd", "Acao",
]

# Exibe com verde claro na Sugestão Qtd via Styler
df_exibir = df_filtrado[colunas_principais].copy()
df_exibir = df_exibir.rename(columns={
    "EstoqueCentral": "Est. Central",
    "EstoqueLoja": "Est. Loja",
    "Pulmao": "Pulmão",
    "Total": "VM+Pulmão",
    "SugestaoQtd": "Sugestão Qtd",
    "Acao": "Ação",
})

def _verde_sugestao(val):
    if isinstance(val, (int, float)) and val > 0:
        return "background-color: #E8F5E9"
    return ""

styled = df_exibir.style.applymap(_verde_sugestao, subset=["Sugestão Qtd"])

st.dataframe(styled, use_container_width=True, hide_index=True)

st.caption(f"**{len(df_filtrado)}** SKUs exibidos")

# =================================================================
# DIAGNÓSTICO VM (expander)
# =================================================================
with st.expander("🔍 Diagnóstico VM Dinâmico — Detalhes do Cálculo"):
    st.caption(
        "Mostra como o VM e Pulmão foram calculados para cada SKU. "
        "**Pulmão** = Z × σ × √LT (absorve picos de demanda)."
    )

    colunas_diag = [
        "SKU", "Produto", "Colegio", "VM", "Pulmao", "Total", "FonteVM",
        "PA", "Sigma", "D_Alta", "TaxaCresc", "Correcao",
    ]

    df_diag = df_filtrado[colunas_diag].drop_duplicates(subset=["SKU"]).sort_values("Total", ascending=False)

    st.dataframe(
        df_diag,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Pulmao": st.column_config.NumberColumn("Pulmão"),
            "Total": st.column_config.NumberColumn("VM+Pulmão"),
            "PA": st.column_config.NumberColumn("PA (pçs/atend)", format="%.1f"),
            "Sigma": st.column_config.NumberColumn("σ diário", format="%.2f"),
            "D_Alta": st.column_config.NumberColumn("Demanda/Dia", format="%.3f"),
            "TaxaCresc": st.column_config.NumberColumn("Taxa Cresc.", format="%.2f"),
            "Correcao": st.column_config.NumberColumn("Correção", format="%.2f"),
            "FonteVM": st.column_config.TextColumn("Fonte VM"),
        },
    )

    st.caption(
        "**σ alto** = vendas irregulares → pulmão maior. "
        "**σ ≈ 0** = vendas estáveis → pulmão mínimo."
    )

# =================================================================
# GRÁFICOS
# =================================================================

st.subheader("Distribuição por Ação")
dist_acao = df_filtrado["Acao"].value_counts().reset_index()
dist_acao.columns = ["Ação", "Quantidade"]

fig_acao = px.bar(
    dist_acao, x="Ação", y="Quantidade",
    color="Ação", text="Quantidade",
)
fig_acao.update_layout(showlegend=False, height=350)
fig_acao.update_traces(textposition="outside")
st.plotly_chart(fig_acao, use_container_width=True)

# Pareto por Categoria
if df_filtrado["Categoria"].notna().any() and df_filtrado["Categoria"].str.strip().ne("").any():
    st.subheader("Pareto — Sugestão de Reposição por Categoria")
    transf_cat = (
        df_filtrado[df_filtrado["Acao"] == "✨ Repor"]
        .groupby("SuperCategoria")["SugestaoQtd"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
    )
    transf_cat.columns = ["Super Categoria", "Quantidade"]

    if len(transf_cat) > 0:
        transf_cat["% Acumulado"] = (transf_cat["Quantidade"].cumsum() / transf_cat["Quantidade"].sum() * 100)

        fig_pareto = px.bar(
            transf_cat, x="Super Categoria", y="Quantidade", text="Quantidade",
        )
        fig_pareto.add_scatter(
            x=transf_cat["Super Categoria"], y=transf_cat["% Acumulado"],
            mode="lines+markers", name="% Acumulado", yaxis="y2",
        )
        fig_pareto.update_layout(
            yaxis2=dict(title="% Acumulado", overlaying="y", side="right", range=[0, 110]),
            showlegend=False, height=400,
        )
        st.plotly_chart(fig_pareto, use_container_width=True)
