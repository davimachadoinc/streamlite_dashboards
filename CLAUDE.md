# CLAUDE.md — InChurch Dashboard

Instruções de arquitetura e lógicas de negócio para o assistente de código.

---

## Estrutura do projeto

```
C:\Claude_Files\
├── CLAUDE.md                     # Dicionário de variáveis e racionais de negócio
├── Dashboards\                   # Pasta para futuros projetos de dashboard
└── streamlite_dashboards\        # Código do dashboard Streamlit
    ├── app.py                    # Entry point — autenticação Google OIDC
    ├── CLAUDE.md                 # Este arquivo
    ├── pages/
    │   ├── 1_📊_Cobranca.py      # Dashboard de Cobrança & Módulos
    │   ├── 2_❌_Desativacoes.py  # Dashboard de Desativações & MRR perdido
    │   ├── 3_💳_Transacoes.py    # Dashboard de Transações por método
    │   └── 4_⚠️_Inadimplencia.py # Dashboard de Inadimplência 30d/90d
    ├── utils/
    │   ├── data.py               # Queries BigQuery, cache, helpers de KPI e gráficos
    │   └── style.py              # Design system (CSS/JS injetado via st.markdown)
    └── requirements.txt
```

---

## Arquitetura Streamlit

### Padrão de páginas
- Toda página começa com `st.set_page_config(...)` como **primeira instrução**.
- Logo após: checar `st.user.is_logged_in` — se `False`, exibir erro e `st.stop()`.
- Definir `st.session_state["_page_key"] = "<nome>"` antes de importar utils (usado pelo `period_selector` para isolar o selectbox por página).
- Chamar `inject_css()` no início de cada página.

### Autenticação
- Gerenciada em `app.py` via `st.login()` / `st.logout()` (Google OIDC nativo do Streamlit).
- Lista de e-mails permitidos em `st.secrets["app_config"]["allowed_emails"]`.
- Ao final de `app.py`, redireciona com `st.switch_page("pages/1_📊_Cobranca.py")`.
- As páginas individualmente **não fazem redirect de login**, apenas param com erro.

### Cache
- `@st.cache_resource` — clientes BigQuery (uma instância por project_key, sem TTL).
- `@st.cache_data(ttl=3600)` — resultados de queries (1 hora).

### BigQuery — duas conexões separadas
| Alias | Projeto GCP | Secret key |
|---|---|---|
| `bigquery_tech` | `inchurch-gcp` | `st.secrets["connections"]["bigquery_tech"]` |
| `bigquery_bi` | `business-intelligence-467516` | `st.secrets["connections"]["bigquery_bi"]` |

> ⚠️ Queries cross-project **não funcionam**. Joins entre as duas bases devem ser feitos no Python com pandas. Ao fazer join, converter `tertiarygroup_id` (INT do BQ_TECH) para STRING antes de cruzar com `st_sincro_sac` (STRING do BQ_BI).

### Helpers de dados (`utils/data.py`)
| Função | Uso |
|---|---|
| `period_selector()` | Selectbox na sidebar — retorna `n_months` (int) |
| `filter_months(df, n, col)` | Filtra DataFrame pelos últimos N meses |
| `mes_fmt_ordered(df, col)` | Adiciona `mes_fmt` (ex: `Mar/25`) e retorna ordem cronológica para `categoryarray` do Plotly |
| `chart_layout(fig, height, legend_bottom)` | Aplica template dark padrão ao gráfico |
| `last_val(df, col)` / `prev_val(df, col)` | Valores do último e penúltimo registro (para delta nos KPIs) |
| `delta_str(curr, prev, fmt, suffix)` | Formata string de delta para `st.metric` |
| `no_data(label)` | Exibe `st.info` quando DataFrame está vazio |
| `fmt_brl(value, decimals)` | Formata valor monetário em BRL — padrão 2 casas decimais |
| `load_inadimplencia_serie()` | Snapshot diário de inadimplência 30d/90d — loop Python sobre dias úteis com numpy |
| `load_inadimplencia_por_plano()` | Snapshot atual: clientes e valor em aberto por plano (janela 30d) |
| `load_inadimplencia_top_clientes(dias)` | Top 30 inadimplentes na janela de `dias` dias (30 ou 90) |

### Design system (`utils/style.py`)
- Tema: dark mode, fonte Outfit, acento verde `#6eda2c`.
- Chamar `inject_css()` **uma vez** por página — injeta fontes, CSS e JS via `st.markdown(unsafe_allow_html=True)`.
- Variáveis CSS principais: `--accent-1: #6eda2c`, `--bg-card: #121212`, `--text-muted: #a0a0a0`.
- `h1 span` fica em verde — usar `<h1>Título <span>Subtítulo</span></h1>`.

### Paleta de cores
```python
PALETTE = ["#6eda2c","#ffffff","#57d124","#a0a0a0","#4c4c4c","#292929","#8ae650","#3ba811","#cccccc","#111111"]
MODULE_COLORS = {"kids": "#6eda2c", "jornada": "#ffffff", "loja_inteligente": "#a0a0a0", "base": "#4c4c4c"}
```

---

## Lógicas de negócio

