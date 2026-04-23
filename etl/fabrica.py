"""
fabrica.py — ETL de Planejamento de Fábrica (PCP)

Calcula sugestão de produção baseada em demanda histórica, backlog e pipeline.
Equivale ao Fabrica.gs V9.1/V10 do Google Apps Script.

BUGFIX vs V9.1: Coluna "Custo Unit" agora recebe preco_custo (não sugestão duplicada).

Uso:
    from etl.fabrica import processar_fabrica
    df = processar_fabrica(dados, config)
"""

import pandas as pd
import numpy as np
from datetime import datetime
import math


def processar_fabrica(dados: dict, config: dict, pipeline: pd.DataFrame = None) -> pd.DataFrame:
    """
    Calcula necessidade de produção para cada SKU.

    Args:
        dados: dicionário retornado por carregar_dados()
        config: dicionário do config.yaml
        pipeline: DataFrame opcional com ordens em produção
                  Colunas: SKU, Quantidade, Status

    Retorna:
        DataFrame com colunas:
        SKU, Produto, Categoria, SuperCategoria, Grupo, Colegio,
        VendasHist, MediaMensal, EstoqueRede, Backlog, Pipeline,
        DemandaProjetada, EstoqueMeta, NecessidadeBruta,
        SugestaoProducao, CustoUnit, InvestimentoFabril
    """
    cfg_fab = config["fabrica"]
    excecoes = config.get("excecoes_sku", {}) or {}

    data_inicio = pd.Timestamp(cfg_fab["data_inicio"])
    data_fim = pd.Timestamp(cfg_fab["data_fim"])
    crescimento_pct = cfg_fab["crescimento_pct"]
    sazonalidade_global = cfg_fab["sazonalidade"]
    cobertura_meses = cfg_fab["cobertura_meses"]
    correcao_global = cfg_fab["correcao_manual"]
    sit_backlog = cfg_fab["situacoes_backlog"]

    produtos = dados["produtos"]
    itens = dados["itens"]
    estoque = dados["estoque"]
    pedidos = dados["pedidos"]
    detalhes = dados["detalhes"]

    # ---------------------------------------------------------------
    # 1. Mapa Pedido → Situação
    # ---------------------------------------------------------------
    map_ped_sit = pedidos.set_index("ID")["id_situacao"].to_dict()

    # ---------------------------------------------------------------
    # 2. Backlog (pedidos que consomem estoque sem faturar)
    # ---------------------------------------------------------------
    itens_c = itens.copy()
    itens_c["situacao_pedido"] = itens_c["ID_pedido"].map(map_ped_sit)

    backlog = (
        itens_c[itens_c["situacao_pedido"].isin(sit_backlog)]
        .groupby("ID_produto")["Quantidade"]
        .sum()
        .to_dict()
    )

    # ---------------------------------------------------------------
    # 3. Vendas no período histórico
    # ---------------------------------------------------------------
    vendas_hist = (
        itens_c[
            (itens_c["Data"] >= data_inicio) &
            (itens_c["Data"] <= data_fim)
        ]
        .groupby("ID_produto")["Quantidade"]
        .sum()
        .to_dict()
    )

    # Meses no período
    diff_days = (data_fim - data_inicio).days
    meses_periodo = max(diff_days / 30, 1)

    # ---------------------------------------------------------------
    # 4. Estoque total da rede (soma todos os depósitos)
    # ---------------------------------------------------------------
    estoque_rede = (
        estoque
        .groupby("ID_produto")["saldoFisico"]
        .sum()
        .to_dict()
    )

    # ---------------------------------------------------------------
    # 5. Pipeline (ordens em produção)
    # ---------------------------------------------------------------
    map_pipeline = {}
    if pipeline is not None and len(pipeline) > 0:
        status_validos = ["EM PRODUÇÃO", "EM PRODUCAO", "PRODUZINDO"]
        pipe_valido = pipeline[
            pipeline["Status"].astype(str).str.strip().str.upper().isin(status_validos)
        ]
        map_pipeline = pipe_valido.groupby("SKU")["Quantidade"].sum().to_dict()

    # ---------------------------------------------------------------
    # 6. Detalhes
    # ---------------------------------------------------------------
    colunas_detalhe = ["categoria", "Super_categoria", "Grupo"]
    if "Marca_sku" in detalhes.columns:
        colunas_detalhe.append("Marca_sku")
    det_map = detalhes.set_index("ID_produto")[
        colunas_detalhe
    ].to_dict("index")

    # ---------------------------------------------------------------
    # 7. Cálculo de Necessidade por SKU
    # ---------------------------------------------------------------
    resultados = []

    for _, prod in produtos.iterrows():
        id_prod = str(prod["ID"]).strip()
        sku = prod["codigo"]
        nome = prod["Descricao"]
        preco_custo = prod["preco_custo"]

        # Exceções
        exc = excecoes.get(sku, {}) if excecoes else {}
        sazonalidade = exc.get("sazonalidade", sazonalidade_global)
        correcao_sku = exc.get("correcao", 0)

        # Dados do SKU
        vd_hist = vendas_hist.get(id_prod, 0)
        est_atual = estoque_rede.get(id_prod, 0)
        bklog = backlog.get(id_prod, 0)
        pipe = map_pipeline.get(sku, 0)

        # Cálculos
        media_mensal = vd_hist / meses_periodo
        demanda_projetada = media_mensal * (1 + crescimento_pct / 100) * sazonalidade
        demanda_projetada += correcao_global + correcao_sku

        estoque_meta = demanda_projetada * cobertura_meses
        if estoque_meta < 2:
            estoque_meta = 2  # Mínimo existencial

        # Disponível líquido = atual - backlog
        # Efetivo = disponível + pipeline (o que já está vindo)
        disponivel_liquido = est_atual - bklog
        efetivo = disponivel_liquido + pipe
        necessidade = estoque_meta - efetivo

        if necessidade < 0:
            necessidade = 0

        # Arredonda para cima, forçando número par
        sugestao = math.ceil(necessidade)
        if sugestao % 2 != 0:
            sugestao += 1

        # Segurança: demanda existe mas estoque líquido zerado
        if sugestao == 0 and disponivel_liquido <= 0 and media_mensal > 0:
            sugestao = 2

        # Detalhes
        det = det_map.get(id_prod, {})

        resultados.append({
            "SKU": sku,
            "Produto": nome,
            "Categoria": det.get("categoria", ""),
            "SuperCategoria": det.get("Super_categoria", ""),
            "Grupo": det.get("Grupo", ""),
            "Colegio": det.get("Marca_sku", ""),
            "VendasHist": vd_hist,
            "MediaMensal": round(media_mensal, 2),
            "EstoqueRede": est_atual,
            "Backlog": bklog,
            "Pipeline": pipe,
            "DemandaProjetada": round(demanda_projetada, 2),
            "EstoqueMeta": round(estoque_meta),
            "NecessidadeBruta": round(necessidade, 2),
            "SugestaoProducao": sugestao,
            "CustoUnit": preco_custo,               # ← BUGFIX: era sugestão duplicada no V9.1
            "InvestimentoFabril": sugestao * preco_custo,
        })

    df = pd.DataFrame(resultados)
    df = df.sort_values("SugestaoProducao", ascending=False).reset_index(drop=True)
    return df
