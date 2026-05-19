"""
loader.py — Leitura e Validação da Exportação Bling

Fontes de dados suportadas (selecionadas por st.secrets["fonte_dados"]):
  - "supabase" (DEFAULT, produção): lê o Postgres do Supabase via SQLAlchemy
  - "sheets" (transição/rollback): lê o Google Sheets via gspread — LEGADO
  - Excel local (desenvolvimento): fallback quando nada configurado

Nenhuma página ou módulo ETL precisa ser alterado — a interface é idêntica
(dict de DataFrames com as chaves/colunas do SCHEMA).

Uso:
    from etl.loader import carregar_dados
    dados = carregar_dados()                                    # fonte conforme secrets
    dados = carregar_dados("data/Integração Bling ERP.xlsx")    # força Excel local
    dados["pedidos"]  # DataFrame dos pedidos
"""

import pandas as pd
import streamlit as st
from pathlib import Path


# Mapa de abas esperadas e suas colunas obrigatórias
SCHEMA = {
    "Pedidos": ["ID", "Pedido", "id_situacao", "Vendedor", "Loja ID", "Data",
                "Total Produtos", "Total Venda", "Cliente"],
    "Itens": ["ID_pedido", "ID_produto", "Quantidade", "Data", "Valor Unidade", "Desconto Item"],
    "Produtos": ["ID", "codigo", "Descricao", "situacao", "preco_custo"],
    "EstoqueV3": ["ID_deposito", "ID_produto", "saldoFisico"],
    "Produtos_detalhes": ["ID_produto", "Codigo", "categoria", "Super_categoria",
                          "Grupo", "Tamanho"],
    "Vendedores": ["ID", "nome"],
    "Lojas": ["ID", "descricao", "Situacao"],
    "Situações": ["ID", "descricao"],
    "Depósitos": ["ID", "descricao"],
}


# Mapa: aba do SCHEMA → nome da tabela no Supabase (schema 'public').
# PREENCHER/CONFIRMAR com `python scripts/inspecionar_supabase.py` (Fase 0).
# Os valores abaixo são um palpite snake_case sem acento — ajustar conforme
# os nomes reais criados pela pipeline Bling→Supabase.
TABELAS_SUPABASE = {
    "Pedidos": "pedidos",
    "Itens": "itens",
    "Produtos": "produtos",
    "EstoqueV3": "estoque_v3",
    "Produtos_detalhes": "produtos_detalhes",
    "Vendedores": "vendedores",
    "Lojas": "lojas",
    "Situações": "situacoes",
    "Depósitos": "depositos",
}

# Renomeio opcional de colunas: aba → {coluna_no_supabase: coluna_do_SCHEMA}.
# Vazio = colunas do Supabase já batem com o SCHEMA. Preencher se a pipeline
# usar nomes diferentes (descoberto na Fase 0 / paridade Fase 2).
COLUNAS_SUPABASE = {
    # "Pedidos": {"loja_id": "Loja ID", "total_venda": "Total Venda"},
}


def limpar_id(valor):
    """
    Limpa IDs que o pandas converte para float (ex: 203379922.0 → "203379922").
    Trata: float, int, str com '.0' no final, NaN.
    """
    if pd.isna(valor):
        return ""
    s = str(valor).strip()
    # Remove '.0' do final de IDs numéricos (artefato do pandas lendo float)
    if s.endswith(".0"):
        try:
            return str(int(float(s)))
        except (ValueError, OverflowError):
            pass
    return s


