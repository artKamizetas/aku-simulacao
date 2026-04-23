"""
Página: Configurações do Sistema (Admin Only)
Gerencia todos os parâmetros de produção via UI:
- Parâmetros gerais (metas, IDs, períodos)
- Exceções de SKU (upload/download CSV)
- Upload de dados (Excel)
- Sistema (cache, backup config)
"""

import streamlit as st
from auth import exigir_login
exigir_login()

from pathlib import Path
import yaml
from ruamel.yaml import YAML
from datetime import datetime, date
import pandas as pd
import io

# Pega as credenciais do session_state (setado em auth.py)
# Busca o role no secrets.toml baseado no username
username = st.session_state.get("username", "")
auth_config = dict(st.secrets.get("auth_config", {}))
usernames = auth_config.get("credentials", {}).get("usernames", {})
user_data = usernames.get(username, {})
role = user_data.get("role", "")

if role != "admin":
    st.error("⛔ Acesso negado. Apenas administradores podem acessar esta página.")
    st.stop()

# =================================================================
# FUNÇÕES AUXILIARES
# =================================================================

def carregar_config():
    """Carrega config.yaml com ruamel.yaml para preservar comentários."""
    caminho_config = Path(__file__).parent.parent / "config.yaml"
    yaml_handler = YAML()
    yaml_handler.preserve_quotes = True
    yaml_handler.default_flow_style = False
    with open(caminho_config, "r", encoding="utf-8") as f:
        config = yaml_handler.load(f)
    return config, caminho_config, yaml_handler


def salvar_config(config, caminho_config, yaml_handler):
    """Salva config.yaml preservando comentários."""
    with open(caminho_config, "w", encoding="utf-8") as f:
        yaml_handler.dump(config, f)


def validar_config(config):
    """Valida estrutura mínima do config antes de salvar."""
    erros = []

    # Verificar seções obrigatórias
    obrigatorias = ["fonte", "depositos", "logistica", "daily", "fabrica", "planejamento"]
    for secao in obrigatorias:
        if secao not in config:
            erros.append(f"Seção '{secao}' ausente")

    # Validar datas
    if "fabrica" in config:
        try:
            data_ini = datetime.fromisoformat(config["fabrica"]["data_inicio"])
            data_fim = datetime.fromisoformat(config["fabrica"]["data_fim"])
            if data_ini > data_fim:
                erros.append("Fábrica: data_inicio > data_fim")
        except (ValueError, KeyError) as e:
            erros.append(f"Fábrica: datas inválidas ({e})")

    if "planejamento" in config:
        try:
            data_ini = datetime.fromisoformat(config["planejamento"]["sazonalidade_inicio"])
            data_fim = datetime.fromisoformat(config["planejamento"]["sazonalidade_fim"])
            if data_ini > data_fim:
                erros.append("Planejamento: sazonalidade_inicio > sazonalidade_fim")
        except (ValueError, KeyError) as e:
            erros.append(f"Planejamento: datas de sazonalidade inválidas ({e})")

    # Validar números positivos
    campos_positivos = [
        ("logistica.vm_padrao", ["logistica", "vm_padrao"]),
        ("logistica.dias_analise_giro", ["logistica", "dias_analise_giro"]),
        ("logistica.dias_cobertura_minima", ["logistica", "dias_cobertura_minima"]),
        ("fabrica.crescimento_pct", ["fabrica", "crescimento_pct"]),
        ("fabrica.cobertura_meses", ["fabrica", "cobertura_meses"]),
        ("planejamento.lead_time_semanas", ["planejamento", "lead_time_semanas"]),
        ("planejamento.buffer_pct", ["planejamento", "buffer_pct"]),
    ]

    for nome_campo, caminho in campos_positivos:
        try:
            valor = config
            for chave in caminho:
                valor = valor[chave]
            if valor < 0:
                erros.append(f"{nome_campo} não pode ser negativo")
        except (KeyError, TypeError):
            pass

    return erros


