"""
pages/2_💳_Transacoes.py
Dashboard de Transações — últimos 15 meses.

- Soma de value por payment_method (status: active | payed)
- Filtro por payment_channel
- Breakdown mensal e comparativo por método
"""
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

# ── Guard de autenticação ─────────────────────
if not st.session_state.get("authenticated"):
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

# ── Config & Injeção ──────────────────────────
st.set_page_config(page_title="Transações | InChurch", page_icon="💳", layout="wide")
st.session_state["_page_key"] = "transacoes"

from utils.style import inject_css
from utils.data import (
    PALETTE, chart_layout, period_selector, filter_months,
    last_val, prev_val, delta_str, no_data,
    load_transactions_por_metodo,
)

inject_css()

# ─────────────────────────────────────────────
# PALETA POR MÉTODO (dinâmica — até 10 métodos)
# ─────────────────────────────────────────────
METHOD_PALETTE = [
    "#6eda2c", "#ffffff", "#57d124", "#a0a0a0",
    "#4c4c4c", "#8ae650", "#3ba811", "#cccccc", "#e0ff99", "#2d7a00",
]


def method_color_map(methods: list[str]) -> dict[str, str]:
    return {m: METHOD_PALETTE[i % len(METHOD_PALETTE)] for i, m in enumerate(sorted(methods))}


# ─────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────
col_title, col_filter = st.columns([8, 2], vertical_alignment="bottom")
with col_title:
    st.markdown("<h1>Transações <span>por Método</span></h1>", unsafe_allow_html=True)
with col_filter:
    n_months = period_selector()

# ─────────────────────────────────────────────
# CARGA DE DADOS
# ─────────────────────────────────────────────
with st.spinner("Carregando dados de transações..."):
    df_raw = load_transactions_por_metodo()

if df_raw.empty:
    no_data("Nenhum dado de transação encontrado para o período.")
    st.stop()

# ─────────────────────────────────────────────
# FILTRO DE PAYMENT_CHANNEL (sidebar)
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📡 Canal de Pagamento")
    channels_available = sorted(df_raw["payment_channel"].dropna().unique().tolist())

    selected_channels = st.multiselect(
        "Filtrar por canal",
        options=channels_available,
        default=channels_available,
        key="filter_channels",
        placeholder="Selecione canais...",
    )

if not selected_channels:
    st.warning("Selecione ao menos um canal de pagamento na barra lateral.", icon="⚠️")
    st.stop()

# ─────────────────────────────────────────────
# APLICAR FILTROS
# ─────────────────────────────────────────────
df = df_raw[df_raw["payment_channel"].isin(selected_channels)].copy()
df = filter_months(df, n_months, "mes")

if df.empty:
    no_data("Nenhuma transação encontrada com os filtros selecionados.")
    st.stop()

# Agrupado por mês + método (após filtro de canal)
df_agg = (
    df.groupby(["mes", "payment_method"], as_index=False)
    .agg(total_value=("total_value", "sum"), qtd=("qtd_transacoes", "sum"))
)
df_agg["mes_fmt"] = df_agg["mes"].dt.strftime("%b/%y")

methods = sorted(df_agg["payment_method"].unique().tolist())
color_map = method_color_map(methods)

# Total geral por mês (para KPIs)
df_total = df_agg.groupby("mes", as_index=False).agg(
    total_value=("total_value", "sum"),
    qtd=("qtd", "sum"),
)
df_total = df_total.sort_values("mes")

# ─────────────────────────────────────────────
# KPI CARDS
# ─────────────────────────────────────────────
st.subheader("Visão Geral do Período")

k1, k2, k3, k4 = st.columns(4)

# Volume total (último mês)
curr_val  = last_val(df_total, "total_value", "mes")
prev_val_ = prev_val(df_total, "total_value", "mes")
with k1:
    st.metric(
        "Volume Total (R$)",
        f"R$ {curr_val:,.2f}" if curr_val else "—",
        delta=delta_str(curr_val, prev_val_, fmt="+,.2f", suffix=" R$"),
        help="Soma de value (status active/payed) no último mês completo",
    )

# Qtd de transações (último mês)
curr_qtd = last_val(df_total, "qtd", "mes")
prev_qtd = prev_val(df_total, "qtd", "mes")
with k2:
    st.metric(
        "Qtd. de Transações",
        f"{int(curr_qtd):,}" if curr_qtd else "—",
        delta=delta_str(curr_qtd, prev_qtd),
        help="Número de transações no último mês completo",
    )

