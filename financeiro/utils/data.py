"""
utils/data.py
Helpers de dados, cache, paleta de cores e layout de gráficos.
"""
from __future__ import annotations

import json
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import numpy as np
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

# Filtro SQL para excluir linhas de módulos (KIDS, JORNADA, LOJA, TOTEM, VÍDEOS, módulos STARTER)
# Usar substituindo {col} pelo nome da coluna adequado na query
_EXCL_MODULOS = """
    {col} NOT LIKE '%[KIDS]%'
    AND {col} NOT LIKE '%[JORNADA]%'
    AND {col} NOT LIKE '%[LOJAINTELIGENTE]%'
    AND {col} NOT LIKE '%[LOJAINTELIGENTE_INC]%'
    AND {col} NOT LIKE '%[TOTEM]%'
    AND {col} NOT LIKE '%[V_DEOS]%'
    AND NOT ({col} LIKE '%[STARTER]%' AND {col} LIKE '%Módulo%')
"""

# Filtro para excluir itens que não são mensalidade 1.2.2:
# descontos, abonos, intermediação, acordos e reajustes anuais.
# A vw-splgc-tabela_mrr_validos não expõe comp_st_conta_cont, então filtramos por nome.
_EXCL_NAO_MENSALIDADE = """
    {col} NOT LIKE '%Desconto%'
    AND {col} NOT LIKE '%Abono%'
    AND {col} NOT LIKE '%Intermediação%'
    AND {col} NOT LIKE 'Especialista%'
    AND {col} NOT LIKE 'Acordo%'
    AND {col} NOT LIKE 'Reajuste%'
"""

# dt_desativacao_sac só substitui dt_fim_mens na ÚLTIMA geração de contrato do
# cliente (MAX(dt_fim_mens) por st_sincro_sac). Sem isso, o churn financeiro do
# cliente é aplicado retroativamente a gerações de contrato já migradas/renovadas,
# empurrando-as para o mesmo mês da baixa real (caso id_sacado 171 / jul-2026).
_DT_FIM_EFETIVO = """
    CASE
      WHEN {fim_col} = {ultima_col} THEN COALESCE({desativ_col}, {fim_col})
      ELSE {fim_col}
    END
"""

# Família do produto: remove a faixa numérica de membros/igrejas do final do
# nome para casar renovações mesmo com upsell/downsell de tier (caso id_sacado 3846).
_FAMILIA_PRODUTO = r"REGEXP_REPLACE({col}, r'\s+\d+\s*-.*$', '')"

# CASE SQL para classificar plano base (usar substituindo {col})
_PLAN_CASE = """
    CASE
      WHEN {col} LIKE '%[PRO]%'          THEN 'pro'
      WHEN {col} LIKE '%[LITE]%'         THEN 'lite'
      WHEN {col} LIKE '%[STARTER]%'      THEN 'starter'
      WHEN {col} LIKE '%[FILHA]%'        THEN 'filha'
      WHEN {col} LIKE '%[BASIC]%'        THEN 'basic'
      WHEN {col} LIKE '%0 - 9 Igrejas%'  THEN 'pro'
      WHEN {col} LIKE '%10+ Igrejas%'    THEN 'pro'
      WHEN {col} LIKE '%App Lite%'        THEN 'lite'
      WHEN {col} LIKE '%App da Igreja%'   THEN 'starter'
      WHEN {col} LIKE '%Squad as a Service%' THEN 'squad'
      ELSE 'outros'
    END
"""

# ─────────────────────────────────────────────
# BRANCH 3 — cliente desativado SEM NENHUMA linha em vw-splgc-tabela_mrr_validos
# (nem com dt_fim_mens IS NULL) cuja ÚNICA liquidação paga > 0 não é mensalidade
# (Setup/Adesão/etc). Valor vem de `vw-splgc-tabela_mrr_e_descricao` (view sobre a
# tabela NÃO filtrada `splgc-tabela_mrr` que já traz st_descricao_prd real — inclui
# MRR nunca liquidado). Sem isso o cliente some do churn inteiro — bug descoberto
# ago/2026 (caso ADEPI, 102 clientes afetados). Ver churn-desativacoes.md no vault
# Obsidian para o diagnóstico completo e a regra de negócio.
# ─────────────────────────────────────────────
_EXCL_LIQUIDACAO_NAO_MENSALIDADE = """
    (   liq.comp_st_descricao_prd LIKE '%Setup%'
     OR liq.comp_st_descricao_prd LIKE '%[PRO-RATA]%'
     OR liq.comp_st_descricao_prd LIKE '%Desconto%'
     OR liq.comp_st_descricao_prd LIKE '%Abono%'
     OR liq.comp_st_descricao_prd LIKE '%Intermedia%'
     OR liq.comp_st_descricao_prd LIKE 'Especialista%'
     OR liq.comp_st_descricao_prd LIKE 'Acordo%'
     OR liq.comp_st_descricao_prd LIKE 'Reajuste%'
     OR liq.comp_st_descricao_prd LIKE '%Multa%'
     OR liq.comp_st_descricao_prd LIKE '%Ades%'
     OR liq.comp_st_descricao_prd LIKE '%Juros%'
     OR liq.comp_st_descricao_prd LIKE '%Taxa banc%'
     OR liq.comp_st_descricao_prd LIKE 'PLANO MENSAL'
    )
"""

_BRANCH3_LIQUIDACAO_UNICA = """
      UNION ALL
      -- Clientes desativados SEM NENHUMA linha em vw-splgc-tabela_mrr_validos cuja
      -- UNICA liquidacao paga > 0 nao e mensalidade (Setup/Adesao) -- valor vem de
      -- vw-splgc-tabela_mrr_e_descricao (nao filtrada). Ver churn-desativacoes.md
      -- (vault, ago/2026).
      SELECT
        mrr.st_sincro_sac,
        mrr.st_descricao_prd,
        CAST(c.dt_desativacao_sac AS DATE)                    AS dt_fim,
        DATE_TRUNC(CAST(c.dt_desativacao_sac AS DATE), MONTH) AS mes,
        mrr.valor_total
      FROM `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
      INNER JOIN (
        SELECT
          st_sincro_sac, st_descricao_prd, valor_total,
          COALESCE(CAST(dt_fim_mens AS DATE), DATE '9999-12-31') AS fim_efetivo,
          MAX(COALESCE(CAST(dt_fim_mens AS DATE), DATE '9999-12-31'))
            OVER (PARTITION BY st_sincro_sac) AS max_fim
        FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_e_descricao`
        WHERE valor_total > 0
          AND st_descricao_prd NOT LIKE '%Setup%'
          AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
          AND st_descricao_prd NOT LIKE '%Desconto%'
          AND st_descricao_prd NOT LIKE '%Abono%'
          AND st_descricao_prd NOT LIKE '%Intermedia%'
          AND st_descricao_prd NOT LIKE 'Especialista%'
          AND st_descricao_prd NOT LIKE 'Acordo%'
          AND st_descricao_prd NOT LIKE 'Reajuste%'
      ) mrr
        ON mrr.st_sincro_sac = c.st_sincro_sac AND mrr.fim_efetivo = mrr.max_fim
      WHERE c.dt_desativacao_sac IS NOT NULL
        AND CAST(c.dt_desativacao_sac AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL {janela_meses} MONTH)
        AND CAST(c.dt_desativacao_sac AS DATE) <= LAST_DAY(CURRENT_DATE())
        AND NOT EXISTS (
          SELECT 1 FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` v
          WHERE v.st_sincro_sac = c.st_sincro_sac
        )
        AND (
          SELECT COUNT(*) FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all` liq
          WHERE liq.st_sincro_sac = c.st_sincro_sac AND liq.comp_valor > 0
        ) = 1
        AND EXISTS (
          SELECT 1 FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all` liq
          WHERE liq.st_sincro_sac = c.st_sincro_sac AND liq.comp_valor > 0
            AND {excl_liquidacao}
        )
        {filtro_extra}
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
        xaxis=dict(
            showgrid=True, gridcolor="#292929", gridwidth=1,
            zeroline=False, title="", type="category",
        ),
        yaxis=dict(
            showgrid=True, gridcolor="#292929", gridwidth=1,
            zeroline=False, title="",
        ),
        hoverlabel=dict(
            bgcolor="#141414", bordercolor="#292929",
            font_size=13, font_family="Outfit, sans-serif", font_color="#ffffff",
        ),
    )
    return fig


def mes_fmt_ordered(df: pd.DataFrame, date_col: str = "mes") -> tuple[pd.DataFrame, list[str]]:
    """
    Adiciona coluna mes_fmt (Mmm/YY) e retorna df ordenado + lista cronológica.
    Usar categoryarray no Plotly para garantir ordem correta no eixo X.
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col)
    df["mes_fmt"] = df[date_col].dt.strftime("%b/%y").str.capitalize()
    ordered = df["mes_fmt"].drop_duplicates().tolist()
    return df, ordered


# ─────────────────────────────────────────────
# SELETORES DE PERÍODO
# ─────────────────────────────────────────────
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