# =================================================================
# INTERFACE PRINCIPAL
# =================================================================

st.title("⚙️ Configurações do Sistema")
st.markdown("_Gerenciar parâmetros de produção, exceções de SKU e sistema._")

tab1, tab2, tab3 = st.tabs([
    "📋 Parâmetros Gerais",
    "📦 Exceções de SKU",
    "ℹ️ Sistema"
])

# =================================================================
# ABA 1 — PARÂMETROS GERAIS
# =================================================================

with tab1:
    config, caminho_config, yaml_handler = carregar_config()

    st.subheader("Parâmetros de Operação")

    with st.form("form_parametros"):
        col1, col2 = st.columns(2)

        # DAILY — Metas
        with col1:
            st.markdown("#### 📈 Daily (Comercial)")
            meta_natal = st.number_input(
                "Meta Natal (R$)",
                value=float(config["daily"]["metas"].get("Natal", 150000)),
                min_value=0.0,
                step=1000.0,
            )
            meta_mossoró = st.number_input(
                "Meta Mossoró (R$)",
                value=float(config["daily"]["metas"].get("Mossoró", 100000)),
                min_value=0.0,
                step=1000.0,
            )

        # LOGÍSTICA — VM
        with col2:
            st.markdown("#### 📦 Logística (Reposição)")
            vm_padrao = st.number_input(
                "VM Padrão (unidades)",
                value=int(config["logistica"]["vm_padrao"]),
                min_value=0,
            )
            dias_analise = st.number_input(
                "Dias análise giro",
                value=int(config["logistica"]["dias_analise_giro"]),
                min_value=1,
            )
            dias_cobertura = st.number_input(
                "Dias cobertura mínima",
                value=int(config["logistica"]["dias_cobertura_minima"]),
                min_value=1,
            )

        # FÁBRICA
        st.markdown("#### 🏭 Fábrica (PCP)")
        col3, col4, col5 = st.columns(3)

        with col3:
            data_inicio = st.date_input(
                "Período histórico — Início",
                value=datetime.fromisoformat(config["fabrica"]["data_inicio"]).date(),
            )
            crescimento = st.number_input(
                "Crescimento esperado (%)",
                value=float(config["fabrica"]["crescimento_pct"]),
                min_value=0.0,
                step=0.5,
            )

        with col4:
            data_fim = st.date_input(
                "Período histórico — Fim",
                value=datetime.fromisoformat(config["fabrica"]["data_fim"]).date(),
            )
            sazonalidade = st.number_input(
                "Sazonalidade global (multiplicador)",
                value=float(config["fabrica"]["sazonalidade"]),
                min_value=0.1,
                step=0.1,
            )

        with col5:
            cobertura_meses = st.number_input(
                "Cobertura meta (meses)",
                value=int(config["fabrica"]["cobertura_meses"]),
                min_value=1,
            )
            correcao_manual = st.number_input(
                "Correção manual (unidades)",
                value=int(config["fabrica"]["correcao_manual"]),
                step=1,
            )

        # PLANEJAMENTO
        st.markdown("#### 📅 Planejamento (Rodadas)")
        col6, col7, col8 = st.columns(3)

        with col6:
            rodadas = st.multiselect(
                "Meses das rodadas de produção",
                options=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
                default=config["planejamento"]["rodadas"],
                help="Selecione os meses em que pedidos são disparados para a fábrica",
            )
            lead_time = st.number_input(
                "Lead time (semanas)",
                value=int(config["planejamento"]["lead_time_semanas"]),
                min_value=1,
            )

        with col7:
            sazon_ini = st.date_input(
                "Sazonalidade — Início",
                value=datetime.fromisoformat(config["planejamento"]["sazonalidade_inicio"]).date(),
            )
            buffer = st.number_input(
                "Buffer de segurança (%)",
                value=int(config["planejamento"]["buffer_pct"]),
                min_value=0,
                step=1,
            )

        with col8:
            sazon_fim = st.date_input(
                "Sazonalidade — Fim",
                value=datetime.fromisoformat(config["planejamento"]["sazonalidade_fim"]).date(),
            )

        # Status IDs
        st.markdown("#### 🔖 Status de Pedido")
        col9, col10, col11 = st.columns(3)

        with col9:
            status_aberto = st.number_input(
                "ID — Em Aberto",
                value=int(config["daily"]["status_ids"]["em_aberto"]),
            )

        with col10:
            status_andamento = st.number_input(
                "ID — Em Andamento",
                value=int(config["daily"]["status_ids"]["em_andamento"]),
            )

        with col11:
            status_pronto = st.number_input(
                "ID — Pronto para Retirada",
                value=int(config["daily"]["status_ids"]["pronto_retirada"]),
            )

        # Botão enviar
        submitted = st.form_submit_button("💾 Salvar Configurações", type="primary")

    if submitted:
        # Atualizar config
        config["daily"]["metas"]["Natal"] = meta_natal
        config["daily"]["metas"]["Mossoró"] = meta_mossoró
        config["logistica"]["vm_padrao"] = vm_padrao
        config["logistica"]["dias_analise_giro"] = dias_analise
        config["logistica"]["dias_cobertura_minima"] = dias_cobertura
        config["fabrica"]["data_inicio"] = data_inicio.isoformat()
        config["fabrica"]["data_fim"] = data_fim.isoformat()
        config["fabrica"]["crescimento_pct"] = crescimento
        config["fabrica"]["sazonalidade"] = sazonalidade
        config["fabrica"]["cobertura_meses"] = cobertura_meses
        config["fabrica"]["correcao_manual"] = correcao_manual
        config["planejamento"]["rodadas"] = sorted(list(set(rodadas)))
        config["planejamento"]["lead_time_semanas"] = lead_time
        config["planejamento"]["sazonalidade_inicio"] = sazon_ini.isoformat()
        config["planejamento"]["sazonalidade_fim"] = sazon_fim.isoformat()
        config["planejamento"]["buffer_pct"] = buffer
        config["daily"]["status_ids"]["em_aberto"] = status_aberto
        config["daily"]["status_ids"]["em_andamento"] = status_andamento
        config["daily"]["status_ids"]["pronto_retirada"] = status_pronto

        # Validar
        erros = validar_config(config)
        if erros:
            st.error("❌ Erros encontrados:")
            for erro in erros:
                st.write(f"- {erro}")
        else:
            # Salvar
            salvar_config(config, caminho_config, yaml_handler)
            st.cache_data.clear()
            st.success("✅ Configurações salvas com sucesso!")
            st.info("💡 Cache limpo. Os dados serão recarregados na próxima visualização das páginas.")

