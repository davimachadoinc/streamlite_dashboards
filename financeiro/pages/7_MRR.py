"""
pages/7_MRR.py
Dashboard de Variação de MRR — Novas Vendas, Upsell, Desativações e NRR.

Regra de fontes (definida com o usuário em 15/09/2026):
  Novas Vendas → Fechamentos_com_ajustes, new_deal = TRUE (só formulário de vendas).
  Upsell       → Fechamentos_com_ajustes, upsell = TRUE (formulário de upsell OU
                 painel de controle — os dois canais, união via upsell=TRUE).
  Desativações → mesma lógica já usada no dashboard (load_desativacoes_mensais).
  MRR início   → Superlógica (vw-splgc-tabela_mrr_validos), mesma convenção do
                 waterfall do Unit Economics — garante que o NRR aqui seja
                 comparável ao NRR daquela página.

NRR = (MRR início + Upsell − Desativações) / MRR início × 100
  Exclui Novas Vendas do numerador de propósito — mede retenção da base
  existente, não crescimento por vendas novas (mesma convenção do Unit
  Economics). Novas Vendas aparece só como barra, fora da fórmula.

Gráfico 2 (variação de MRR) é uma visão GERENCIAL, não reconciliada com o
MRR real da Superlógica: MRR_fim = MRR_início + Novas Vendas + Upsell −
Desativações, todos os 3 movimentos vindos das fontes acima. Pode divergir
do MRR real ao longo do tempo por causa do delay entre venda (first_payment)
e início real da mensalidade — decisão consciente para começar simples.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="MRR | InChurch", page_icon="📈", layout="wide")

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "mrr"

from utils.style import inject_css
from utils.data import (
    PALETTE, chart_layout, mes_fmt_ordered, period_selector, filter_months,
    last_val, prev_val, delta_str, no_data, fmt_brl,
    load_mrr_inicio_mensal, load_fechamentos_mrr_mensal, load_desativacoes_mensais,
)

inject_css()

COR_NOVAS_VENDAS = PALETTE[0]   # verde escuro
COR_UPSELL       = "#ffffff"    # branco
COR_DESATIVACAO  = "#e5484d"    # vermelho — única cor de "perda" do dashboard
COR_NRR          = PALETTE[6]   # verde claro

# ── Header ────────────────────────────────────
col_title, col_filter = st.columns([8, 2], vertical_alignment="bottom")
with col_title:
    st.markdown("<h1>Variação de <span>MRR</span></h1>", unsafe_allow_html=True)
with col_filter:
    n_months = period_selector()

# ── Carga ─────────────────────────────────────
with st.spinner("Carregando dados de MRR..."):
    df_inicio_raw = load_mrr_inicio_mensal()
    df_fech_raw   = load_fechamentos_mrr_mensal()
    df_desativ_raw = load_desativacoes_mensais()

if df_inicio_raw.empty:
    no_data("Nenhum dado de MRR encontrado.")
    st.stop()

# ── Monta base única por mês ───────────────────
df_inicio = filter_months(df_inicio_raw, n_months, "mes")

df_fech_pivot = (
    df_fech_raw.pivot_table(index="mes", columns="tipo", values="mrr", aggfunc="sum")
    .reindex(columns=["novo", "upsell"], fill_value=0)
    .reset_index()
    .rename(columns={"novo": "novas_vendas_mrr", "upsell": "upsell_mrr"})
)

df_desativ = (
    df_desativ_raw.groupby("mes", as_index=False)["mrr_perdido"]
    .sum()
    .rename(columns={"mrr_perdido": "desativacoes_mrr"})
)

df = df_inicio.merge(df_fech_pivot, on="mes", how="left").merge(df_desativ, on="mes", how="left")
# BigQuery NUMERIC pode voltar como Decimal (ex: mrr_perdido) em vez de float,
# dependendo da coluna/agregação — cast explícito evita erro de aritmética
# ao misturar Decimal e float no mesmo DataFrame.
for col in ["mrr_inicio", "novas_vendas_mrr", "upsell_mrr", "desativacoes_mrr"]:
    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

df = df.sort_values("mes")
df["variacao_liquida"] = df["novas_vendas_mrr"] + df["upsell_mrr"] - df["desativacoes_mrr"]
df["mrr_fim"] = df["mrr_inicio"] + df["variacao_liquida"]
df["nrr"] = (
    (df["mrr_inicio"] + df["upsell_mrr"] - df["desativacoes_mrr"])
    / df["mrr_inicio"].where(df["mrr_inicio"] > 0)
    * 100
).round(1)

if df.empty:
    no_data("Nenhuma cobrança no período selecionado.")
    st.stop()

df_fmt, x_order = mes_fmt_ordered(df)

# ── KPI Cards ─────────────────────────────────
st.subheader("Visão Geral do Período")
k1, k2, k3, k4, k5 = st.columns(5)

curr_nrr = last_val(df_fmt, "nrr", "mes")
prev_nrr = prev_val(df_fmt, "nrr", "mes")
with k1:
    st.metric(
        "NRR (último mês)",
        f"{curr_nrr:.1f}%" if curr_nrr is not None else "—",
        delta=delta_str(curr_nrr, prev_nrr, fmt="+.1f", suffix=" p.p."),
        help="(MRR início + Upsell − Desativações) / MRR início. Exclui Novas Vendas do cálculo.",
    )

curr_novo = last_val(df_fmt, "novas_vendas_mrr", "mes")
with k2:
    st.metric("Novas Vendas (último mês)", f"R$ {fmt_brl(curr_novo, 0)}" if curr_novo is not None else "—")

curr_upsell = last_val(df_fmt, "upsell_mrr", "mes")
with k3:
    st.metric("Upsell (último mês)", f"R$ {fmt_brl(curr_upsell, 0)}" if curr_upsell is not None else "—")

curr_desativ = last_val(df_fmt, "desativacoes_mrr", "mes")
with k4:
    st.metric("Desativações (último mês)", f"R$ {fmt_brl(curr_desativ, 0)}" if curr_desativ is not None else "—")

curr_mrr_fim = last_val(df_fmt, "mrr_fim", "mes")
with k5:
    st.metric("MRR Final (último mês, gerencial)", f"R$ {fmt_brl(curr_mrr_fim, 0)}" if curr_mrr_fim is not None else "—")

st.caption(
    "MRR início vem da Superlógica (mesma base do waterfall do Unit Economics). "
    "Novas Vendas e Upsell vêm do Fechamentos_com_ajustes (vendas atribuídas, datadas pelo "
    "1º boleto pago) — podem ter defasagem frente ao início real da mensalidade."
)

st.divider()

# ─────────────────────────────────────────────
# GRÁFICO 1 — Desativações / Novas Vendas / Upsell (empilhado) + NRR
# ─────────────────────────────────────────────
st.subheader("Desativações, Novas Vendas e Upsell — com NRR")

fig = go.Figure()
fig.add_bar(
    x=df_fmt["mes_fmt"], y=df_fmt["novas_vendas_mrr"],
    name="Novas Vendas", marker_color=COR_NOVAS_VENDAS, opacity=0.9, yaxis="y",
    hovertemplate="<b>%{x}</b><br>Novas Vendas: R$ %{y:,.2f}<extra></extra>",
)
fig.add_bar(
    x=df_fmt["mes_fmt"], y=df_fmt["upsell_mrr"],
    name="Upsell", marker_color=COR_UPSELL, opacity=0.9, yaxis="y",
    hovertemplate="<b>%{x}</b><br>Upsell: R$ %{y:,.2f}<extra></extra>",
)
fig.add_bar(
    x=df_fmt["mes_fmt"], y=-df_fmt["desativacoes_mrr"],
    name="Desativações", marker_color=COR_DESATIVACAO, opacity=0.9, yaxis="y",
    hovertemplate="<b>%{x}</b><br>Desativações: R$ %{customdata:,.2f}<extra></extra>",
    customdata=df_fmt["desativacoes_mrr"],
)
fig.add_scatter(
    x=df_fmt["mes_fmt"], y=df_fmt["nrr"],
    name="NRR (%)", mode="lines+markers",
    line=dict(color=COR_NRR, width=2.5), marker=dict(size=7), yaxis="y2",
    hovertemplate="<b>%{x}</b><br>NRR: %{y:.1f}%<extra></extra>",
)
fig.update_layout(
    barmode="relative",
    yaxis=dict(title="MRR (R$)"),
    yaxis2=dict(title="NRR (%)", overlaying="y", side="right", showgrid=False, ticksuffix="%"),
    xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
)
st.plotly_chart(chart_layout(fig, height=440, legend_bottom=True), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# GRÁFICO 2 — Variação de MRR (waterfall gerencial)
# ─────────────────────────────────────────────
st.subheader("Variação de MRR (visão gerencial)")
st.caption(
    "MRR início + Novas Vendas + Upsell − Desativações, mês a mês. Não é reconciliado "
    "com o MRR real da Superlógica — pode divergir com o tempo por causa do delay entre "
    "venda e início real da mensalidade."
)

x_wf = ["MRR Inicial"] + df_fmt["mes_fmt"].tolist() + ["MRR Final"]
measure_wf = ["absolute"] + ["relative"] * len(df_fmt) + ["total"]
y_wf = [float(df_fmt["mrr_inicio"].iloc[0])] + df_fmt["variacao_liquida"].tolist() + [0]

fig2 = go.Figure(go.Waterfall(
    x=x_wf,
    measure=measure_wf,
    y=y_wf,
    increasing=dict(marker_color=COR_NOVAS_VENDAS),
    decreasing=dict(marker_color=COR_DESATIVACAO),
    totals=dict(marker_color=PALETTE[3]),
    connector=dict(line=dict(color="#292929", width=1)),
    text=[f"R$ {fmt_brl(v, 0)}" for v in y_wf],
    textposition="outside",
    textfont=dict(size=11, color="#a0a0a0"),
    hovertemplate="<b>%{x}</b><br>R$ %{y:,.2f}<extra></extra>",
))
fig2.update_layout(
    showlegend=False,
    xaxis=dict(type="category"),
    yaxis=dict(title="MRR (R$)"),
)
st.plotly_chart(chart_layout(fig2, height=440), use_container_width=True)