### Módulos comerciais
| Módulo | `feature_alias` (BQ_TECH) | `comp_st_descricao_prd` (BQ_BI) |
|---|---|---|
| Kids | `kids` | `%[KIDS]%` |
| Jornada | `jornada` | `%[JORNADA]%` |
| Loja Inteligente | `loja_inteligente` | `%[LOJAINTELIGENTE]%` ou `%[LOJAINTELIGENTE_INC]%` |

### Receita por módulo
- Usar `comp_valor` (valor do item da composição do boleto), **não** `vl_total_recb` (valor total do boleto).
- Filtrar `comp_st_conta_cont = '1.2.2'` (Mensalidade).
- Identificar módulo via `LIKE '%[KIDS]%'` etc. em `comp_st_descricao_prd`.
- `fl_status_recb = '1'` → boleto pago (STRING, não inteiro).
- Ver query completa em `LOGICAS_DE_NEGOCIO.md` → seção "Receita por módulo".

### Clientes únicos com boleto por mês
- Deduplicar com `ROW_NUMBER() OVER (PARTITION BY id_recebimento_recb)` antes de `COUNT(DISTINCT st_sincro_sac)`.
- Ver query completa em `LOGICAS_DE_NEGOCIO.md` → seção "Clientes únicos com boleto emitido por mês".

### Transações financeiras (`view_transaction`)
- Filtrar `status IN ('active', 'payed')`.
- Excluir métodos: `free` (value = 0), `external` (value = 0), `debit` (volume residual).
- Métodos válidos: `pix`, `credit`, `billet`.
- Canais: `ecommerce`, `pos`.
- A coluna se chama `method`, não `payment_method` — renomear no Python após a query.

### Igreja com acesso ativo ao painel
```sql
WHERE tertiarygroup_is_active = TRUE
  AND is_blocked = FALSE
  AND subgroup_is_active = TRUE
```

### Inadimplência (janela rolante)
- **30d**: boletos com `vencimento BETWEEN D-30 AND D`, abertos em D (`dt_liquidacao IS NULL OR dt_liquidacao > D`).
- **90d**: mesma lógica com janela `[D-90, D]`.
- **Não usar `fl_status_recb`** para análise histórica — reflete estado atual. Usar `dt_liquidacao_recb`.
- Cliente inadimplente válido: `comp_valor > 1` E já pagou algum boleto (`EXISTS fl_status_recb='1'`).
- Snapshot de perfil (por plano, top clientes): usar `fl_status_recb='0'` com filtro `BETWEEN D-30 AND D` — estado atual é suficiente para o snapshot de hoje.

### Datas no BigQuery
- `dt_vencimento_recb` e `dt_liquidacao_recb` são TIMESTAMP — sempre usar `CAST(... AS DATE)` antes de comparar.
- Agrupar por mês: `DATE_TRUNC(CAST(dt_vencimento_recb AS DATE), MONTH)`.

### Chave de join entre bases
| BQ_TECH | BQ_BI |
|---|---|
| `tertiarygroup_id` (INT) | `st_sincro_sac` (STRING) |

Converter: `CAST(tertiarygroup_id AS STRING)` ou `str()` no pandas.

---

## Convenções de código

- Queries SQL ficam em `utils/data.py` como funções com `@st.cache_data(ttl=3600)`.
- Toda função de query usa `_bq_query(query, project_key)` internamente.
- Gráficos são montados nas páginas com `go.Figure()` + `chart_layout(fig)`.
- Sempre passar `categoryorder="array", categoryarray=x_order` ao Plotly para garantir ordem cronológica no eixo X.
- Filtro de período: chamar `period_selector()` no header da página, depois `filter_months(df, n_months)` em cada DataFrame carregado.
- KPIs: padrão `last_val` / `prev_val` / `delta_str` → `st.metric(label, valor, delta=...)`.
- Valores monetários: sempre exibir com no máximo 2 casas decimais — usar `fmt_brl(v)` ou `fmt_brl(v, 0)`.

### Eixo X com datas diárias (gráficos de séries diárias)
```python
# Ticks semanais, último dia sempre visível, formato dd/mm
_dates = df["dia"].sort_values()
_end   = _dates.iloc[-1]
_ticks = list(pd.date_range(start=_dates.iloc[0], end=_end, freq="7D"))
if not _ticks or _ticks[-1] != _end:
    _ticks.append(_end)
fig.update_layout(xaxis=dict(type="date", tickformat="%d/%m", tickvals=_ticks))
```

### Compatibilidade Python 3.14 (Streamlit Cloud)
- **Não usar `pd.NA`** como substituto de zero em divisões — converte série para `object` dtype, quebrando `.round()`.
- Usar `series.where(series > 0)` — mantém `float` dtype com `NaN` nos zeros.
- **Não adicionar `Authlib` ao `requirements.txt`** — Streamlit ≥ 1.41 gerencia OAuth internamente; adicionar causa `ImportError` na Cloud.

### Inadimplência — padrão de implementação
- Função `load_inadimplencia_serie()` carrega boletos brutos (18 meses) do BQ e computa snapshots em Python com numpy, via loop sobre `pd.bdate_range`.
- Para séries de snapshot (cross-date), preferir computação Python em vez de CROSS JOIN no BigQuery.
- Filtros obrigatórios nos snapshots de inadimplência: `comp_valor > 1` + `EXISTS (boleto pago)` para excluir clientes novos sem histórico.