# =================================================================
# ABA 2 — EXCEÇÕES DE SKU
# =================================================================

with tab2:
    config, caminho_config, yaml_handler = carregar_config()

    st.subheader("Gerenciar Exceções de SKU")
    st.markdown("Sobrescreve regras globais para produtos específicos.")

    col_down, col_up = st.columns(2)

    # Download template
    with col_down:
        st.markdown("#### 📥 Baixar Template")

        # Preparar dados atuais
        excecoes = config.get("excecoes_sku") or {}
        df_excecoes = pd.DataFrame([
            {
                "sku": sku,
                "vm_override": params.get("vm", "") if isinstance(params, dict) else "",
                "dias_analise": params.get("dias_analise", "") if isinstance(params, dict) else "",
                "sazonalidade": params.get("sazonalidade", "") if isinstance(params, dict) else "",
                "correcao_manual": params.get("correcao", "") if isinstance(params, dict) else "",
            }
            for sku, params in excecoes.items()
        ])

        if len(df_excecoes) == 0:
            df_excecoes = pd.DataFrame({
                "sku": ["EXEMPLO-P", "EXEMPLO-M"],
                "vm_override": [5, 8],
                "dias_analise": [60, ""],
                "sazonalidade": [2.5, ""],
                "correcao_manual": ["", 10],
            })
            csv_data = df_excecoes.to_csv(index=False)
            st.info("📝 Template padrão (nenhuma exceção cadastrada ainda)")
        else:
            csv_data = df_excecoes.to_csv(index=False)
            st.info(f"📝 {len(df_excecoes)} exceção(ões) cadastrada(s)")

        st.download_button(
            label="⬇️ Baixar CSV",
            data=csv_data,
            file_name="excecoes_sku.csv",
            mime="text/csv",
            type="primary",
        )

    # Upload de exceções
    with col_up:
        st.markdown("#### 📤 Fazer Upload")

        uploaded_file = st.file_uploader("Selecione arquivo CSV", type=["csv"])

        if uploaded_file is not None:
            try:
                df_novo = pd.read_csv(uploaded_file)

                # Validar colunas
                colunas_obrigatorias = ["sku"]
                if not all(col in df_novo.columns for col in colunas_obrigatorias):
                    st.error(f"❌ Colunas obrigatórias: {', '.join(colunas_obrigatorias)}")
                else:
                    st.dataframe(df_novo, use_container_width=True)

                    if st.button("✅ Aplicar Exceções", key="btn_aplicar_sku", type="primary"):
                        # Converter para dict
                        excecoes_novo = {}
                        for _, row in df_novo.iterrows():
                            sku = str(row["sku"]).strip()
                            params = {}

                            if pd.notna(row.get("vm_override")):
                                params["vm"] = int(row["vm_override"])
                            if pd.notna(row.get("dias_analise")):
                                params["dias_analise"] = int(row["dias_analise"])
                            if pd.notna(row.get("sazonalidade")):
                                params["sazonalidade"] = float(row["sazonalidade"])
                            if pd.notna(row.get("correcao_manual")):
                                params["correcao"] = int(row["correcao_manual"])

                            if params:
                                excecoes_novo[sku] = params

                        # Salvar
                        config["excecoes_sku"] = excecoes_novo
                        salvar_config(config, caminho_config, yaml_handler)
                        st.cache_data.clear()
                        st.success(f"✅ {len(excecoes_novo)} exceção(ões) aplicada(s)!")

            except Exception as e:
                st.error(f"❌ Erro ao processar CSV: {e}")

