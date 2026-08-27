"""
pages/3_Tempo_Entre_Etapas.py
Distribuição de tempo entre etapas do funil de SDR — média, mediana, boxplot,
velocidade vs. resultado, idade dos leads em aberto, tempo até 1º contato por
dia da semana. Ver spec completa em Obsidian:
Documentacoes/[VND] Dashboard_Funis_Vendas.md
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(
    page_title="Tempo entre Etapas | InChurch",
    page_icon="⏱️",
    layout="wide",
)

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "tempo_entre_etapas"

from utils.style import inject_css
from utils.data import (
    load_lead_stage_with_cohort,
    month_options,
    compute_transitions,
    transition_summary,
    truncate_at_p95,
    velocity_vs_conversion,
    aging_em_aberto,
    time_to_contact_by_weekday,
    fmt_int,
    fmt_pct,
    PALETTE_GREEN,
    COLOR_ABERTO,
    COLOR_DESQ,
    CHART_TEMPLATE,
    TRANSITION_PAIRS,
    WEEKDAYS_PT,
)

inject_css()

st.markdown("<h1>Tempo <span>entre Etapas</span></h1>", unsafe_allow_html=True)
st.caption(
    "Coorte por mês da 1ª Entrada, mesma semântica da página 'Funil de SDR — Coorte'. "
    "Cortes por SDR Owner e Lead Source, iguais aos das outras páginas."
)

# ── Carga de dados ─────────────────────────────
with st.spinner("Carregando dados..."):
    df = load_lead_stage_with_cohort()

if df.empty:
    st.info("Nenhum dado encontrado na base.", icon="ℹ️")
    st.stop()

# ── Sidebar — Filtros ──────────────────────────
with st.sidebar:
    st.markdown("### 🔍 Filtros")

    meses = month_options(df)
    sel_meses = st.multiselect("Mês de Entrada (coorte)", meses, placeholder="Todos")

    sdr_ids = sorted(df["sdr_owner"].dropna().unique().tolist())
    sel_sdr = st.multiselect(
        "SDR Owner",
        sdr_ids,
        placeholder="Todos",
        help="Exibindo o ID numérico do HubSpot — dim_owner ainda não foi populada pelo time de Operações.",
    )

    fontes = sorted(df["lead_source_name"].dropna().unique().tolist())
    sel_fontes = st.multiselect("Lead Source", fontes, placeholder="Todas")

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

# ── Aplicar filtros ────────────────────────────
dfv = df.copy()
if sel_meses:
    dfv = dfv[dfv["_mes_entrada_fmt"].isin(sel_meses)]
if sel_sdr:
    dfv = dfv[dfv["sdr_owner"].isin(sel_sdr)]
if sel_fontes:
    dfv = dfv[dfv["lead_source_name"].isin(sel_fontes)]

if dfv.empty:
    st.warning("Nenhum lead encontrado para os filtros selecionados.", icon="⚠️")
    st.stop()

transitions = compute_transitions(dfv)
if transitions.empty:
    st.warning("Não há transições suficientes para os filtros selecionados.", icon="⚠️")
    st.stop()

# ── Tabela resumo ────────────────────────────────
st.markdown("### 📊 Média, Mediana e Percentis por Transição (minutos)")
summary = transition_summary(transitions)
summary_min = summary.copy()
for col in ["media_dias", "mediana_dias", "p25_dias", "p75_dias", "p95_dias"]:
    summary_min[col] = summary_min[col] * 24 * 60

_fmt_min = lambda v: f"{v:,.0f}".replace(",", ".")
st.dataframe(
    summary_min.rename(columns={
        "pair": "Transição", "leads": "Leads",
        "media_dias": "Média", "mediana_dias": "Mediana",
        "p25_dias": "P25", "p75_dias": "P75", "p95_dias": "P95",
    }).style.format({
        "Média": _fmt_min, "Mediana": _fmt_min, "P25": _fmt_min, "P75": _fmt_min, "P95": _fmt_min,
    }),
    use_container_width=True,
    hide_index=True,
)
st.caption(
    "Médias tendem a ser bem maiores que as medianas nessas distribuições (cauda longa forte) — "
    "prefira a mediana pra entender o comportamento típico."
)

# ── Boxplot truncado no p95 ──────────────────────
st.markdown("### 📦 Distribuição (Boxplot, truncado no P95)")
dentro, fora = truncate_at_p95(transitions)
n_outliers = len(fora)

order = [label for _, _, label in TRANSITION_PAIRS]
fig = go.Figure()
for pair in order:
    sub = dentro[dentro["pair"] == pair]
    if sub.empty:
        continue
    fig.add_trace(go.Box(
        y=sub["dias"], name=pair, marker_color=PALETTE_GREEN,
        boxpoints="outliers", line=dict(color=PALETTE_GREEN),
    ))
fig.update_layout(
    template=CHART_TEMPLATE,
    height=460,
    margin=dict(l=4, r=4, t=16, b=8),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Outfit, sans-serif", color="#ffffff", size=12),
    yaxis_title="Dias",
    showlegend=False,
)
st.plotly_chart(fig, use_container_width=True)
st.caption(
    f"⚠️ {fmt_int(n_outliers)} transições acima do percentil 95 (por par) não aparecem no "
    "gráfico — ver tabela de outliers abaixo para inspeção manual."
)

# ── Tabela de outliers ───────────────────────────
with st.expander(f"🔎 Ver outliers (acima do P95) — {fmt_int(n_outliers)} transições"):
    if fora.empty:
        st.info("Nenhum outlier no recorte atual.")
    else:
        tabela_out = fora[["lead_id", "pair", "dias", "sdr_owner", "lead_source_name"]].rename(columns={
            "lead_id": "Lead ID", "pair": "Transição", "dias": "Dias",
            "sdr_owner": "SDR Owner", "lead_source_name": "Lead Source",
        }).sort_values("Dias", ascending=False)
        st.dataframe(
            tabela_out.style.format({"Dias": "{:.1f}"}),
            use_container_width=True,
            hide_index=True,
        )

st.divider()

# ── Velocidade vs. Resultado ─────────────────────
st.markdown("### 🚀 Velocidade até o 1º Contato vs. Taxa de Conversão")
vel = velocity_vs_conversion(dfv)
if vel.empty:
    st.info("Sem dados suficientes para essa análise no recorte atual.")
else:
    fig_vel = go.Figure(go.Bar(
        x=vel["bucket"].astype(str), y=vel["taxa_conversao"],
        marker_color=PALETTE_GREEN,
        text=[f"{v:.1f}%" for v in vel["taxa_conversao"]],
        textposition="outside",
        customdata=vel[["leads", "chegaram"]],
        hovertemplate="<b>%{x}</b><br>Taxa de conversão: %{y:.1f}%<br>Leads: %{customdata[0]}"
                      "<br>Chegaram em Reunião Agendada: %{customdata[1]}<extra></extra>",
    ))
    fig_vel.update_layout(
        template=CHART_TEMPLATE,
        height=380,
        margin=dict(l=4, r=4, t=16, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Outfit, sans-serif", color="#ffffff", size=13),
        yaxis_title="% chegaram em Reunião Agendada",
        xaxis_title="Tempo até o 1º contato (Entrada → Tentando Contato)",
    )
    st.plotly_chart(fig_vel, use_container_width=True)
    st.caption(
        "Leads contatados quase instantaneamente (< 1h) tendem a ser transições automáticas do "
        "sistema, não necessariamente um contato humano real — por isso essa faixa pode converter "
        "pior do que faixas de resposta 'rápida mas não instantânea' (1h–24h)."
    )

st.divider()

# ── Idade dos leads em aberto ────────────────────
st.markdown("### ⏳ Idade dos Leads \"Em Aberto\" (dias parados até hoje)")
aging = aging_em_aberto(dfv)
if aging.empty:
    st.info("Nenhum lead em aberto no recorte atual.")
else:
    grp_aging = aging.groupby("stage_name")["dias_parado"]
    resumo_aging = pd.DataFrame({
        "leads": grp_aging.count(),
        "mediana": grp_aging.median(),
        "media": grp_aging.mean(),
    })
    resumo_aging.index.name = "stage_name"
    resumo_aging = (
        resumo_aging
        .reindex(["Entrada", "Tentando Contato", "Em Contato", "Reunião Agendada"])
        .dropna(how="all")
        .reset_index()
    )
    st.dataframe(
        resumo_aging.rename(columns={"stage_name": "Etapa", "leads": "Leads Parados"}).style.format({
            "mediana": "{:.1f} dias", "media": "{:.1f} dias",
        }),
        use_container_width=True,
        hide_index=True,
    )
    with st.expander(f"🔎 Ver os 20 leads mais tempo parados — {fmt_int(len(aging))} em aberto no total"):
        top20 = aging.head(20)[["lead_id", "stage_name", "dias_parado", "sdr_owner", "lead_source_name"]].rename(
            columns={
                "lead_id": "Lead ID", "stage_name": "Etapa Atual", "dias_parado": "Dias Parado",
                "sdr_owner": "SDR Owner", "lead_source_name": "Lead Source",
            }
        )
        st.dataframe(
            top20.style.format({"Dias Parado": "{:.1f}"}),
            use_container_width=True,
            hide_index=True,
        )

st.divider()

# ── Tempo até 1º contato por dia da semana ───────
st.markdown("### 📅 Tempo até o 1º Contato por Dia da Semana da Entrada")
wd = time_to_contact_by_weekday(dfv)
if wd.empty:
    st.info("Sem dados suficientes para essa análise no recorte atual.")
else:
    fig_wd = go.Figure(go.Bar(
        x=wd["dia_semana"], y=wd["media_horas"],
        marker_color=PALETTE_GREEN,
        text=[f"{v:.1f}h" for v in wd["media_horas"]],
        textposition="outside",
        customdata=wd[["leads", "mediana_horas"]],
        hovertemplate="<b>%{x}</b><br>Média: %{y:.1f}h<br>Mediana: %{customdata[1]:.2f}h"
                      "<br>Leads: %{customdata[0]}<extra></extra>",
    ))
    fig_wd.update_layout(
        template=CHART_TEMPLATE,
        height=360,
        margin=dict(l=4, r=4, t=16, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Outfit, sans-serif", color="#ffffff", size=13),
        yaxis_title="Média de horas até 1º contato",
        xaxis=dict(categoryorder="array", categoryarray=WEEKDAYS_PT),
    )
    st.plotly_chart(fig_wd, use_container_width=True)
    st.caption(
        "Usando a **média** aqui, não a mediana — a mediana fica achatada perto de zero em "
        "todos os dias (dominada por transições automáticas quase instantâneas) e escondia a "
        "diferença real. A média revela o padrão: fim de semana tem cauda bem mais lenta "
        "(passe o mouse pra ver mediana e nº de leads de cada dia)."
    )
