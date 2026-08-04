"""
utils/data.py
Helpers de dados e queries BigQuery para o dashboard Visão de Clientes.
"""
from __future__ import annotations

import json
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from datetime import date
from dateutil.relativedelta import relativedelta
from google.oauth2 import service_account
from google.cloud import bigquery

# ─────────────────────────────────────────────
# PALETA & TEMPLATE
# ─────────────────────────────────────────────
PALETTE = [
    "#6eda2c",  # 0 — verde primário
    "#ffffff",  # 1 — branco
    "#57d124",  # 2 — verde secundário
    "#a0a0a0",  # 3 — cinza médio
    "#4c4c4c",  # 4 — cinza escuro
    "#292929",  # 5 — borda
    "#8ae650",  # 6 — verde claro
    "#3ba811",  # 7 — verde profundo
    "#cccccc",  # 8 — cinza claro
    "#111111",  # 9 — quase preto
]
CHART_TEMPLATE = "plotly_dark"

MODULE_LABELS = {
    "kids":             "Kids",
    "jornada":          "Jornada",
    "loja_inteligente": "Loja Inteligente",
}

MODULE_COLORS = {
    "kids":             "#6eda2c",
    "jornada":          "#ffffff",
    "loja_inteligente": "#a0a0a0",
    "base":             "#4c4c4c",
}

PLAN_LABELS = {
    "pro":     "PRO",
    "lite":    "LITE",
    "starter": "STARTER",
    "basic":   "BASIC",
    "filha":   "FILHA",
    "squad":   "Squad as a Service",
    "outros":  "Outros",
}

PLAN_COLORS = {
    "pro":     "#6eda2c",
    "lite":    "#ffffff",
    "starter": "#a0a0a0",
    "basic":   "#8ae650",
    "filha":   "#4c4c4c",
    "squad":   "#f0a500",
    "outros":  "#292929",
}

# Planos exibidos por padrão no filtro da página de Clientes
DEFAULT_PLAN_FILTER = ["lite", "pro", "basic", "starter"]

# ─────────────────────────────────────────────
# CONSTANTES SQL REUTILIZADAS (mesmo padrão do dashboard Financeiro)
# ─────────────────────────────────────────────

# Família do produto: remove a faixa numérica de membros/igrejas do final do
# nome para casar renovações mesmo com upsell/downsell de tier.
_FAMILIA_PRODUTO = r"REGEXP_REPLACE({col}, r'\s+\d+\s*-.*$', '')"

# Exclusão de linhas de módulo — usado para isolar a mensalidade base
_EXCL_MODULOS = """
    {col} NOT LIKE '%[KIDS]%'
    AND {col} NOT LIKE '%[JORNADA]%'
    AND {col} NOT LIKE '%[LOJAINTELIGENTE]%'
    AND {col} NOT LIKE '%[LOJAINTELIGENTE_INC]%'
    AND {col} NOT LIKE '%[TOTEM]%'
    AND {col} NOT LIKE '%[V_DEOS]%'
    AND NOT ({col} LIKE '%[STARTER]%' AND {col} LIKE '%Módulo%')
"""

# Exclusão de itens que não são mensalidade "de verdade": descontos, abonos,
# intermediação, acordos e reajustes anuais (já embutidos na linha de origem).
# Sem isso, cada "Reajuste Anual" soma MRR extra, além da mensalidade que ajusta.
_EXCL_NAO_MENSALIDADE = """
    {col} NOT LIKE '%Desconto%'
    AND {col} NOT LIKE '%Abono%'
    AND {col} NOT LIKE '%Intermediação%'
    AND {col} NOT LIKE 'Especialista%'
    AND {col} NOT LIKE 'Acordo%'
    AND {col} NOT LIKE 'Reajuste%'
"""

# dt_desativacao_sac só substitui dt_fim_mens na ÚLTIMA geração de contrato do
# cliente (MAX(dt_fim_mens) por st_sincro_sac) — evita retrodatar gerações já
# migradas/renovadas para o mês do churn real.
_DT_FIM_EFETIVO = """
    CASE
      WHEN {fim_col} = {ultima_col} THEN COALESCE({desativ_col}, {fim_col})
      ELSE {fim_col}
    END
"""

_PLAN_CASE = """
    CASE
      WHEN {col} LIKE '%[PRO]%'              THEN 'pro'
      WHEN {col} LIKE '%[LITE]%'             THEN 'lite'
      WHEN {col} LIKE '%[STARTER]%'          THEN 'starter'
      WHEN {col} LIKE '%[FILHA]%'            THEN 'filha'
      WHEN {col} LIKE '%[BASIC]%'            THEN 'basic'
      WHEN {col} LIKE '%0 - 9 Igrejas%'      THEN 'pro'
      WHEN {col} LIKE '%10+ Igrejas%'        THEN 'pro'
      WHEN {col} LIKE '%App Lite%'           THEN 'lite'
      WHEN {col} LIKE '%App da Igreja%'      THEN 'starter'
      WHEN {col} LIKE '%Squad as a Service%' THEN 'squad'
      ELSE 'outros'
    END
"""


