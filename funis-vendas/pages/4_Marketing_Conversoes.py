"""
pages/4_Marketing_Conversoes.py
Conversões de marketing (topo de funil) — business-intelligence-467516.marketing_data.VW_CONVERSOES.
Página isolada do funil de SDR (páginas 1-3): id_hubspot está 100% vazio na fonte,
não há join confiável com hubspot_data hoje. Ver spec completa em Obsidian:
Documentacoes/[VND] Dashboard_Funis_Vendas.md, Página 4.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(
    page_title="Conversões de Marketing | InChurch",
    page_icon="📣",
    layout="wide",
)

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "marketing_conversoes"

from utils.style import inject_css
from utils.data import (
    load_marketing_conversoes,
    mkt_options,
    mkt_lead_unico,
    fmt_int,
    fmt_pct,
    PALETTE_GREEN,
    PALETTE_GREEN_LIGHT,
    CHART_TEMPLATE,
    MKT_JANELA_ANOS,
    CAMPANHA_LABELS,
    CAMPANHA_NAO_CLASSIFICADO,
)

MKT_DEFAULT_MESES = 13

inject_css()

st.markdown("<h1>Conversões <span>de Marketing</span></h1>", unsafe_allow_html=True)
st.caption(
    "Topo de funil isolado — leads/conversões de formulário (UTMs, canal, campanha). "
    "Não conectado ao funil de SDR: `id_hubspot` está 100% vazio na fonte hoje, "
    "sem chave de join confiável com o pipeline de vendas. "
    f"⚠️ Janela travada nos últimos {MKT_JANELA_ANOS} anos (fonte tem histórico completo desde "
    "2021-04-20, mas essa página não carrega além da janela, pra ficar mais leve)."
)

# ── Carga de dados ─────────────────────────────
with st.spinner("Carregando dados..."):
    df = load_marketing_conversoes()

if df.empty:
    st.info("Nenhum dado encontrado na base.", icon="ℹ️")
    st.stop()

# ── Sidebar — Filtros ──────────────────────────
with st.sidebar:
    st.markdown("### 🔍 Filtros")

    campanha_opcoes = [CAMPANHA_LABELS["MEIO"], CAMPANHA_LABELS["TOPO"], CAMPANHA_NAO_CLASSIFICADO]
    sel_campanha = st.pills(
        "Campanha (Forms)",
        campanha_opcoes,
        selection_mode="multi",
        default=campanha_opcoes,
        help="Meio/Topo são os valores reais da fonte (não existe 'Fundo'). 'Não Classificado' "
             "agrupa leads sem essa informação (~5% da base) — não fica escondido em nenhuma "
             "das outras duas caixas.",
    )

    sel_tamanho = st.multiselect(
        "Tamanho da Igreja", mkt_options(df, "tamanho_igreja_norm"), placeholder="Todos",
        help="Valores normalizados (DE-PARA) — intervalos de esquemas de formulário diferentes "
             "(ex. '101-250' vs '101-300' vs '101-200') são mantidos separados, não são a mesma faixa.",
    )
    sel_cargo = st.multiselect("Cargo", mkt_options(df, "cargo_norm"), placeholder="Todos")

    min_data, max_data = df["data_br"].min().date(), df["data_br"].max().date()
    _hoje = pd.Timestamp.now().normalize()
    _default_inicio = max((_hoje.replace(day=1) - pd.DateOffset(months=MKT_DEFAULT_MESES)).date(), min_data)
    periodo = st.date_input(
        "Período (data da conversão)",
        value=(_default_inicio, max_data),
        min_value=min_data,
        max_value=max_data,
        help=f"Padrão: últimos {MKT_DEFAULT_MESES} meses completos + o mês corrente até hoje. "
             "Pode ser expandido manualmente até o limite da janela travada acima.",
    )

    sel_decisor = st.multiselect("Decisor", mkt_options(df, "decisor"), placeholder="Todos")
    sel_formulario = st.multiselect("Formulário", mkt_options(df, "id_formulario"), placeholder="Todos")
    sel_canal = st.multiselect("Canal", mkt_options(df, "canal"), placeholder="Todos")

    st.markdown("**UTMs**")
    sel_utm_source = st.multiselect("UTM Source", mkt_options(df, "utm_source"), placeholder="Todos")
    sel_utm_medium = st.multiselect("UTM Medium", mkt_options(df, "utm_medium"), placeholder="Todos")
    sel_utm_campaign = st.multiselect("UTM Campaign", mkt_options(df, "utm_campaign"), placeholder="Todos")
    sel_utm_content = st.multiselect("UTM Content", mkt_options(df, "utm_content"), placeholder="Todos")

    st.divider()
    lead_unico = st.toggle(
        "👤 Lead único (remover duplicidade por e-mail)",
        value=False,
        help="Um lead entra se QUALQUER uma das suas conversões bater com os filtros ativos. "
             "O registro exibido é o mais completo dentre as conversões que bateram no filtro.",
    )

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

# ── Aplicar filtros (nível de conversão) ────────
dfv = df.copy()
if len(periodo) == 2:
    ini, fim = periodo
    dfv = dfv[(dfv["data_br"].dt.date >= ini) & (dfv["data_br"].dt.date <= fim)]

_sel_map = {
    "cargo_norm": sel_cargo,
    "tamanho_igreja_norm": sel_tamanho,
    "decisor": sel_decisor,
    "id_formulario": sel_formulario,
    "campanha_forms_disp": sel_campanha,
    "canal": sel_canal,
    "utm_source": sel_utm_source,
    "utm_medium": sel_utm_medium,
    "utm_campaign": sel_utm_campaign,
    "utm_content": sel_utm_content,
}
active_filters = {col: vals for col, vals in _sel_map.items() if vals}
for col, vals in active_filters.items():
    dfv = dfv[dfv[col].isin(vals)]

if dfv.empty:
    st.warning("Nenhuma conversão encontrada para os filtros selecionados.", icon="⚠️")
    st.stop()

# ── Lead único (dedup) ──────────────────────────
n_overlap = 0
if lead_unico:
    work_df, n_overlap = mkt_lead_unico(dfv, df, active_filters)
else:
    work_df = dfv

# ── KPIs de topo ────────────────────────────────
n_conversoes = len(dfv)
n_leads = dfv["email"].nunique()
n_decisor_sim = int((work_df["decisor"] == "Sim").sum())
taxa_recorrencia = float((dfv.drop_duplicates("email")["total_conversoes_lead"] > 1).mean() * 100)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Conversões", fmt_int(n_conversoes))
c2.metric("Leads Únicos", fmt_int(n_leads))
c3.metric("Decisores (no recorte exibido)", fmt_int(n_decisor_sim))
c4.metric("Taxa de Recorrência (leads com >1 conversão)", fmt_pct(taxa_recorrencia))

if lead_unico:
    st.info(
        f"👤 Modo **lead único** ativo: exibindo {fmt_int(len(work_df))} leads (1 linha por e-mail, "
        f"registro mais completo dentre as conversões que bateram no filtro). "
        + (
            f"**{fmt_int(n_overlap)} desses leads** também têm conversões fora da combinação de "
            "filtros selecionada — os totais por canal/UTM/etc. não são mutuamente exclusivos."
            if active_filters else
            "Nenhum filtro categórico ativo além do período — nota de overlap não se aplica."
        ),
        icon="👤",
    )

st.divider()

# ── Tendência mensal ────────────────────────────
st.markdown("### 📈 Conversões por Mês")
st.caption(
    "Sempre no nível de conversão (não é afetado pelo toggle 'lead único', já que o conceito de "
    "**Retorno** só existe olhando cada conversão individualmente). **Única** = 1ª conversão já "
    "registrada daquele lead (`ordem_conversao_lead == 1`); **Retorno** = conversão de um lead que "
    "já havia convertido antes."
)
_tipo = dfv["ordem_conversao_lead"].eq(1).map({True: "Única", False: "Retorno"})
mensal = (
    dfv.assign(_tipo=_tipo)
    .groupby(["mes_br", "_tipo"])
    .size()
    .unstack("_tipo", fill_value=0)
    .reindex(columns=["Única", "Retorno"], fill_value=0)
    .sort_index()
)
fig_mensal = go.Figure()
fig_mensal.add_trace(go.Bar(
    x=mensal.index, y=mensal["Única"], name="Única", marker_color=PALETTE_GREEN,
    hovertemplate="<b>%{x|%b/%Y}</b><br>Única: %{y}<extra></extra>",
))
fig_mensal.add_trace(go.Bar(
    x=mensal.index, y=mensal["Retorno"], name="Retorno", marker_color=PALETTE_GREEN_LIGHT,
    hovertemplate="<b>%{x|%b/%Y}</b><br>Retorno: %{y}<extra></extra>",
))
fig_mensal.update_layout(
    template=CHART_TEMPLATE,
    barmode="stack",
    height=380,
    margin=dict(l=4, r=4, t=16, b=8),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Outfit, sans-serif", color="#ffffff", size=12),
    yaxis_title="Conversões",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)
st.plotly_chart(fig_mensal, use_container_width=True)

st.divider()


# ── Helper de gráfico de barra horizontal (top N) ────
def bar_top(data: pd.DataFrame, col: str, title: str, top_n: int = 15, height: int = 380):
    vc = data[col].value_counts().head(top_n).sort_values(ascending=True)
    if vc.empty:
        st.info("Sem dados para essa quebra no recorte atual.")
        return
    fig = go.Figure(go.Bar(
        x=vc.values, y=vc.index.astype(str), orientation="h",
        marker_color=PALETTE_GREEN,
        text=[fmt_int(v) for v in vc.values],
        textposition="outside",
    ))
    fig.update_layout(
        template=CHART_TEMPLATE,
        height=height,
        margin=dict(l=4, r=4, t=16, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Outfit, sans-serif", color="#ffffff", size=12),
        xaxis_title="Leads" if lead_unico else "Conversões",
    )
    st.plotly_chart(fig, use_container_width=True, key=f"bar_{col}_{title}")


# ── Canal e UTM ──────────────────────────────────
col_a, col_b = st.columns(2)
with col_a:
    st.markdown("### 📡 Canal")
    bar_top(work_df, "canal", "canal", top_n=10, height=320)
with col_b:
    st.markdown("### 🔗 UTM Source (grupo)")
    bar_top(work_df, "utm_source_grupo", "utm_source_grupo", top_n=10, height=320)

st.divider()

# ── Qualificação do lead ─────────────────────────
st.markdown("### 🎯 Qualificação do Lead")
col_c, col_d = st.columns(2)
with col_c:
    st.markdown("**Cargo**")
    bar_top(work_df, "cargo_norm", "cargo", top_n=12)
with col_d:
    st.markdown("**Tamanho da Igreja**")
    bar_top(work_df, "tamanho_igreja_norm", "tamanho", top_n=12)

col_e, col_f = st.columns(2)
with col_e:
    st.markdown("**Decisor**")
    bar_top(work_df, "decisor", "decisor", top_n=5, height=240)
with col_f:
    st.markdown("**Já é Cliente InChurch**")
    bar_top(work_df, "cliente_inchurch", "cliente_inchurch", top_n=8, height=240)

st.divider()

# ── Recorrência (jornada multi-touch) ────────────
st.markdown("### 🔁 Recorrência de Conversões por Lead")
st.caption(
    "`total_conversoes_lead` é calculado na fonte sobre o histórico REAL e completo do lead "
    "(não é afetado pela janela de carga desta página) — mas como só carregamos os últimos "
    f"{MKT_JANELA_ANOS} anos, a LINHA que representa a 1ª conversão de um lead mais antigo que "
    "isso pode não estar disponível aqui pra inspeção, mesmo que o número já a contabilize."
)
rec = dfv.drop_duplicates("email")["total_conversoes_lead"].clip(upper=5)
rec_labels = {1: "1", 2: "2", 3: "3", 4: "4", 5: "5+"}
rec_counts = rec.map(rec_labels).value_counts().reindex(["1", "2", "3", "4", "5+"]).dropna()
fig_rec = go.Figure(go.Bar(
    x=rec_counts.index, y=rec_counts.values,
    marker_color=PALETTE_GREEN,
    text=[fmt_int(v) for v in rec_counts.values],
    textposition="outside",
))
fig_rec.update_layout(
    template=CHART_TEMPLATE,
    height=320,
    margin=dict(l=4, r=4, t=16, b=8),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Outfit, sans-serif", color="#ffffff", size=12),
    xaxis_title="Total de conversões do lead (histórico completo)",
    yaxis_title="Leads",
)
st.plotly_chart(fig_rec, use_container_width=True)

st.divider()

# ── Tabela detalhada ──────────────────────────────
st.markdown("### 📋 Tabela Detalhada")
cols_tabela = [
    "data_conversao_br", "nome", "email", "cargo_norm", "tamanho_igreja_norm",
    "nome_igreja", "decisor", "cliente_inchurch", "canal", "utm_source_grupo",
    "utm_medium", "campanha_forms_disp", "id_formulario", "total_conversoes_lead",
]
tabela = work_df[cols_tabela].rename(columns={
    "data_conversao_br": "Data", "nome": "Nome", "email": "E-mail",
    "cargo_norm": "Cargo", "tamanho_igreja_norm": "Tamanho Igreja",
    "nome_igreja": "Igreja", "decisor": "Decisor", "cliente_inchurch": "Já é Cliente",
    "canal": "Canal", "utm_source_grupo": "UTM Source (grupo)", "utm_medium": "UTM Medium",
    "campanha_forms_disp": "Campanha", "id_formulario": "Formulário",
    "total_conversoes_lead": "Total Conversões (lead)",
}).sort_values("Data", ascending=False)

st.caption(f"Exibindo até 1.000 de {fmt_int(len(tabela))} linhas no recorte atual.")
st.dataframe(tabela.head(1000), use_container_width=True, hide_index=True)
