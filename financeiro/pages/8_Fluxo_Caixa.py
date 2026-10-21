"""
pages/8_Fluxo_Caixa.py
Fluxo de Caixa projetado — Mensalidade + Setup (boletos) + Meios de pagamento (Intermediação).

Regra de recebimento (D0 = dia do vencimento, D+n = n dias ÚTEIS depois; D-n = crédito antes do vencimento):
  a curva de crédito de cada categoria é aprendida nos boletos dos últimos N meses (CGADB fora) e
  aplicada aos boletos em aberto, condicionada a "ainda não pago". Créditos já agendados na tabela
  entram como certeza. Sem recebimento em fim de semana/feriado. Motor: utils/fluxo_calc.py.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from datetime import date

st.set_page_config(page_title="Fluxo de Caixa | InChurch", page_icon="💵", layout="wide")

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "fluxo_caixa"

from utils.style import inject_css
from plotly.subplots import make_subplots
from utils.data import PALETTE, br_style, chart_layout, fmt_brl, fmt_num, fmt_int, no_data, _bq_query
from utils import fluxo_calc as fc
from utils.superlogica import buscar_despesas_abertas

inject_css()

DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
COR = {"Mensalidade": PALETTE[0], "Setup": PALETTE[6], "Meios de pagamento": PALETTE[3], "Saídas": "#e5534b"}


@st.cache_data(ttl=3600)
def load_boletos_fluxo() -> pd.DataFrame:
    return _bq_query(fc.SQL_BOLETOS, "bigquery_bi")


@st.cache_data(ttl=3600)
def load_intermediacao_fluxo() -> pd.DataFrame:
    return _bq_query(fc.SQL_INTERM, "bigquery_bi")


@st.cache_data(ttl=3600)
def load_despesas_fluxo(_app_token: str, _access_token: str, dia: str) -> pd.DataFrame:
    """`dia` só invalida o cache na virada do dia (os tokens ficam fora da chave de cache)."""
    return buscar_despesas_abertas(_app_token, _access_token, pd.Timestamp(dia))


def brl(v: float) -> str:
    """R$ 12.000.420,21 — milhar com ponto, centavos com vírgula."""
    return f"R$ {fmt_brl(v)}"


def parse_brl(txt: str) -> float | None:
    """Lê '12.000.420,21' (padrão BR). Ponto = milhar, vírgula = centavos. None se inválido."""
    t = (txt or "").strip().replace("R$", "").replace(" ", "")
    if not t:
        return 0.0
    neg = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("-()").replace(".", "").replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


# ── Header ────────────────────────────────────
col_title, col_janela, col_hor = st.columns([6, 2, 2], vertical_alignment="bottom")
with col_title:
    st.markdown("<h1>Fluxo de Caixa <span>Projetado</span></h1>", unsafe_allow_html=True)
with col_janela:
    janela = st.selectbox("Janela do padrão (meses)", [2, 3, 4, 6], index=2)
with col_hor:
    horizonte = st.slider("Horizonte (dias)", 7, 28, 25)

incluir_atrasadas = st.checkbox(
    "Incluir despesas atrasadas em aberto nas saídas (pagas hoje)", value=False,
    help="Contas a pagar com vencimento anterior a hoje e ainda em aberto. Por padrão ficam fora do fluxo e "
         "aparecem à parte, porque podem ser baixas ainda não feitas.")

with st.spinner("Carregando boletos e intermediação..."):
    df_bol = load_boletos_fluxo()
    df_int = load_intermediacao_fluxo()

if df_bol.empty or df_int.empty:
    no_data("Sem dados de boletos/intermediação para projetar.")
    st.stop()

hoje = pd.Timestamp(date.today())
res = fc.calcular_fluxo(df_bol, df_int, hoje, janela_meses=janela, horizonte_dias=horizonte)
fluxo, curvas = res["fluxo"], res["curvas"]

# ── Despesas (API Superlógica) ────────────────
cred = st.secrets.get("superlogica", {})
desp = None
if cred.get("app_token") and cred.get("access_token"):
    try:
        with st.spinner("Buscando contas a pagar na Superlógica..."):
            df_desp = load_despesas_fluxo(cred["app_token"], cred["access_token"], hoje.strftime("%Y-%m-%d"))
        desp = fc.projetar_despesas(df_desp, fluxo.index, hoje, incluir_atrasadas)
    except Exception as e:  # API fora do ar / token inválido: segue só com as entradas
        st.warning(f"Não foi possível carregar as despesas da Superlógica: {e}")
else:
    st.info("Despesas não carregadas: adicione `[superlogica]` com `app_token` e `access_token` nos secrets do app.")
tem_desp = desp is not None
fluxo["Saídas"] = desp["serie"] if tem_desp else 0.0
fluxo["Resultado do dia"] = fluxo["Total"] - fluxo["Saídas"]

if fluxo.empty:
    no_data("Nenhum dia útil no horizonte selecionado.")
    st.stop()

# ── Saldo inicial (preenchido por você) ──────
if "fluxo_saldo_txt" in st.session_state:            # mantém o valor ao trocar de página
    st.session_state["fluxo_saldo_txt"] = st.session_state["fluxo_saldo_txt"]
with st.container(border=True):
    cs1, cs2 = st.columns([2, 5], vertical_alignment="center")
    with cs1:
        saldo_txt = st.text_input("Saldo inicial de caixa (R$)", value="0,00", key="fluxo_saldo_txt",
                                  help="Digite no padrão brasileiro, ex.: 1.250.000,00 (ponto = milhar, vírgula = centavos). "
                                       "Confirme com Enter.")
    saldo_lido = parse_brl(saldo_txt)
    saldo_inicial = saldo_lido if saldo_lido is not None else 0.0
    with cs2:
        if saldo_lido is None:
            st.error("Valor inválido. Use o formato 1.250.000,00")
        else:
            st.caption(
                f"Lido como **{brl(saldo_inicial)}** — saldo em conta no início de hoje ({hoje:%d/%m}), antes das "
                "movimentações de hoje. O **Saldo projetado** parte dele: saldo + entradas − saídas, dia a dia.")
fluxo["Saldo projetado"] = saldo_inicial + fluxo["Resultado do dia"].cumsum()

# ── KPIs ──────────────────────────────────────
st.subheader(f"Caixa previsto — {fluxo.index[0]:%d/%m} a {fluxo.index[-1]:%d/%m}")
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Entradas previstas", brl(fluxo["Total"].sum()),
          help="Mensalidade + Setup + Meios de pagamento.")
k2.metric("Saídas previstas", brl(fluxo["Saídas"].sum()) if tem_desp else "—",
          help="Contas a pagar em aberto (API Superlógica), no dia do vencimento (ou próximo dia útil).")
k3.metric("Resultado do período", brl(fluxo["Resultado do dia"].sum()) if tem_desp else "—")
k4.metric("Saldo final projetado", brl(fluxo["Saldo projetado"].iloc[-1]) if tem_desp else "—",
          help="Saldo inicial informado + entradas − saídas.")
k5.metric("Entradas já agendadas (certas)", brl(fluxo["já agendado"].sum()),
          help="Clientes que já pagaram e cujo crédito está agendado em dt_recebimento_recb.")
if tem_desp:
    dia_min = fluxo["Saldo projetado"].idxmin()
    st.caption(f"Menor saldo projetado no período: {brl(fluxo['Saldo projetado'].min())} em {dia_min:%d/%m}"
               + (" — **caixa negativo**." if fluxo["Saldo projetado"].min() < 0 else "."))
st.caption(
    f"Entradas: Mensalidade {brl(fluxo['Mensalidade'].sum())} · Setup {brl(fluxo['Setup'].sum())} · "
    f"Meios de pagamento {brl(fluxo['Meios de pagamento'].sum())}"
)
if tem_desp:
    for e in desp["excluidas"]:
        if e["n"]:
            st.caption(f"Fora do fluxo por regra — {e['nome']}: {e['n']} itens em aberto ({brl(e['valor'])} no total, "
                       f"{brl(e['valor_janela'])} dentro desta janela).")
if tem_desp and desp["atrasadas_n"]:
    st.caption(
        f"⚠️ {desp['atrasadas_n']} despesas atrasadas ainda em aberto somam {brl(desp['atrasadas_valor'])} — "
        + ("já incluídas nas saídas de hoje." if incluir_atrasadas else
           "fora do fluxo (marque a opção acima para incluí-las).")
    )

st.divider()

# ── Gráfico diário ────────────────────────────
st.subheader("Caixa diário previsto")
x = [f"{d:%d/%m} {DIAS_SEMANA[d.weekday()]}" for d in fluxo.index]
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.07, row_heights=[0.6, 0.4],
                    subplot_titles=("Entradas e saídas do dia", "Saldo projetado" if tem_desp else "Entradas acumuladas"))
for nome in ("Mensalidade", "Setup", "Meios de pagamento"):
    fig.add_bar(x=x, y=fluxo[nome], name=nome, marker_color=COR[nome], row=1, col=1,
                hovertemplate="%{x}<br>" + nome + ": R$ %{y:,.2f}<extra></extra>")
if tem_desp:
    fig.add_bar(x=x, y=-fluxo["Saídas"], name="Saídas", marker_color=COR["Saídas"], row=1, col=1,
                customdata=fluxo["Saídas"], hovertemplate="%{x}<br>Saídas: R$ %{customdata:,.2f}<extra></extra>")
    linha_y, linha_nome = fluxo["Saldo projetado"], "Saldo projetado"
else:
    linha_y, linha_nome = fluxo["Total"].cumsum(), "Entradas acumuladas"
fig.add_scatter(x=x, y=linha_y, name=linha_nome, mode="lines+markers", row=2, col=1,
                line=dict(color=PALETTE[1], width=2),
                marker=dict(size=7, color=[COR["Saídas"] if v < 0 else PALETTE[0] for v in linha_y]),
                hovertemplate="%{x}<br>" + linha_nome + ": R$ %{y:,.2f}<extra></extra>")
fig.add_hline(y=0, row=2, col=1, line=dict(color=PALETTE[3], width=1, dash="dot"))
chart_layout(fig, height=620, legend_bottom=True)
fig.update_layout(barmode="relative")
fig.update_xaxes(type="category", showgrid=False)
fig.update_yaxes(tickprefix="R$ ", tickformat=",.2~f", showgrid=True, gridcolor="#292929", zeroline=False)
st.plotly_chart(fig, use_container_width=True)

# ── Tabela diária ─────────────────────────────
with st.expander("Tabela diária", expanded=False):
    t = fluxo.drop(columns=["Acumulado"]).rename(columns={"Total": "Entradas", "já agendado": "Entradas já agendadas"})
    t.insert(0, "Dia da semana", [DIAS_SEMANA[d.weekday()] for d in t.index])
    t = t.reset_index().rename(columns={"dia": "Data"})
    st.dataframe(br_style(t, {"Data": "data", **{c: "brl" for c in t.columns[2:]}}),
                 use_container_width=True, hide_index=True)

if tem_desp and not desp["itens"].empty:
    with st.expander("Despesas previstas — por categoria e maiores itens", expanded=False):
        it = desp["itens"]
        cat = it.groupby("categoria")["valor"].sum().sort_values(ascending=False)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Por categoria**")
            st.dataframe(br_style(pd.DataFrame({"Categoria": cat.index, "Valor": cat.values}), {"Valor": "brl"}),
                         use_container_width=True, hide_index=True)
        with c2:
            st.markdown("**Maiores itens**")
            top = it.sort_values("valor", ascending=False).head(15)
            st.dataframe(br_style(pd.DataFrame({
                "Pagamento": top["pagto"].values, "Fornecedor": top["fornecedor"].values,
                "Categoria": top["categoria"].values, "Valor": top["valor"].values}),
                {"Pagamento": "data", "Valor": "brl"}), use_container_width=True, hide_index=True)

st.divider()

# ── Caixas de regra ───────────────────────────
st.subheader("Regra de recebimento aplicada")
st.caption(
    "D0 = dia do vencimento (se cair em dia não útil, o próximo dia útil). D+n = n dias úteis depois do D0; "
    "'Antes do D0' = crédito em conta antes do vencimento. Percentuais ponderados por valor (comp_valor), "
    f"aprendidos nos boletos dos últimos {janela} meses com cauda de {fc.LAG_MAX} dias úteis já completa."
)


def caixa_regra(conta: str) -> None:
    c = curvas[conta]
    nome = fc.CONTAS[conta]
    r = fc.resumo_curva(c)
    with st.container(border=True):
        st.markdown(f"**{nome}** — base de R$ {fmt_brl(c['base'])} · {fmt_int(c['n_boletos'])} boletos · "
                    f"vencimentos de {c['ini']:%d/%m/%Y} a {c['fim']:%d/%m/%Y}")
        linhas = [r.iloc[i:i + 7] for i in (0, 7)]
        for bloco in linhas:
            cols = st.columns(len(bloco))
            for col, (_, row) in zip(cols, bloco.iterrows()):
                col.metric(row["faixa"], f"{fmt_num(row['pct'] * 100, 1)}%")
        resto = r.iloc[14:]
        if len(resto):
            cols = st.columns(len(resto))
            for col, (_, row) in zip(cols, resto.iterrows()):
                col.metric(row["faixa"], f"{fmt_num(row['pct'] * 100, 1)}%")
        lags = c["lags"]
        sel = (lags >= -8) & (lags <= 14)
        f2 = go.Figure(go.Bar(
            x=[("D0" if k == 0 else (f"D{k}" if k < 0 else f"D+{k}")) for k in lags[sel]],
            y=c["p"][sel] * 100, marker_color=COR[nome],
            hovertemplate="%{x}: %{y:.1f}%<extra></extra>"))
        f2.update_layout(yaxis=dict(ticksuffix="%"))
        st.plotly_chart(chart_layout(f2, height=220), use_container_width=True)


cA, cB = st.columns(2)
with cA:
    caixa_regra("1.2.2")
with cB:
    caixa_regra("1.2.1")

# ── Meios de pagamento ────────────────────────
perfil = res["perfil_interm"]
with st.container(border=True):
    st.markdown(f"**Meios de pagamento (Intermediação)** — média diária dos últimos {janela} meses fechados, "
                f"por dia do mês (R$ por dia corrido). Fim de semana e feriado acumulam no próximo dia útil. "
                f"Dados até {res['interm_ate']:%d/%m} (a tabela chega com defasagem).")
    faixas = [("Dias 1–5", 1, 5), ("Dias 6–10", 6, 10), ("Dias 11–20", 11, 20), ("Dias 21–31", 21, 31)]
    cols = st.columns(len(faixas))
    for col, (nome, a, b) in zip(cols, faixas):
        col.metric(nome, f"{brl(perfil.loc[a:b].mean())}/dia")
    f3 = go.Figure(go.Bar(x=[str(i) for i in perfil.index], y=perfil.values, marker_color=COR["Meios de pagamento"],
                          hovertemplate="Dia %{x}: R$ %{y:,.0f}<extra></extra>"))
    f3.update_layout(yaxis=dict(tickprefix="R$ ", tickformat=",.0f"))
    st.plotly_chart(chart_layout(f3, height=220), use_container_width=True)

# ── Premissas ─────────────────────────────────
with st.expander("Premissas e limitações"):
    st.markdown(
        f"""