# ─────────────────────────────────────────────
# LAYOUT PADRÃO DE GRÁFICOS
# ─────────────────────────────────────────────
def chart_layout(fig: go.Figure, height: int = 380, legend_bottom: bool = False) -> go.Figure:
    legend_cfg = dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(family="Outfit", size=12, color="#a0a0a0"),
    )
    if legend_bottom:
        legend_cfg.update(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5)

    fig.update_layout(
        height=height,
        template=CHART_TEMPLATE,
        margin=dict(l=4, r=4, t=32, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Outfit, sans-serif", color="#ffffff", size=13),
        legend=legend_cfg,
        xaxis=dict(showgrid=True, gridcolor="#292929", gridwidth=1, zeroline=False, title="", type="category"),
        yaxis=dict(showgrid=True, gridcolor="#292929", gridwidth=1, zeroline=False, title=""),
        hoverlabel=dict(bgcolor="#141414", bordercolor="#292929", font_size=13, font_family="Outfit, sans-serif", font_color="#ffffff"),
    )
    return fig


def mes_fmt_ordered(df: pd.DataFrame, date_col: str = "mes") -> tuple[pd.DataFrame, list[str]]:
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col)
    df["mes_fmt"] = df[date_col].dt.strftime("%b/%y").str.capitalize()
    ordered = df["mes_fmt"].drop_duplicates().tolist()
    return df, ordered


def period_selector() -> int:
    with st.sidebar:
        st.markdown("### 🗓️ Período")
        n = st.selectbox(
            "Últimos N meses",
            options=[3, 6, 12, 15, 0],
            index=3,
            format_func=lambda x: "Todos" if x == 0 else f"Últimos {x} meses",
            key=f"period_{st.session_state.get('_page_key', 'default')}",
        )
    return n


def filter_months(df: pd.DataFrame, n_months: int, date_col: str = "mes") -> pd.DataFrame:
    if df.empty or n_months == 0:
        return df
    cutoff = date.today() - relativedelta(months=n_months)
    cutoff_ts = pd.Timestamp(cutoff)
    col = df[date_col]
    if not pd.api.types.is_datetime64_any_dtype(col):
        col = pd.to_datetime(col, errors="coerce")
    return df[col >= cutoff_ts].copy()


def last_val(df: pd.DataFrame, col: str, date_col: str = "mes"):
    if df.empty or col not in df.columns:
        return None
    ordered = df.sort_values(date_col)
    return ordered[col].iloc[-1] if len(ordered) >= 1 else None


def prev_val(df: pd.DataFrame, col: str, date_col: str = "mes"):
    if df.empty or col not in df.columns:
        return None
    ordered = df.sort_values(date_col)
    return ordered[col].iloc[-2] if len(ordered) >= 2 else None


def delta_str(curr, prev, fmt: str = "+,.0f", suffix: str = "") -> str | None:
    if curr is None or prev is None:
        return None
    diff = curr - prev
    try:
        return f"{diff:{fmt}}{suffix}"
    except Exception:
        return f"{diff:+.2f}{suffix}"


def fmt_brl(value, decimals: int = 2) -> str:
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def no_data(label: str = "Dados não disponíveis") -> None:
    st.info(label, icon="ℹ️")


# ─────────────────────────────────────────────
# CONEXÕES BIGQUERY
# ─────────────────────────────────────────────
def _get_bq_client(project_key: str) -> bigquery.Client:
    cfg = st.secrets["connections"][project_key]
    creds_raw = cfg["credentials"]
    creds_dict = json.loads(creds_raw) if isinstance(creds_raw, str) else dict(creds_raw)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/bigquery"],
    )
    return bigquery.Client(project=cfg["project"], credentials=credentials)


@st.cache_resource
def _bq_client_tech() -> bigquery.Client:
    return _get_bq_client("bigquery_tech")


@st.cache_resource
def _bq_client_bi() -> bigquery.Client:
    return _get_bq_client("bigquery_bi")


def _bq_query(query: str, project_key: str = "bigquery_tech") -> pd.DataFrame:
    try:
        client = _bq_client_tech() if project_key == "bigquery_tech" else _bq_client_bi()
        return client.query(query).to_dataframe()
    except Exception as e:
        st.error(f"Erro ao consultar BigQuery ({project_key}): {e}")
        return pd.DataFrame()


# ─────────────────────────────────────────────
# ── PÁGINA 1: CLIENTES (MRR ativo + transacionado) ───
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_mrr_ativo_por_igreja() -> pd.DataFrame:
    """
    MRR ativo hoje por igreja: soma de todas as linhas de mensalidade vigentes
    (dt_fim_mens IS NULL), excluindo Setup, PRO-RATA e as categorias de
    _EXCL_NAO_MENSALIDADE (Desconto/Abono/Intermediação/Especialista/Acordo/
    Reajuste) — mesmo padrão usado no waterfall de MRR (Unit Economics) e nas
    desativações (Financeiro). Sem essa exclusão, "Reajuste Anual" soma como
    MRR extra além da mensalidade que ele ajusta (dupla contagem).
    Plano é classificado a partir da linha de mensalidade base (módulos
    excluídos); se houver mais de uma linha base num mesmo cliente, prevalece
    a de maior valor.
    Retorna: st_sincro_sac, nome_splgc, mrr_ativo, plano.
    """
    query = f"""
    WITH mrr_lines AS (
      SELECT st_sincro_sac, st_nome_sac, valor_total, st_descricao_prd
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE dt_fim_mens IS NULL
        AND st_descricao_prd NOT LIKE '%Setup%'
        AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
        AND {_EXCL_NAO_MENSALIDADE.format(col="st_descricao_prd")}
    ),
    mrr_total AS (
      SELECT
        st_sincro_sac,
        ANY_VALUE(st_nome_sac) AS nome_splgc,
        SUM(valor_total)       AS mrr_ativo
      FROM mrr_lines
      GROUP BY 1
    ),
    plano_base AS (
      SELECT
        st_sincro_sac,
        {_PLAN_CASE.format(col="st_descricao_prd")} AS plano,
        valor_total
      FROM mrr_lines
      WHERE {_EXCL_MODULOS.format(col="st_descricao_prd")}
      QUALIFY ROW_NUMBER() OVER (PARTITION BY st_sincro_sac ORDER BY valor_total DESC) = 1
    )
    SELECT
      t.st_sincro_sac,
      t.nome_splgc,
      t.mrr_ativo,
      COALESCE(p.plano, 'outros') AS plano
    FROM mrr_total t
    LEFT JOIN plano_base p ON t.st_sincro_sac = p.st_sincro_sac
    """
    return _bq_query(query, "bigquery_bi")


