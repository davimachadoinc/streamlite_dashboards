"""
pages/6_Lifetime.py
Lifetime de cliente via análise de sobrevivência (Kaplan-Meier).

Racional completo (t0, critério de perda, censura, RMST por plano):
G:\\Meu Drive\\Obisidian\\Davi\\Documentacoes\\[FIN] Dashboard_Lifetime_Sobrevivencia.md
Decidido em sessão /grill-me (2026-09-03).
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="Lifetime | InChurch", page_icon="⏳", layout="wide")

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "lifetime"

from utils.style import inject_css
from utils.data import (
    PALETTE, PLAN_LABELS, PLAN_COLORS,
    chart_layout, no_data,
    RMST_HORIZONTES_MESES,
    load_lifetime_base, compute_lifetime_survival,
    fit_km_por_plano, compute_rmst_snapshots,
)

inject_css()

st.markdown("<h1>Lifetime <span>& Sobrevivência</span></h1>", unsafe_allow_html=True)
st.caption(
    "Tempo de vida do cliente estimado por análise de sobrevivência (Kaplan-Meier), "
    "com censura à direita para quem ainda está ativo. t0 = primeira liquidação; "
    "perda = desativação total OU 90 dias sem liquidar mensalidade."
)

# ── Carga ─────────────────────────────────────
with st.spinner("Carregando base de sobrevivência..."):
    df_base = load_lifetime_base()

if df_base.empty:
    no_data("Nenhum cliente com liquidação encontrado.")
    st.stop()

df = compute_lifetime_survival(df_base)

# ─────────────────────────────────────────────
# VISÃO GERAL (todos os planos)
# ─────────────────────────────────────────────
st.subheader("Visão Geral")

k1, k2, k3 = st.columns(3)
with k1:
    st.metric("Clientes na análise", f"{len(df):,}".replace(",", "."))
with k2:
    pct_perdidos = df["evento"].mean() * 100
    st.metric("% já perdidos", f"{pct_perdidos:.1f}%")
with k3:
    st.metric("% ainda ativos (censurados)", f"{(100 - pct_perdidos):.1f}%")

rmst_geral = compute_rmst_snapshots(df.assign(plano="Todos os clientes"), n_min=1)

if not rmst_geral.empty:
    st.markdown("**Tempo médio de vida esperado (RMST) — todos os clientes**")
    cols = st.columns(len(RMST_HORIZONTES_MESES))
    row = rmst_geral.iloc[0]
    for col, tau in zip(cols, RMST_HORIZONTES_MESES):
        val = row.get(f"rmst_{tau}m")
        with col:
            st.metric(f"RMST @ {tau} meses", f"{val:.1f} meses" if val is not None else "—")

st.divider()

# ─────────────────────────────────────────────
# CURVAS DE SOBREVIVÊNCIA POR PLANO
# ─────────────────────────────────────────────
st.subheader("Curva de Sobrevivência por Plano (plano de entrada)")
st.caption(
    "Cada cliente é rotulado pelo plano da SUA PRIMEIRA liquidação — não muda de "
    "categoria se migrar de plano depois. Planos com poucos clientes ficam de fora "
    "(amostra insuficiente pra uma curva confiável)."
)

kms_por_plano = fit_km_por_plano(df)

if not kms_por_plano:
    no_data("Nenhum plano com amostra suficiente para curva de sobrevivência.")
else:
    fig = go.Figure()
    for plano, (kmf, n) in sorted(kms_por_plano.items(), key=lambda kv: -kv[1][1]):
        sf = kmf.survival_function_.reset_index()
        sf.columns = ["meses", "sobrevivencia"]
        label = PLAN_LABELS.get(plano, plano.title())
        cor = PLAN_COLORS.get(plano, PALETTE[3])
        fig.add_scatter(
            x=sf["meses"], y=sf["sobrevivencia"] * 100,
            name=f"{label} (n={n})",
            mode="lines", line=dict(color=cor, width=2, shape="hv"),
            hovertemplate="%{x:.0f} meses<br>%{y:.1f}% ainda ativos<extra>" + label + "</extra>",
        )
    fig.update_layout(
        yaxis=dict(title="% de clientes ainda ativos", ticksuffix="%", range=[0, 100]),
        xaxis=dict(title="Meses desde a primeira liquidação (t0)", type="linear"),
    )
    st.plotly_chart(chart_layout(fig, height=440, legend_bottom=True), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SNAPSHOTS DE RMST POR PLANO
# ─────────────────────────────────────────────
st.subheader("Snapshots de RMST (tempo médio de sobrevida restrito) por Plano")
st.caption(
    "RMST em horizontes fixos (6/12/24/36 meses) — mais robusto que uma média "
    "'cheia', que fica instável quando poucos clientes têm tenure muito longa. "
    "Horizonte fica em branco quando o plano ainda não tem follow-up suficiente "
    "para alcançá-lo (ex: planos novos)."
)

df_rmst = compute_rmst_snapshots(df)

if df_rmst.empty:
    no_data("Nenhum plano com amostra suficiente para RMST.")
else:
    df_show = df_rmst.copy()
    df_show["Plano"] = df_show["plano"].map(PLAN_LABELS).fillna(df_show["plano"])
    df_show = df_show.sort_values("n_clientes", ascending=False)

    cols_order = ["Plano", "n_clientes"] + [f"rmst_{t}m" for t in RMST_HORIZONTES_MESES]
    df_show = df_show[cols_order]

    rename_map = {"n_clientes": "Clientes"}
    rename_map.update({f"rmst_{t}m": f"RMST @ {t}m" for t in RMST_HORIZONTES_MESES})
    df_show = df_show.rename(columns=rename_map)

    for t in RMST_HORIZONTES_MESES:
        col = f"RMST @ {t}m"
        df_show[col] = df_show[col].apply(lambda v: f"{v:.1f} meses" if pd.notna(v) else "—")

    st.dataframe(df_show, use_container_width=True, hide_index=True)

with st.expander("ℹ️ Como ler esta página"):
    st.markdown(
        """
        - **t0**: data da primeira liquidação do cliente (qualquer tipo, inclusive Setup).
        - **Perda**: desativação total (cliente sem nenhuma linha de mensalidade ativa) OU
          90 dias corridos sem liquidar mensalidade — o que vier primeiro.
        - **Censura**: cliente ainda ativo hoje entra na curva como "vivo até agora",
          não é descartado — é assim que a curva Kaplan-Meier evita subestimar o
          lifetime real ao ignorar clientes antigos que ainda não perderam.
        - **RMST** (restricted mean survival time): área sob a curva de sobrevivência
          até um horizonte fixo — a melhor estimativa de "tempo médio de vida esperado"
          quando nem todo mundo já teve o evento de perda.
        """
    )
