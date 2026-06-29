"""
memoria_calculo_fabrica.py — Memória de Cálculo da Fábrica (PCP)

Mostra passo a passo como a sugestão de produção é calculada para um SKU.

Uso:
    python memoria_calculo_fabrica.py                     # SKU padrão (primeiro da lista)
    python memoria_calculo_fabrica.py NEV020CAMEDF-PP     # SKU específico

Conceitos:
    BACKLOG  = peças já vendidas mas não faturadas (comprometidas)
    PIPELINE = peças em produção na fábrica (chegando em breve)
"""

import sys
import yaml
import math
import pandas as pd
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from etl.loader import carregar_dados


# ── Formatação ──
def linha(titulo):
    print(f"\n{'=' * 70}")
    print(f"  {titulo}")
    print(f"{'=' * 70}")

def sub(titulo):
    print(f"\n  --- {titulo} ---")

def calc(descricao, formula, resultado):
    print(f"  {descricao}")
    print(f"    {formula}")
    print(f"    = {resultado}")


def main():
    caminho_config = Path(__file__).parent / "config.yaml"
    with open(caminho_config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    dados = carregar_dados()

    produtos = dados["produtos"]

    # SKU alvo
    if len(sys.argv) > 1:
        sku_alvo = sys.argv[1]
    else:
        sku_alvo = produtos.iloc[0]["codigo"]

    prod = produtos[produtos["codigo"] == sku_alvo]
    if len(prod) == 0:
        print(f"❌ SKU '{sku_alvo}' não encontrado nos produtos ativos.")
        print(f"   SKUs disponíveis: {', '.join(produtos['codigo'].head(10).tolist())}")
        return

    prod = prod.iloc[0]
    id_prod = str(prod["ID"]).strip()
    nome = prod["Descricao"]
    preco_custo = prod["preco_custo"]

    # Detalhes
    detalhes = dados["detalhes"]
    det = detalhes[detalhes["ID_produto"] == id_prod]
    if len(det) > 0:
        det = det.iloc[0]
        categoria = det.get("categoria", "")
        super_cat = det.get("Super_categoria", "")
        grupo = det.get("Grupo", "")
    else:
        categoria = super_cat = grupo = ""

    linha(f"MEMÓRIA DE CÁLCULO FÁBRICA — SKU: {sku_alvo}")
    print(f"\n  Produto: {nome}")
    print(f"  ID Bling: {id_prod}")
    print(f"  Preço Custo: R$ {preco_custo:.2f}")
    print(f"  Categoria: {categoria} | Super: {super_cat} | Grupo: {grupo}")

    # ================================================================
    # ETAPA 1 — PARÂMETROS
    # ================================================================
    linha("ETAPA 1 — PARÂMETROS DO CÁLCULO")

    cfg = config["fabrica"]
    excecoes = config.get("excecoes_sku", {}) or {}

    data_inicio = pd.Timestamp(cfg["data_inicio"])
    data_fim = pd.Timestamp(cfg["data_fim"])
    crescimento = cfg["crescimento_pct"]
    sazonalidade_global = cfg["sazonalidade"]
    cobertura_meses = cfg["cobertura_meses"]
    correcao_global = cfg["correcao_manual"]
    sit_backlog = cfg["situacoes_backlog"]

    exc = excecoes.get(sku_alvo, {}) if excecoes else {}
    sazonalidade = exc.get("sazonalidade", sazonalidade_global)
    correcao_sku = exc.get("correcao", 0)

    diff_days = (data_fim - data_inicio).days
    meses_periodo = max(diff_days / 30, 1)

    sub("Parâmetros Globais (config.yaml → fabrica)")
    print(f"  Período Histórico:     {data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}")
    print(f"  Meses no período:      {meses_periodo:.1f}")
    print(f"  Crescimento:           {crescimento}%")
    print(f"  Sazonalidade:          {sazonalidade}x")
    print(f"  Cobertura Meta:        {cobertura_meses} meses")
    print(f"  Correção Global:       {correcao_global}")
    print(f"  Situações Backlog:     {sit_backlog}")

    if exc:
        sub(f"Exceções do SKU '{sku_alvo}'")
        for k, v in exc.items():
            print(f"  {k}: {v}")
    else:
        print(f"\n  SKU sem exceções configuradas.")

    # ================================================================
    # ETAPA 2 — VENDAS HISTÓRICAS
    # ================================================================
    linha("ETAPA 2 — VENDAS HISTÓRICAS")

    itens = dados["itens"]
    vendas_sku = itens[itens["ID_produto"] == id_prod].copy()

    print(f"\n  Total de registros de venda (all time): {len(vendas_sku)}")
    print(f"  Total de peças vendidas (all time): {vendas_sku['Quantidade'].sum():.0f}")

    vendas_periodo = vendas_sku[
        (vendas_sku["Data"] >= data_inicio) &
        (vendas_sku["Data"] <= data_fim)
    ]
    vd_hist = vendas_periodo["Quantidade"].sum()

    sub(f"Vendas no Período ({data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')})")
    print(f"  Registros no período: {len(vendas_periodo)}")
    print(f"  Peças vendidas:       {vd_hist:.0f}")

    media_mensal = vd_hist / meses_periodo

    calc("Média Mensal:",
         f"Vendas no período / Meses = {vd_hist:.0f} / {meses_periodo:.1f}",
         f"{media_mensal:.2f} peças/mês")

    print(f"\n  📖 O QUE É A MÉDIA MENSAL:")
    print(f"     Quantas peças deste SKU saem POR MÊS em média.")
    print(f"     Base para projetar a demanda futura.")

    # ================================================================
    # ETAPA 3 — ESTOQUE DA REDE
    # ================================================================
    linha("ETAPA 3 — ESTOQUE DA REDE")

    estoque = dados["estoque"]
    cfg_dep = config["depositos"]

    est_por_dep = (
        estoque[estoque["ID_produto"] == id_prod]
        .groupby("ID_deposito")["saldoFisico"]
        .sum()
    )

    id_central = str(cfg_dep["central"]["deposito_id"]).strip()
    est_central = est_por_dep.get(id_central, 0)
    print(f"\n  Central (depósito {id_central}): {est_central:.0f} peças")

    for loja_cfg in cfg_dep["lojas"]:
        id_dep = str(loja_cfg["deposito_id"]).strip()
        est = est_por_dep.get(id_dep, 0)
        print(f"  {loja_cfg['nome']} (depósito {id_dep}): {est:.0f} peças")

    est_rede = est_por_dep.sum()
    print(f"\n  Estoque Total da Rede: {est_rede:.0f} peças")

    print(f"\n  📖 O QUE É O ESTOQUE REDE:")
    print(f"     Soma de TODOS os depósitos (central + todas as lojas).")
    print(f"     É tudo que a empresa tem deste SKU no momento.")

    # ================================================================
    # ETAPA 4 — BACKLOG
    # ================================================================
    linha("ETAPA 4 — BACKLOG (PEDIDOS EM CARTEIRA)")

    pedidos = dados["pedidos"]
    map_ped_sit = pedidos.set_index("ID")["id_situacao"].to_dict()

    itens_c = itens.copy()
    itens_c["situacao_pedido"] = itens_c["ID_pedido"].map(map_ped_sit)

    # Backlog deste SKU
    bklog_itens = itens_c[
        (itens_c["ID_produto"] == id_prod) &
        (itens_c["situacao_pedido"].isin(sit_backlog))
    ]
    bklog = bklog_itens["Quantidade"].sum()

    print(f"\n  Situações que contam como Backlog: {sit_backlog}")
    print(f"  Pedidos deste SKU nessas situações: {len(bklog_itens)}")
    print(f"  Peças no Backlog: {bklog:.0f}")

    print(f"\n  📖 O QUE É O BACKLOG:")
    print(f"     São pedidos que JÁ FORAM VENDIDOS ao cliente, mas ainda")
    print(f"     não foram faturados/despachados. As peças aparecem no")
    print(f"     saldo físico do estoque, mas estão COMPROMETIDAS —")
    print(f"     pertencem a alguém e precisam ser entregues.")
    print(f"     Por isso, subtraímos do estoque disponível.")
    print(f"     Ex: 25 em estoque − 5 backlog = 20 realmente disponíveis.")

    # ================================================================
    # ETAPA 5 — PIPELINE
    # ================================================================
    linha("ETAPA 5 — PIPELINE (EM PRODUÇÃO)")

    pipe = 0  # Atualmente não alimentado

    print(f"\n  Peças em Pipeline: {pipe:.0f}")

    print(f"\n  📖 O QUE É O PIPELINE:")
    print(f"     São peças que JÁ ESTÃO SENDO PRODUZIDAS na fábrica.")
    print(f"     Corte feito, costura em andamento, acabamento etc.")
    print(f"     Vão chegar ao estoque em breve, então não faz sentido")
    print(f"     mandar produzir de novo.")
    print(f"     Se tem 50 peças vindo, a necessidade de produção diminui 50.")
    print(f"\n  ⚠️  Pipeline não está alimentado atualmente (sempre 0).")
    print(f"     Para ativar, forneça um DataFrame com colunas: SKU, Quantidade, Status")

    # ================================================================
    # ETAPA 6 — CÁLCULO DA NECESSIDADE
    # ================================================================
    linha("ETAPA 6 — CÁLCULO DA NECESSIDADE DE PRODUÇÃO")

    # Demanda projetada
    demanda_proj = media_mensal * (1 + crescimento / 100) * sazonalidade
    demanda_proj += correcao_global + correcao_sku

    sub("Demanda Projetada (mensal)")
    calc("Base:",
         f"Média_mensal × (1 + Crescimento%) × Sazonalidade",
         f"{media_mensal:.2f} × {1 + crescimento/100:.2f} × {sazonalidade}")
    calc("+ Correções:",
         f"+ Correção_global + Correção_SKU = + {correcao_global} + {correcao_sku}",
         f"{demanda_proj:.2f} peças/mês")

    print(f"\n  📖 O QUE É A DEMANDA PROJETADA:")
    print(f"     A previsão de quantas peças vão sair POR MÊS no futuro.")
    print(f"     Parte da média histórica e ajusta por crescimento esperado,")
    print(f"     sazonalidade e correções manuais.")

    # Estoque Meta
    estoque_meta = demanda_proj * cobertura_meses
    if estoque_meta < 2:
        estoque_meta = 2

    sub("Estoque Meta")
    calc("Estoque Meta:",
         f"Demanda_projetada × Cobertura = {demanda_proj:.2f} × {cobertura_meses}",
         f"{estoque_meta:.0f} peças (mínimo: 2)")

    print(f"\n  📖 O QUE É O ESTOQUE META:")
    print(f"     Quanto a empresa DEVERIA TER em estoque total (toda a rede)")
    print(f"     para cobrir {cobertura_meses} meses de demanda projetada.")
    print(f"     Se demanda projetada é 50/mês e cobertura é 2 meses,")
    print(f"     estoque meta = 100 peças.")

    # Disponível Líquido
    disponivel = est_rede - bklog

    sub("Disponível Líquido")
    calc("Disponível Líquido:",
         f"Estoque_rede − Backlog = {est_rede:.0f} − {bklog:.0f}",
         f"{disponivel:.0f} peças")

    print(f"\n  📖 O QUE É O DISPONÍVEL LÍQUIDO:")
    print(f"     Estoque real MENOS o que já está comprometido (backlog).")
    print(f"     É o que a empresa realmente tem 'livre' para vender.")

    # Efetivo
    efetivo = disponivel + pipe

    sub("Estoque Efetivo")
    calc("Efetivo:",
         f"Disponível_líquido + Pipeline = {disponivel:.0f} + {pipe:.0f}",
         f"{efetivo:.0f} peças")

    print(f"\n  📖 O QUE É O ESTOQUE EFETIVO:")
    print(f"     Tudo que a empresa TEM ou VAI TER em breve.")
    print(f"     = Disponível (livre) + Pipeline (chegando da fábrica).")

    # Necessidade
    necessidade = max(estoque_meta - efetivo, 0)

    sub("Necessidade Bruta")
    calc("Necessidade:",
         f"max(Estoque_meta − Efetivo, 0) = max({estoque_meta:.0f} − {efetivo:.0f}, 0)",
         f"{necessidade:.0f} peças")

    print(f"\n  📖 O QUE É A NECESSIDADE:")
    print(f"     A diferença entre o que DEVERIA TER e o que TEM/VAI TER.")
    print(f"     Se é 0, está tudo coberto. Se é positivo, precisa produzir.")

    # Sugestão final
    sugestao = math.ceil(necessidade)
    if sugestao % 2 != 0:
        sugestao += 1

    if sugestao == 0 and disponivel <= 0 and media_mensal > 0:
        sugestao = 2

    sub("Sugestão de Produção")
    print(f"  Necessidade bruta: {necessidade:.0f}")
    print(f"  Arredondado (par): {sugestao}")

    if sugestao == 2 and necessidade == 0:
        print(f"  ⚠️  Segurança: sugestão mínima=2 porque disponível ≤ 0 e produto tem demanda")

    investimento = sugestao * preco_custo

    print(f"\n  ┌──────────────────────────────────────────────────┐")
    print(f"  │  SUGESTÃO DE PRODUÇÃO = {sugestao:>5} peças              │")
    print(f"  │  Custo Unitário       = R$ {preco_custo:>8.2f}             │")
    print(f"  │  Investimento Fabril  = R$ {investimento:>10.2f}           │")
    print(f"  └──────────────────────────────────────────────────┘")

    # ================================================================
    # RESUMO VISUAL
    # ================================================================
    linha("RESUMO DO FLUXO")

    print(f"""
  ┌─────────────────────────────────────────────────────────┐
  │                    FLUXO DO CÁLCULO                     │
  │                                                         │
  │  Vendas Históricas ──→ Média Mensal                     │
  │       {vd_hist:>5.0f} pçs           {media_mensal:>6.2f} pçs/mês              │
  │                            │                            │
  │                     × Crescimento ({crescimento}%)                │
  │                     × Sazonalidade ({sazonalidade}x)              │
  │                            │                            │
  │                     Demanda Projetada                    │
  │                         {demanda_proj:>6.2f} pçs/mês              │
  │                            │                            │
  │                     × Cobertura ({cobertura_meses} meses)               │
  │                            │                            │
  │                     Estoque Meta                         │
  │                         {estoque_meta:>5.0f} pçs                     │
  │                            │                            │
  │  Estoque Rede ──→ − Backlog ──→ + Pipeline              │
  │      {est_rede:>5.0f} pçs       {bklog:>5.0f} pçs      {pipe:>5.0f} pçs          │
  │                     = Efetivo                            │
  │                        {efetivo:>5.0f} pçs                     │
  │                            │                            │
  │  NECESSIDADE = Meta − Efetivo                           │
  │             = {estoque_meta:.0f} − {efetivo:.0f} = {necessidade:.0f} pçs                     │
  │                            │                            │
  │  SUGESTÃO   = {sugestao} peças (arredondado par)              │
  │  INVESTIMENTO = R$ {investimento:.2f}                          │
  └─────────────────────────────────────────────────────────┘""")


if __name__ == "__main__":
    main()