@st.cache_data(ttl=3600)
def load_empresas() -> pd.DataFrame:
    """Cadastro de igrejas (BQ_TECH) — id/nome da igreja e da denominação (subgroup)."""
    query = """
    SELECT tertiarygroup_id, tertiarygroup_name, subgroup_id, subgroup_name
    FROM `inchurch-gcp.backend_bi.view_company_list`
    """
    return _bq_query(query, "bigquery_tech")


@st.cache_data(ttl=3600)
def load_transacionado_diario() -> pd.DataFrame:
    """
    TPV diário por igreja, últimos 6 meses (mês atual incluso, ainda que
    parcial). status active/payed, exclui métodos free/external/debit — ver
    bigquery-regras.md. Granularidade diária permite comparar o mês atual
    contra o MESMO período (dia 1 até hoje) do mês anterior.
    Retorna: tertiarygroup_id, dia, transacionado.
    """
    query = """
    SELECT
      tertiarygroup_id,
      CAST(datetime AS DATE) AS dia,
      SUM(value)             AS transacionado
    FROM `inchurch-gcp.backend_bi.view_transaction`
    WHERE status IN ('active', 'payed')
      AND method NOT IN ('free', 'external', 'debit')
      AND CAST(datetime AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 5 MONTH)
    GROUP BY 1, 2
    """
    df = _bq_query(query, "bigquery_tech")
    if not df.empty:
        df["dia"] = pd.to_datetime(df["dia"])
    return df


def _meses_janela_6m() -> list[pd.Timestamp]:
    """Últimos 6 meses (cronológico, mais antigo → mês atual), início de cada mês."""
    inicio_mes_atual = pd.Timestamp.today().normalize().replace(day=1)
    return [inicio_mes_atual - pd.DateOffset(months=i) for i in range(5, -1, -1)]


def _build_trend_mensal(ids: pd.Series, df_tpv_diario: pd.DataFrame) -> pd.DataFrame:
    """
    Para cada tertiarygroup_id em `ids`, monta a série dos últimos 6 meses de
    transacionado (preenchendo com 0 onde não há transação), o valor nominal
    do mês atual (soma de todos os dias já ocorridos) e a variação % contra o
    MESMO período do mês anterior — dia 1 até o dia de hoje em ambos os meses,
    não o mês anterior completo. Isso evita comparar um mês atual parcial
    (ex: só 4 dias) contra um mês anterior fechado (30 dias), o que sempre
    daria uma "queda" artificial no início do mês.
    Retorna: tertiarygroup_id, transacionado_trend (list[float]),
             transacionado_mes_atual, transacionado_variacao_mom (% ou None).
    """
    meses = _meses_janela_6m()
    mes_atual_ts = meses[-1]
    mes_anterior_ts = meses[-2]
    dia_do_mes = pd.Timestamp.today().day

    base = pd.DataFrame({"tertiarygroup_id": pd.unique(ids)})
    base["tertiarygroup_id"] = base["tertiarygroup_id"].astype("Int64")
    base_idx = base["tertiarygroup_id"]

    if df_tpv_diario.empty:
        pivot = pd.DataFrame(0.0, index=base_idx, columns=meses)
        mtd_atual = pd.Series(0.0, index=base_idx)
        mtd_anterior_mesmo_periodo = pd.Series(0.0, index=base_idx)
    else:
        df_tpv_diario = df_tpv_diario.copy()
        df_tpv_diario["tertiarygroup_id"] = df_tpv_diario["tertiarygroup_id"].astype("Int64")
        df_tpv_diario["mes"] = df_tpv_diario["dia"].dt.to_period("M").dt.to_timestamp()

        pivot = df_tpv_diario.pivot_table(
            index="tertiarygroup_id", columns="mes", values="transacionado",
            aggfunc="sum", fill_value=0.0,
        )
        pivot = pivot.reindex(index=base_idx, fill_value=0.0)
        for m in meses:
            if m not in pivot.columns:
                pivot[m] = 0.0
        pivot = pivot[meses]

        mtd_atual = (
            df_tpv_diario[(df_tpv_diario["mes"] == mes_atual_ts) & (df_tpv_diario["dia"].dt.day <= dia_do_mes)]
            .groupby("tertiarygroup_id")["transacionado"].sum()
            .reindex(base_idx, fill_value=0.0)
        )
        mtd_anterior_mesmo_periodo = (
            df_tpv_diario[(df_tpv_diario["mes"] == mes_anterior_ts) & (df_tpv_diario["dia"].dt.day <= dia_do_mes)]
            .groupby("tertiarygroup_id")["transacionado"].sum()
            .reindex(base_idx, fill_value=0.0)
        )

    variacao = (
        (mtd_atual - mtd_anterior_mesmo_periodo)
        / mtd_anterior_mesmo_periodo.where(mtd_anterior_mesmo_periodo > 0) * 100
    ).round(1)

    return pd.DataFrame({
        "tertiarygroup_id":            pivot.index,
        "transacionado_trend":         pivot.values.tolist(),
        "transacionado_mes_atual":     pivot[mes_atual_ts].values,
        "transacionado_variacao_mom":  variacao.values,
    })


