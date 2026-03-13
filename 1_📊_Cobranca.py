"""
pages/1_📊_Cobranca.py
Dashboard de Cobrança e Módulos — últimos 15 meses.

Seção 1: Clientes sob contrato (boleto emitido) + módulos Kids / Jornada / Loja Inteligente
Seção 2: Receita por módulo (com toggle de liquidação)
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
st.set_page_config(page_title="Cobrança | InChurch", page_icon="📊", layout="wide")
st.session_state["_page_key"] = "cobranca"

from utils.style import inject_css
from utils.data import (
    PALETTE, MODULE_LABELS, MODULE_COLORS,
    chart_layout, period_selector, filter_months,
    last_val, prev_val, delta_str, no_data,
    load_contratos_mensais, load_modulos_mensais, load_receita_modulos_mensais,
)

inject_css()

# ─────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────
col_title, col_filter = st.columns([8, 2], vertical_alignment="bottom")
with col_title:
    st.markdown("<h1>Cobrança <span>& Módulos</span></h1>", unsafe_allow_html=True)
with col_filter:
    n_months = period_selector()

# ─────────────────────────────────────────────
# CARGA DE DADOS
# ─────────────────────────────────────────────
with st.spinner("Carregando dados de cobrança..."):
    df_contratos   = load_contratos_mensais()
    df_modulos     = load_modulos_mensais()
    df_rec_modulos = load_receita_modulos_mensais()

# Filtrar período
df_contratos   = filter_months(df_contratos,   n_months, "mes")
df_modulos     = filter_months(df_modulos,     n_months, "mes")
df_rec_modulos = filter_months(df_rec_modulos, n_months, "mes")

# ─────────────────────────────────────────────
# KPI CARDS — Linha de métricas principais
# ─────────────────────────────────────────────
st.subheader("Visão Geral do Período")

k1, k2, k3, k4 = st.columns(4)

# 1. Total de clientes com boleto (último mês)
curr_cli = last_val(df_contratos, "clientes_com_boleto", "mes")
prev_cli = prev_val(df_contratos, "clientes_com_boleto", "mes")
with k1:
    st.metric(
        "Clientes com Boleto",
        f"{int(curr_cli):,}" if curr_cli else "—",
        delta=delta_str(curr_cli, prev_cli),
        help="Clientes únicos com ao menos 1 boleto emitido no último mês completo",
    )

# 2. Kids
df_kids = df_modulos[df_modulos["modulo"] == "kids"]
curr_kids = last_val(df_kids, "clientes", "mes")
prev_kids = prev_val(df_kids, "clientes", "mes")
with k2:
    st.metric(
        "Clientes · Kids",
        f"{int(curr_kids):,}" if curr_kids else "—",
        delta=delta_str(curr_kids, prev_kids),
        help="Clientes com módulo Kids ativo e boleto emitido",
    )

# 3. Jornada
df_jornada = df_modulos[df_modulos["modulo"] == "jornada"]
curr_jornada = last_val(df_jornada, "clientes", "mes")
prev_jornada = prev_val(df_jornada, "clientes", "mes")
with k3:
    st.metric(
        "Clientes · Jornada",
        f"{int(curr_jornada):,}" if curr_jornada else "—",
        delta=delta_str(curr_jornada, prev_jornada),
        help="Clientes com módulo Jornada ativo e boleto emitido",
    )

# 4. Loja Inteligente
df_loja = df_modulos[df_modulos["modulo"] == "loja_inteligente"]
curr_loja = last_val(df_loja, "clientes", "mes")
prev_loja = prev_val(df_loja, "clientes", "mes")
with k4:
    st.metric(
        "Clientes · Loja Inteligente",
        f"{int(curr_loja):,}" if curr_loja else "—",
        delta=delta_str(curr_loja, prev_loja),
        help="Clientes com módulo Loja Inteligente ativo e boleto emitido",
    )

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 1 — Clientes com boleto emitido + Módulos
# ─────────────────────────────────────────────
st.subheader("Clientes com Boleto Emitido")

col_a, col_b = st.columns(2)

# ── Gráfico 1A: Total de clientes com boleto ──
with col_a:
    st.subheader("Total de Clientes sob Contrato")
    if df_contratos.empty:
        no_data()
    else:
        df_plot = df_contratos.copy()
        df_plot["mes_fmt"] = df_plot["mes"].dt.strftime("%b/%y")

        fig = go.Figure()
        fig.add_bar(
            x=df_plot["mes_fmt"],
            y=df_plot["clientes_com_boleto"],
            name="Clientes",
            marker_color=PALETTE[0],
            text=df_plot["clientes_com_boleto"].apply(lambda v: f"{int(v):,}"),
            textposition="outside",
            textfont=dict(size=11, color="#a0a0a0"),
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(chart_layout(fig), use_container_width=True)

# ── Gráfico 1B: Boletos emitidos por módulo ───
with col_b:
    st.subheader("Clientes por Módulo Contratado")
    if df_modulos.empty:
        no_data()
    else:
        # Pivot para linhas por módulo
        pivot = (
            df_modulos
            .assign(mes_fmt=df_modulos["mes"].dt.strftime("%b/%y"))
            .pivot_table(index="mes_fmt", columns="modulo", values="clientes", aggfunc="sum")
            .reset_index()
        )

        fig = go.Figure()
        for modulo, label in MODULE_LABELS.items():
            if modulo not in pivot.columns:
                continue
            fig.add_scatter(
                x=pivot["mes_fmt"],
                y=pivot[modulo],
                name=label,
                mode="lines+markers",
                line=dict(color=MODULE_COLORS[modulo], width=2),
                marker=dict(size=6),
            )
        st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

# ── Gráfico 1C: Total de boletos emitidos (linha + barras) ───
st.subheader("Volume Total de Boletos Emitidos")
if df_contratos.empty:
    no_data()
else:
    df_plot = df_contratos.copy()
    df_plot["mes_fmt"] = df_plot["mes"].dt.strftime("%b/%y")

    fig = go.Figure()
    fig.add_bar(
        x=df_plot["mes_fmt"],
        y=df_plot["total_boletos"],
        name="Boletos Emitidos",
        marker_color=PALETTE[0],
        opacity=0.85,
    )
    st.plotly_chart(chart_layout(fig), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 2 — Receita por Módulo
# ─────────────────────────────────────────────
st.subheader("Receita por Módulo")

# Toggle de liquidação
col_toggle, _ = st.columns([3, 7])
with col_toggle:
    apenas_liquidado = st.toggle(
        "Considerar apenas boletos liquidados",
        value=False,
        key="toggle_liquidacao",
        help="Ativado: soma apenas receita com dt_liquidacao (fl_status_recb = '1'). "
             "Desativado: soma toda receita emitida.",
    )

col_receita_valor = "receita_liquidada" if apenas_liquidado else "receita_emitida"
label_receita = "Receita Liquidada (R$)" if apenas_liquidado else "Receita Emitida (R$)"

col_c, col_d = st.columns(2)

# ── Gráfico 2A: Receita total por módulo (barras empilhadas) ──
with col_c:
    st.subheader(f"{label_receita} — Empilhado por Módulo")
    if df_rec_modulos.empty:
        no_data()
    else:
        pivot_rec = (
            df_rec_modulos
            .assign(mes_fmt=df_rec_modulos["mes"].dt.strftime("%b/%y"))
            .pivot_table(
                index="mes_fmt", columns="modulo",
                values=col_receita_valor, aggfunc="sum",
            )
            .reset_index()
        )

        fig = go.Figure()
        for modulo, label in MODULE_LABELS.items():
            if modulo not in pivot_rec.columns:
                continue
            fig.add_bar(
                x=pivot_rec["mes_fmt"],
                y=pivot_rec[modulo],
                name=label,
                marker_color=MODULE_COLORS[modulo],
            )
        fig.update_layout(barmode="stack")
        st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

# ── Gráfico 2B: Receita por módulo (linha de tendência) ──
with col_d:
    st.subheader(f"{label_receita} — Tendência por Módulo")
    if df_rec_modulos.empty:
        no_data()
    else:
        pivot_rec_line = (
            df_rec_modulos
            .assign(mes_fmt=df_rec_modulos["mes"].dt.strftime("%b/%y"))
            .pivot_table(
                index="mes_fmt", columns="modulo",
                values=col_receita_valor, aggfunc="sum",
            )
            .reset_index()
        )

        fig = go.Figure()
        for modulo, label in MODULE_LABELS.items():
            if modulo not in pivot_rec_line.columns:
                continue
            fig.add_scatter(
                x=pivot_rec_line["mes_fmt"],
                y=pivot_rec_line[modulo],
                name=label,
                mode="lines+markers",
                line=dict(color=MODULE_COLORS[modulo], width=2.5),
                marker=dict(size=7),
                fill="tonexty" if modulo == "kids" else None,
                fillcolor="rgba(110,218,44,0.05)" if modulo == "kids" else None,
            )
        st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

# ── Gráfico 2C: Comparativo receita emitida vs liquidada (total) ──
st.subheader("Receita Total: Emitida vs Liquidada")
if df_contratos.empty:
    no_data()
else:
    df_plot = df_contratos.copy()
    df_plot["mes_fmt"] = df_plot["mes"].dt.strftime("%b/%y")

    fig = go.Figure()
    fig.add_bar(
        x=df_plot["mes_fmt"],
        y=df_plot["receita_total"],
        name="Emitida",
        marker_color=PALETTE[4],
        opacity=0.8,
    )
    fig.add_bar(
        x=df_plot["mes_fmt"],
        y=df_plot["receita_liquidada"],
        name="Liquidada",
        marker_color=PALETTE[0],
        opacity=0.9,
    )
    fig.update_layout(barmode="overlay")
    st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)
