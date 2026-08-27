"""
pages/1_Funil_SDR_Coorte.py
Funil de SDR — visão coorte por mês de Entrada.
Métrica cumulativa ("já passou por"), dupla porcentagem (vs. Entrada e vs. etapa
anterior), caixas satélite de Em Aberto / Desqualificado por etapa, badge de
retorno de etapa. Ver spec completa em Obsidian:
Documentacoes/[VND] Dashboard_Funis_Vendas.md
"""
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(
    page_title="Funil de SDR (Coorte) | InChurch",
    page_icon="🔻",
    layout="wide",
)

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "funil_sdr_coorte"

from utils.style import inject_css
from utils.data import (
    load_lead_stage_with_cohort,
    month_options,
    compute_funnel_stats,
    fmt_int,
    fmt_pct,
    STAGE_ORDER,
    COLOR_ABERTO,
    COLOR_DESQ,
    PALETTE_GREEN,
    CHART_TEMPLATE,
)

inject_css()

st.markdown("<h1>Funil de SDR <span>— Coorte</span></h1>", unsafe_allow_html=True)
st.caption(
    "Coorte por mês da 1ª 'Entrada' — mostra o percurso completo dos leads que entraram no "
    "mês selecionado, mesmo que etapas seguintes tenham ocorrido depois."
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

stats = compute_funnel_stats(dfv)
if stats.empty:
    st.warning("Não há dados suficientes para montar o funil com esses filtros.", icon="⚠️")
    st.stop()

# ── KPIs de topo ────────────────────────────────
n_leads = dfv["lead_id"].nunique()
n_reuniao = int(stats.loc[stats["stage_id"] == "qualified-stage-id", "alcancou"].iloc[0])
n_desq_total = int(stats["desqualificado"].sum())
pct_conversao_final = (n_reuniao / n_leads * 100) if n_leads else 0.0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Leads na Coorte", fmt_int(n_leads))
c2.metric("Chegaram em Reunião Agendada", fmt_int(n_reuniao))
c3.metric("Taxa de Conversão (vs. Entrada)", fmt_pct(pct_conversao_final))
c4.metric("Total Desqualificado (alguma etapa)", fmt_int(n_desq_total))

st.divider()

# ── Funil (Plotly) ──────────────────────────────
labels = []
for _, row in stats.iterrows():
    label = row["stage_name"]
    if row["retorno_n"] > 0:
        label += f"  ↻ {int(row['retorno_n'])}x"
    labels.append(label)

green_ramp = ["#8ae650", "#6eda2c", "#57d124", "#3ba811"]

fig = go.Figure(
    go.Funnel(
        y=labels,
        x=stats["alcancou"],
        textposition="inside",
        textinfo="value+percent initial+percent previous",
        marker=dict(color=green_ramp[: len(stats)]),
        connector=dict(line=dict(color="#292929", width=2)),
        hovertemplate=(
            "<b>%{y}</b><br>Já passaram: %{x}<br>%{percentInitial} da Entrada"
            "<br>%{percentPrevious} vs. etapa anterior<extra></extra>"
        ),
    )
)
fig.update_layout(
    template=CHART_TEMPLATE,
    height=440,
    margin=dict(l=4, r=4, t=16, b=8),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Outfit, sans-serif", color="#ffffff", size=14),
)
st.plotly_chart(fig, use_container_width=True)
st.caption(
    "Badge ↻ Nx ao lado do nome da etapa = leads que visitaram aquela etapa mais de uma vez "
    "(evento raro — retorno de etapa)."
)

st.markdown("### 🩸 Vazamento por Etapa")
st.caption(
    "**Em Aberto**: leads parados nessa etapa, sem avançar e sem desqualificação. "
    "**Desqualificado**: leads desqualificados saindo dessa etapa (alguma vez, mesmo que "
    "revividos depois). Os dois não são mutuamente exclusivos entre si nem com 'Avançou' "
    "(implícito na etapa seguinte) — não somam 100% do trapézio."
)


def stat_card(label: str, value: int, pct: float, color: str) -> str:
    return f"""
    <div style="background:#121212; border:1px solid #292929; border-left:4px solid {color};
                border-radius:10px; padding:14px 16px; min-height:92px;">
      <div style="color:#a0a0a0; font-size:0.78rem; text-transform:uppercase;
                  letter-spacing:0.05em; margin-bottom:6px;">{label}</div>
      <div style="color:#ffffff; font-size:1.6rem; font-weight:700; line-height:1.1;">
        {fmt_int(value)}
      </div>
      <div style="color:{color}; font-size:0.85rem; font-weight:600; margin-top:2px;">
        {fmt_pct(pct)} da etapa
      </div>
    </div>
    """


for _, row in stats.iterrows():
    col_aberto, col_nome, col_desq = st.columns([1, 1.1, 1])
    with col_aberto:
        st.markdown(
            stat_card("Em Aberto", row["em_aberto"], row["pct_em_aberto"], COLOR_ABERTO),
            unsafe_allow_html=True,
        )
    with col_nome:
        st.markdown(
            f"""
            <div style="display:flex; align-items:center; justify-content:center;
                        height:92px; text-align:center;">
              <div>
                <div style="color:#ffffff; font-size:1.05rem; font-weight:700;">{row['stage_name']}</div>
                <div style="color:{PALETTE_GREEN}; font-size:0.85rem; font-weight:600;">
                  {fmt_int(row['alcancou'])} já passaram · {fmt_pct(row['pct_entrada'])} da Entrada
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_desq:
        st.markdown(
            stat_card("Desqualificado", row["desqualificado"], row["pct_desqualificado"], COLOR_DESQ),
            unsafe_allow_html=True,
        )

st.divider()

# ── Tabela de apoio ─────────────────────────────
st.markdown("### 📋 Tabela Detalhada")
tabela = stats[[
    "stage_name", "alcancou", "pct_entrada", "pct_etapa_anterior",
    "em_aberto", "pct_em_aberto", "desqualificado", "pct_desqualificado", "retorno_n",
]].rename(columns={
    "stage_name": "Etapa",
    "alcancou": "Já Passaram",
    "pct_entrada": "% vs. Entrada",
    "pct_etapa_anterior": "% vs. Etapa Anterior",
    "em_aberto": "Em Aberto",
    "pct_em_aberto": "% Em Aberto",
    "desqualificado": "Desqualificado",
    "pct_desqualificado": "% Desqualificado",
    "retorno_n": "Retorno de Etapa",
})
st.dataframe(
    tabela.style.format({
        "% vs. Entrada": "{:.1f}%",
        "% vs. Etapa Anterior": "{:.1f}%",
        "% Em Aberto": "{:.1f}%",
        "% Desqualificado": "{:.1f}%",
    }),
    use_container_width=True,
    hide_index=True,
)