# ─────────────────────────────────────────────
# HELPERS DE KPI
# ─────────────────────────────────────────────
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
    """Formata número no padrão brasileiro: 1.000,00"""
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def no_data(label: str = "Dados não disponíveis") -> None:
    st.info(label, icon="ℹ️")


# ─────────────────────────────────────────────
# CONEXÃO BIGQUERY — cliente nativo
# ─────────────────────────────────────────────
def _get_bq_client(project_key: str) -> bigquery.Client:
    cfg = st.secrets["connections"][project_key]
    project = cfg["project"]
    creds_raw = cfg["credentials"]
    if isinstance(creds_raw, str):
        creds_dict = json.loads(creds_raw)
    else:
        creds_dict = dict(creds_raw)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/bigquery"],
    )
    return bigquery.Client(project=project, credentials=credentials)


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
# ── PÁGINA 1: COBRANÇA / MÓDULOS ─────────────
# ─────────────────────────────────────────────

@st.cache_data(ttl=72000)
def load_contratos_mensais() -> pd.DataFrame:
    """
    Clientes únicos com boleto emitido por mês + totais de receita.
    Deduplicação por id_recebimento_recb via ROW_NUMBER.
    """
    query = """
    WITH dedup AS (
      SELECT
        st_sincro_sac,
        DATE_TRUNC(CAST(dt_vencimento_recb AS DATE), MONTH) AS mes,
        id_recebimento_recb,
        vl_total_recb,
        fl_status_recb,
        ROW_NUMBER() OVER (
          PARTITION BY id_recebimento_recb
          ORDER BY dt_vencimento_recb
        ) AS rn
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE CAST(dt_vencimento_recb AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
        AND CAST(dt_vencimento_recb AS DATE) <= LAST_DAY(CURRENT_DATE())
    )
    SELECT
      mes,
      COUNT(DISTINCT st_sincro_sac)                                          AS clientes_com_boleto,
      COUNT(id_recebimento_recb)                                             AS total_boletos,
      SUM(vl_total_recb)                                                     AS receita_total,
      SUM(CASE WHEN fl_status_recb = '1' THEN vl_total_recb ELSE 0 END)     AS receita_liquidada
    FROM dedup
    WHERE rn = 1
    GROUP BY mes
    ORDER BY mes
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"] = pd.to_datetime(df["mes"])
    return df


@st.cache_data(ttl=72000)
def load_modulos_mensais() -> pd.DataFrame:
    """
    Clientes únicos com cobrança emitida por módulo por mês.
    Identifica módulo via comp_st_descricao_prd diretamente na tabela de cobranças
    (mesmo padrão [KIDS], [JORNADA], [LOJAINTELIGENTE], [LOJAINTELIGENTE_INC]).
    Conta st_sincro_sac distintos que tiveram ao menos 1 linha do módulo no mês.
    """
    query = """
    SELECT
      DATE_TRUNC(CAST(dt_vencimento_recb AS DATE), MONTH) AS mes,
      CASE
        WHEN comp_st_descricao_prd LIKE '%[KIDS]%'                THEN 'kids'
        WHEN comp_st_descricao_prd LIKE '%[JORNADA]%'             THEN 'jornada'
        WHEN comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'     THEN 'loja_inteligente'
        WHEN comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%' THEN 'loja_inteligente'
      END AS modulo,
      COUNT(DISTINCT st_sincro_sac) AS clientes
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
    WHERE comp_st_conta_cont = '1.2.2'
      AND CAST(dt_vencimento_recb AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
      AND CAST(dt_vencimento_recb AS DATE) <= LAST_DAY(CURRENT_DATE())
      AND (
        comp_st_descricao_prd LIKE '%[KIDS]%'
        OR comp_st_descricao_prd LIKE '%[JORNADA]%'
        OR comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'
        OR comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%'
      )
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"] = pd.to_datetime(df["mes"])
        df["modulo"] = df["modulo"].str.lower()
    return df


@st.cache_data(ttl=72000)
def load_receita_modulos_mensais() -> pd.DataFrame:
    """
    Receita por módulo por mês usando comp_valor diretamente na tabela de cobranças.
    Filtra comp_st_conta_cont = '1.2.2' e identifica módulo via comp_st_descricao_prd.
    Isso garante que somente o valor do item Kids/Jornada/Loja entra na soma,
    sem contaminar com plano base, PRO, FILHA ou outros módulos do mesmo boleto.
    """
    query = """
    SELECT
      DATE_TRUNC(CAST(dt_vencimento_recb AS DATE), MONTH) AS mes,
      CASE
        WHEN comp_st_descricao_prd LIKE '%[KIDS]%'                THEN 'kids'
        WHEN comp_st_descricao_prd LIKE '%[JORNADA]%'             THEN 'jornada'
        WHEN comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'     THEN 'loja_inteligente'
        WHEN comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%' THEN 'loja_inteligente'
      END AS modulo,
      SUM(comp_valor)                                                    AS receita_emitida,
      SUM(CASE WHEN fl_status_recb = '1' THEN comp_valor ELSE 0 END)    AS receita_liquidada
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
    WHERE comp_st_conta_cont = '1.2.2'
      AND CAST(dt_vencimento_recb AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
      AND CAST(dt_vencimento_recb AS DATE) <= LAST_DAY(CURRENT_DATE())
      AND (
        comp_st_descricao_prd LIKE '%[KIDS]%'
        OR comp_st_descricao_prd LIKE '%[JORNADA]%'
        OR comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'
        OR comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%'
      )
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"] = pd.to_datetime(df["mes"])
        df["modulo"] = df["modulo"].str.lower()
    return df


@st.cache_data(ttl=72000)
def load_receita_liquidada_diaria(n_meses: int = 4) -> pd.DataFrame:
    """
    Receita liquidada por dia (dt_liquidacao_recb), últimos n_meses (mês atual incluso).
    Fonte: splgc-cobrancas_liquidacao-all — tabela só contém boletos pagos
    (fl_status_recb='1' em 100% das linhas), 1 linha por item de composição.
    Dedup por id_recebimento_recb antes de somar vl_total_recb, senão infla ~10x
    (mesmo padrão de load_contratos_mensais, só que agrupando por dia de
    liquidação em vez de mês de vencimento).
    """
    query = f"""
    WITH dedup AS (
      SELECT
        CAST(dt_liquidacao_recb AS DATE) AS dia,
        id_recebimento_recb,
        vl_total_recb,
        ROW_NUMBER() OVER (
          PARTITION BY id_recebimento_recb
          ORDER BY dt_liquidacao_recb
        ) AS rn
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
      WHERE CAST(dt_liquidacao_recb AS DATE)
              >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL {n_meses - 1} MONTH), MONTH)
        AND CAST(dt_liquidacao_recb AS DATE) <= CURRENT_DATE()
    )
    SELECT
      dia,
      SUM(vl_total_recb) AS receita_liquidada
    FROM dedup
    WHERE rn = 1
    GROUP BY dia
    ORDER BY dia
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["dia"] = pd.to_datetime(df["dia"])
    return df


# ─────────────────────────────────────────────
# ── PÁGINA 2: TRANSAÇÕES ─────────────────────
# ─────────────────────────────────────────────

@st.cache_data(ttl=72000)
def load_sara_ids() -> tuple:
    """Retorna tuple de tertiarygroup_ids de toda a denominação Sara Nossa Terra."""
    query = """
    SELECT tertiarygroup_id
    FROM `inchurch-gcp.backend_bi.view_company_list`
    WHERE subgroup_id = (
      SELECT subgroup_id
      FROM `inchurch-gcp.backend_bi.view_company_list`
      WHERE tertiarygroup_id = 32187
      LIMIT 1
    )
    """
    df = _bq_query(query, "bigquery_tech")
    if df.empty:
        return (32187,)
    return tuple(sorted(df["tertiarygroup_id"].astype(int).tolist()))


