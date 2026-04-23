"""
planejamento.py — Planejamento de Produção Anual

Calcula sazonalidade mensal a partir do histórico e simula
rodadas de produção distribuídas ao longo do ano.

Uso:
    from etl.planejamento import calcular_sazonalidade, simular_rodadas
    saz = calcular_sazonalidade(dados, config)
    sim = simular_rodadas(dados, config, saz)
"""

import pandas as pd
import numpy as np
import math


NOMES_MES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
             "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def calcular_sazonalidade(dados: dict, config: dict) -> pd.DataFrame:
    """
    Calcula peso relativo de cada mês a partir do histórico de vendas.
    
    PesoNormalizado: soma = 12.0 (mês médio = 1.0)
        > 1.0 = mês acima da média (alta)
        < 1.0 = mês abaixo da média (baixa)
    """
    cfg = config.get("planejamento", {})
    dt_ini = pd.Timestamp(cfg.get("sazonalidade_inicio", "2025-01-01"))
    dt_fim = pd.Timestamp(cfg.get("sazonalidade_fim", "2026-02-28"))

    itens = dados["itens"]
    vendas = itens[(itens["Data"] >= dt_ini) & (itens["Data"] <= dt_fim)].copy()

    if len(vendas) == 0:
        return pd.DataFrame({
            "Mes": range(1, 13),
            "NomeMes": NOMES_MES,
            "Vendas": 0,
            "PesoRelativo": [1/12] * 12,
            "PesoNormalizado": [1.0] * 12,
        })

    vendas["Mes"] = vendas["Data"].dt.month
    vendas["AnoMes"] = vendas["Data"].dt.to_period("M")

    # Média por mês-calendário (se tem Jan/25 e Jan/26, faz média)
    por_anomes = vendas.groupby("AnoMes")["Quantidade"].sum().reset_index()
    por_anomes["Mes"] = por_anomes["AnoMes"].dt.month
    media_por_mes = por_anomes.groupby("Mes")["Quantidade"].mean()

    rows = []
    for m in range(1, 13):
        rows.append({
            "Mes": m,
            "NomeMes": NOMES_MES[m-1],
            "Vendas": round(media_por_mes.get(m, 0), 1),
        })

    df = pd.DataFrame(rows)
    total = df["Vendas"].sum()

    if total > 0:
        df["PesoRelativo"] = df["Vendas"] / total
        df["PesoNormalizado"] = round(df["PesoRelativo"] * 12, 3)
    else:
        df["PesoRelativo"] = 1/12
        df["PesoNormalizado"] = 1.0

    return df


