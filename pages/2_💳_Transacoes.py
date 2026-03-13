"""
pages/2_💳_Transacoes.py
Dashboard de Transações — últimos 15 meses.
Métodos: pix, credit, billet (excluídos: free, external, debit).
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

if not st.session_state.get("authenticated"):
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.set_page_config(page_title="Transações | InChurch", page_icon="💳", layout="wide")
st.session_state["_page_key"] = "transacoes"

from utils.style import inject_css
from utils.data import (
    PALETTE, chart_layout, mes_fmt_ordered, period_selector, filter_months,
    last_val, prev_val, delta_str, no_data,
    load_transactions_por_metodo,
)

inject_css()

METHOD_PALETTE = {
    "pix":    "#6eda2c",
    "credit": "#ffffff",
    "billet": "#a0a0a0",
}

def method_color(m: str) -> str:
    colors = ["#6eda2c","#ffffff","#57d124","#a0a0a0","#8ae650","#3ba811","#cccccc"]
    keys = list(METHOD_PALETTE.keys())
    if m in METHOD_PALETTE:
        return METHOD_PALETTE[m]
    idx = hash(m) % len(colors)
    return colors[idx]

# ── Header ────────────────────────────────────
col_title, col_filter = st.columns([8, 2], vertical_alignment="bottom")
with col_title:
    st.markdown("<h1>Transações <span>por Método</span></h1>", unsafe_allow_html=True)
with col_filter:
    n_months = period_selector()

# ── Carga ─────────────────────────────────────
with st.spinner("Carregando dados de transações..."):
    df_raw = load_transactions_por_metodo()

if df_raw.empty:
    no_data("Nenhum dado de transação encontrado.")
    st.stop()

# ── Filtro de canal (sidebar) ─────────────────
with st.sidebar:
    st.markdown("### 📡 Canal de Pagamento")
    channels = sorted(df_raw["payment_channel"].dropna().unique().tolist())
    selected_channels = st.multiselect(
        "Filtrar por canal", options=channels, default=channels, key="filter_channels"
    )

if not selected_channels:
    st.warning("Selecione ao menos um canal.", icon="⚠️")
    st.stop()

# ── Aplicar filtros ───────────────────────────
df = df_raw[df_raw["payment_channel"].isin(selected_channels)].copy()
df = filter_months(df, n_months, "mes")

if df.empty:
    no_data("Nenhuma transação com os filtros selecionados.")
    st.stop()

# Agrupa por mês + método
df_agg = (
    df.groupby(["mes", "payment_method"], as_index=False)
    .agg(total_value=("total_value", "sum"), qtd=("qtd_transacoes", "sum"))
)
df_agg, x_order = mes_fmt_ordered(df_agg)

# Total geral por mês
df_total = df_agg.groupby("mes", as_index=False).agg(
    total_value=("total_value", "sum"), qtd=("qtd", "sum")
).sort_values("mes")
df_total, x_order_total = mes_fmt_ordered(df_total)

methods = sorted(df_agg["payment_method"].unique().tolist())

# ── KPI Cards ─────────────────────────────────
st.subheader("Visão Geral do Período")
k1, k2, k3, k4 = st.columns(4)

curr_val = last_val(df_total, "total_value", "mes")
prev_val_ = prev_val(df_total, "total_value", "mes")
with k1:
    st.metric("Volume Total (R$)",
              f"R$ {curr_val:,.2f}" if curr_val else "—",
              delta=delta_str(curr_val, prev_val_, fmt="+,.2f", suffix=" R$"))

curr_qtd = last_val(df_total, "qtd", "mes")
prev_qtd = prev_val(df_total, "qtd", "mes")
with k2:
    st.metric("Qtd. de Transações",
              f"{int(curr_qtd):,}" if curr_qtd else "—",
              delta=delta_str(curr_qtd, prev_qtd))

ticket    = (curr_val / curr_qtd) if (curr_val and curr_qtd and curr_qtd > 0) else None
prev_tick = (prev_val_ / prev_qtd) if (prev_val_ and prev_qtd and prev_qtd > 0) else None
with k3:
    st.metric("Ticket Médio",
              f"R$ {ticket:,.2f}" if ticket else "—",
              delta=delta_str(ticket, prev_tick, fmt="+,.2f", suffix=" R$"))

with k4:
    st.metric("Métodos Ativos", str(len(methods)))

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 1 — Volume por Método
# ─────────────────────────────────────────────
st.subheader("Volume Financeiro por Método de Pagamento")
col_a, col_b = st.columns(2)

# Gráfico 1A — Barras empilhadas
with col_a:
    st.subheader("Volume (R$) — Empilhado por Método")
    fig = go.Figure()
    for method in methods:
        sub = df_agg[df_agg["payment_method"] == method].sort_values("mes")
        fig.add_bar(x=sub["mes_fmt"], y=sub["total_value"],
                    name=method, marker_color=method_color(method))
    fig.update_layout(
        barmode="stack",
        xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
    )
    st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

# Gráfico 1B — Barras agrupadas
with col_b:
    st.subheader("Volume (R$) — Comparativo por Método")
    fig = go.Figure()
    for method in methods:
        sub = df_agg[df_agg["payment_method"] == method].sort_values("mes")
        fig.add_bar(x=sub["mes_fmt"], y=sub["total_value"],
                    name=method, marker_color=method_color(method))
    fig.update_layout(
        barmode="group",
        xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
    )
    st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 2 — Tendência e Distribuição
# ─────────────────────────────────────────────
st.subheader("Tendência e Distribuição")
col_c, col_d = st.columns(2)

# Gráfico 2A — Linhas de tendência
with col_c:
    st.subheader("Tendência de Volume por Método")
    fig = go.Figure()
    for method in methods:
        sub = df_agg[df_agg["payment_method"] == method].sort_values("mes")
        fig.add_scatter(
            x=sub["mes_fmt"], y=sub["total_value"],
            name=method, mode="lines+markers",
            line=dict(color=method_color(method), width=2.5),
            marker=dict(size=6),
        )
    fig.update_layout(
        xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
    )
    st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

# Gráfico 2B — Participação % último mês (pizza)
with col_d:
    st.subheader("Participação por Método — Último Mês")
    last_month = df_agg["mes"].max()
    df_last = df_agg[df_agg["mes"] == last_month]
    if df_last.empty:
        no_data()
    else:
        fig = go.Figure(go.Pie(
            labels=df_last["payment_method"],
            values=df_last["total_value"],
            hole=0.45,
            marker_colors=[method_color(m) for m in df_last["payment_method"]],
            textfont=dict(size=12, family="Outfit"),
        ))
        fig.update_traces(
            texttemplate="%{label}<br>%{percent}",
            hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>%{percent}<extra></extra>",
        )
        st.plotly_chart(chart_layout(fig, height=360), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 3 — Volume Total + Qtd (dual axis)
# ─────────────────────────────────────────────
st.subheader("Volume Total (R$) e Quantidade de Transações")
fig = go.Figure()
fig.add_bar(
    x=df_total["mes_fmt"], y=df_total["total_value"],
    name="Volume (R$)", marker_color=PALETTE[0], opacity=0.85, yaxis="y",
)
fig.add_scatter(
    x=df_total["mes_fmt"], y=df_total["qtd"],
    name="Qtd. Transações", mode="lines+markers",
    line=dict(color=PALETTE[1], width=2.5), marker=dict(size=7), yaxis="y2",
)
fig.update_layout(
    yaxis2=dict(overlaying="y", side="right", showgrid=False, color=PALETTE[1]),
    xaxis=dict(categoryorder="array", categoryarray=x_order_total, type="category"),
)
st.plotly_chart(chart_layout(fig, height=400, legend_bottom=True), use_container_width=True)

# ── Tabela detalhada ──────────────────────────
with st.expander("📋 Tabela Detalhada por Mês e Método"):
    df_table = (
        df_agg
        .pivot_table(index="mes_fmt", columns="payment_method",
                     values="total_value", aggfunc="sum")
        .round(2).reset_index().rename(columns={"mes_fmt": "Mês"})
    )
    st.dataframe(df_table, use_container_width=True, hide_index=True)