@st.cache_data(ttl=72000)
def load_transactions_por_metodo(exclude_ids: tuple = (), only_ids: tuple = ()) -> pd.DataFrame:
    """
    Soma de value por método de pagamento, canal, tipo (doacao/outros) e mês (últimos 15 meses).
    Status: active ou payed.
    Métodos excluídos: free (valor zero), external (valor zero), debit (volume residual).
    tipo = 'doacao' quando id da transação está em view_donation.transaction_ptr_id.
    exclude_ids: exclui esses tertiarygroup_ids da agregação.
    only_ids: restringe a esses tertiarygroup_ids.
    """
    sara_filter = ""
    if exclude_ids:
        ids_str = ", ".join(str(i) for i in exclude_ids)
        sara_filter = f"\n      AND t.tertiarygroup_id NOT IN ({ids_str})"
    elif only_ids:
        ids_str = ", ".join(str(i) for i in only_ids)
        sara_filter = f"\n      AND t.tertiarygroup_id IN ({ids_str})"

    query = f"""
    SELECT
      DATE_TRUNC(CAST(t.datetime AS DATE), MONTH)                       AS mes,
      t.method                                                           AS payment_method,
      t.payment_channel,
      CASE WHEN d.transaction_ptr_id IS NOT NULL THEN 'doacao'
           ELSE 'outros' END                                             AS tipo,
      SUM(t.value)                                                       AS total_value,
      COUNT(*)                                                           AS qtd_transacoes
    FROM `inchurch-gcp.backend_bi.view_transaction` t
    LEFT JOIN `inchurch-gcp.backend_bi.view_donation` d
           ON d.transaction_ptr_id = t.id
    WHERE
      t.status IN ('active', 'payed')
      AND t.method NOT IN ('free', 'external', 'debit')
      AND CAST(t.datetime AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
      AND CAST(t.datetime AS DATE) <= LAST_DAY(CURRENT_DATE()){sara_filter}
    GROUP BY 1, 2, 3, 4
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_tech")
    if not df.empty:
        df["mes"]             = pd.to_datetime(df["mes"])
        df["payment_method"]  = df["payment_method"].fillna("Não informado")
        df["payment_channel"] = df["payment_channel"].fillna("Não informado")
        df["tipo"]            = df["tipo"].fillna("outros")
    return df


@st.cache_data(ttl=72000)
def load_take_rate_snapshot_v2(exclude_ids: tuple = (), only_ids: tuple = ()) -> dict:
    """
    Snapshot do take rate do mês corrente.
    A receita de intermediação é lançada manualmente, então o cálculo só
    considera o período em que ela já foi inserida:
    - dia_max = último dia do mês atual com receita de intermediação lançada
    - receita_intermediacao = soma de comp_valor (1.2.4, fl_status_recb='1')
      de todos os dias do mês até dia_max (inclusive)
    - tpv = soma de value em view_transaction no mesmo intervalo
    - take_rate_pct = receita / tpv * 100
    exclude_ids/only_ids: filtram o TPV (view_transaction) pelo tertiarygroup_id.
    """
    q_interm = """
    SELECT
      MAX(CAST(dt_liquidacao_recb AS DATE)) AS dia_max,
      SUM(comp_valor)                       AS receita_intermediacao
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
    WHERE comp_st_conta_cont = '1.2.4'
      AND fl_status_recb = '1'
      AND dt_liquidacao_recb IS NOT NULL
      AND DATE_TRUNC(CAST(dt_liquidacao_recb AS DATE), MONTH) = DATE_TRUNC(CURRENT_DATE(), MONTH)
    """
    df_interm = _bq_query(q_interm, "bigquery_bi")
    if df_interm.empty or pd.isnull(df_interm["dia_max"].iloc[0]):
        return {}

    dia_max = pd.Timestamp(df_interm["dia_max"].iloc[0])
    dia_max_str = dia_max.strftime("%Y-%m-%d")
    inicio_mes_str = dia_max.replace(day=1).strftime("%Y-%m-%d")
    receita_intermediacao = float(df_interm["receita_intermediacao"].iloc[0])

    sara_filter = ""
    if exclude_ids:
        ids_str = ", ".join(str(i) for i in exclude_ids)
        sara_filter = f"\n      AND tertiarygroup_id NOT IN ({ids_str})"
    elif only_ids:
        ids_str = ", ".join(str(i) for i in only_ids)
        sara_filter = f"\n      AND tertiarygroup_id IN ({ids_str})"

    q_tpv = f"""
    SELECT SUM(value) AS tpv
    FROM `inchurch-gcp.backend_bi.view_transaction`
    WHERE status IN ('active', 'payed')
      AND method NOT IN ('free', 'external', 'debit')
      AND CAST(datetime AS DATE) BETWEEN DATE '{inicio_mes_str}' AND DATE '{dia_max_str}'{sara_filter}
    """
    df_tpv = _bq_query(q_tpv, "bigquery_tech")
    tpv = (
        float(df_tpv["tpv"].iloc[0])
        if not df_tpv.empty and df_tpv["tpv"].iloc[0] is not None
        else 0.0
    )
    take_rate_pct = (receita_intermediacao / tpv * 100) if tpv > 0 else None

    return {
        "dia_max": dia_max_str,
        "inicio_mes": inicio_mes_str,
        "receita_intermediacao": receita_intermediacao,
        "tpv": tpv,
        "take_rate_pct": take_rate_pct,
    }


@st.cache_data(ttl=72000)
def load_take_rate_historico_v2(exclude_ids: tuple = (), only_ids: tuple = ()) -> pd.DataFrame:
    """
    Take rate histórico mensal.
    A receita de intermediação é lançada manualmente, então cada mês só
    considera o período em que ela já foi inserida:
    - Para cada mês: dia_max = último dia desse mês com receita lançada
    - receita_intermediacao = soma de comp_valor (1.2.4, fl_status='1')
      do dia 1 do mês até dia_max
    - tpv = soma de value em view_transaction no mesmo intervalo (BQ_TECH)
    - take_rate_pct = receita / tpv * 100
    Cross-project: merge feito em Python (BQ_BI x BQ_TECH).
    exclude_ids/only_ids: filtram o TPV (view_transaction) pelo tertiarygroup_id.
    """
    q_interm = """
    SELECT
      DATE_TRUNC(CAST(dt_liquidacao_recb AS DATE), MONTH) AS mes,
      MAX(CAST(dt_liquidacao_recb AS DATE))               AS dia_max,
      SUM(comp_valor)                                     AS receita_intermediacao
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
    WHERE comp_st_conta_cont = '1.2.4'
      AND fl_status_recb = '1'
      AND dt_liquidacao_recb IS NOT NULL
      AND CAST(dt_liquidacao_recb AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
    GROUP BY 1
    ORDER BY 1
    """
    df_interm = _bq_query(q_interm, "bigquery_bi")
    if df_interm.empty:
        return pd.DataFrame()

    df_interm["mes"]     = pd.to_datetime(df_interm["mes"])
    df_interm["dia_max"] = pd.to_datetime(df_interm["dia_max"]).dt.strftime("%Y-%m-%d")
    df_interm = df_interm[df_interm["dia_max"].notna() & (df_interm["dia_max"] != "NaT")]

    if df_interm.empty:
        return pd.DataFrame()

    sara_filter = ""
    if exclude_ids:
        ids_str = ", ".join(str(i) for i in exclude_ids)
        sara_filter = f"\n      AND tertiarygroup_id NOT IN ({ids_str})"
    elif only_ids:
        ids_str = ", ".join(str(i) for i in only_ids)
        sara_filter = f"\n      AND tertiarygroup_id IN ({ids_str})"

    # TPV por mês: do dia 1 até o dia_max do mês (lado BQ_TECH)
    intervalos = [
        f"(CAST(datetime AS DATE) BETWEEN DATE '{m.strftime('%Y-%m-%d')}' AND DATE '{d}')"
        for m, d in zip(df_interm["mes"], df_interm["dia_max"])
    ]
    where_intervalos = " OR ".join(intervalos)
    q_tpv = f"""
    SELECT
      DATE_TRUNC(CAST(datetime AS DATE), MONTH) AS mes,
      SUM(value)                                AS tpv
    FROM `inchurch-gcp.backend_bi.view_transaction`
    WHERE status IN ('active', 'payed')
      AND method NOT IN ('free', 'external', 'debit')
      AND ({where_intervalos}){sara_filter}
    GROUP BY 1
    """
    df_tpv = _bq_query(q_tpv, "bigquery_tech")
    if not df_tpv.empty:
        df_tpv["mes"] = pd.to_datetime(df_tpv["mes"])

    df = df_interm.merge(df_tpv, on="mes", how="left")
    df["tpv"]           = df["tpv"].fillna(0.0)
    df["take_rate_pct"] = (
        df["receita_intermediacao"] / df["tpv"].where(df["tpv"] > 0) * 100
    ).round(4)
    return df[["mes", "dia_max", "receita_intermediacao", "tpv", "take_rate_pct"]].sort_values("mes")


@st.cache_data(ttl=72000)
def load_intermediacao_mensal() -> pd.DataFrame:
    """
    Receita de Intermediação de Negócios (comp_st_conta_cont = '1.2.4') por mês.
    Fonte: BQ_BI — splgc-cobrancas_competencia-all.
    Usada para calcular Take Rate = Intermediação / TPV.
    """
    query = """
    SELECT
      DATE_TRUNC(CAST(dt_vencimento_recb AS DATE), MONTH) AS mes,
      SUM(comp_valor)                                                    AS receita_intermediacao,
      SUM(CASE WHEN fl_status_recb = '1' THEN comp_valor ELSE 0 END)    AS receita_intermediacao_paga
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
    WHERE comp_st_conta_cont = '1.2.4'
      AND comp_valor > 0
      AND CAST(dt_vencimento_recb AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
      AND CAST(dt_vencimento_recb AS DATE) <= LAST_DAY(CURRENT_DATE())
    GROUP BY 1
    ORDER BY 1
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"] = pd.to_datetime(df["mes"])
    return df


@st.cache_data(ttl=72000)
def load_transactions_clientes_por_mes(exclude_ids: tuple = (), only_ids: tuple = ()) -> pd.DataFrame:
    """
    Uma linha por (mes, channel, tipo, tertiarygroup_id) único — sem pré-agregar clientes.
    A agregação final é feita na página via nunique() para evitar dupla contagem de igrejas
    que transacionaram em mais de um canal ou tipo no mesmo mês.
    exclude_ids: exclui esses tertiarygroup_ids.
    only_ids: restringe a esses tertiarygroup_ids.
    """
    sara_filter = ""
    if exclude_ids:
        ids_str = ", ".join(str(i) for i in exclude_ids)
        sara_filter = f"\n      AND t.tertiarygroup_id NOT IN ({ids_str})"
    elif only_ids:
        ids_str = ", ".join(str(i) for i in only_ids)
        sara_filter = f"\n      AND t.tertiarygroup_id IN ({ids_str})"

    query = f"""
    SELECT
      DATE_TRUNC(CAST(t.datetime AS DATE), MONTH)                       AS mes,
      t.payment_channel,
      CASE WHEN d.transaction_ptr_id IS NOT NULL THEN 'doacao'
           ELSE 'outros' END                                             AS tipo,
      t.tertiarygroup_id
    FROM `inchurch-gcp.backend_bi.view_transaction` t
    LEFT JOIN `inchurch-gcp.backend_bi.view_donation` d
           ON d.transaction_ptr_id = t.id
    WHERE
      t.status IN ('active', 'payed')
      AND t.method NOT IN ('free', 'external', 'debit')
      AND CAST(t.datetime AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
      AND CAST(t.datetime AS DATE) <= LAST_DAY(CURRENT_DATE()){sara_filter}
    GROUP BY 1, 2, 3, 4
    ORDER BY 1
    """
    df = _bq_query(query, "bigquery_tech")
    if not df.empty:
        df["mes"]             = pd.to_datetime(df["mes"])
        df["payment_channel"] = df["payment_channel"].fillna("Não informado")
        df["tipo"]            = df["tipo"].fillna("outros")
    return df


# ─────────────────────────────────────────────
# ── PÁGINA 3: DESATIVAÇÕES ───────────────────
# ─────────────────────────────────────────────

@st.cache_data(ttl=72000)
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
      {_BRANCH3_LIQUIDACAO_UNICA.format(janela_meses=15, excl_liquidacao=_EXCL_LIQUIDACAO_NAO_MENSALIDADE, filtro_extra="")}
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


@st.cache_data(ttl=72000)
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
      {_BRANCH3_LIQUIDACAO_UNICA.format(janela_meses=15, excl_liquidacao=_EXCL_LIQUIDACAO_NAO_MENSALIDADE, filtro_extra="AND " + _EXCL_NAO_MENSALIDADE.format(col="mrr.st_descricao_prd"))}
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


@st.cache_data(ttl=72000)
def load_receita_planos_mensais() -> pd.DataFrame:
    """
    Receita emitida e liquidada por PLANO BASE por mês (últimos 15 meses).
    Exclui linhas de módulos (KIDS, JORNADA, LOJA, TOTEM, VÍDEOS, módulos STARTER).
    Classifica plano via comp_st_descricao_prd usando o DE-PARA validado.
    """
    query = f"""
    WITH boleto_plano AS (
      -- Para cada boleto, identifica o plano base a partir das linhas que não são Reajuste Anual
      SELECT
        id_recebimento_recb,
        MAX(CASE
          WHEN comp_st_descricao_prd LIKE '%[PRO]%'         THEN 'pro'
          WHEN comp_st_descricao_prd LIKE '%[LITE]%'        THEN 'lite'
          WHEN comp_st_descricao_prd LIKE '%[STARTER]%'     THEN 'starter'
          WHEN comp_st_descricao_prd LIKE '%[FILHA]%'       THEN 'filha'
          WHEN comp_st_descricao_prd LIKE '%[BASIC]%'       THEN 'basic'
          WHEN comp_st_descricao_prd LIKE '%0 - 9 Igrejas%' THEN 'pro'
          WHEN comp_st_descricao_prd LIKE '%10+ Igrejas%'   THEN 'pro'
          WHEN comp_st_descricao_prd LIKE '%App Lite%'      THEN 'lite'
          WHEN comp_st_descricao_prd LIKE '%App da Igreja%' THEN 'starter'
          ELSE NULL
        END) AS plano_boleto
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE comp_st_conta_cont = '1.2.2'
        AND comp_st_descricao_prd != 'Reajuste Anual'
        AND {_EXCL_MODULOS.format(col="comp_st_descricao_prd")}
      GROUP BY 1
    ),
    linhas AS (
      SELECT
        st_sincro_sac,
        dt_vencimento_recb,
        id_recebimento_recb,
        comp_valor,
        fl_status_recb,
        comp_st_descricao_prd,
        {_PLAN_CASE.format(col="comp_st_descricao_prd")} AS plano_direto
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE comp_st_conta_cont = '1.2.2'
        AND CAST(dt_vencimento_recb AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
        AND CAST(dt_vencimento_recb AS DATE) <= LAST_DAY(CURRENT_DATE())
        AND {_EXCL_MODULOS.format(col="comp_st_descricao_prd")}
    )
    SELECT
      DATE_TRUNC(CAST(l.dt_vencimento_recb AS DATE), MONTH)            AS mes,
      CASE
        WHEN l.comp_st_descricao_prd = 'Reajuste Anual'
          THEN COALESCE(bp.plano_boleto, 'outros')
        ELSE l.plano_direto
      END                                                               AS plano,
      COUNT(DISTINCT l.st_sincro_sac)                                   AS clientes,
      SUM(l.comp_valor)                                                 AS receita_emitida,
      SUM(CASE WHEN l.fl_status_recb = '1' THEN l.comp_valor ELSE 0 END) AS receita_liquidada
    FROM linhas l
    LEFT JOIN boleto_plano bp
      ON l.id_recebimento_recb = bp.id_recebimento_recb
      AND l.comp_st_descricao_prd = 'Reajuste Anual'
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"]   = pd.to_datetime(df["mes"])
        df["plano"] = df["plano"].str.lower()
    return df


@st.cache_data(ttl=72000)
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
      {_BRANCH3_LIQUIDACAO_UNICA.format(janela_meses=15, excl_liquidacao=_EXCL_LIQUIDACAO_NAO_MENSALIDADE, filtro_extra="AND " + _EXCL_MODULOS.format(col="mrr.st_descricao_prd") + " AND " + _EXCL_NAO_MENSALIDADE.format(col="mrr.st_descricao_prd"))}
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


@st.cache_data(ttl=72000)
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
      {_BRANCH3_LIQUIDACAO_UNICA.format(janela_meses=15, excl_liquidacao=_EXCL_LIQUIDACAO_NAO_MENSALIDADE, filtro_extra="AND " + _EXCL_NAO_MENSALIDADE.format(col="mrr.st_descricao_prd"))}
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
        df["mes"]   = pd.to_datetime(df["mes"])
        df["plano"] = df["plano"].str.upper()
    return df


# ─────────────────────────────────────────────
# ── PÁGINA 4: INADIMPLÊNCIA ───────────────────
# ─────────────────────────────────────────────

@st.cache_data(ttl=72000)
def load_grupos() -> list[str]:
    """Retorna grupos disponíveis em splgc-grupo (ex: Ana, Priscila)."""
    query = """
    SELECT DISTINCT grupo
    FROM `business-intelligence-467516.Splgc.splgc-grupo`
    WHERE grupo IS NOT NULL
    ORDER BY grupo
    """
    df = _bq_query(query, "bigquery_bi")
    return sorted(df["grupo"].tolist()) if not df.empty else []


@st.cache_data(ttl=72000)
def load_inadimplencia_serie(grupo: str | None = None) -> pd.DataFrame:
    """
    Série histórica de inadimplência — snapshot por dia útil (últimos 6 meses).

    Janela ROLANTE: para cada data de observação D, olha os N dias anteriores de vencimento.
      30d: boletos com vencimento em [D-30, D] — emitido no último mês
      90d: boletos com vencimento em [D-90, D] — emitido nos últimos 3 meses
      Em ambos: aberto = boletos ainda não pagos EM D (dia_pago IS NULL OR dia_pago > D)
      % = aberto / emitido × 100

    Exemplo: em 12/02, 30d olha [13/01–12/02]. Se em 13/02 um boleto vencido em 05/02
    for pago, ele sai do numerador do dia 13/02 em diante.
    """
    # --- 1. Carrega boletos brutos do BigQuery ---
    _grupo_join = (
        f"INNER JOIN `business-intelligence-467516.Splgc.splgc-grupo` g\n"
        f"      ON b.id_sacado_sac = g.id_sacado_sac AND g.grupo = '{grupo}'"
    ) if grupo else ""
    query = f"""
    SELECT
      CAST(b.dt_vencimento_recb  AS DATE) AS dia_venc,
      CAST(b.dt_liquidacao_recb  AS DATE) AS dia_pago,
      b.comp_valor
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` b
    LEFT JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
      ON b.id_sacado_sac = c.id_sacado_sac
    {_grupo_join}
    WHERE b.comp_st_conta_cont IN ('1.2.1', '1.2.2')
      AND CAST(b.dt_vencimento_recb AS DATE)
            >= DATE_SUB(CURRENT_DATE(), INTERVAL 18 MONTH)
      AND CAST(b.dt_vencimento_recb AS DATE) < CURRENT_DATE()
      AND (c.dt_desativacao_sac IS NULL
           OR c.dt_desativacao_sac > CAST(b.dt_vencimento_recb AS DATE))
      AND EXISTS (
        SELECT 1
        FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` pago
        WHERE pago.id_sacado_sac = b.id_sacado_sac
          AND pago.dt_liquidacao_recb IS NOT NULL
      )
    """
    df_b = _bq_query(query, "bigquery_bi")
    if df_b.empty:
        return pd.DataFrame()

    df_b["dia_venc"]   = pd.to_datetime(df_b["dia_venc"])
    df_b["dia_pago"]   = pd.to_datetime(df_b["dia_pago"])
    df_b["comp_valor"] = pd.to_numeric(df_b["comp_valor"], errors="coerce").fillna(0)

    # Arrays numpy para operações vetorizadas dentro do loop
    v      = df_b["dia_venc"].values    # datetime64[ns]
    p      = df_b["dia_pago"].values    # datetime64[ns] — NaT se não pago
    c_vals = df_b["comp_valor"].values

    # --- 2. Datas de observação: dias úteis últimos 6 meses até 2 dias úteis atrás ---
    today_ts  = pd.Timestamp.today().normalize()
    end_obs   = today_ts - pd.tseries.offsets.BDay(2)
    start_obs = today_ts - pd.DateOffset(months=6)
    obs_dates = pd.bdate_range(start=start_obs, end=end_obs)

    # --- 3. Snapshot para cada data de observação ---
    rows = []
    for D in obs_dates:
        D_np      = np.datetime64(D)
        D_30_ini  = np.datetime64(D - pd.Timedelta(days=30))   # início janela 30d
        D_90_ini  = np.datetime64(D - pd.Timedelta(days=90))   # início janela 90d

        # Boleto aberto EM D: não pago ou pago depois de D
        is_open = np.isnat(p) | (p > D_np)

        # 30d: vencimento em [D-30, D]  ← janela rolante de 30 dias
        m_30        = (v >= D_30_ini) & (v <= D_np)
        emitido_30d = float(c_vals[m_30].sum())
        aberto_30d  = float(c_vals[m_30 & is_open].sum())

        # 90d: vencimento em [D-90, D]  ← janela rolante de 90 dias
        m_90        = (v >= D_90_ini) & (v <= D_np)
        emitido_90d = float(c_vals[m_90].sum())
        aberto_90d  = float(c_vals[m_90 & is_open].sum())

        # emitido/aberto geral (alias de 90d, mantido para compatibilidade com KPIs)
        emitido = emitido_90d
        aberto  = aberto_90d

        rows.append({
            "dia":         D,
            "emitido":     emitido,
            "aberto":      aberto,
            "emitido_30d": emitido_30d,
            "aberto_30d":  aberto_30d,
            "emitido_90d": emitido_90d,
            "aberto_90d":  aberto_90d,
        })

    result = pd.DataFrame(rows)
    result["dia"] = pd.to_datetime(result["dia"])
    result["pct_inadimp"]     = (result["aberto"]     / result["emitido"].where(result["emitido"] > 0)         * 100).round(2)
    result["pct_inadimp_30d"] = (result["aberto_30d"] / result["emitido_30d"].where(result["emitido_30d"] > 0) * 100).round(2)
    result["pct_inadimp_90d"] = (result["aberto_90d"] / result["emitido_90d"].where(result["emitido_90d"] > 0) * 100).round(2)
    return result


@st.cache_data(ttl=72000)
def load_inadimplencia_por_plano(grupo: str | None = None) -> pd.DataFrame:
    """
    Inadimplência 30d atual agregada por plano base.
    Retorna clientes únicos inadimplentes e valor em aberto por plano.
    """
    _grupo_join = (
        f"INNER JOIN `business-intelligence-467516.Splgc.splgc-grupo` g\n"
        f"      ON b.id_sacado_sac = g.id_sacado_sac AND g.grupo = '{grupo}'"
    ) if grupo else ""
    query = f"""
    SELECT
      {_PLAN_CASE.format(col="b.comp_st_descricao_prd")}              AS plano,
      COUNT(DISTINCT b.id_sacado_sac)                                  AS clientes_inadimplentes,
      SUM(b.comp_valor)                                                AS valor_aberto
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` b
    LEFT JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
      ON b.id_sacado_sac = c.id_sacado_sac
    {_grupo_join}
    WHERE b.comp_st_conta_cont IN ('1.2.1', '1.2.2')
      AND b.dt_liquidacao_recb IS NULL
      AND CAST(b.dt_vencimento_recb AS DATE)
            BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) AND CURRENT_DATE()
      AND (c.dt_desativacao_sac IS NULL
           OR c.dt_desativacao_sac > CAST(b.dt_vencimento_recb AS DATE))
      AND EXISTS (
        SELECT 1
        FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` pago
        WHERE pago.id_sacado_sac = b.id_sacado_sac
          AND pago.dt_liquidacao_recb IS NOT NULL
      )
    GROUP BY 1
    ORDER BY valor_aberto DESC
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["plano"] = df["plano"].str.lower()
    return df


