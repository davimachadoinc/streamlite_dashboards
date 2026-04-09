"""
pages/1_📊_Cobranca.py
Dashboard de Cobrança — últimos 15 meses.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="Cobrança | InChurch", page_icon="📊", layout="wide")

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "cobranca"

from utils.style import inject_css
from utils.data import (
    PALETTE, MODULE_LABELS, MODULE_COLORS, PLAN_LABELS, PLAN_COLORS,
    chart_layout, mes_fmt_ordered, period_selector, filter_months,
    last_val, prev_val, delta_str, no_data,
    load_contratos_mensais, load_modulos_mensais, load_receita_modulos_mensais,
    load_receita_planos_mensais,
)

inject_css()

# ── Header ────────────────────────────────────
col_title, col_filter = st.columns([8, 2], vertical_alignment="bottom")
with col_title:
    st.markdown("<h1>Cobrança <span>& Receita</span></h1>", unsafe_allow_html=True)
with col_filter:
    n_months = period_selector()

# ── Carga ─────────────────────────────────────
with st.spinner("Carregando dados..."):
    df_contratos   = load_contratos_mensais()
    df_modulos     = load_modulos_mensais()
    df_rec_modulos = load_receita_modulos_mensais()
    df_rec_planos  = load_receita_planos_mensais()

df_contratos   = filter_months(df_contratos,   n_months, "mes")
df_modulos     = filter_months(df_modulos,     n_months, "mes")
df_rec_modulos = filter_months(df_rec_modulos, n_months, "mes")
df_rec_planos  = filter_months(df_rec_planos,  n_months, "mes")

# ── Toggle receita ────────────────────────────
col_toggle, _ = st.columns([3, 7])
with col_toggle:
    apenas_liquidado = st.toggle(
        "Apenas boletos liquidados",
        value=False,
        key="toggle_liquidacao",
        help="Ativado: soma comp_valor apenas de boletos pagos (fl_status_recb='1').",
    )

col_receita_valor = "receita_liquidada" if apenas_liquidado else "receita_emitida"
label_receita     = "Receita Liquidada (R$)" if apenas_liquidado else "Receita Emitida (R$)"

# ── KPI Cards ─────────────────────────────────
st.subheader("Visão Geral do Período")
k1, k2, k3, k4 = st.columns(4)

curr_cli  = last_val(df_contratos, "clientes_com_boleto", "mes")
prev_cli  = prev_val(df_contratos, "clientes_com_boleto", "mes")
with k1:
    st.metric("Clientes com Boleto", f"{int(curr_cli):,}" if curr_cli else "—",
              delta=delta_str(curr_cli, prev_cli))

for col_widget, modulo in zip([k2, k3, k4], ["kids", "jornada", "loja_inteligente"]):
    df_m = df_modulos[df_modulos["modulo"] == modulo] if "modulo" in df_modulos.columns else pd.DataFrame()
    curr = last_val(df_m, "clientes", "mes")
    prev = prev_val(df_m, "clientes", "mes")
    with col_widget:
        st.metric(f"Clientes · {MODULE_LABELS[modulo]}",
                  f"{int(curr):,}" if curr else "—",
                  delta=delta_str(curr, prev))

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 1 — Total de Clientes sob Contrato (largura inteira)
# ─────────────────────────────────────────────
st.subheader("Total de Clientes sob Contrato")
if df_contratos.empty:
    no_data()
else:
    df_plot, x_order = mes_fmt_ordered(df_contratos)
    fig = go.Figure()
    fig.add_bar(
        x=df_plot["mes_fmt"],
        y=df_plot["clientes_com_boleto"],
        marker_color=PALETTE[0],
        text=df_plot["clientes_com_boleto"].apply(lambda v: f"{int(v):,}"),
        textposition="outside",
        textfont=dict(size=11, color="#a0a0a0"),
    )
    fig.update_layout(
        showlegend=False,
        xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
    )
    st.plotly_chart(chart_layout(fig, height=360), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 2 — Módulos
# ─────────────────────────────────────────────
st.subheader("Módulos")
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("Clientes por Módulo Contratado")
    if df_modulos.empty:
        no_data()
    else:
        df_plot, x_order = mes_fmt_ordered(df_modulos)
        fig = go.Figure()
        for modulo, label in MODULE_LABELS.items():
            sub = df_plot[df_plot["modulo"] == modulo].sort_values("mes")
            if sub.empty:
                continue
            fig.add_scatter(
                x=sub["mes_fmt"], y=sub["clientes"],
                name=label, mode="lines+markers",
                line=dict(color=MODULE_COLORS[modulo], width=2.5),
                marker=dict(size=7),
            )
        fig.update_layout(
            xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
        )
        st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

with col_b:
    st.subheader(f"{label_receita} — Empilhado por Módulo")
    if df_rec_modulos.empty:
        no_data()
    else:
        df_plot, x_order = mes_fmt_ordered(df_rec_modulos)
        fig = go.Figure()
        for modulo, label in MODULE_LABELS.items():
            sub = df_plot[df_plot["modulo"] == modulo].sort_values("mes")
            if sub.empty:
                continue
            fig.add_bar(
                x=sub["mes_fmt"], y=sub[col_receita_valor],
                name=label, marker_color=MODULE_COLORS[modulo],
            )
        fig.update_layout(
            barmode="stack",
            xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
        )
        st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 3 — Planos
# ─────────────────────────────────────────────
st.subheader("Planos")
col_c, col_d = st.columns(2)

with col_c:
    st.subheader("Clientes por Plano Contratado")
    if df_rec_planos.empty or "clientes" not in df_rec_planos.columns:
        no_data()
    else:
        df_plot, x_order = mes_fmt_ordered(df_rec_planos)
        fig = go.Figure()
        for plano, label in PLAN_LABELS.items():
            sub = df_plot[df_plot["plano"] == plano].sort_values("mes")
            if sub.empty:
                continue
            fig.add_scatter(
                x=sub["mes_fmt"], y=sub["clientes"],
                name=label, mode="lines+markers",
                line=dict(color=PLAN_COLORS[plano], width=2.5),
                marker=dict(size=7),
            )
        fig.update_layout(
            xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
        )
        st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

with col_d:
    st.subheader(f"{label_receita} — Empilhado por Plano")
    if df_rec_planos.empty:
        no_data()
    else:
        df_plot, x_order = mes_fmt_ordered(df_rec_planos)
        fig = go.Figure()
        for plano, label in PLAN_LABELS.items():
            sub = df_plot[df_plot["plano"] == plano].sort_values("mes")
            if sub.empty:
                continue
            fig.add_bar(
                x=sub["mes_fmt"], y=sub[col_receita_valor],
                name=label, marker_color=PLAN_COLORS[plano],
            )
        fig.update_layout(
            barmode="stack",
            xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
        )
        st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 4 — Receita Total: Emitida vs Liquidada (largura inteira)
# ─────────────────────────────────────────────
st.subheader("Receita Total: Emitida vs Liquidada")
if df_contratos.empty:
    no_data()
else:
    df_plot, x_order = mes_fmt_ordered(df_contratos)
    fig = go.Figure()
    fig.add_bar(
        x=df_plot["mes_fmt"], y=df_plot["receita_total"],
        name="Emitida", marker_color=PALETTE[4], opacity=0.8,
    )
    fig.add_bar(
        x=df_plot["mes_fmt"], y=df_plot["receita_liquidada"],
        name="Liquidada", marker_color=PALETTE[0], opacity=0.9,
    )
    fig.update_layout(
        barmode="overlay",
        xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
    )
    st.plotly_chart(chart_layout(fig, height=380, legend_bottom=True), use_container_width=True)