# Ticket médio (último mês)
ticket = (curr_val / curr_qtd) if (curr_val and curr_qtd and curr_qtd > 0) else None
prev_t = (prev_val_ / prev_qtd) if (prev_val_ and prev_qtd and prev_qtd > 0) else None
with k3:
    st.metric(
        "Ticket Médio",
        f"R$ {ticket:,.2f}" if ticket else "—",
        delta=delta_str(ticket, prev_t, fmt="+,.2f", suffix=" R$"),
        help="Valor médio por transação no último mês completo",
    )

# Métodos ativos
with k4:
    st.metric(
        "Métodos Ativos",
        str(len(methods)),
        help="Número de métodos de pagamento distintos com transações no período",
    )

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 1 — Volume por Método (barras mensais)
# ─────────────────────────────────────────────
st.subheader("Volume Financeiro por Método de Pagamento")

col_a, col_b = st.columns(2)

# ── Gráfico 1A: Barras empilhadas por método ──
with col_a:
    st.subheader("Volume (R$) — Empilhado por Método")
    pivot = (
        df_agg
        .pivot_table(index="mes_fmt", columns="payment_method", values="total_value", aggfunc="sum")
        .reset_index()
    )

    fig = go.Figure()
    for method in methods:
        if method not in pivot.columns:
            continue
        fig.add_bar(
            x=pivot["mes_fmt"],
            y=pivot[method],
            name=method,
            marker_color=color_map[method],
        )
    fig.update_layout(barmode="stack")
    st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

# ── Gráfico 1B: Barras agrupadas por método ──
with col_b:
    st.subheader("Volume (R$) — Comparativo por Método")
    fig = go.Figure()
    for method in methods:
        sub = df_agg[df_agg["payment_method"] == method]
        fig.add_bar(
            x=sub["mes_fmt"],
            y=sub["total_value"],
            name=method,
            marker_color=color_map[method],
        )
    fig.update_layout(barmode="group")
    st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 2 — Tendência e Distribuição
# ─────────────────────────────────────────────
st.subheader("Tendência e Distribuição")

col_c, col_d = st.columns(2)

# ── Gráfico 2A: Linhas de tendência por método ──
with col_c:
    st.subheader("Tendência de Volume por Método")
    fig = go.Figure()
    for method in methods:
        sub = df_agg[df_agg["payment_method"] == method].sort_values("mes")
        fig.add_scatter(
            x=sub["mes_fmt"],
            y=sub["total_value"],
            name=method,
            mode="lines+markers",
            line=dict(color=color_map[method], width=2.5),
            marker=dict(size=6),
        )
    st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

# ── Gráfico 2B: Participação % por método (último mês) ──
with col_d:
    st.subheader("Participação por Método — Último Mês")
    last_month = df_agg["mes"].max()
    df_last = df_agg[df_agg["mes"] == last_month]
    if df_last.empty:
        no_data()
    else:
        fig = go.Figure(
            go.Pie(
                labels=df_last["payment_method"],
                values=df_last["total_value"],
                hole=0.45,
                marker_colors=[color_map[m] for m in df_last["payment_method"]],
                textfont=dict(size=12, family="Outfit"),
                insidetextorientation="horizontal",
            )
        )
        fig.update_traces(
            texttemplate="%{label}<br>%{percent}",
            hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>%{percent}<extra></extra>",
        )
        st.plotly_chart(chart_layout(fig, height=360), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 3 — Volume Total + Qtd Transações (dual axis)
# ─────────────────────────────────────────────
st.subheader("Volume Total (R$) e Quantidade de Transações")

fig = go.Figure()
fig.add_bar(
    x=df_total["mes"].dt.strftime("%b/%y"),
    y=df_total["total_value"],
    name="Volume (R$)",
    marker_color=PALETTE[0],
    opacity=0.85,
    yaxis="y",
)
fig.add_scatter(
    x=df_total["mes"].dt.strftime("%b/%y"),
    y=df_total["qtd"],
    name="Qtd. Transações",
    mode="lines+markers",
    line=dict(color=PALETTE[1], width=2.5),
    marker=dict(size=7),
    yaxis="y2",
)
fig.update_layout(
    yaxis2=dict(
        overlaying="y",
        side="right",
        showgrid=False,
        color=PALETTE[1],
        title="Qtd.",
    ),
)
st.plotly_chart(chart_layout(fig, height=400, legend_bottom=True), use_container_width=True)

# ─────────────────────────────────────────────
# TABELA DETALHADA (expandível)
# ─────────────────────────────────────────────
with st.expander("📋 Tabela Detalhada por Mês e Método"):
    df_table = (
        df_agg
        .assign(mes_fmt=df_agg["mes"].dt.strftime("%b/%y"))
        .pivot_table(index="mes_fmt", columns="payment_method", values="total_value", aggfunc="sum")
        .round(2)
        .reset_index()
        .rename(columns={"mes_fmt": "Mês"})
    )
    st.dataframe(
        df_table,
        use_container_width=True,
        hide_index=True,
    )