@st.cache_data(ttl=72000)
def load_inadimplencia_por_frequencia() -> pd.DataFrame:
    """
    Distribuição de clientes inadimplentes (30d) por quantidade de boletos em aberto.
    Buckets: 1, 2-4, 5-9, 10-14, 15-19, 20+
    """
    query = """
    WITH inadimplentes AS (
      SELECT
        b.id_sacado_sac,
        COUNT(DISTINCT b.id_recebimento_recb) AS boletos_abertos,
        SUM(b.comp_valor)                      AS valor_aberto
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` b
      LEFT JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
        ON b.id_sacado_sac = c.id_sacado_sac
      WHERE b.comp_st_conta_cont IN ('1.2.1', '1.2.2')
        AND b.dt_liquidacao_recb IS NULL
        AND CAST(b.dt_vencimento_recb AS DATE)
              BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) AND CURRENT_DATE()
        AND (c.dt_desativacao_sac IS NULL
             OR c.dt_desativacao_sac > CAST(b.dt_vencimento_recb AS DATE))
        AND EXISTS (
          SELECT 1
          FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` pago
          WHERE pago.id_sacado_sac = b.id_sacado_sac
            AND pago.dt_liquidacao_recb IS NOT NULL
        )
      GROUP BY 1
    )
    SELECT
      CASE
        WHEN boletos_abertos = 1          THEN '1 boleto'
        WHEN boletos_abertos BETWEEN 2 AND 4   THEN '2 – 4 boletos'
        WHEN boletos_abertos BETWEEN 5 AND 9   THEN '5 – 9 boletos'
        WHEN boletos_abertos BETWEEN 10 AND 14 THEN '10 – 14 boletos'
        WHEN boletos_abertos BETWEEN 15 AND 19 THEN '15 – 19 boletos'
        ELSE '20+ boletos'
      END                              AS faixa,
      COUNT(*)                         AS clientes,
      SUM(valor_aberto)                AS valor_aberto
    FROM inadimplentes
    GROUP BY 1
    ORDER BY MIN(boletos_abertos)
    """
    df = _bq_query(query, "bigquery_bi")
    return df