def _format_nome_igreja(row) -> str:
    """
    "[subgroup_id] subgroup_name - (tertiarygroup_id) tertiarygroup_name" quando
    há match em view_company_list (BQ_TECH). Sem esse match, cai para o nome do
    Superlógica e, na ausência dele, para o próprio st_sincro_sac.
    """
    tert_name = row.get("tertiarygroup_name")
    if pd.notna(tert_name) and str(tert_name).strip():
        tert_id = row.get("tertiarygroup_id")
        tert_part = f"({int(tert_id)}) {tert_name}" if pd.notna(tert_id) else str(tert_name)

        sub_id = row.get("subgroup_id")
        sub_name = row.get("subgroup_name")
        if pd.notna(sub_id) and pd.notna(sub_name) and str(sub_name).strip():
            return f"[{int(sub_id)}] {sub_name} - {tert_part}"
        return tert_part

    nome_splgc = row.get("nome_splgc")
    if pd.notna(nome_splgc) and str(nome_splgc).strip():
        return nome_splgc
    return row.get("st_sincro_sac")


@st.cache_data(ttl=3600)
def load_visao_clientes() -> pd.DataFrame:
    """
    Junta MRR ativo (BQ_BI) com cadastro oficial (BQ_TECH) e a série diária de
    transacionado dos últimos 6 meses (BQ_TECH). Escopo: apenas igrejas com
    MRR ativo hoje (join cross-project feito em pandas, convertendo
    tertiarygroup_id para string — ver bigquery-conexoes.md).
    Retorna: tertiarygroup_id, tertiarygroup_name, plano, mrr_ativo,
             transacionado_trend, transacionado_mes_atual, transacionado_variacao_mom.
    """
    df_mrr = load_mrr_ativo_por_igreja()
    if df_mrr.empty:
        return pd.DataFrame()

    df_emp = load_empresas()
    df_tpv = load_transacionado_diario()

    df_mrr = df_mrr.copy()
    df_mrr["st_sincro_sac"] = df_mrr["st_sincro_sac"].astype(str)

    if not df_emp.empty:
        df_emp = df_emp.copy()
        df_emp["tertiarygroup_id"] = df_emp["tertiarygroup_id"].astype("Int64")
        df_emp["_id_str"] = df_emp["tertiarygroup_id"].astype(str)
    else:
        df_emp = pd.DataFrame(columns=["tertiarygroup_id", "tertiarygroup_name", "subgroup_id", "subgroup_name", "_id_str"])

    df = df_mrr.merge(df_emp, left_on="st_sincro_sac", right_on="_id_str", how="left")

    # tertiarygroup_id: usa o do BQ_TECH quando existe; senão, deriva do próprio st_sincro_sac
    id_from_bi = pd.to_numeric(df["st_sincro_sac"], errors="coerce")
    df["tertiarygroup_id"] = df["tertiarygroup_id"].fillna(id_from_bi).astype("Int64")

    # nome: "[subgroup_id] subgroup_name - (tertiarygroup_id) tertiarygroup_name"
    df["tertiarygroup_name"] = df.apply(_format_nome_igreja, axis=1)

    try:
        trend_df = _build_trend_mensal(df["tertiarygroup_id"], df_tpv)
        df = df.merge(trend_df, on="tertiarygroup_id", how="left")
    except Exception as e:
        # Nunca deixa a tabela de clientes cair por causa da série de transacionado —
        # pior caso: mostra 0/— nessas colunas, mas MRR e cadastro continuam de pé.
        st.warning(f"Não foi possível calcular o transacionado mensal: {e}")

    # Garante que as 3 colunas de transacionado sempre existem no retorno, com
    # fallback seguro — protege contra qualquer falha upstream (conexão BQ_TECH
    # fora do ar, dado inesperado etc.) que impediria o merge acima de rodar.
    if "transacionado_trend" not in df.columns:
        df["transacionado_trend"] = [[0.0] * 6] * len(df)
    else:
        df["transacionado_trend"] = df["transacionado_trend"].apply(
            lambda v: v if isinstance(v, list) else [0.0] * 6
        )
    if "transacionado_mes_atual" not in df.columns:
        df["transacionado_mes_atual"] = 0.0
    else:
        df["transacionado_mes_atual"] = df["transacionado_mes_atual"].fillna(0.0)
    if "transacionado_variacao_mom" not in df.columns:
        df["transacionado_variacao_mom"] = None

    return (
        df[[
            "tertiarygroup_id", "tertiarygroup_name", "plano", "mrr_ativo",
            "transacionado_trend", "transacionado_mes_atual", "transacionado_variacao_mom",
        ]]
        .sort_values("mrr_ativo", ascending=False)
        .reset_index(drop=True)
    )


