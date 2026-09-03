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

with st.expander("💡 O que é RMST? (explicação sem jargão)", expanded=True):
    st.markdown(
        """
        As métricas desta página usam uma sigla técnica, **RMST**, que aparece em vários
        lugares abaixo. Aqui vai a versão simples do que ela significa.

        **O problema que o RMST resolve:** pra saber "quanto tempo, em média, um cliente
        fica ativo", o jeito óbvio seria pegar todo mundo que já cancelou, somar o tempo
        que cada um durou e dividir pela quantidade. O problema é que **boa parte dos
        clientes ainda não cancelou** — estão pagando até hoje. Não dá pra ignorá-los (isso
        jogaria a média pra baixo, contando só quem já morreu), mas também não dá pra fingir
        que já sabemos quanto tempo mais eles vão durar.

        **A solução:** é a mesma lógica usada para calcular a **expectativa de vida de um
        país** — ninguém espera todo mundo morrer para calcular isso. Olha-se para a fração
        de pessoas que continua viva a cada ano (misturando quem já morreu com quem ainda
        está vivo) e soma-se essas frações ao longo do tempo. O **RMST faz exatamente isso
        com clientes**: soma, mês a mês, a fração de clientes que ainda continua ativa — o
        resultado dá um número em **meses**, que é a melhor estimativa de "vida útil média"
        disponível com os dados que já temos.

        **Por que "restrito" (o R de RMST)?** Porque essa soma precisa parar em algum ponto
        (um "horizonte") — não dá pra somar até o infinito quando ainda não observamos
        clientes durando pra sempre. Por isso as tabelas abaixo mostram o RMST em alguns
        horizontes diferentes (6, 12, 24, 36 meses, e também um "RMST completo" que vai até
        onde os dados permitem).

        **Exemplo bem simples:** imagine 100 clientes que entraram juntos. No mês 1, 100%
        ainda estão ativos. No mês 6, 80% seguem ativos. No mês 12, 50%. Somando essas
        frações mês a mês (a "área" sob a curva de sobrevivência) até o mês 12, chegamos a
        um RMST de, digamos, **8,5 meses** — que se lê como: *"em média, dentro do primeiro
        ano, um cliente desse grupo fica ativo por 8,5 meses"*.
        """
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
    st.markdown("**Tempo médio de vida esperado — todos os clientes**")
    row = rmst_geral.iloc[0]
    cols = st.columns(1 + len(RMST_HORIZONTES_MESES))
    with cols[0]:
        st.metric(
            "Tempo médio (RMST completo)",
            f"{row['rmst_completo']:.1f} meses",
            help=f"Follow-up disponível: até {row['max_obs_meses']:.0f} meses",
        )
    for col, tau in zip(cols[1:], RMST_HORIZONTES_MESES):
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
    # chart_layout() PRECISA vir antes do update_layout customizado — ele
    # redefine xaxis.type="category" e title="" (padrão pensado pra gráficos
    # de série mensal), sobrescrevendo qualquer eixo customizado setado
    # depois. Mesmo gotcha já documentado nas Páginas 2 e 5 deste dashboard.
    fig = chart_layout(fig, height=440, legend_bottom=True)
    fig.update_layout(
        yaxis=dict(title="% de clientes ainda ativos", ticksuffix="%", range=[0, 100]),
        xaxis=dict(title="Meses desde a primeira liquidação (t0)", type="linear"),
    )
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# TEMPO MÉDIO DE VIDA POR PLANO (RMST completo)
# ─────────────────────────────────────────────
st.subheader("Tempo Médio de Vida Estimado por Plano")
st.caption(
    "RMST completo: área sob a curva de sobrevivência até o maior tempo "
    "observado naquele plano — a melhor estimativa disponível de \"tempo "
    "médio de vida\", já que uma média de verdade não existe enquanto parte "
    "da base ainda está ativa (censurada). Planos com follow-up mais curto "
    "(ex: lançados recentemente) tendem a mostrar um número menor aqui — "
    "não porque duram menos, mas porque ainda não houve tempo de observar "
    "mais."
)

df_rmst = compute_rmst_snapshots(df)

if df_rmst.empty:
    no_data("Nenhum plano com amostra suficiente para RMST.")
else:
    df_rmst_sorted = df_rmst.sort_values("n_clientes", ascending=False)
    cols_medio = st.columns(len(df_rmst_sorted))
    for col, (_, row) in zip(cols_medio, df_rmst_sorted.iterrows()):
        label = PLAN_LABELS.get(row["plano"], row["plano"].title())
        with col:
            st.metric(
                f"{label} (n={int(row['n_clientes'])})",
                f"{row['rmst_completo']:.1f} meses",
                help=f"Follow-up disponível: até {row['max_obs_meses']:.0f} meses",
            )

    st.markdown("**Snapshots de RMST em horizontes fixos**")
    st.caption(
        "Mais robusto que o RMST completo pra COMPARAR planos entre si — usa "
        "o mesmo horizonte pra todos, em vez do maior tempo observado de "
        "cada um (que varia por plano). Fica em branco quando o plano ainda "
        "não tem follow-up suficiente pra alcançar aquele horizonte."
    )

    df_show = df_rmst_sorted.copy()
    df_show["Plano"] = df_show["plano"].map(PLAN_LABELS).fillna(df_show["plano"])

    cols_order = ["Plano", "n_clientes", "max_obs_meses", "rmst_completo"] + [
        f"rmst_{t}m" for t in RMST_HORIZONTES_MESES
    ]
    df_show = df_show[cols_order]

    rename_map = {
        "n_clientes": "Clientes",
        "max_obs_meses": "Follow-up (meses)",
        "rmst_completo": "RMST completo",
    }
    rename_map.update({f"rmst_{t}m": f"RMST @ {t}m" for t in RMST_HORIZONTES_MESES})
    df_show = df_show.rename(columns=rename_map)

    df_show["Follow-up (meses)"] = df_show["Follow-up (meses)"].apply(lambda v: f"{v:.0f}")
    for col in ["RMST completo"] + [f"RMST @ {t}m" for t in RMST_HORIZONTES_MESES]:
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