@st.cache_data(ttl=72000)
def load_inadimplencia_top_clientes(dias: int = 30, grupo: str | None = None) -> pd.DataFrame:
    """
    Top 30 clientes com maior valor em aberto na janela rolante de N dias.
    Só conta clientes com comp_valor > 1 e que já pagaram pelo menos um boleto.
    """
    _grupo_join = (
        f"INNER JOIN `business-intelligence-467516.Splgc.splgc-grupo` g\n"
        f"        ON b.id_sacado_sac = g.id_sacado_sac AND g.grupo = '{grupo}'"
    ) if grupo else ""
    query = f"""
    WITH inad AS (
      SELECT
        b.id_sacado_sac,
        COUNT(DISTINCT b.id_recebimento_recb)                          AS boletos_abertos,
        SUM(b.comp_valor)                                              AS valor_aberto,
        MAX(DATE_DIFF(CURRENT_DATE(), CAST(b.dt_vencimento_recb AS DATE), DAY)) AS max_dias_atraso,
        {_PLAN_CASE.format(col="MAX(b.comp_st_descricao_prd)")}        AS plano
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` b
      LEFT JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
        ON b.id_sacado_sac = c.id_sacado_sac
      {_grupo_join}
      WHERE b.comp_st_conta_cont IN ('1.2.1', '1.2.2')
        AND b.dt_liquidacao_recb IS NULL
        AND CAST(b.dt_vencimento_recb AS DATE)
              BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL {dias} DAY) AND CURRENT_DATE()
        AND (c.dt_desativacao_sac IS NULL
             OR c.dt_desativacao_sac > CAST(b.dt_vencimento_recb AS DATE))
        AND EXISTS (
          SELECT 1
          FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` pago
          WHERE pago.id_sacado_sac = b.id_sacado_sac
            AND pago.dt_liquidacao_recb IS NOT NULL
        )
      GROUP BY 1
    )
    SELECT
      i.id_sacado_sac                  AS id_cliente,
      c.st_nome_sac                    AS nome_cliente,
      i.plano,
      ROUND(i.valor_aberto, 2)         AS valor_aberto,
      i.boletos_abertos,
      i.max_dias_atraso
    FROM inad i
    LEFT JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
      ON i.id_sacado_sac = c.id_sacado_sac
    ORDER BY i.valor_aberto DESC
    LIMIT 30
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["plano"] = df["plano"].str.lower()
    return df


@st.cache_data(ttl=72000)
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


# ─────────────────────────────────────────────
# ── PÁGINA 5: COLABORADORES ──────────────────
# Fonte: dp_inchurch (BQ_BI, mesmo projeto de Splgc — join direto em SQL,
# sem pandas). Ver dp-inchurch-dicionario-dados.md no vault Obsidian.
# ─────────────────────────────────────────────

COLAB_LABELS = {"clt": "CLT", "pj": "PJ", "outros": "Outros"}
COLAB_ORDER  = ["clt", "pj", "outros"]
COLAB_COLORS = {"clt": "#6eda2c", "pj": "#ffffff", "outros": "#a0a0a0"}

# Valores reais de cadastro_colaborador.contrato (checado ao vivo em 2026-08-31):
# 'CLT', 'PJ', 'ESTÁGIO', 'JOVEM APRENDIZ', 'Sócio' (case mistura, cuidado ao
# alterar). 'Sócio' e contrato vazio (NULL) ficam fora do headcount — não são
# força de trabalho operacional / erro de cadastro.
_COLAB_BUCKET = """
    CASE
      WHEN cc.contrato = 'CLT' THEN 'clt'
      WHEN cc.contrato = 'PJ' THEN 'pj'
      WHEN cc.contrato IN ('ESTÁGIO', 'JOVEM APRENDIZ') THEN 'outros'
    END
