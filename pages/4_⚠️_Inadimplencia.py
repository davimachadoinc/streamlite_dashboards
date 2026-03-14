"""
pages/4_⚠️_Inadimplencia.py
Dashboard de Inadimplência — série diária 30d / 90d e perfil dos inadimplentes.

Racional:
  Inadimplência 30d / 90d:
    Para cada dia no eixo X → soma de comp_valor (1.2.1 + 1.2.2) com vencimento
    naquele dia, de clientes não desativados na data, ainda em aberto hoje.
    % = valor ainda aberto / total emitido naquele dia.
    O filtro 30d/90d = idade mínima do vencimento (excluir cobranças muito recentes).

  Sem filtro de idade:
    Mesmo cálculo sem restrição de idade — mostra todo valor não recebido
    por dia de vencimento, incluindo cobranças recentes.
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
    chart_layout, period_selector, filter_months,
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
    df_serie = load_inadimplencia_serie()
    df_plano = load_inadimplencia_por_plano()
    df_freq  = load_inadimplencia_por_frequencia()
    df_top   = load_inadimplencia_top_clientes()

if df_serie.empty:
    no_data("Nenhum dado de inadimplência encontrado.")
    st.stop()

df_serie = filter_months(df_serie, n_months, "dia")

if df_serie.empty:
    no_data("Nenhuma cobrança no período selecionado.")
    st.stop()

df_serie = df_serie.sort_values("dia")

# ── KPI Cards ─────────────────────────────────
st.subheader("Visão Geral do Período")
k1, k2, k3, k4 = st.columns(4)

curr_30 = last_val(df_serie, "pct_inadimp_30d", "dia")
prev_30 = prev_val(df_serie, "pct_inadimp_30d", "dia")
with k1:
    st.metric(
        "Inadimplência 30d (último dia)",
        f"{curr_30:.1f}%" if curr_30 is not None else "—",
        delta=delta_str(curr_30, prev_30, fmt="+.1f", suffix=" p.p."),
        delta_color="inverse",
    )

aberto_30d_atual = last_val(df_serie, "aberto_30d", "dia")
with k2:
    st.metric("Valor em Aberto 30d (snapshot)", f"R$ {fmt_brl(aberto_30d_atual)}" if aberto_30d_atual is not None else "—")

curr_90 = last_val(df_serie, "pct_inadimp_90d", "dia")
prev_90 = prev_val(df_serie, "pct_inadimp_90d", "dia")
with k3:
    st.metric(
        "Inadimplência 90d (último dia)",
        f"{curr_90:.1f}%" if curr_90 is not None else "—",
        delta=delta_str(curr_90, prev_90, fmt="+.1f", suffix=" p.p."),
        delta_color="inverse",
    )

aberto_90d_atual = last_val(df_serie, "aberto_90d", "dia")
with k4:
    st.metric("Valor em Aberto 90d (snapshot)", f"R$ {fmt_brl(aberto_90d_atual)}" if aberto_90d_atual is not None else "—")

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 1 — Inadimplência 30d vs sem filtro (largura inteira, eixo diário)
# ─────────────────────────────────────────────
st.subheader("Inadimplência 30 dias vs Sem Filtro de Idade")

df_30  = df_serie[df_serie["emitido_30d"] > 0].copy()
df_all = df_serie[df_serie["emitido"] > 0].copy()

if df_30.empty:
    no_data("Sem dados suficientes para o período.")
else:
    fig = go.Figure()
    fig.add_scatter(
        x=df_30["dia"], y=df_30["pct_inadimp_30d"],
        name="Inadimplência 30d",
        mode="lines", line=dict(color=PALETTE[0], width=2),
    )
    fig.add_scatter(
        x=df_all["dia"], y=df_all["pct_inadimp"],
        name="Sem filtro de idade",
        mode="lines", line=dict(color=PALETTE[3], width=1.5, dash="dot"),
    )
    fig.update_layout(
        yaxis=dict(ticksuffix="%"),
        xaxis=dict(type="date", tickformat="%d/%b/%y", dtick=604800000),
    )
    st.plotly_chart(chart_layout(fig, height=380, legend_bottom=True), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 2 — Inadimplência 90d (largura inteira, eixo diário)
# ─────────────────────────────────────────────
st.subheader("Inadimplência 90 dias")

df_90 = df_serie[df_serie["emitido_90d"] > 0].copy()

if df_90.empty:
    no_data("Sem dados com 90+ dias de vencimento no período.")
else:
    fig = go.Figure()
    fig.add_scatter(
        x=df_90["dia"], y=df_90["pct_inadimp_90d"],
        name="Inadimplência 90d",
        mode="lines", line=dict(color=PALETTE[0], width=2),
        fill="tozeroy", fillcolor="rgba(110,218,44,0.08)",
    )
    fig.update_layout(
        showlegend=False,
        yaxis=dict(ticksuffix="%"),
        xaxis=dict(type="date", tickformat="%d/%b/%y", dtick=604800000),
    )
    st.plotly_chart(chart_layout(fig, height=340), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 3 — Perfil dos Inadimplentes (snapshot atual)
# ─────────────────────────────────────────────
st.subheader("Perfil dos Inadimplentes (30d — snapshot atual)")
col_a, col_b = st.columns(2)

cores_freq = [PALETTE[0], PALETTE[6], PALETTE[3], PALETTE[4], PALETTE[1], PALETTE[8]]

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
            x=df_p["valor_aberto"], y=df_p["label"],
            orientation="h",
            marker_color=df_p["cor"].tolist(),
            text=df_p["valor_aberto"].apply(lambda v: f"R$ {fmt_brl(v, 0)}"),
            textposition="outside",
            textfont=dict(size=11, color="#a0a0a0"),
        )
        fig.update_layout(
            showlegend=False,
            xaxis=dict(showgrid=True, gridcolor="#292929", type="linear"),
            yaxis=dict(showgrid=False),
        )
        st.plotly_chart(chart_layout(fig, height=320), use_container_width=True)

with col_b:
    st.subheader("Clientes por Qtd. de Boletos em Aberto")
    if df_freq.empty:
        no_data()
    else:
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
            x=df_p2["label"], y=df_p2["clientes_inadimplentes"],
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
            x=df_freq["faixa"], y=df_freq["valor_aberto"],
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