def simular_rodadas(dados: dict, config: dict, sazonalidade: pd.DataFrame,
                    rodadas_override: list = None, buffer_override: float = None,
                    pct_por_rodada: dict = None) -> dict:
    """
    Simula as rodadas de produção.

    Args:
        rodadas_override: lista de meses (substitui config para simulação interativa)
        buffer_override: % buffer (substitui config)
        pct_por_rodada: dict {mes_disparo: pct_demanda_anual} — controle individual
                        por rodada. Se None, distribui igualmente entre as rodadas.

    Retorna dict com: demanda_mensal, rodadas, totais, estoque_projetado
    """
    cfg_plan = config.get("planejamento", {})
    cfg_fab = config.get("fabrica", {})

    rodadas_meses = rodadas_override or cfg_plan.get("rodadas", [3, 7, 11])
    lt_semanas = cfg_plan.get("lead_time_semanas", 4)
    buffer_pct = buffer_override if buffer_override is not None else cfg_plan.get("buffer_pct", 10)
    crescimento = cfg_fab.get("crescimento_pct", 10)

    lt_meses = math.ceil(lt_semanas / 4)

    produtos = dados["produtos"]
    itens = dados["itens"]

    # Custo médio ponderado
    custo_medio = produtos["preco_custo"].mean() if len(produtos) > 0 else 0

    # ================================================================
    # MÉDIA MENSAL BASE — normalizada pela sazonalidade
    # ================================================================
    # Se o histórico só cobre meses de alta (Out-Mar), a média bruta
    # seria inflada. Corrigimos dividindo pelo peso dos meses COM dados.
    #
    # Exemplo: se só tenho Out-Mar e esses meses representam 65% das
    # vendas anuais (soma dos pesos = 7.8 de 12), a média real mensal
    # é: vendas_periodo / meses_com_dados * (12 / soma_pesos_cobertos)
    # Isso extrapola corretamente para o ano todo.
    # ================================================================
    cfg_saz_ini = pd.Timestamp(cfg_plan.get("sazonalidade_inicio", "2025-01-01"))
    cfg_saz_fim = pd.Timestamp(cfg_plan.get("sazonalidade_fim", "2026-02-28"))
    vendas_periodo = itens[
        (itens["Data"] >= cfg_saz_ini) & (itens["Data"] <= cfg_saz_fim)
    ]["Quantidade"].sum()

    meses_periodo = max((cfg_saz_fim - cfg_saz_ini).days / 30, 1)

    # Identificar quais meses-calendário têm dados no período
    vendas_no_periodo = itens[
        (itens["Data"] >= cfg_saz_ini) & (itens["Data"] <= cfg_saz_fim)
    ].copy()
    if len(vendas_no_periodo) > 0:
        meses_com_dados = vendas_no_periodo["Data"].dt.month.unique().tolist()
    else:
        meses_com_dados = list(range(1, 13))

    # Soma dos pesos de sazonalidade dos meses com dados
    saz_temp = sazonalidade.set_index("Mes")
    soma_pesos_cobertos = sum(
        float(saz_temp.loc[m, "PesoNormalizado"]) if m in saz_temp.index else 1.0
        for m in meses_com_dados
    )

    # Média mensal corrigida: remove viés de só ter dados de alta/baixa
    if soma_pesos_cobertos > 0 and meses_periodo > 0:
        # vendas / meses = média bruta (enviesada)
        # × (n_meses_dados / soma_pesos) = fator de correção
        media_bruta = vendas_periodo / meses_periodo
        fator_correcao = len(meses_com_dados) / soma_pesos_cobertos
        media_mensal_base = media_bruta * fator_correcao
    else:
        media_mensal_base = vendas_periodo / meses_periodo if meses_periodo > 0 else 0

    media_mensal_proj = media_mensal_base * (1 + crescimento / 100)

    # Demanda mensal projetada
    saz = sazonalidade.set_index("Mes")
    demanda_mensal = []
    for m in range(1, 13):
        peso = saz.loc[m, "PesoNormalizado"] if m in saz.index else 1.0
        demanda_mensal.append({
            "Mes": m,
            "NomeMes": NOMES_MES[m-1],
            "Peso": round(float(peso), 3),
            "Demanda": round(media_mensal_proj * float(peso)),
        })

    df_demanda = pd.DataFrame(demanda_mensal)
    demanda_dict = df_demanda.set_index("Mes")["Demanda"].to_dict()
    demanda_anual = df_demanda["Demanda"].sum()

    # ================================================================
    # Simulação das rodadas
    # ================================================================
    rodadas_sorted = sorted(rodadas_meses)
    n_rodadas = len(rodadas_sorted)

    # Distribuição de % da demanda anual por rodada
    if pct_por_rodada is None:
        pct_igual = round(100 / n_rodadas, 1) if n_rodadas > 0 else 100
        pct_por_rodada = {m: pct_igual for m in rodadas_sorted}

    resultado_rodadas = []

    for i, mes_disparo in enumerate(rodadas_sorted):
        mes_chegada = mes_disparo + lt_meses
        if mes_chegada > 12:
            mes_chegada -= 12

        # Próxima chegada
        if i < n_rodadas - 1:
            prox_chegada = rodadas_sorted[i + 1] + lt_meses
        else:
            prox_chegada = rodadas_sorted[0] + lt_meses
        if prox_chegada > 12:
            prox_chegada -= 12

        # Meses cobertos (info contextual)
        meses_cobertos = []
        m = mes_chegada
        for _ in range(12):
            meses_cobertos.append(m)
            m = m + 1 if m < 12 else 1
            if m == prox_chegada:
                break

        demanda_periodo = sum(demanda_dict.get(mc, 0) for mc in meses_cobertos)

        # Produção baseada em % da demanda anual (controle individual)
        pct_rodada = pct_por_rodada.get(mes_disparo, 0)
        demanda_base = demanda_anual * pct_rodada / 100
        buffer = demanda_base * buffer_pct / 100
        producao = math.ceil(demanda_base + buffer)
        if producao % 2 != 0:
            producao += 1

        investimento = producao * custo_medio
        pct_anual = (producao / demanda_anual * 100) if demanda_anual > 0 else 0

        resultado_rodadas.append({
            "rodada": i + 1,
            "mes_disparo": mes_disparo,
            "nome_disparo": NOMES_MES[mes_disparo - 1],
            "mes_chegada": mes_chegada,
            "nome_chegada": NOMES_MES[mes_chegada - 1],
            "meses_cobertos": meses_cobertos,
            "nomes_cobertos": ", ".join(NOMES_MES[mc-1] for mc in meses_cobertos),
            "n_meses": len(meses_cobertos),
            "demanda_periodo": round(demanda_periodo),
            "pct_rodada": pct_rodada,
            "buffer": round(buffer),
            "producao": producao,
            "investimento": round(investimento, 2),
            "pct_anual": round(pct_anual, 1),
        })

    producao_total = sum(r["producao"] for r in resultado_rodadas)
    investimento_total = sum(r["investimento"] for r in resultado_rodadas)

    # ================================================================
    # Curva de estoque projetada
    # ================================================================
    estoque_proj = []
    estoque_atual = 0

    for m in range(1, 13):
        entrada = sum(
            r["producao"] for r in resultado_rodadas if r["mes_chegada"] == m
        )
        estoque_atual += entrada
        demanda_mes = demanda_dict.get(m, 0)
        estoque_atual -= demanda_mes

        estoque_proj.append({
            "Mes": m,
            "NomeMes": NOMES_MES[m-1],
            "Entrada": round(entrada),
            "Demanda": round(demanda_mes),
            "EstoqueFinal": round(estoque_atual),
        })

    return {
        "demanda_mensal": df_demanda,
        "rodadas": resultado_rodadas,
        "totais": {
            "producao_total": int(producao_total),
            "investimento_total": round(float(investimento_total), 2),
            "demanda_anual": int(round(demanda_anual)),
            "custo_medio": round(float(custo_medio), 2),
            "media_mensal_proj": round(float(media_mensal_proj), 1),
            "meses_com_dados": sorted(meses_com_dados),
            "fator_correcao": round(fator_correcao, 3) if soma_pesos_cobertos > 0 else 1.0,
        },
        "estoque_projetado": pd.DataFrame(estoque_proj),
    }