# =================================================================
# ABA 3 — INFORMAÇÕES DO SISTEMA
# =================================================================

with tab3:
    st.subheader("Informações do Sistema")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 📊 Versões")
        st.write(f"**Python:** {__import__('sys').version.split()[0]}")
        st.write(f"**Streamlit:** {st.__version__}")
        st.write(f"**Pandas:** {pd.__version__}")

    with col2:
        st.markdown("#### 📊 Fonte de Dados")
        st.write("**Fonte:** Google Sheets — Bling ERP")
        st.write("**Cache:** Recarregado a cada 1 hora (ou ao clicar 🔄)")

        try:
            caminho_config = Path(__file__).parent.parent / "config.yaml"
            mod_time = datetime.fromtimestamp(caminho_config.stat().st_mtime)
            st.write(f"**Config:** {mod_time.strftime('%d/%m/%Y %H:%M')}")
        except:
            st.write("**Config:** Erro ao ler")

    st.markdown("---")

    col3, col4 = st.columns(2)

    with col3:
        if st.button("🔄 Forçar Recarga de Dados"):
            st.cache_data.clear()
            st.success("✅ Cache limpo. Próxima página vai recarregar os dados.")

    with col4:
        config, _, yaml_handler = carregar_config()
        config_yaml = io.StringIO()
        yaml_handler.dump(config, config_yaml)

        st.download_button(
            label="💾 Backup config.yaml",
            data=config_yaml.getvalue(),
            file_name=f"config_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml",
            mime="text/plain",
        )
