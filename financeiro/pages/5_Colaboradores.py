"""
pages/5_👥_Colaboradores.py
Dashboard de Colaboradores — headcount CLT/PJ/Outros, MRR por colaborador e
custo por centro de custo.

Fonte: dp_inchurch (BQ_BI, dataset separado de Splgc mas mesmo projeto GCP
business-intelligence-467516). Ver dp-inchurch-dicionario-dados.md no vault
Obsidian pro schema completo e as regras de dedup por CPF/CNPJ.

Janela fixa de 18 meses pros gráficos de série (não usa o period_selector
padrão do resto do dashboard, que vai só até 15 meses) — igual ao padrão já
usado na página de Inadimplência pra série diária.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="Colaboradores | InChurch", page_icon="👥", layout="wide")

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

# Restrição extra: dado sensível de remuneração/custo por pessoa — só um
# subconjunto dos e-mails já autorizados no app inteiro pode ver esta página.
_colab_allowed = st.secrets.get("app_config", {}).get("colaboradores_allowed_emails", [])
if st.user.email not in _colab_allowed:
    st.error(
        "⛔ Você não tem permissão para acessar a página Colaboradores.\n\n"
        "Fale com o administrador se precisar de acesso."
    )
    st.stop()

st.session_state["_page_key"] = "colaboradores"

from utils.style import inject_css
from utils.data import (
    PALETTE, COLAB_LABELS, COLAB_ORDER, COLAB_COLORS, CATEG_COLORS,
    chart_layout, mes_fmt_ordered,
    last_val, prev_val, delta_str, no_data, fmt_brl,
    load_colaboradores_mensal, load_mrr_por_colaborador, load_custo_por_centro_custo,
    load_custo_por_categoria,
)

inject_css()

# ── Header ────────────────────────────────────
col_title, col_squad = st.columns([8, 3], vertical_alignment="bottom")
with col_title:
    st.markdown("<h1>Colaboradores <span>& Custo</span></h1>", unsafe_allow_html=True)
    st.caption("Últimos 18 meses · Fonte: Plataforma DP InChurch (dp_inchurch)")
with col_squad:
    incluir_squad = st.checkbox(
        "Incluir Squad as a Service no MRR",
        value=True,
        help="Só 3 contratos ativos hoje, mas ~10% do MRR total (ticket médio ~R$36k/contrato). Afeta o KPI e o gráfico de MRR/Colaborador.",
    )

# ── Carga ─────────────────────────────────────
with st.spinner("Carregando dados de colaboradores..."):
    df_headcount    = load_colaboradores_mensal(n_meses=18)
    df_mrr_colab    = load_mrr_por_colaborador(n_meses=18, incluir_squad=incluir_squad)
    df_custo_cc     = load_custo_por_centro_custo()
    df_custo_categ  = load_custo_por_categoria()

if df_headcount.empty:
    no_data("Nenhum dado de colaboradores encontrado.")
    st.stop()

# ── Totais por mês (todos os buckets) ──────────
df_total_mes = (
    df_headcount
    .groupby("mes", as_index=False)
    .agg(colaboradores=("colaboradores", "sum"))
    .sort_values("mes")
)

# ── KPI Cards ─────────────────────────────────
st.subheader("Visão Geral")
k1, k2, k3, k4, k5 = st.columns(5)

for col, bucket in zip([k1, k2, k3], COLAB_ORDER):
    sub = df_headcount[df_headcount["bucket"] == bucket]
    curr = last_val(sub, "colaboradores", "mes")
    prev = prev_val(sub, "colaboradores", "mes")
    with col:
        st.metric(
            COLAB_LABELS[bucket],
            f"{int(curr):,}".replace(",", ".") if curr is not None else "—",
            delta=delta_str(curr, prev),
        )

curr_total = last_val(df_total_mes, "colaboradores", "mes")
prev_total = prev_val(df_total_mes, "colaboradores", "mes")
with k4:
    st.metric(
        "Total",
        f"{int(curr_total):,}".replace(",", ".") if curr_total is not None else "—",
        delta=delta_str(curr_total, prev_total),
    )

with k5:
    if not df_mrr_colab.empty:
        curr_mrr_colab = last_val(df_mrr_colab, "mrr_por_colaborador", "mes")
        prev_mrr_colab = prev_val(df_mrr_colab, "mrr_por_colaborador", "mes")
        st.metric(
            "MRR / Colaborador",
            f"R$ {fmt_brl(curr_mrr_colab, 0)}" if curr_mrr_colab is not None else "—",
            delta=delta_str(curr_mrr_colab, prev_mrr_colab, fmt="+,.0f", suffix=" R$"),
        )
    else:
        st.metric("MRR / Colaborador", "—")

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 1 — Headcount por mês, empilhado (CLT, PJ, Outros)
# ─────────────────────────────────────────────
st.subheader("Colaboradores por Mês")
df_plot_hc, x_order_hc = mes_fmt_ordered(df_headcount)

fig = go.Figure()
for bucket in COLAB_ORDER:
    sub = df_plot_hc[df_plot_hc["bucket"] == bucket].sort_values("mes")
    if sub.empty:
        continue
    fig.add_bar(
        x=sub["mes_fmt"],
        y=sub["colaboradores"],
        name=COLAB_LABELS[bucket],
        marker_color=COLAB_COLORS[bucket],
    )
fig = chart_layout(fig, height=420, legend_bottom=True)
fig.update_layout(
    barmode="stack",
    xaxis=dict(categoryorder="array", categoryarray=x_order_hc, type="category"),
    yaxis=dict(title="Colaboradores"),
)
st.plotly_chart(fig, use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 2 — MRR / Colaborador
# ─────────────────────────────────────────────
st.subheader("MRR por Colaborador")

if df_mrr_colab.empty:
    no_data("Dados insuficientes para calcular MRR por colaborador.")
else:
    df_plot_mrr, x_order_mrr = mes_fmt_ordered(df_mrr_colab)
    fig = go.Figure()
    fig.add_scatter(
        x=df_plot_mrr["mes_fmt"],
        y=df_plot_mrr["mrr_por_colaborador"],
        mode="lines+markers",
        line=dict(color=PALETTE[0], width=2.5),
        marker=dict(size=7),
        name="MRR / Colaborador",
        hovertemplate="R$ %{y:,.0f}<extra></extra>",
    )
    fig = chart_layout(fig, height=380)
    fig.update_layout(
        xaxis=dict(categoryorder="array", categoryarray=x_order_mrr, type="category"),
        yaxis=dict(title="R$ / colaborador", tickprefix="R$ "),
    )
    st.plotly_chart(fig, use_container_width=True)
    squad_nota = "incluindo" if incluir_squad else "excluindo"
    st.caption(f"MRR total ativo (vw-splgc-tabela_mrr_validos, {squad_nota} Squad as a Service) ÷ headcount total (CLT + PJ + Outros) no início de cada mês.")

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 3 — Custo por Centro de Custo (snapshot mês mais recente)
# ─────────────────────────────────────────────
st.subheader("Custo por Centro de Custo")
st.caption("Snapshot do mês mais recente disponível · CLT: custo empresa estimado (com encargos) · PJ: valor da NF paga")

if df_custo_cc.empty:
    no_data("Nenhum dado de custo por centro de custo encontrado.")
else:
    fig = go.Figure()
    fig.add_bar(
        x=df_custo_cc["custo_total"],
        y=df_custo_cc["centro_custo"],
        orientation="h",
        marker_color=PALETTE[0],
        text=[f"R$ {fmt_brl(v, 0)}" for v in df_custo_cc["custo_total"]],
        textposition="outside",
    )
    fig = chart_layout(fig, height=max(380, 28 * len(df_custo_cc)))
    fig.update_layout(
        yaxis=dict(autorange="reversed", type="category", title=""),
        xaxis=dict(title="Custo (R$)", tickprefix="R$ ", type="linear"),
        margin=dict(l=4, r=60, t=32, b=8),
    )
    st.plotly_chart(fig, use_container_width=True)

    custo_total_geral = df_custo_cc["custo_total"].sum()
    st.metric("Custo Total (mês mais recente)", f"R$ {fmt_brl(custo_total_geral, 0)}")

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 4 — Composição do Custo por Categoria (snapshot mês mais recente)
# CLT/Estágio/Jovem Aprendiz decompostos em Salário/Encargos/Benefícios/VT;
# PJ e Sócio entram como categoria única cada (sem essa quebra na fonte).
# ─────────────────────────────────────────────
st.subheader("Composição do Custo por Categoria")
st.caption("Snapshot do mês mais recente · CLT/Estágio/Jovem Aprendiz decompostos (folha_colaborador); PJ e Sócio como categoria única")

if df_custo_categ.empty:
    no_data("Nenhum dado de composição de custo encontrado.")
else:
    categ_colors = [CATEG_COLORS.get(c, PALETTE[3]) for c in df_custo_categ["categoria"]]
    fig = go.Figure()
    fig.add_bar(
        x=df_custo_categ["valor"],
        y=df_custo_categ["categoria"],
        orientation="h",
        marker_color=categ_colors,
        text=[f"R$ {fmt_brl(v, 0)}" for v in df_custo_categ["valor"]],
        textposition="outside",
    )
    fig = chart_layout(fig, height=max(280, 50 * len(df_custo_categ)))
    fig.update_layout(
        yaxis=dict(autorange="reversed", type="category", title=""),
        xaxis=dict(title="Custo (R$)", tickprefix="R$ ", type="linear"),
        margin=dict(l=4, r=60, t=32, b=8),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Encargos = FGTS + INSS Patronal estimado. Vale Transporte não entra no custo_empresa_estimado do CLT usado na seção anterior — por isso a soma aqui pode divergir ligeiramente do total de Custo por Centro de Custo.")