- **Fonte:** `splgc-cobrancas_competencia-all` (contas 1.2.2 Mensalidade, 1.2.1 Setup e 1.2.4 Intermediação), deduplicada.
  Data de caixa = `dt_recebimento_recb`. Os boletos são gerados com ~28 dias de antecedência, por isso o horizonte máximo é 28 dias.
- **CGADB (id 6648) fica fora** da curva e do fluxo (boleto mensal de ~R$ 322 mil sistematicamente em aberto).
- **Boleto em aberto:** probabilidade de crédito em cada dia = curva do cliente pagando (D0+m) combinada com o intervalo
  pagamento→crédito (92% em exatamente 2 dias úteis, 5% no mesmo dia, ~2% cartão com 20+ dias), **condicionada a ainda não ter pago**.
  Assim um boleto que vence no dia 10 já contribui para o caixa do dia 05.
- **Créditos já agendados** (cliente pagou, crédito em data futura) entram como certeza, sem probabilidade.
- **Dias sem recebimento:** fins de semana, feriados nacionais (biblioteca `holidays`), Carnaval e Corpus Christi.
- **Não incluído nas entradas:** Acordos (1.2.13), Plano Anual (1.2.16), 1.2.20, 1.3.x e boletos ainda não gerados.
- **Saídas:** contas a pagar em aberto (`fl_status_mov = 0`) da API Superlógica (`/v2/financeiro/caixa`), sem curva — valem o vencimento e o valor exatos; vencimento em dia não útil paga no próximo dia útil. Transferências entre contas ficam fora. Busca de 9 meses atrás a 60 dias à frente (a API estoura a memória em janelas maiores).
- **Exclusões por regra:** parcelas da Eduzz ("Parcela N de M", vencimento até 31/12/2026) ficam fora porque foi negociado não pagá-las em 2026 — regra em `EXCLUSOES_DESPESAS` (`utils/fluxo_calc.py`); some sozinha quando o contas a pagar remover os itens.
- **Despesas atrasadas** (vencimento < hoje e ainda em aberto) ficam fora por padrão e são mostradas à parte, porque podem ser baixas não feitas.
- **Pipeline:** liquidações podem chegar ao BQ com 1–3 dias úteis de atraso após feriado, o que pode atrasar um pouco a leitura.
- **Backtest (rodado em 21/10/2026, janela de 4 meses, 25 dias à frente):** erro no total de **−1% a +1%** nas datas-base
  de mai, jun, jul e ago/2026 e **+8%** em 14/set (período com inadimplência subindo — a curva histórica é otimista quando o
  comportamento de pagamento piora). Erro diário médio de ~19–37% do valor do dia: o total do período é mais confiável que o dia isolado.
"""
    )