"""

# Chave de dedup por pessoa: cpf_cnpj normalizado, com fallback pra
# empresa+codigo quando cpf_cnpj é NULL (2 casos). Necessário porque pessoas
# migradas entre empresas (Atos6/Justus -> Inradar App) ganham codigo novo e
# viram uma 2ª/3ª linha na tabela — contar por linha infla o headcount.
# Ver "achado central" em dp-inchurch-dicionario-dados.md.
_COLAB_DOC_KEY = (
    "COALESCE(NULLIF(REGEXP_REPLACE(cc.cpf_cnpj, r'[^0-9]', ''), ''), "
    "CONCAT(cc.empresa, '|', cc.codigo))"
)


@st.cache_data(ttl=72000)
def load_colaboradores_mensal(n_meses: int = 18) -> pd.DataFrame:
    """
    Contagem de colaboradores por mês (CLT/PJ/Outros), últimos n_meses.
    Snapshot no início de cada mês: data_entrada <= mês E (data_saida IS NULL
    OU data_saida > mês) — mesmo padrão de load_base_ativa_por_plano.
    """
    query = f"""
    SELECT
      cal.mes,
      {_COLAB_BUCKET} AS bucket,
      COUNT(DISTINCT {_COLAB_DOC_KEY}) AS colaboradores
    FROM (
      SELECT mes
      FROM UNNEST(GENERATE_DATE_ARRAY(
        DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL {n_meses} MONTH),
        DATE_TRUNC(CURRENT_DATE(), MONTH),
        INTERVAL 1 MONTH
      )) AS mes
    ) cal
    CROSS JOIN `business-intelligence-467516.dp_inchurch.cadastro_colaborador` cc
    WHERE cc.contrato IN ('CLT', 'PJ', 'ESTÁGIO', 'JOVEM APRENDIZ')
      AND cc.data_entrada IS NOT NULL
      AND cc.data_entrada <= cal.mes
      AND (cc.data_saida IS NULL OR cc.data_saida > cal.mes)
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"] = pd.to_datetime(df["mes"])
    return df


