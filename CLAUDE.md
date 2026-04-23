# Bling Dashboard — Contexto do Projeto

## O que é este projeto
Dashboard Streamlit que substitui o fluxo Google Apps Script + Looker Studio da Art Kamizetas.
Lê dados do **Google Sheets** integrado com o Bling ERP, processa via pandas e exibe análises de estoque, PCP e vendas.
Empresa: Art Kamizetas — lojas em Natal e Mossoró (RN).

## Como rodar
```bash
# Ativar venv (Windows)
venv\Scripts\activate

# Rodar o dashboard
streamlit run app.py
```

**Origem dos dados:** Google Sheets (configurado em `st.secrets["sheet_id"]`). Não há dependência de arquivo Excel local.

## Arquitetura

```
app.py                      # Ponto de entrada — registra as páginas
config.yaml                 # Todas as configurações (metas, IDs, janelas de tempo, exceções SKU)
auth.py                     # Autenticação Streamlit (role-based access control)
data/                       # Dados locais (Parametros_VM.xlsx, não sincronizado com Bling)
etl/
  loader.py                 # Lê Google Sheets (via secrets) e valida → retorna dict de DataFrames
  daily.py                  # Lógica de Comercial / Metas diárias
  logistica.py              # Lógica de Reposição de Loja
  fabrica.py                # Lógica de PCP / Planejamento de Produção
  planejamento.py           # Lógica de Planejamento Anual de Rodadas
  vm_dinamico.py            # Cálculo de VM (Visual Merchandising) dinâmico
pages/
  0_Home.py                 # Tela inicial / status do sistema
  1_Daily.py                # Dashboard Comercial (metas, vendedores, lojas)
  2_Logistica.py            # Reposição de Loja (sugestões de transferência)
  3_Fabrica.py              # PCP / Estoque de Fábrica
  4_Planejamento.py         # Planejamento de produção anual por rodadas
  5_Configuracoes.py        # (Admin) Configuração de parâmetros, exceções SKU e sistema
```

## Fluxo de dados padrão
1. `loader.py::carregar_dados()` lê **Google Sheets** (via `st.secrets["sheet_id"]`) e retorna um `dict` de DataFrames
   - Se Google Sheets não estiver disponível, tenta carregar do Excel local como fallback (para desenvolvimento)
2. Páginas importam funções dos módulos `etl/` e passam os DataFrames
3. Configurações são sempre lidas do `config.yaml` via `yaml.safe_load()` ou via `ruamel.yaml` (para preservar comentários)
4. **Nunca** leia o Excel diretamente nas páginas — sempre passe pelo `loader.py()`
5. Em produção: dados vêm 100% do Google Sheets; arquivo Excel local não é necessário

## DataFrames disponíveis após `carregar_dados()`
- `dados["pedidos"]` — Pedidos (Loja ID, Data, Total Venda, id_situacao)
- `dados["itens"]` — Itens dos pedidos (ID_pedido, ID_produto, Quantidade)
- `dados["produtos"]` — Produtos ATIVOS (situacao == "A")
- `dados["produtos_todos"]` — Todos os produtos (incluindo inativos)
- `dados["estoque"]` — Saldo físico por depósito (ID_deposito, ID_produto, saldoFisico)
- `dados["detalhes"]` — Detalhes do produto (categoria, Super_categoria, Grupo, Tamanho)
- `dados["vendedores"]`, `dados["lojas"]`, `dados["situacoes"]`, `dados["depositos"]`

## IDs importantes (config.yaml)
- Lojas (usado em Pedidos): Natal = `203379922`, Mossoró = `203575032`
- Depósitos (usado em EstoqueV3): Natal = `7011018386`, Mossoró = `14887086441`, CD = `11105614627`
- Situações de venda efetiva: `[9]` (Atendido)
- Situações de backlog: `[6, 15]`

## Regras de negócio críticas
- **Loja ID ≠ Depósito ID**: loja aparece em Pedidos, depósito em EstoqueV3
- **SKU format**: código alfanumérico sem padrão fixo, mas normalmente `CATEGORIA-TAMANHO`
- **Produtos**: só trabalhar com `dados["produtos"]` (ativos). Usar `dados["produtos_todos"]` apenas para referência histórica
- **IDs como string**: IDs do Bling são sempre tratados como string após `limpar_id()` — nunca compare como int
- **Datas**: coluna `Data` já convertida para datetime no loader

## Convenções de código
- Pandas para toda manipulação de dados
- `st.cache_data` nos carregamentos pesados (leitura do Google Sheets via `loader.py`)
- Configurações sempre de `config.yaml`, nunca hardcoded nas páginas
- **Autenticação:** `auth.py` com role-based access (admin, user) via `st.secrets["auth_config"]`
- **Configuração dinâmica:** página `5_Configuracoes.py` permite salvar alterações em `config.yaml` via UI (admin only)
- Nomes de variáveis e comentários em português (padrão do projeto)
- Cada módulo ETL recebe DataFrames e o dicionário `config` — não abre arquivos diretamente
- **YAML:** usar `ruamel.yaml` (não `yaml`) quando precisar salvar config.yaml preservando comentários

## Página de Configuração (5_Configuracoes.py)

**Admin only** — acesso controlado por role em `st.secrets["auth_config"]`.

### Aba 1: Parâmetros Gerais
Formulário para editar configurações de produção:
- Metas comerciais (Natal, Mossoró)
- Parâmetros de logística (VM padrão, dias análise, cobertura mínima)
- Parâmetros de fábrica (período histórico, crescimento, sazonalidade, cobertura)
- Planejamento (rodadas de produção, lead time, sazonalidade, buffer)
- Status IDs de pedido (em_aberto, em_andamento, pronto_retirada)

Ao salvar:
1. Valida estrutura mínima e valores numéricos
2. Salva em `config.yaml` usando `ruamel.yaml` (preserva comentários)
3. Limpa cache do Streamlit (`st.cache_data.clear()`)

### Aba 2: Exceções de SKU
CSV template para sobrescrever parâmetros globais por SKU:
- Columns: `sku`, `vm_override`, `dias_analise`, `sazonalidade`, `correcao_manual`
- Download: template atual (ou exemplo padrão se nenhuma exceção existe)
- Upload: aplicar novas exceções via CSV
- Salva em `config.yaml["excecoes_sku"]`

### Aba 3: Sistema
Informações do sistema:
- Versões (Python, Streamlit, Pandas)
- Fonte de dados: Google Sheets — Bling ERP (não Excel local)
- Data de última modificação do `config.yaml`
- Botão: Forçar recarga de cache
- Botão: Backup do `config.yaml` (download)

---

## Não faça sem perguntar
- Alterar `config.yaml` manualmente (use a página de Configurações, ou pergunte ao usuário)
- Alterar a estrutura de retorno de `loader.py::carregar_dados()` (quebra todas as páginas)
- Renomear colunas dos DataFrames
- Adicionar dependências ao `requirements.txt`

---

## Dependências (requirements.txt)
```
streamlit
pandas
openpyxl
pyyaml
ruamel.yaml
gspread
oauth2client
streamlit-authenticator
```

---

## Secrets esperados (streamlit/secrets.toml)
```toml
# Google Sheets
sheet_id = "SEU_SHEET_ID_AQUI"

# Autenticação
[auth_config]
credentials = { usernames = { admin = { password = "HASH_BCrypt", role = "admin" }, ... } }
```