def converter_data_flexivel(valor):
    """
    Converte datas em múltiplos formatos:
      - ISO: YYYY-MM-DD (ex: 2026-02-24)
      - BR: DD/MM/YYYY (ex: 24/02/2026)

    Retorna datetime ou NaT se não conseguir converter.
    """
    if pd.isna(valor):
        return pd.NaT

    s = str(valor).strip()
    if not s:
        return pd.NaT

    # Tenta formato ISO primeiro
    if "-" in s and len(s) == 10:
        try:
            return pd.to_datetime(s, format="%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    # Tenta formato BR (DD/MM/YYYY)
    if "/" in s:
        try:
            return pd.to_datetime(s, format="%d/%m/%Y")
        except (ValueError, TypeError):
            pass

    # Fallback: deixa o pandas tentar com dayfirst=True
    try:
        return pd.to_datetime(s, errors="coerce", dayfirst=True)
    except Exception:
        return pd.NaT


def _usar_sheets() -> bool:
    """Retorna True se st.secrets tem sheet_id configurado (modo Streamlit Cloud)."""
    try:
        return bool(st.secrets.get("sheet_id"))
    except Exception:
        return False


@st.cache_data(ttl=3600)
def _ler_sheets(sheet_id: str) -> dict:
    """
    Lê todas as abas do Google Sheets e retorna um dict {nome_aba: DataFrame}.
    Cacheado por 1 hora para minimizar chamadas à API do Google.

    Requer em st.secrets:
        sheet_id = "ID_DA_PLANILHA"
        [gcp_service_account]
        type = "service_account"
        ... (JSON completo da Service Account)
    """
    import gspread

    creds_dict = dict(st.secrets["gcp_service_account"])
    gc = gspread.service_account_from_dict(creds_dict)
    sh = gc.open_by_key(sheet_id)

    todas_abas = {}
    for ws in sh.worksheets():
        values = ws.get_all_values()
        if len(values) > 1:
            # Primeira linha = cabeçalho; demais = dados
            cabecalho = [str(c).strip() for c in values[0]]
            df = pd.DataFrame(values[1:], columns=cabecalho)
        elif len(values) == 1:
            cabecalho = [str(c).strip() for c in values[0]]
            df = pd.DataFrame(columns=cabecalho)
        else:
            df = pd.DataFrame()

        # Strings vazias → pd.NA para que dropna() funcione corretamente
        todas_abas[ws.title] = df.replace("", pd.NA)

    return todas_abas


def _fonte() -> str:
    """Fonte de dados ativa: 'supabase' (default), 'sheets' ou 'excel'."""
    try:
        f = st.secrets.get("fonte_dados")
        if f:
            return str(f).strip().lower()
        # Compatibilidade: se só houver sheet_id, mantém Sheets
        if st.secrets.get("sheet_id"):
            return "sheets"
    except Exception:
        pass
    return "excel"


@st.cache_resource
def _conn_supabase():
    """Engine SQLAlchemy do Supabase (cacheada por sessão)."""
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL

    cfg = st.secrets["supabase"]
    url = URL.create(
        "postgresql+psycopg2",
        username=cfg["user"],
        password=cfg["password"],
        host=cfg["host"],
        port=int(cfg.get("port", 5432)),
        database=cfg["dbname"],
    )
    return create_engine(url, pool_pre_ping=True)


@st.cache_data(ttl=3600)
def _ler_supabase() -> dict:
    """
    Lê cada tabela do Supabase e retorna {nome_aba_SCHEMA: DataFrame}.
    Cacheado por 1 hora. Tabelas via TABELAS_SUPABASE; colunas renomeadas
    via COLUNAS_SUPABASE quando necessário.
    """
    from sqlalchemy import text

    engine = _conn_supabase()
    schema = st.secrets["supabase"].get("schema", "public")

    todas_abas = {}
    with engine.connect() as conn:
        for aba, tabela in TABELAS_SUPABASE.items():
            if not tabela:
                continue  # aba não mapeada — validação acusa aba ausente
            query = text(f'SELECT * FROM "{schema}"."{tabela}"')
            df = pd.read_sql_query(query, conn)

            rename = COLUNAS_SUPABASE.get(aba)
            if rename:
                df = df.rename(columns=rename)

            # Paridade com _ler_sheets: vazio → pd.NA p/ dropna() funcionar
            todas_abas[aba] = df.replace("", pd.NA)

    return todas_abas


def carregar_dados(caminho_excel: str = None, fonte: str = None) -> dict:
    """
    Lê os dados do Bling e retorna um dicionário de DataFrames.

    Fonte de dados (escolha automática via st.secrets["fonte_dados"]):
      - "supabase": Postgres do Supabase (default em produção).
      - "sheets":   Google Sheets (legado/rollback).
      - "excel":    arquivo local (desenvolvimento).
    O parâmetro `fonte` força a fonte (usado por scripts de paridade/teste).

    Retorna:
        {
            "pedidos":       DataFrame,
            "itens":         DataFrame,
            "produtos":      DataFrame,   ← apenas ativos (situacao == "A")
            "produtos_todos": DataFrame,  ← todos os produtos
            "estoque":       DataFrame,
            "detalhes":      DataFrame,
            "vendedores":    DataFrame,
            "lojas":         DataFrame,
            "situacoes":     DataFrame,
            "depositos":     DataFrame,
            "validacao": {"ok": bool, "erros": list, "avisos": list}
        }
    """
    erros = []
    avisos = []

    # ----------------------------------------------------------------
    # Leitura da fonte de dados
    # ----------------------------------------------------------------
    fonte = (fonte or _fonte()).strip().lower()
    if fonte == "supabase":
        try:
            todas_abas = _ler_supabase()
        except Exception as e:
            st.error(f"❌ Erro ao conectar ao Supabase: {e}")
            return {"validacao": {"ok": False, "erros": [f"Erro ao ler Supabase: {e}"], "avisos": []}}
    elif fonte == "sheets":
        try:
            sheet_id = st.secrets["sheet_id"]
            todas_abas = _ler_sheets(sheet_id)
        except Exception as e:
            st.error(f"❌ Erro ao conectar ao Google Sheets: {e}")
            return {"validacao": {"ok": False, "erros": [f"Erro ao ler Google Sheets: {e}"], "avisos": []}}
    else:
        caminho = Path(caminho_excel) if caminho_excel else Path("data/Integração Bling ERP.xlsx")
        if not caminho.exists():
            return {"validacao": {"ok": False, "erros": [f"Arquivo não encontrado: {caminho}"], "avisos": []}}
        try:
            todas_abas = pd.read_excel(caminho, sheet_name=None, engine="openpyxl")
        except Exception as e:
            return {"validacao": {"ok": False, "erros": [f"Erro ao ler Excel: {e}"], "avisos": []}}

    # ----------------------------------------------------------------
    # Validação: presença de abas e colunas obrigatórias
    # ----------------------------------------------------------------
    for aba, colunas_requeridas in SCHEMA.items():
        if aba not in todas_abas:
            erros.append(f"Aba ausente: '{aba}'")
            continue

        df = todas_abas[aba]
        colunas_existentes = [str(c).strip() for c in df.columns]
        for col in colunas_requeridas:
            if col not in colunas_existentes:
                erros.append(f"Coluna '{col}' ausente na aba '{aba}'")

        if len(df) == 0:
            avisos.append(f"Aba '{aba}' está vazia (sem dados)")

    if erros:
        return {"validacao": {"ok": False, "erros": erros, "avisos": avisos}}

    # ----------------------------------------------------------------
    # Limpeza e tipagem de cada aba
    # ----------------------------------------------------------------
    dados = {}

    # --- Pedidos ---
    df = todas_abas["Pedidos"].copy()
    df = df.dropna(subset=["ID"])
    df["ID"] = df["ID"].apply(limpar_id)
    df["Loja ID"] = df["Loja ID"].apply(limpar_id)
    df["Vendedor"] = df["Vendedor"].apply(limpar_id)
    df["id_situacao"] = pd.to_numeric(df["id_situacao"], errors="coerce")
    # Converte datas em formato ISO (YYYY-MM-DD) ou BR (DD/MM/YYYY)
    df["Data"] = df["Data"].apply(converter_data_flexivel)
    df["Total Venda"] = pd.to_numeric(
        df["Total Venda"].astype(str).str.replace(",", "."), errors="coerce"
    ).fillna(0)
    df["Total Produtos"] = pd.to_numeric(
        df["Total Produtos"].astype(str).str.replace(",", "."), errors="coerce"
    ).fillna(0)
    dados["pedidos"] = df

    # --- Itens ---
    df = todas_abas["Itens"].copy()
    df = df.dropna(subset=["ID_pedido"])
    df["ID_pedido"] = df["ID_pedido"].apply(limpar_id)
    df["ID_produto"] = df["ID_produto"].apply(limpar_id)
    df["Quantidade"] = pd.to_numeric(df["Quantidade"], errors="coerce").fillna(0)
    df["Valor Unidade"] = pd.to_numeric(
        df["Valor Unidade"].astype(str).str.replace(",", "."), errors="coerce"
    ).fillna(0)
    df["Desconto Item"] = pd.to_numeric(
        df["Desconto Item"].astype(str).str.replace(",", "."), errors="coerce"
    ).fillna(0)
    df["Data"] = df["Data"].apply(converter_data_flexivel)
    dados["itens"] = df

    # --- Produtos ---
    df = todas_abas["Produtos"].copy()
    df = df.dropna(subset=["ID"])
    df["ID"] = df["ID"].apply(limpar_id)
    df["situacao"] = df["situacao"].astype(str).str.strip().str.upper()
    df["preco_custo"] = pd.to_numeric(
        df["preco_custo"].astype(str).str.replace("R$ ", "").str.replace(",", "."), errors="coerce"
    ).fillna(0)
    # Filtra apenas ativos (situacao = 'A'). Remove Inativos, Excluídos e sem situação.
    dados["produtos"] = df[df["situacao"] == "A"].copy()
    dados["produtos_todos"] = df  # Versão completa para referência histórica

    # --- Estoque ---
    df = todas_abas["EstoqueV3"].copy()
    df = df.dropna(subset=["ID_produto"])
    df["ID_deposito"] = df["ID_deposito"].apply(limpar_id)
    df["ID_produto"] = df["ID_produto"].apply(limpar_id)
    df["saldoFisico"] = pd.to_numeric(df["saldoFisico"], errors="coerce").fillna(0)
    dados["estoque"] = df

    # --- Produtos Detalhes ---
    df = todas_abas["Produtos_detalhes"].copy()
    df = df.dropna(subset=["ID_produto"])
    df["ID_produto"] = df["ID_produto"].apply(limpar_id)
    # Força todas as colunas de categorização para string (evita tipos misturados)
    for col in ["categoria", "Super_categoria", "Grupo", "Tamanho", "Marca_sku"]:
        if col in df.columns:
            df[col] = df[col].astype(str).replace("nan", "").str.strip()
    dados["detalhes"] = df

    # --- Vendedores ---
    df = todas_abas["Vendedores"].copy()
    df = df.dropna(subset=["ID"])
    df["ID"] = df["ID"].apply(limpar_id)
    dados["vendedores"] = df

    # --- Lojas ---
    df = todas_abas["Lojas"].copy()
    df = df.dropna(subset=["ID"])
    df["ID"] = df["ID"].apply(limpar_id)
    dados["lojas"] = df

    # --- Situações ---
    df = todas_abas["Situações"].copy()
    df = df.dropna(subset=["ID"])
    df["ID"] = pd.to_numeric(df["ID"], errors="coerce")
    dados["situacoes"] = df

    # --- Depósitos ---
    df = todas_abas["Depósitos"].copy()
    df = df.dropna(subset=["ID"])
    df["ID"] = df["ID"].apply(limpar_id)
    dados["depositos"] = df

    dados["validacao"] = {"ok": True, "erros": [], "avisos": avisos}
    return dados


def enriquecer_produtos(produtos: pd.DataFrame, detalhes: pd.DataFrame) -> pd.DataFrame:
    """
    Faz JOIN entre Produtos e Produtos_detalhes.
    Adiciona colunas: categoria, Super_categoria, Grupo, Tamanho, Marca_sku.

    Equivale ao carregarDetalhes() do Utils.gs.
    """
    colunas_detalhe = ["ID_produto", "categoria", "Super_categoria", "Grupo", "Tamanho", "Marca_sku"]
    det = detalhes[colunas_detalhe].copy()
    det = det.rename(columns={"ID_produto": "ID"})

    return produtos.merge(det, on="ID", how="left")
