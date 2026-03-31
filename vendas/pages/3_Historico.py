"""
pages/3_📊_Histórico.py
Gráficos históricos de fechamentos — FYV, Mensalidade, por Vendedor e Canal.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(
    page_title="Histórico | InChurch",
    page_icon="📊",
    layout="wide",
)

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "historico"

from utils.style import inject_css
from utils.data import (
    load_fechamentos, PALETTE, chart_layout, mes_fmt_ordered,
    period_selector, filter_months, fmt_brl,
)

inject_css()

# ── Header ──────────────────────────────────────
st.markdown("<h1>Histórico <span>de Fechamentos</span></h1>", unsafe_allow_html=True)

# ── Sidebar ─────────────────────────────────────
with st.sidebar:
    st.markdown("### 🗓️ Período")
    n_months = period_selector(default_idx=2)  # default: últimos 12 meses

    st.divider()
    user_name  = getattr(st.user, "name", st.user.email)
    user_email = st.user.email
    st.markdown(
        f"<p style='color:#a0a0a0; font-size:0.82rem; margin-bottom:2px;'>👤 {user_name}</p>"
        f"<p style='color:#4c4c4c; font-size:0.75rem; margin-bottom:16px;'>{user_email}</p>",
        unsafe_allow_html=True,
    )
    if st.button("🚪 Sair", use_container_width=True):
        st.logout()

# ── Carga de dados ───────────────────────────────
with st.spinner("Carregando dados..."):
    df_raw = load_fechamentos()

if df_raw.empty:
    st.info("Nenhum dado encontrado na base.", icon="ℹ️")
    st.stop()

# ── Preparar coluna de mês ───────────────────────
df_raw = df_raw.copy()
df_raw["mes"] = df_raw["first_payment"].dt.to_period("M").dt.to_timestamp()

df = filter_months(df_raw, n_months, "mes")

if df.empty:
    st.info("Nenhum dado no período selecionado.", icon="ℹ️")
    st.stop()

# ─────────────────────────────────────────────
# SEÇÃO 1 — FYV e Mensalidade por Mês
# ─────────────────────────────────────────────
st.subheader("FYV & Mensalidade por Mês")

df_month = (
    df.groupby("mes")
    .agg(FYV=("FYV", "sum"), mensalidade=("value", "sum"), n=("value", "count"))
    .reset_index()
)

col_fyv, col_mrr = st.columns(2)

with col_fyv:
    st.subheader("FYV Total por Mês")
    df_plot, x_order = mes_fmt_ordered(df_month)
    fig = go.Figure()
    fig.add_bar(
        x=df_plot["mes_fmt"],
        y=df_plot["FYV"],
        marker_color=PALETTE[0],
        text=df_plot["FYV"].apply(lambda v: f"R$ {v:,.0f}".replace(",", ".")),
        textposition="outside",
        textfont=dict(size=10, color="#a0a0a0"),
    )
    fig.update_layout(xaxis=dict(categoryorder="array", categoryarray=x_order))
    st.plotly_chart(chart_layout(fig, height=360), use_container_width=True)

with col_mrr:
    st.subheader("Mensalidade (MRR) por Mês")
    df_plot, x_order = mes_fmt_ordered(df_month)
    fig = go.Figure()
    fig.add_bar(
        x=df_plot["mes_fmt"],
        y=df_plot["mensalidade"],
        marker_color=PALETTE[1],
        text=df_plot["mensalidade"].apply(lambda v: f"R$ {v:,.0f}".replace(",", ".")),
        textposition="outside",
        textfont=dict(size=10, color="#a0a0a0"),
    )
    fig.update_layout(xaxis=dict(categoryorder="array", categoryarray=x_order))
    st.plotly_chart(chart_layout(fig, height=360), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 2 — Nº de Vendas por Mês
# ─────────────────────────────────────────────
st.subheader("Número de Fechamentos por Mês")
df_plot, x_order = mes_fmt_ordered(df_month)
fig = go.Figure()
fig.add_bar(
    x=df_plot["mes_fmt"],
    y=df_plot["n"],
    marker_color=PALETTE[6],
    text=df_plot["n"].astype(int),
    textposition="outside",
    textfont=dict(size=11, color="#a0a0a0"),
)
fig.update_layout(
    showlegend=False,
    xaxis=dict(categoryorder="array", categoryarray=x_order),
)
st.plotly_chart(chart_layout(fig, height=340), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 3 — Por Vendedor
# ─────────────────────────────────────────────
st.subheader("Por Vendedor")
col_a, col_b = st.columns(2)

df_vend = (
    df.groupby(["mes", "sales_owner"])
    .agg(FYV=("FYV", "sum"), mensalidade=("value", "sum"))
    .reset_index()
)
vendedores_sorted = (
    df_vend.groupby("sales_owner")["FYV"].sum()
    .sort_values(ascending=False)
    .index.tolist()
)
# color cycle for vendedores
_colors = [PALETTE[i % len(PALETTE)] for i in range(len(vendedores_sorted))]

with col_a:
    st.subheader("FYV por Vendedor — Mês a Mês")
    if df_vend.empty:
        st.info("Sem dados.", icon="ℹ️")
    else:
        df_plot, x_order = mes_fmt_ordered(df_vend)
        fig = go.Figure()
        for i, vend in enumerate(vendedores_sorted):
            sub = df_plot[df_plot["sales_owner"] == vend].sort_values("mes")
            if sub.empty:
                continue
            fig.add_scatter(
                x=sub["mes_fmt"], y=sub["FYV"],
                name=vend, mode="lines+markers",
                line=dict(color=_colors[i], width=2),
                marker=dict(size=6),
            )
        fig.update_layout(xaxis=dict(categoryorder="array", categoryarray=x_order))
        st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

with col_b:
    st.subheader("Mensalidade por Vendedor — Mês a Mês")
    if df_vend.empty:
        st.info("Sem dados.", icon="ℹ️")
    else:
        df_plot, x_order = mes_fmt_ordered(df_vend)
        fig = go.Figure()
        for i, vend in enumerate(vendedores_sorted):
            sub = df_plot[df_plot["sales_owner"] == vend].sort_values("mes")
            if sub.empty:
                continue
            fig.add_scatter(
                x=sub["mes_fmt"], y=sub["mensalidade"],
                name=vend, mode="lines+markers",
                line=dict(color=_colors[i], width=2),
                marker=dict(size=6),
            )
        fig.update_layout(xaxis=dict(categoryorder="array", categoryarray=x_order))
        st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 4 — Por Canal
# ─────────────────────────────────────────────
st.subheader("Por Canal")
col_c, col_d = st.columns(2)

df_canal = (
    df.groupby(["mes", "channel"])
    .agg(FYV=("FYV", "sum"), mensalidade=("value", "sum"))
    .reset_index()
)
canais_sorted = (
    df_canal.groupby("channel")["FYV"].sum()
    .sort_values(ascending=False)
    .index.tolist()
)
_canal_colors = [PALETTE[i % len(PALETTE)] for i in range(len(canais_sorted))]

with col_c:
    st.subheader("FYV por Canal — Mês a Mês")
    if df_canal.empty:
        st.info("Sem dados.", icon="ℹ️")
    else:
        df_plot, x_order = mes_fmt_ordered(df_canal)
        fig = go.Figure()
        for i, canal in enumerate(canais_sorted):
            sub = df_plot[df_plot["channel"] == canal].sort_values("mes")
            if sub.empty:
                continue
            fig.add_scatter(
                x=sub["mes_fmt"], y=sub["FYV"],
                name=canal, mode="lines+markers",
                line=dict(color=_canal_colors[i], width=2),
                marker=dict(size=6),
            )
        fig.update_layout(xaxis=dict(categoryorder="array", categoryarray=x_order))
        st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

with col_d:
    st.subheader("FYV por Canal — Empilhado")
    if df_canal.empty:
        st.info("Sem dados.", icon="ℹ️")
    else:
        df_plot, x_order = mes_fmt_ordered(df_canal)
        fig = go.Figure()
        for i, canal in enumerate(canais_sorted):
            sub = df_plot[df_plot["channel"] == canal].sort_values("mes")
            if sub.empty:
                continue
            fig.add_bar(
                x=sub["mes_fmt"], y=sub["FYV"],
                name=canal, marker_color=_canal_colors[i],
            )
        fig.update_layout(
            barmode="stack",
            xaxis=dict(categoryorder="array", categoryarray=x_order),
        )
        st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)