@st.cache_data(ttl=72000)
def load_mrr_por_colaborador(n_meses: int = 18, incluir_squad: bool = True) -> pd.DataFrame:
    """
    MRR total da empresa / headcount total (CLT+PJ+Outros) por mês.
    Splgc.vw-splgc-tabela_mrr_validos e dp_inchurch.cadastro_colaborador estão
    no mesmo projeto BQ_BI (business-intelligence-467516) -> join direto em
    SQL puro, sem precisar de merge em pandas.

    incluir_squad=False exclui os contratos Squad as a Service do MRR — só 3
    contratos ativos hoje, mas ticket alto (~R$36k/contrato, ~10% do MRR
    total), então vale a opção de ver o MRR/Colaborador com e sem eles.
    """
    squad_filter = "" if incluir_squad else "AND mrr.st_descricao_prd NOT LIKE '%Squad as a Service%'"
    query = f"""
    WITH cal AS (
      SELECT mes
      FROM UNNEST(GENERATE_DATE_ARRAY(
        DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL {n_meses} MONTH),
        DATE_TRUNC(CURRENT_DATE(), MONTH),
        INTERVAL 1 MONTH
      )) AS mes
    ),
    mrr AS (
      SELECT cal.mes, SUM(mrr.valor_total) AS mrr_total
      FROM cal
      CROSS JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` mrr
      WHERE CAST(mrr.dt_inicio_mens AS DATE) <= cal.mes
        AND (mrr.dt_fim_mens IS NULL OR CAST(mrr.dt_fim_mens AS DATE) > cal.mes)
        {squad_filter}
      GROUP BY 1
    ),
    headcount AS (
      SELECT cal.mes, COUNT(DISTINCT {_COLAB_DOC_KEY}) AS colaboradores
      FROM cal
      CROSS JOIN `business-intelligence-467516.dp_inchurch.cadastro_colaborador` cc
      WHERE cc.contrato IN ('CLT', 'PJ', 'ESTÁGIO', 'JOVEM APRENDIZ')
        AND cc.data_entrada IS NOT NULL
        AND cc.data_entrada <= cal.mes
        AND (cc.data_saida IS NULL OR cc.data_saida > cal.mes)
      GROUP BY 1
    )
    SELECT
      mrr.mes,
      mrr.mrr_total,
      headcount.colaboradores,
      SAFE_DIVIDE(mrr.mrr_total, headcount.colaboradores) AS mrr_por_colaborador
    FROM mrr
    JOIN headcount USING (mes)
    ORDER BY 1
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"] = pd.to_datetime(df["mes"])
    return df


@st.cache_data(ttl=72000)
def load_custo_por_centro_custo() -> pd.DataFrame:
    """
    Distribuição de custo por centro de custo — snapshot do mês mais recente
    disponível em cada fonte (folha_colaborador pra CLT/Estágio/Jovem
    Aprendiz, pj_pagamentos pra PJ). Cada fonte usa seu próprio mês mais
    recente (podem divergir por até ~1 mês entre pipelines).
    CLT: custo_empresa_estimado (já inclui encargos/INSS patronal).
    PJ: valor da NF paga.
    Sócio: NÃO aparece (ou aparece só parcialmente) em folha_colaborador nem
    pj_pagamentos — confirmado ao vivo em 2026-08-31 (1 dos 2 sócios ativos
    tem 0 linhas nas duas tabelas; o outro tem uma linha de folha de
    R$3.486, uma fração do pró-labore real dele). Usa
    remuneracao_fixa + remuneracao_variavel de cadastro_colaborador em vez
    disso — exclui o sócio das fontes de folha/pj pra não contar 2x a
    fração que porventura exista lá.
    Join com cadastro_colaborador por CPF/CNPJ normalizado, restrito a
    situacao='ATIVO' e dedupado por pessoa (ROW_NUMBER, fica com a linha de
    data_entrada mais recente) — sem isso, pessoa migrada de empresa
    (Atos6/Justus -> Inradar App, 2-3 linhas por CPF) casa 2x no join e infla
    o custo do centro de custo dela.
    """
    query = """
    WITH cc_ativo AS (
      SELECT * EXCEPT(rn) FROM (
        SELECT
          cc.centro_custo,
          cc.contrato,
          REGEXP_REPLACE(cc.cpf_cnpj, r'[^0-9]', '') AS doc_norm,
          cc.remuneracao_fixa,
          cc.remuneracao_variavel,
          ROW_NUMBER() OVER (
            PARTITION BY REGEXP_REPLACE(cc.cpf_cnpj, r'[^0-9]', '')
            ORDER BY cc.data_entrada DESC
          ) AS rn
        FROM `business-intelligence-467516.dp_inchurch.cadastro_colaborador` cc
        WHERE cc.situacao = 'ATIVO' AND cc.cpf_cnpj IS NOT NULL
      )
      WHERE rn = 1
    ),
    socio_custo AS (
      SELECT doc_norm, (COALESCE(remuneracao_fixa, 0) + COALESCE(remuneracao_variavel, 0)) AS custo
      FROM cc_ativo
      WHERE contrato = 'Sócio'
    ),
    folha_ultimo_mes AS (
      SELECT
        REGEXP_REPLACE(f.cpf, r'[^0-9]', '') AS doc_norm,
        f.custo_empresa_estimado AS custo
      FROM `business-intelligence-467516.dp_inchurch.folha_colaborador` f
      WHERE f.competencia = (
        SELECT MAX(competencia) FROM `business-intelligence-467516.dp_inchurch.folha_colaborador`
      )
        AND REGEXP_REPLACE(f.cpf, r'[^0-9]', '') NOT IN (SELECT doc_norm FROM socio_custo)
    ),
    pj_ultimo_mes AS (
      SELECT
        REGEXP_REPLACE(p.cnpj, r'[^0-9]', '') AS doc_norm,
        p.valor AS custo
      FROM `business-intelligence-467516.dp_inchurch.pj_pagamentos` p
      WHERE p.competencia = (
        SELECT MAX(competencia) FROM `business-intelligence-467516.dp_inchurch.pj_pagamentos`
      )
        AND REGEXP_REPLACE(p.cnpj, r'[^0-9]', '') NOT IN (SELECT doc_norm FROM socio_custo)
    ),
    custos AS (
      SELECT doc_norm, custo FROM folha_ultimo_mes
      UNION ALL
      SELECT doc_norm, custo FROM pj_ultimo_mes
      UNION ALL
      SELECT doc_norm, custo FROM socio_custo
    )
    SELECT
      COALESCE(cc_ativo.centro_custo, 'Sem Centro de Custo') AS centro_custo,
      SUM(custos.custo) AS custo_total
    FROM custos
    JOIN cc_ativo USING (doc_norm)
    GROUP BY 1
    ORDER BY 2 DESC
    """
    return _bq_query(query, "bigquery_bi")


CATEG_COLORS = {
    "Salário":                         "#6eda2c",
    "Encargos (INSS + FGTS Patronal)": "#57d124",
    "Benefícios":                      "#8ae650",
    "Vale Transporte":                 "#3ba811",
    "PJ":                              "#ffffff",
    "Sócio":                           "#a0a0a0",
}


@st.cache_data(ttl=72000)
def load_custo_por_categoria() -> pd.DataFrame:
    """
    Composição do custo total por categoria — snapshot do mês mais recente.
    CLT/Estágio/Jovem Aprendiz (folha_colaborador) decompostos em Salário,
    Encargos, Benefícios e Vale Transporte (campos já pré-agregados na
    fonte). PJ e Sócio entram como categoria única cada — não têm essa
    decomposição na fonte (PJ é 1 valor de NF só; Sócio usa
    remuneracao_fixa/variavel de cadastro_colaborador). Exclui a linha de
    Sócio que eventualmente aparece em folha_colaborador (pró-labore
    parcial, ver load_custo_por_centro_custo) pra não contar 2x.

    As 4 categorias de CLT batem quase exatamente com custo_empresa_estimado
    (validado ao vivo em 2026-08-31: diferença = exatamente o total de Vale
    Transporte, que não entra em custo_empresa_estimado na fonte):
      Salário            = salario_bruto
      Encargos            = valor_fgts + inss_patronal_estimado
      Benefícios          = beneficios_empresa
      Vale Transporte     = vale_transporte
    """
    query = """
    WITH cc_ativo AS (
      SELECT * EXCEPT(rn) FROM (
        SELECT
          cc.contrato,
          REGEXP_REPLACE(cc.cpf_cnpj, r'[^0-9]', '') AS doc_norm,
          cc.remuneracao_fixa,
          cc.remuneracao_variavel,
          ROW_NUMBER() OVER (
            PARTITION BY REGEXP_REPLACE(cc.cpf_cnpj, r'[^0-9]', '')
            ORDER BY cc.data_entrada DESC
          ) AS rn
        FROM `business-intelligence-467516.dp_inchurch.cadastro_colaborador` cc
        WHERE cc.situacao = 'ATIVO' AND cc.cpf_cnpj IS NOT NULL
      )
      WHERE rn = 1
    ),
    folha_mes AS (
      SELECT *
      FROM `business-intelligence-467516.dp_inchurch.folha_colaborador`
      WHERE competencia = (
        SELECT MAX(competencia) FROM `business-intelligence-467516.dp_inchurch.folha_colaborador`
      )
    ),
    folha_clt AS (
      -- INNER JOIN (não LEFT) — mesma regra da Seção "Custo por Centro de
      -- Custo": só conta CLT com cadastro ATIVO. Sem isso, a linha parcial
      -- de Sócio que às vezes aparece em folha_colaborador (ex: Sydney, cujo
      -- cpf na folha não bate com cpf_cnpj do cadastro) não é excluída pelo
      -- filtro de Sócio e conta 2x (uma vez aqui fatiada, outra em
      -- socio_custo) — confirmado ao vivo em 2026-08-31.
      SELECT f.*
      FROM folha_mes f
      INNER JOIN cc_ativo cc ON cc.doc_norm = REGEXP_REPLACE(f.cpf, r'[^0-9]', '')
      WHERE cc.contrato != 'Sócio'
    ),
    pj_ultimo_mes AS (
      -- INNER JOIN com cc_ativo (não LEFT) — mesma regra da Seção "Custo por
      -- Centro de Custo": só conta PJ com cadastro ATIVO em
      -- cadastro_colaborador. Pagamentos pra CNPJ sem cadastro (fornecedor/
      -- agência classificado em pj_pagamentos por engano, ou cadastro
      -- faltando) ficam de fora, senão o total de PJ diverge do resto da
      -- página. Confirmado ao vivo em 2026-08-31: 2 CNPJ pagos (R$61.558,40)
      -- não existem em cadastro_colaborador; 1 PJ inativo desde 28/02/2026
      -- recebeu R$8.000 no mês mais recente — investigar na Plataforma DP.
      SELECT p.valor
      FROM `business-intelligence-467516.dp_inchurch.pj_pagamentos` p
      INNER JOIN cc_ativo cc ON cc.doc_norm = REGEXP_REPLACE(p.cnpj, r'[^0-9]', '')
      WHERE p.competencia = (
        SELECT MAX(competencia) FROM `business-intelligence-467516.dp_inchurch.pj_pagamentos`
      )
        AND cc.contrato != 'Sócio'
    ),
    socio_custo AS (
      SELECT (COALESCE(remuneracao_fixa, 0) + COALESCE(remuneracao_variavel, 0)) AS valor
      FROM cc_ativo
      WHERE contrato = 'Sócio'
    )
    SELECT categoria, SUM(valor) AS valor
    FROM (
      SELECT 'Salário' AS categoria, salario_bruto AS valor FROM folha_clt
      UNION ALL
      SELECT 'Encargos (INSS + FGTS Patronal)', COALESCE(valor_fgts,0) + COALESCE(inss_patronal_estimado,0) FROM folha_clt
      UNION ALL
      SELECT 'Benefícios', COALESCE(beneficios_empresa,0) FROM folha_clt
      UNION ALL
      SELECT 'Vale Transporte', COALESCE(vale_transporte,0) FROM folha_clt
      UNION ALL
      SELECT 'PJ', valor FROM pj_ultimo_mes
      UNION ALL
      SELECT 'Sócio', valor FROM socio_custo
    )
    GROUP BY 1
    ORDER BY 2 DESC
    """
    return _bq_query(query, "bigquery_bi")


# ─────────────────────────────────────────────
# ── PÁGINA 6: LIFETIME (ANÁLISE DE SOBREVIVÊNCIA) ─
# ─────────────────────────────────────────────
# Spec completa (decidida em sessão /grill-me 2026-09-03): vault Obsidian,
# G:\Meu Drive\Obisidian\Davi\Documentacoes\[FIN] Dashboard_Lifetime_Sobrevivencia.md

RMST_HORIZONTES_MESES = [6, 12, 24, 36]
_DIAS_POR_MES = 30.4368
_LIFETIME_N_MIN = 5  # amostra mínima por plano pra entrar em curva/RMST


@st.cache_data(ttl=72000)
def load_lifetime_base() -> pd.DataFrame:
    """
    Base de sobrevivência: 1 linha por cliente (st_sincro_sac) com t0
    (primeira liquidação, qualquer tipo), plano de entrada, última
    liquidação de mensalidade (1.2.2) e data de desativação total. A
    composição de evento/censura/duração é feita em Python
    (compute_lifetime_survival), não aqui — mantém a lógica de negócio
    legível e testável fora do SQL.

    - t0 = MIN(dt_liquidacao_recb) de QUALQUER liquidação (inclusive Setup).
    - Plano de entrada = classificação (_PLAN_CASE) da liquidação
      reconhecível MAIS ANTIGA do cliente — não trava no mesmo dia do t0,
      porque boa parte dos clientes paga o Setup isolado no dia 1 (t0), sem
      nenhum item de plano no mesmo boleto; casar só no dia do t0 jogava a
      maioria em 'outros' (medido: 55% -> 11% ao soltar essa trava).
    - Desativação total = cliente sem NENHUMA linha de mensalidade ativa
      hoje (`dt_fim_mens IS NULL`) em vw-splgc-tabela_mrr_validos, data =
      COALESCE(dt_desativacao_sac, MAX(dt_fim_mens) das linhas encerradas).
      dt_desativacao_sac é um campo do CLIENTE (não do produto), então não
      precisa da máquina de Branch 1/2/3 do churn-desativacoes — aquela
      existe pra atribuir R$ perdido por produto/mês, não pra saber SE o
      cliente ainda tem alguma mensalidade ativa.
    """
    query = f"""
    WITH liq AS (
      SELECT DISTINCT
        st_sincro_sac,
        CAST(dt_liquidacao_recb AS DATE) AS dt_liq,
        comp_st_conta_cont,
        comp_st_descricao_prd,
        comp_valor
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_liquidacao-all`
      WHERE SAFE_CAST(st_sincro_sac AS INT64) IS NOT NULL
        AND comp_valor > 0
    ),
    primeira_liq AS (
      SELECT st_sincro_sac, MIN(dt_liq) AS t0
      FROM liq
      GROUP BY st_sincro_sac
    ),
    plano_t0 AS (
      SELECT
        l.st_sincro_sac,
        {_PLAN_CASE.format(col="l.comp_st_descricao_prd")} AS plano
      FROM liq l
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY l.st_sincro_sac
        ORDER BY
          CASE WHEN {_PLAN_CASE.format(col="l.comp_st_descricao_prd")} != 'outros' THEN 0 ELSE 1 END,
          l.dt_liq ASC,
          l.comp_valor DESC
      ) = 1
    ),
    ultima_mensalidade AS (
      SELECT st_sincro_sac, MAX(dt_liq) AS ultima_liq_mensalidade
      FROM liq
      WHERE comp_st_conta_cont = '1.2.2'
      GROUP BY st_sincro_sac
    ),
    mrr_ativo AS (
      SELECT DISTINCT st_sincro_sac
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE dt_fim_mens IS NULL
        AND valor_total > 0
        AND st_descricao_prd NOT LIKE '%Setup%'
        AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
        AND {_EXCL_NAO_MENSALIDADE.format(col="st_descricao_prd")}
    ),
    mrr_ultima_fim AS (
      SELECT st_sincro_sac, MAX(CAST(dt_fim_mens AS DATE)) AS max_fim
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE dt_fim_mens IS NOT NULL
        AND valor_total > 0
        AND st_descricao_prd NOT LIKE '%Setup%'
        AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
        AND {_EXCL_NAO_MENSALIDADE.format(col="st_descricao_prd")}
      GROUP BY st_sincro_sac
    ),
    clientes_sac AS (
      SELECT st_sincro_sac, CAST(dt_desativacao_sac AS DATE) AS dt_desativacao_sac
      FROM `business-intelligence-467516.Splgc.splgc-clientes-inchurch`
      WHERE dt_desativacao_sac IS NOT NULL
    ),
    desativacao_total AS (
      SELECT
        pl.st_sincro_sac,
        COALESCE(cs.dt_desativacao_sac, mf.max_fim) AS data_desativacao
      FROM primeira_liq pl
      LEFT JOIN mrr_ultima_fim mf USING (st_sincro_sac)
      LEFT JOIN clientes_sac   cs USING (st_sincro_sac)
      LEFT JOIN mrr_ativo      ma USING (st_sincro_sac)
      WHERE ma.st_sincro_sac IS NULL
        AND (mf.max_fim IS NOT NULL OR cs.dt_desativacao_sac IS NOT NULL)
    )
    SELECT
      pl.st_sincro_sac,
      pt.plano,
      pl.t0,
      um.ultima_liq_mensalidade,
      dt.data_desativacao
    FROM primeira_liq pl
    LEFT JOIN plano_t0           pt USING (st_sincro_sac)
    LEFT JOIN ultima_mensalidade um USING (st_sincro_sac)
    LEFT JOIN desativacao_total  dt USING (st_sincro_sac)
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["t0"] = pd.to_datetime(df["t0"])
        df["ultima_liq_mensalidade"] = pd.to_datetime(df["ultima_liq_mensalidade"])
        df["data_desativacao"] = pd.to_datetime(df["data_desativacao"])
        df["plano"] = df["plano"].fillna("outros")
    return df


def compute_lifetime_survival(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aplica a lógica de evento/censura/duração sobre a base crua de
    load_lifetime_base(). Regras (spec completa no vault Obsidian):

    - Sem NENHUMA liquidação de mensalidade → perda imediata (duration=0):
      cliente que só pagou Setup/Adesão, nunca sustentou assinatura.
    - Inadimplência: >=90 dias corridos desde a última liquidação de
      mensalidade (dt_liquidacao_recb — nunca fl_status_recb, que reflete
      estado atual, não histórico).
    - Desativação: cliente sem nenhuma linha de mensalidade ativa hoje.
    - Perda = desativação OU inadimplência (90d). Data do evento, quando os
      dois disparam: a mais antiga das duas — captura o momento real em que
      o cliente parou de gerar valor, sem esperar a burocracia da
      desativação formal (que sabemos que atrasa, ver churn-desativacoes.md).
    - Sem nenhum critério disparado → censurado hoje (Kaplan-Meier).
    """
    if df.empty:
        return df

    df = df.copy()
    hoje = pd.Timestamp(date.today())

    tem_mensalidade = df["ultima_liq_mensalidade"].notna()
    dias_sem_pagar = (hoje - df["ultima_liq_mensalidade"]).dt.days
    inadimplente_90d = tem_mensalidade & (dias_sem_pagar >= 90)
    tem_desativacao = df["data_desativacao"].notna()

    evento = (~tem_mensalidade) | tem_desativacao | inadimplente_90d

    data_evento = pd.Series(hoje, index=df.index)
    mask = inadimplente_90d & ~tem_desativacao
    data_evento[mask] = df.loc[mask, "ultima_liq_mensalidade"]
    mask = tem_desativacao & ~inadimplente_90d
    data_evento[mask] = df.loc[mask, "data_desativacao"]
    mask = tem_desativacao & inadimplente_90d
    data_evento[mask] = df.loc[mask, ["data_desativacao", "ultima_liq_mensalidade"]].min(axis=1)
    mask = ~tem_mensalidade
    data_evento[mask] = df.loc[mask, "t0"]

    duration_dias = (data_evento - df["t0"]).dt.days.clip(lower=0)

    df["evento"] = evento.astype(int)
    df["data_evento"] = data_evento
    df["duration_dias"] = duration_dias
    df["duration_meses"] = duration_dias / _DIAS_POR_MES
    return df


def fit_km_por_plano(df: pd.DataFrame, n_min: int = _LIFETIME_N_MIN) -> dict:
    """
    Um KaplanMeierFitter por plano (só planos com >= n_min clientes).
    Retorna {plano: (kmf, n_clientes)}.
    """
    from lifelines import KaplanMeierFitter

    resultado = {}
    for plano, grupo in df.groupby("plano"):
        if len(grupo) < n_min:
            continue
        kmf = KaplanMeierFitter()
        kmf.fit(grupo["duration_meses"], event_observed=grupo["evento"], label=plano)
        resultado[plano] = (kmf, len(grupo))
    return resultado


def compute_rmst_snapshots(
    df: pd.DataFrame,
    horizontes: list[int] = RMST_HORIZONTES_MESES,
    n_min: int = _LIFETIME_N_MIN,
) -> pd.DataFrame:
    """
    RMST (restricted mean survival time, em meses) por plano, em cada
    horizonte de `horizontes`. Omite (None) horizontes maiores que o maior
    tempo observado (evento ou censura) naquele plano — evita RMST
    calculado sobre extrapolação (ex: plano com pouco tempo de mercado
    ainda não tem follow-up de 24/36 meses). Ver spec no vault.
    """
    from lifelines import KaplanMeierFitter
    from lifelines.utils import restricted_mean_survival_time

    linhas = []
    for plano, grupo in df.groupby("plano"):
        if len(grupo) < n_min:
            continue
        max_obs = grupo["duration_meses"].max()
        kmf = KaplanMeierFitter()
        kmf.fit(grupo["duration_meses"], event_observed=grupo["evento"])
        linha = {"plano": plano, "n_clientes": len(grupo)}
        for tau in horizontes:
            linha[f"rmst_{tau}m"] = (
                restricted_mean_survival_time(kmf, t=tau) if max_obs >= tau else None
            )
        linhas.append(linha)
    return pd.DataFrame(linhas)