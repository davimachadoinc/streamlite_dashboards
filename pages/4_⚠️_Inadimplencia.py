"""
pages/4_⚠️_Inadimplencia.py
Dashboard de Inadimplência — série histórica 30d / 90d e perfil dos inadimplentes.

Racional das métricas:
  Inadimplência 30d / 90d:
    Para cada mês no eixo X → comp_valor de boletos (1.2.1 + 1.2.2) com vencimento
    naquele mês, de clientes não desativados na data da cobrança, ainda em aberto hoje.
    % = valor ainda aberto / total emitido no mês.
    O filtro de 30d / 90d refere-se à idade mínima do vencimento
    (boletos mais recentes têm menos tempo para serem pagos e distorcem o índice).

  Inadimplência 30d (sem atrasos):
    Mesmo cálculo, SEM filtro de idade mínima — mostra o total não recebido
    por mês de vencimento, incluindo cobranças recentes.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="Inadimplência | InChurch", page_icon="⚠️", layout="wide")

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "inadimplencia"

from utils.style import inject_css
from utils.data import (
    PALETTE, PLAN_LABELS, PLAN_COLORS,
    chart_layout, mes_fmt_ordered, period_selector, filter_months,
    last_val, prev_val, delta_str, no_data, fmt_brl,
    load_inadimplencia_serie, load_inadimplencia_por_plano,
    load_inadimplencia_por_frequencia, load_inadimplencia_top_clientes,
)

inject_css()

# ── Header ────────────────────────────────────
col_title, col_filter = st.columns([8, 2], vertical_alignment="bottom")
with col_title:
    st.markdown("<h1>Inadimplência <span>& Perfil</span></h1>", unsafe_allow_html=True)
with col_filter:
    n_months = period_selector()

# ── Carga ─────────────────────────────────────
with st.spinner("Carregando dados de inadimplência..."):
    df_serie   = load_inadimplencia_serie()
    df_plano   = load_inadimplencia_por_plano()
    df_freq    = load_inadimplencia_por_frequencia()
    df_top     = load_inadimplencia_top_clientes()

if df_serie.empty:
    no_data("Nenhum dado de inadimplência encontrado.")
    st.stop()

df_serie = filter_months(df_serie, n_months, "mes")

if df_serie.empty:
    no_data("Nenhuma cobrança no período selecionado.")
    st.stop()

# ── KPI Cards ─────────────────────────────────
st.subheader("Visão Geral do Período")
k1, k2, k3, k4 = st.columns(4)

# Última inadimplência 30d com filtro
curr_30  = last_val(df_serie, "pct_inadimp_30d", "mes")
prev_30  = prev_val(df_serie, "pct_inadimp_30d", "mes")
with k1:
    st.metric(
        "Inadimplência 30d (último mês)",
        f"{curr_30:.1f}%" if curr_30 is not None else "—",
        delta=delta_str(curr_30, prev_30, fmt="+.1f", suffix=" p.p."),
        delta_color="inverse",
    )

# Valor absoluto em aberto 30d (acumulado do período)
aberto_30d_total = df_serie["aberto_30d"].sum()
with k2:
    st.metric("Valor em Aberto 30d (período)", f"R$ {fmt_brl(aberto_30d_total)}")

# Última inadimplência 90d
curr_90  = last_val(df_serie, "pct_inadimp_90d", "mes")
prev_90  = prev_val(df_serie, "pct_inadimp_90d", "mes")
with k3:
    st.metric(
        "Inadimplência 90d (último mês)",
        f"{curr_90:.1f}%" if curr_90 is not None else "—",
        delta=delta_str(curr_90, prev_90, fmt="+.1f", suffix=" p.p."),
        delta_color="inverse",
    )

aberto_90d_total = df_serie["aberto_90d"].sum()
with k4:
    st.metric("Valor em Aberto 90d (período)", f"R$ {fmt_brl(aberto_90d_total)}")

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 1 — Inadimplência 30d vs sem filtro (largura inteira)
# ─────────────────────────────────────────────
st.subheader("Inadimplência 30 dias vs Sem Filtro de Idade")

# Filtra só meses com emitido_30d > 0 para não poluir com meses recentes sem dado
df_30 = df_serie[df_serie["emitido_30d"] > 0].copy()
df_all = df_serie[df_serie["emitido"] > 0].copy()

if df_30.empty:
    no_data("Sem dados suficientes para o período.")
else:
    df_plot_30, x_order_30 = mes_fmt_ordered(df_30)
    df_plot_all, _ = mes_fmt_ordered(df_all)

    fig = go.Figure()
    fig.add_scatter(
        x=df_plot_30["mes_fmt"], y=df_plot_30["pct_inadimp_30d"],
        name="Inadimplência 30d", mode="lines+markers",
        line=dict(color=PALETTE[0], width=2.5), marker=dict(size=7),
    )
    fig.add_scatter(
        x=df_plot_all["mes_fmt"], y=df_plot_all["pct_inadimp"],
        name="Sem filtro de idade", mode="lines+markers",
        line=dict(color=PALETTE[3], width=2, dash="dot"), marker=dict(size=6),
    )
    fig.update_layout(
        yaxis=dict(ticksuffix="%"),
        xaxis=dict(categoryorder="array", categoryarray=x_order_30, type="category"),
    )
    st.plotly_chart(chart_layout(fig, height=380, legend_bottom=True), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 2 — Inadimplência 90d (largura inteira)
# ─────────────────────────────────────────────
st.subheader("Inadimplência 90 dias")

df_90 = df_serie[df_serie["emitido_90d"] > 0].copy()

if df_90.empty:
    no_data("Sem dados com 90+ dias de vencimento no período.")
else:
    df_plot_90, x_order_90 = mes_fmt_ordered(df_90)
    fig = go.Figure()
    fig.add_bar(
        x=df_plot_90["mes_fmt"],
        y=df_plot_90["pct_inadimp_90d"],
        marker_color=PALETTE[0],
        text=df_plot_90["pct_inadimp_90d"].apply(lambda v: f"{v:.1f}%"),
        textposition="outside",
        textfont=dict(size=11, color="#a0a0a0"),
    )
    fig.add_scatter(
        x=df_plot_90["mes_fmt"],
        y=df_plot_90["pct_inadimp_90d"],
        mode="lines+markers",
        line=dict(color=PALETTE[1], width=2, dash="dot"),
        marker=dict(size=6),
        name="Tendência",
        showlegend=True,
    )
    fig.update_layout(
        showlegend=True,
        yaxis=dict(ticksuffix="%"),
        xaxis=dict(categoryorder="array", categoryarray=x_order_90, type="category"),
    )
    st.plotly_chart(chart_layout(fig, height=360, legend_bottom=True), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 3 — Perfil dos Inadimplentes
# ─────────────────────────────────────────────
st.subheader("Perfil dos Inadimplentes (30d — snapshot atual)")
col_a, col_b = st.columns(2)

# Gráfico 3A — Por Plano (barras horizontais)
with col_a:
    st.subheader("Valor em Aberto por Plano")
    if df_plano.empty:
        no_data()
    else:
        df_p = df_plano[df_plano["plano"].isin(PLAN_LABELS.keys())].copy()
        df_p["label"] = df_p["plano"].map(PLAN_LABELS)
        df_p["cor"]   = df_p["plano"].map(PLAN_COLORS)
        df_p = df_p.sort_values("valor_aberto", ascending=True)

        fig = go.Figure()
        fig.add_bar(
            x=df_p["valor_aberto"],
            y=df_p["label"],
            orientation="h",
            marker_color=df_p["cor"].tolist(),
            text=df_p["valor_aberto"].apply(lambda v: f"R$ {fmt_brl(v, 0)}"),
            textposition="outside",
            textfont=dict(size=11, color="#a0a0a0"),
        )
        fig.update_layout(
            showlegend=False,
            xaxis=dict(showgrid=True, gridcolor="#292929"),
            yaxis=dict(showgrid=False),
        )
        st.plotly_chart(chart_layout(fig, height=320), use_container_width=True)

# Gráfico 3B — Por Frequência (donut)
with col_b:
    st.subheader("Clientes por Qtd. de Boletos em Aberto")
    if df_freq.empty:
        no_data()
    else:
        cores_freq = [PALETTE[0], PALETTE[6], PALETTE[3], PALETTE[4], PALETTE[1], PALETTE[8]]
        fig = go.Figure(go.Pie(
            labels=df_freq["faixa"],
            values=df_freq["clientes"],
            hole=0.45,
            marker_colors=cores_freq[:len(df_freq)],
            textfont=dict(size=12, family="Outfit"),
        ))
        fig.update_traces(
            texttemplate="%{label}<br>%{percent}",
            hovertemplate="<b>%{label}</b><br>%{value} clientes<br>%{percent}<extra></extra>",
        )
        st.plotly_chart(chart_layout(fig, height=320), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 4 — Clientes por Plano (linha) + Valor por Frequência (barras)
# ─────────────────────────────────────────────
col_c, col_d = st.columns(2)

with col_c:
    st.subheader("Clientes Inadimplentes por Plano")
    if df_plano.empty:
        no_data()
    else:
        df_p2 = df_plano[df_plano["plano"].isin(PLAN_LABELS.keys())].copy()
        df_p2["label"] = df_p2["plano"].map(PLAN_LABELS)
        df_p2["cor"]   = df_p2["plano"].map(PLAN_COLORS)
        df_p2 = df_p2.sort_values("clientes_inadimplentes", ascending=False)

        fig = go.Figure()
        fig.add_bar(
            x=df_p2["label"],
            y=df_p2["clientes_inadimplentes"],
            marker_color=df_p2["cor"].tolist(),
            text=df_p2["clientes_inadimplentes"].apply(lambda v: f"{int(v):,}".replace(",", ".")),
            textposition="outside",
            textfont=dict(size=11, color="#a0a0a0"),
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(chart_layout(fig, height=320), use_container_width=True)

with col_d:
    st.subheader("Valor em Aberto por Frequência")
    if df_freq.empty:
        no_data()
    else:
        fig = go.Figure()
        fig.add_bar(
            x=df_freq["faixa"],
            y=df_freq["valor_aberto"],
            marker_color=cores_freq[:len(df_freq)],
            text=df_freq["valor_aberto"].apply(lambda v: f"R$ {fmt_brl(v, 0)}"),
            textposition="outside",
            textfont=dict(size=11, color="#a0a0a0"),
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(chart_layout(fig, height=320), use_container_width=True)

st.divider()

# ── Tabela Top Inadimplentes ──────────────────
with st.expander("📋 Top 30 Clientes — Maior Valor em Aberto (30d)"):
    if df_top.empty:
        no_data()
    else:
        df_show = df_top.copy()
        df_show["plano"]        = df_show["plano"].map(PLAN_LABELS).fillna(df_show["plano"])
        df_show["valor_aberto"] = df_show["valor_aberto"].apply(lambda v: f"R$ {fmt_brl(v)}")
        df_show = df_show.rename(columns={
            "id_cliente":      "ID",
            "nome_cliente":    "Cliente",
            "plano":           "Plano",
            "valor_aberto":    "Valor em Aberto",
            "boletos_abertos": "Boletos Abertos",
            "max_dias_atraso": "Máx. Dias Atraso",
        })
        st.dataframe(df_show, use_container_width=True, hide_index=True)