# ─────────────────────────────────────────────
# ── PÁGINA 2: DESATIVAÇÕES (portado do dashboard Financeiro) ───
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_desativacoes_mensais() -> pd.DataFrame:
    """
    MRR perdido e clientes desativados por módulo por mês (últimos 15 meses).
    Critério de desativação: dt_fim_mens IS NOT NULL.
    dt_desativacao_sac só substitui dt_fim_mens na última geração de contrato do
    cliente — gerações anteriores já migradas/renovadas mantêm sua própria data.
    Exclusão de renovações: casa por família de produto (ignora a faixa numérica
    de membros/igrejas), cobrindo upsell/downsell de tier, não só o mesmo nome exato.
    Módulos identificados via st_descricao_prd; demais itens classificados como 'base'.
    """
    query = f"""
    WITH mrr_base AS (
      SELECT
        st_sincro_sac,
        st_descricao_prd,
        CAST(dt_fim_mens AS DATE)        AS dt_fim_mens,
        CAST(dt_desativacao_sac AS DATE) AS dt_desativacao_sac,
        valor_total,
        MAX(CAST(dt_fim_mens AS DATE)) OVER (PARTITION BY st_sincro_sac) AS ultima_dt_fim_cliente
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE dt_fim_mens IS NOT NULL
        AND st_descricao_prd NOT LIKE '%Setup%'
        AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
    ),
    desativados AS (
      SELECT
        st_sincro_sac,
        st_descricao_prd,
        {_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")} AS dt_fim,
        DATE_TRUNC({_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")}, MONTH) AS mes,
        valor_total
      FROM mrr_base
      WHERE valor_total > 0
        AND st_descricao_prd NOT LIKE '%Desconto%'
        AND st_descricao_prd NOT LIKE '%Abono%'
        AND st_descricao_prd NOT LIKE '%Intermediação%'
        AND st_descricao_prd NOT LIKE 'Especialista%'
        AND st_descricao_prd NOT LIKE 'Acordo%'
        AND st_descricao_prd NOT LIKE 'Reajuste%'
        AND {_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")} >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
        AND {_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")} <= LAST_DAY(CURRENT_DATE())
      UNION ALL
      -- Clientes com dt_desativacao_sac preenchida mas sem dt_fim_mens nos produtos
      SELECT
        m.st_sincro_sac,
        m.st_descricao_prd,
        CAST(c.dt_desativacao_sac AS DATE)                           AS dt_fim,
        DATE_TRUNC(CAST(c.dt_desativacao_sac AS DATE), MONTH)        AS mes,
        m.valor_total
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` m
      INNER JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
        ON m.st_sincro_sac = c.st_sincro_sac
      WHERE m.dt_fim_mens IS NULL
        AND c.dt_desativacao_sac IS NOT NULL
        AND CAST(c.dt_desativacao_sac AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
        AND CAST(c.dt_desativacao_sac AS DATE) <= LAST_DAY(CURRENT_DATE())
        AND m.st_descricao_prd NOT LIKE '%Setup%'
        AND m.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
        AND m.valor_total > 0
        AND m.st_descricao_prd NOT LIKE '%Desconto%'
        AND m.st_descricao_prd NOT LIKE '%Abono%'
        AND m.st_descricao_prd NOT LIKE '%Intermediação%'
        AND m.st_descricao_prd NOT LIKE 'Especialista%'
        AND m.st_descricao_prd NOT LIKE 'Acordo%'
        AND m.st_descricao_prd NOT LIKE 'Reajuste%'
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY m.st_sincro_sac, m.st_descricao_prd
        ORDER BY m.dt_inicio_mens DESC
      ) = 1
    ),
    renovacoes AS (
      -- (cliente, família de produto) com dt_fim no último dia do mês
      -- e um novo dt_inicio_mens no mês seguinte → renovação, não desativação.
      -- Restrição de cardinalidade 1:1 evita casar em massa clientes com vários
      -- produtos simultâneos da mesma família (ex: denominação com várias igrejas
      -- filhas, cada uma com sua própria faixa de membros).
      SELECT DISTINCT
        d.st_sincro_sac,
        d.st_descricao_prd,
        d.mes
      FROM desativados d
      INNER JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` r
        ON  d.st_sincro_sac = r.st_sincro_sac
        AND {_FAMILIA_PRODUTO.format(col="d.st_descricao_prd")} = {_FAMILIA_PRODUTO.format(col="r.st_descricao_prd")}
        AND DATE_TRUNC(CAST(r.dt_inicio_mens AS DATE), MONTH) = DATE_ADD(d.mes, INTERVAL 1 MONTH)
      WHERE d.dt_fim = LAST_DAY(d.dt_fim)
        AND r.dt_inicio_mens IS NOT NULL
      QUALIFY COUNT(DISTINCT d.st_descricao_prd) OVER (PARTITION BY d.st_sincro_sac, {_FAMILIA_PRODUTO.format(col="d.st_descricao_prd")}, d.mes) = 1
           AND COUNT(DISTINCT r.st_descricao_prd) OVER (PARTITION BY d.st_sincro_sac, {_FAMILIA_PRODUTO.format(col="d.st_descricao_prd")}, d.mes) = 1
    )
    SELECT
      d.mes,
      CASE
        WHEN d.st_descricao_prd LIKE '%[KIDS]%'                THEN 'kids'
        WHEN d.st_descricao_prd LIKE '%[JORNADA]%'             THEN 'jornada'
        WHEN d.st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'     THEN 'loja_inteligente'
        ELSE                                                         'base'
      END                                                       AS modulo,
      COUNT(DISTINCT d.st_sincro_sac)                           AS clientes_desativados,
      SUM(d.valor_total)                                        AS mrr_perdido
    FROM desativados d
    LEFT JOIN renovacoes rv
      ON  d.st_sincro_sac    = rv.st_sincro_sac
      AND d.st_descricao_prd = rv.st_descricao_prd
      AND d.mes              = rv.mes
    WHERE rv.st_sincro_sac IS NULL
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"]    = pd.to_datetime(df["mes"])
        df["modulo"] = df["modulo"].str.lower()
    return df


@st.cache_data(ttl=3600)
def load_desativacoes_total_parcial() -> pd.DataFrame:
    """
    Desativações por mês classificadas em Total (cliente sem nenhum produto de
    mensalidade ativo restante) e Parcial (cliente ainda tem ao menos 1 produto
    ativo). Mesma base 'desativados' de load_desativacoes_mensais (sem exclusão
    de módulos), mas colapsada por cliente/mês (não por produto/módulo) e
    cruzada com a base ativa atual (dt_fim_mens IS NULL) em vw-splgc-tabela_mrr_validos.
    """
    query = f"""
    WITH mrr_base AS (
      SELECT
        st_sincro_sac,
        st_descricao_prd,
        CAST(dt_fim_mens AS DATE)        AS dt_fim_mens,
        CAST(dt_desativacao_sac AS DATE) AS dt_desativacao_sac,
        valor_total,
        MAX(CAST(dt_fim_mens AS DATE)) OVER (PARTITION BY st_sincro_sac) AS ultima_dt_fim_cliente
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE dt_fim_mens IS NOT NULL
        AND st_descricao_prd NOT LIKE '%Setup%'
        AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
    ),
    desativados AS (
      SELECT
        st_sincro_sac,
        st_descricao_prd,
        {_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")} AS dt_fim,
        DATE_TRUNC({_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")}, MONTH) AS mes,
        valor_total
      FROM mrr_base
      WHERE valor_total > 0
        AND {_EXCL_NAO_MENSALIDADE.format(col="st_descricao_prd")}
        AND {_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")} >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
        AND {_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")} <= LAST_DAY(CURRENT_DATE())
      UNION ALL
      -- Clientes com dt_desativacao_sac preenchida mas sem dt_fim_mens nos produtos
      SELECT
        m.st_sincro_sac,
        m.st_descricao_prd,
        CAST(c.dt_desativacao_sac AS DATE)                           AS dt_fim,
        DATE_TRUNC(CAST(c.dt_desativacao_sac AS DATE), MONTH)        AS mes,
        m.valor_total
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` m
      INNER JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
        ON m.st_sincro_sac = c.st_sincro_sac
      WHERE m.dt_fim_mens IS NULL
        AND c.dt_desativacao_sac IS NOT NULL
        AND CAST(c.dt_desativacao_sac AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
        AND CAST(c.dt_desativacao_sac AS DATE) <= LAST_DAY(CURRENT_DATE())
        AND m.st_descricao_prd NOT LIKE '%Setup%'
        AND m.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
        AND m.valor_total > 0
        AND {_EXCL_NAO_MENSALIDADE.format(col="m.st_descricao_prd")}
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY m.st_sincro_sac, m.st_descricao_prd
        ORDER BY m.dt_inicio_mens DESC
      ) = 1
    ),
    renovacoes AS (
      SELECT DISTINCT
        d.st_sincro_sac,
        d.st_descricao_prd,
        d.mes
      FROM desativados d
      INNER JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` r
        ON  d.st_sincro_sac = r.st_sincro_sac
        AND {_FAMILIA_PRODUTO.format(col="d.st_descricao_prd")} = {_FAMILIA_PRODUTO.format(col="r.st_descricao_prd")}
        AND DATE_TRUNC(CAST(r.dt_inicio_mens AS DATE), MONTH) = DATE_ADD(d.mes, INTERVAL 1 MONTH)
      WHERE d.dt_fim = LAST_DAY(d.dt_fim)
        AND r.dt_inicio_mens IS NOT NULL
      QUALIFY COUNT(DISTINCT d.st_descricao_prd) OVER (PARTITION BY d.st_sincro_sac, {_FAMILIA_PRODUTO.format(col="d.st_descricao_prd")}, d.mes) = 1
           AND COUNT(DISTINCT r.st_descricao_prd) OVER (PARTITION BY d.st_sincro_sac, {_FAMILIA_PRODUTO.format(col="d.st_descricao_prd")}, d.mes) = 1
    ),
    desativados_cliente AS (
      -- 1 linha por cliente/mês — colapsa múltiplos produtos desativados no mesmo mês
      SELECT DISTINCT d.st_sincro_sac, d.mes
      FROM desativados d
      LEFT JOIN renovacoes rv
        ON  d.st_sincro_sac    = rv.st_sincro_sac
        AND d.st_descricao_prd = rv.st_descricao_prd
        AND d.mes              = rv.mes
      WHERE rv.st_sincro_sac IS NULL
    ),
    ativos_atuais AS (
      -- Clientes com pelo menos 1 produto de mensalidade ainda ativo hoje
      SELECT DISTINCT st_sincro_sac
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE dt_fim_mens IS NULL
        AND valor_total > 0
        AND {_EXCL_NAO_MENSALIDADE.format(col="st_descricao_prd")}
    )
    SELECT
      dc.mes,
      CASE WHEN a.st_sincro_sac IS NULL THEN 'total' ELSE 'parcial' END AS tipo,
      COUNT(DISTINCT dc.st_sincro_sac) AS clientes_desativados
    FROM desativados_cliente dc
    LEFT JOIN ativos_atuais a ON dc.st_sincro_sac = a.st_sincro_sac
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"] = pd.to_datetime(df["mes"])
    return df


@st.cache_data(ttl=3600)
def load_desativacoes_por_plano() -> pd.DataFrame:
    """
    Desativações de PLANO BASE por mês (exclui módulos).
    dt_desativacao_sac só substitui dt_fim_mens na última geração de contrato do
    cliente; exclusão de renovações casa por família de produto (não nome exato) —
    ver load_desativacoes_mensais para detalhe da lógica.
    """
    query = f"""
    WITH mrr_base AS (
      SELECT
        st_sincro_sac,
        st_descricao_prd,
        CAST(dt_fim_mens AS DATE)        AS dt_fim_mens,
        CAST(dt_desativacao_sac AS DATE) AS dt_desativacao_sac,
        valor_total,
        MAX(CAST(dt_fim_mens AS DATE)) OVER (PARTITION BY st_sincro_sac) AS ultima_dt_fim_cliente
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE dt_fim_mens IS NOT NULL
        AND st_descricao_prd NOT LIKE '%Setup%'
        AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
    ),
    desativados AS (
      SELECT
        st_sincro_sac,
        st_descricao_prd,
        {_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")} AS dt_fim,
        DATE_TRUNC({_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")}, MONTH) AS mes,
        valor_total
      FROM mrr_base
      WHERE {_EXCL_MODULOS.format(col="st_descricao_prd")}
        AND valor_total > 0
        AND {_EXCL_NAO_MENSALIDADE.format(col="st_descricao_prd")}
        AND {_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")} >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
        AND {_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")} <= LAST_DAY(CURRENT_DATE())
      UNION ALL
      -- Clientes com dt_desativacao_sac preenchida mas sem dt_fim_mens nos produtos
      SELECT
        m.st_sincro_sac,
        m.st_descricao_prd,
        CAST(c.dt_desativacao_sac AS DATE)                           AS dt_fim,
        DATE_TRUNC(CAST(c.dt_desativacao_sac AS DATE), MONTH)        AS mes,
        m.valor_total
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` m
      INNER JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
        ON m.st_sincro_sac = c.st_sincro_sac
      WHERE m.dt_fim_mens IS NULL
        AND c.dt_desativacao_sac IS NOT NULL
        AND CAST(c.dt_desativacao_sac AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
        AND CAST(c.dt_desativacao_sac AS DATE) <= LAST_DAY(CURRENT_DATE())
        AND m.st_descricao_prd NOT LIKE '%Setup%'
        AND m.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
        AND {_EXCL_MODULOS.format(col="m.st_descricao_prd")}
        AND m.valor_total > 0
        AND {_EXCL_NAO_MENSALIDADE.format(col="m.st_descricao_prd")}
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY m.st_sincro_sac, m.st_descricao_prd
        ORDER BY m.dt_inicio_mens DESC
      ) = 1
    ),
    renovacoes AS (
      -- Restrição de cardinalidade 1:1 evita casar em massa clientes com vários
      -- produtos simultâneos da mesma família (ex: denominação com várias igrejas
      -- filhas, cada uma com sua própria faixa de membros).
      SELECT DISTINCT d.st_sincro_sac, d.st_descricao_prd, d.mes
      FROM desativados d
      INNER JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` r
        ON  d.st_sincro_sac = r.st_sincro_sac
        AND {_FAMILIA_PRODUTO.format(col="d.st_descricao_prd")} = {_FAMILIA_PRODUTO.format(col="r.st_descricao_prd")}
        AND DATE_TRUNC(CAST(r.dt_inicio_mens AS DATE), MONTH) = DATE_ADD(d.mes, INTERVAL 1 MONTH)
      WHERE d.dt_fim = LAST_DAY(d.dt_fim)
        AND r.dt_inicio_mens IS NOT NULL
      QUALIFY COUNT(DISTINCT d.st_descricao_prd) OVER (PARTITION BY d.st_sincro_sac, {_FAMILIA_PRODUTO.format(col="d.st_descricao_prd")}, d.mes) = 1
           AND COUNT(DISTINCT r.st_descricao_prd) OVER (PARTITION BY d.st_sincro_sac, {_FAMILIA_PRODUTO.format(col="d.st_descricao_prd")}, d.mes) = 1
    )
    SELECT
      d.mes,
      {_PLAN_CASE.format(col="d.st_descricao_prd")}                  AS plano,
      COUNT(DISTINCT d.st_sincro_sac)                                 AS clientes_desativados,
      SUM(d.valor_total)                                              AS mrr_perdido
    FROM desativados d
    LEFT JOIN renovacoes rv
      ON  d.st_sincro_sac    = rv.st_sincro_sac
      AND d.st_descricao_prd = rv.st_descricao_prd
      AND d.mes              = rv.mes
    WHERE rv.st_sincro_sac IS NULL
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"]   = pd.to_datetime(df["mes"])
        df["plano"] = df["plano"].str.lower()
    return df


@st.cache_data(ttl=3600)
def load_desativacoes_detalhado() -> pd.DataFrame:
    """
    Desativações no nível de cliente — mês, módulo, plano, nome e MRR perdido.
    dt_desativacao_sac só substitui dt_fim_mens na última geração de contrato do
    cliente; exclusão de renovações casa por família de produto (não nome exato) —
    ver load_desativacoes_mensais para detalhe da lógica.
    Join com splgc-clientes-inchurch para obter o nome do cliente.
    """
    query = f"""
    WITH mrr_base AS (
      SELECT
        m.st_sincro_sac,
        m.st_descricao_prd,
        CAST(m.dt_fim_mens AS DATE)        AS dt_fim_mens,
        CAST(m.dt_desativacao_sac AS DATE) AS dt_desativacao_sac,
        m.valor_total,
        MAX(CAST(m.dt_fim_mens AS DATE)) OVER (PARTITION BY m.st_sincro_sac) AS ultima_dt_fim_cliente
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` m
      WHERE m.dt_fim_mens IS NOT NULL
        AND m.st_descricao_prd NOT LIKE '%Setup%'
        AND m.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
    ),
    desativados AS (
      SELECT
        st_sincro_sac,
        st_descricao_prd,
        {_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")} AS dt_fim,
        DATE_TRUNC({_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")}, MONTH) AS mes,
        valor_total
      FROM mrr_base
      WHERE valor_total > 0
        AND {_EXCL_NAO_MENSALIDADE.format(col="st_descricao_prd")}
        AND {_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")} >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
        AND {_DT_FIM_EFETIVO.format(fim_col="dt_fim_mens", ultima_col="ultima_dt_fim_cliente", desativ_col="dt_desativacao_sac")} <= LAST_DAY(CURRENT_DATE())
      UNION ALL
      -- Clientes com dt_desativacao_sac preenchida mas sem dt_fim_mens nos produtos
      SELECT
        m.st_sincro_sac,
        m.st_descricao_prd,
        CAST(c.dt_desativacao_sac AS DATE)                       AS dt_fim,
        DATE_TRUNC(CAST(c.dt_desativacao_sac AS DATE), MONTH)    AS mes,
        m.valor_total
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` m
      INNER JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
        ON m.st_sincro_sac = c.st_sincro_sac
      WHERE m.dt_fim_mens IS NULL
        AND c.dt_desativacao_sac IS NOT NULL
        AND CAST(c.dt_desativacao_sac AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
        AND CAST(c.dt_desativacao_sac AS DATE) <= LAST_DAY(CURRENT_DATE())
        AND m.st_descricao_prd NOT LIKE '%Setup%'
        AND m.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
        AND m.valor_total > 0
        AND {_EXCL_NAO_MENSALIDADE.format(col="m.st_descricao_prd")}
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY m.st_sincro_sac, m.st_descricao_prd
        ORDER BY m.dt_inicio_mens DESC
      ) = 1
    ),
    renovacoes AS (
      -- Restrição de cardinalidade 1:1 evita casar em massa clientes com vários
      -- produtos simultâneos da mesma família (ex: denominação com várias igrejas
      -- filhas, cada uma com sua própria faixa de membros).
      SELECT DISTINCT d.st_sincro_sac, d.st_descricao_prd, d.mes
      FROM desativados d
      INNER JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` r
        ON  d.st_sincro_sac = r.st_sincro_sac
        AND {_FAMILIA_PRODUTO.format(col="d.st_descricao_prd")} = {_FAMILIA_PRODUTO.format(col="r.st_descricao_prd")}
        AND DATE_TRUNC(CAST(r.dt_inicio_mens AS DATE), MONTH) = DATE_ADD(d.mes, INTERVAL 1 MONTH)
      WHERE d.dt_fim = LAST_DAY(d.dt_fim)
        AND r.dt_inicio_mens IS NOT NULL
      QUALIFY COUNT(DISTINCT d.st_descricao_prd) OVER (PARTITION BY d.st_sincro_sac, {_FAMILIA_PRODUTO.format(col="d.st_descricao_prd")}, d.mes) = 1
           AND COUNT(DISTINCT r.st_descricao_prd) OVER (PARTITION BY d.st_sincro_sac, {_FAMILIA_PRODUTO.format(col="d.st_descricao_prd")}, d.mes) = 1
    )
    SELECT
      d.mes,
      CASE
        WHEN d.st_descricao_prd LIKE '%[KIDS]%'                THEN 'Kids'
        WHEN d.st_descricao_prd LIKE '%[JORNADA]%'             THEN 'Jornada'
        WHEN d.st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'     THEN 'Loja Inteligente'
        WHEN d.st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%' THEN 'Loja Inteligente'
        ELSE                                                        'Base'
      END                                                       AS modulo,
      {_PLAN_CASE.format(col="d.st_descricao_prd")}            AS plano,
      d.st_sincro_sac,
      COALESCE(c.st_nome_sac, d.st_sincro_sac)                 AS nome_cliente,
      d.st_descricao_prd                                        AS produto,
      d.valor_total                                             AS mrr_perdido
    FROM desativados d
    LEFT JOIN renovacoes rv
      ON  d.st_sincro_sac    = rv.st_sincro_sac
      AND d.st_descricao_prd = rv.st_descricao_prd
      AND d.mes              = rv.mes
    LEFT JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
      ON d.st_sincro_sac = c.st_sincro_sac
    WHERE rv.st_sincro_sac IS NULL
    ORDER BY d.mes DESC, d.valor_total DESC
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"]    = pd.to_datetime(df["mes"])
        df["modulo"] = df["modulo"].str.lower()
        df["plano"]  = df["plano"].str.lower()
    return df


@st.cache_data(ttl=3600)
def load_base_ativa_por_plano() -> pd.DataFrame:
    """
    Clientes ativos por PLANO BASE no início de cada mês (últimos 15 meses).
    Usado como denominador para cálculo de churn: item ativo se
    dt_inicio_mens <= primeiro dia do mês E (dt_fim_mens IS NULL OR dt_fim_mens > primeiro dia do mês).
    Exclui módulos para contar apenas o plano base de cada cliente.
    """
    query = f"""
    SELECT
      cal.mes,
      {_PLAN_CASE.format(col="mrr.st_descricao_prd")}                AS plano,
      COUNT(DISTINCT mrr.st_sincro_sac)                               AS clientes_ativos
    FROM (
      SELECT mes
      FROM UNNEST(GENERATE_DATE_ARRAY(
        DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH),
        DATE_TRUNC(CURRENT_DATE(), MONTH),
        INTERVAL 1 MONTH
      )) AS mes
    ) cal
    CROSS JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` mrr
    WHERE CAST(mrr.dt_inicio_mens AS DATE) <= cal.mes
      AND (mrr.dt_fim_mens IS NULL OR CAST(mrr.dt_fim_mens AS DATE) > cal.mes)
      AND {_EXCL_MODULOS.format(col="mrr.st_descricao_prd")}
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"]   = pd.to_datetime(df["mes"])
        df["plano"] = df["plano"].str.lower()
    return df
