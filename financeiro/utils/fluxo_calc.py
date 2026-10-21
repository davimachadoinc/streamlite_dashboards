"""
utils/fluxo_calc.py
Motor de cálculo do Fluxo de Caixa (sem Streamlit — testável isolado).

Receita de boletos (Mensalidade 1.2.2 e Setup 1.2.1):
  D0 = dia do vencimento (se cair em dia não útil, o próximo dia útil).
  Atraso (lag) = dias ÚTEIS entre D0 e dt_recebimento_recb (negativo = crédito antes do vencimento).
  Curva = % do valor (comp_valor) creditado em cada lag, aprendida em boletos "maduros"
  (D0 com pelo menos LAG_MAX dias úteis de cauda já decorridos).
  Projeção de um boleto ABERTO: p[j] / (1 - Σ p[k<=e]), onde e = lag já decorrido hoje.
  Ou seja, é condicionada a "ainda não pago" — um boleto que vence dia 10 já pode cair em D-3.

Meios de pagamento (Intermediação 1.2.4):
  Entra 1x por dia útil. Desfaz-se o acúmulo (valor do dia útil é espalhado nos dias corridos
  desde o dia útil anterior), tira-se a média por dia do mês nos N meses fechados e re-acumula
  no próximo dia útil.
"""
import time
from datetime import timedelta

import numpy as np
import pandas as pd
import holidays
from dateutil.easter import easter

_CARREGADO_EM = time.time()   # usado pela página para detectar versão antiga em memória após um deploy
LAG_MIN, LAG_MAX = -20, 30
CONTAS = {"1.2.2": "Mensalidade", "1.2.1": "Setup"}
CGADB_ID = "6648"  # fora da curva e fora do fluxo (decisão do Davi, 2026-10-21)

SQL_BOLETOS = f"""
WITH x AS (
  SELECT DISTINCT
    id_recebimento_recb, comp_id_composicao_comp,
    comp_st_conta_cont AS conta,
    CAST(dt_vencimento_recb AS DATE)  AS venc,
    CAST(dt_recebimento_recb AS DATE) AS receb,
    CAST(dt_liquidacao_recb AS DATE)  AS liq,
    comp_valor
  FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
  WHERE comp_st_conta_cont IN ('1.2.1', '1.2.2')
    AND id_sacado_sac != '{CGADB_ID}'
    AND comp_valor > 0
    AND CAST(dt_vencimento_recb AS DATE) >= DATE_SUB(CURRENT_DATE(), INTERVAL 9 MONTH)
)
SELECT id_recebimento_recb, conta, MIN(venc) AS venc, MAX(receb) AS receb, MAX(liq) AS liq, SUM(comp_valor) AS valor
FROM x
GROUP BY 1, 2
"""

SQL_INTERM = """
-- Receita bruta de intermediação (1.2.4) e a taxa de intermediação (3.3.1, valor negativo) lançada na MESMA
-- cobrança e no mesmo dia: o parceiro só transfere o líquido (vl_total_recb), a gestão lança bruto e custo.
SELECT receb,
       SUM(IF(conta = '1.2.4', comp_valor, 0))  AS valor,   -- receita bruta
       SUM(IF(conta = '3.3.1', -comp_valor, 0)) AS custo    -- taxa (positiva)
FROM (
  SELECT DISTINCT id_recebimento_recb, comp_id_composicao_comp, comp_st_conta_cont AS conta,
         CAST(dt_recebimento_recb AS DATE) AS receb, comp_valor
  FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
  WHERE comp_st_conta_cont IN ('1.2.4', '3.3.1')
    AND dt_recebimento_recb IS NOT NULL
    AND CAST(dt_recebimento_recb AS DATE) >= DATE_SUB(CURRENT_DATE(), INTERVAL 9 MONTH)
    AND id_recebimento_recb IN (
      SELECT DISTINCT id_recebimento_recb
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE comp_st_conta_cont = '1.2.4'
        AND CAST(dt_vencimento_recb AS DATE) >= DATE_SUB(CURRENT_DATE(), INTERVAL 10 MONTH)
    )
)
GROUP BY 1
ORDER BY 1
"""


# ─────────────────────────────────────────────
# Calendário
# ─────────────────────────────────────────────
def feriados(y0: int = 2024, y1: int = 2028) -> np.ndarray:
    """Feriados nacionais (lib holidays) + Carnaval (seg/ter) e Corpus Christi, sem recebimento."""
    h = set(holidays.Brazil(years=range(y0, y1 + 1)).keys())
    for y in range(y0, y1 + 1):
        e = easter(y)
        h.update({e - timedelta(days=48), e - timedelta(days=47), e + timedelta(days=60)})
    return np.array(sorted(h), dtype="datetime64[D]")


FER = feriados()


def _d(x) -> np.ndarray:
    return np.asarray(pd.to_datetime(x)).astype("datetime64[D]")


def is_bd(x) -> np.ndarray:
    return np.is_busday(_d(x), holidays=FER)


def next_bd(x) -> np.ndarray:
    """Próximo dia útil (o próprio dia se já for útil)."""
    return np.busday_offset(_d(x), 0, roll="forward", holidays=FER)


def prev_bd_strict(x) -> np.ndarray:
    """Dia útil estritamente anterior."""
    return np.busday_offset(_d(x), -1, roll="backward", holidays=FER)


def bd_lag(d0, t) -> np.ndarray:
    """Dias úteis de d0 até t (negativo se t < d0)."""
    a, b = _d(d0), _d(t)
    return np.where(b >= a,
                    np.busday_count(a, b, holidays=FER),
                    -np.busday_count(b, a, holidays=FER))


# ─────────────────────────────────────────────
# Preparação
# ─────────────────────────────────────────────
GAP_MAX = 25  # dias úteis máx. entre pagamento do cliente (liq) e crédito em conta (receb)


def preparar_boletos(df: pd.DataFrame, as_of: pd.Timestamp, censurar: bool = False) -> pd.DataFrame:
    """D0 em dia útil.

    Crédito agendado = receb preenchido e futuro (cliente já pagou, dinheiro ainda não entrou).
    censurar=True (só backtest): pagamentos posteriores a as_of voltam a "em aberto".
    """
    b = df.copy()
    for c in ("venc", "receb", "liq"):
        b[c] = pd.to_datetime(b[c])
    b["valor"] = pd.to_numeric(b["valor"], errors="coerce").fillna(0.0)
    if censurar:
        b.loc[b["liq"] > as_of, ["liq", "receb"]] = pd.NaT
    b["d0"] = pd.to_datetime(next_bd(b["venc"]))
    for col_d, col_l in (("receb", "lag"), ("liq", "lag_pg")):
        b[col_l] = np.nan
        ok = b[col_d].notna()
        b.loc[ok, col_l] = bd_lag(b.loc[ok, "d0"], b.loc[ok, col_d])
    return b


# ─────────────────────────────────────────────
# Curva de recebimento
# ─────────────────────────────────────────────
def _hist(s: pd.DataFrame, col: str, base: float, lo: int, hi: int) -> np.ndarray:
    out = np.zeros(hi - lo + 1)
    if base <= 0:
        return out
    pg = s[s[col].notna()].copy()
    pg[col] = pg[col].clip(lower=lo)
    pg = pg[pg[col] <= hi]
    for k, v in pg.groupby(col)["valor"].sum().items():
        out[int(k) - lo] = v / base
    return out


def curva_recebimento(b: pd.DataFrame, conta: str, as_of: pd.Timestamp, janela_meses: int) -> dict:
    """Aprende, em boletos maduros, (1) a curva de CRÉDITO por lag de D0 (a "regra" exibida),
    (2) a curva de PAGAMENTO do cliente por lag de D0 e (3) o intervalo pagamento -> crédito."""
    cut = pd.Timestamp(np.busday_offset(_d(as_of), -LAG_MAX, roll="backward", holidays=FER))
    ini = cut - pd.DateOffset(months=janela_meses)
    s = b[(b["conta"] == conta) & (b["d0"] > ini) & (b["d0"] <= cut)]
    base = float(s["valor"].sum())
    lags = np.arange(LAG_MIN, LAG_MAX + 1)
    p = _hist(s, "lag", base, LAG_MIN, LAG_MAX)
    q = _hist(s, "lag_pg", base, LAG_MIN, LAG_MAX)
    pg = s[s["lag"].notna() & s["lag_pg"].notna()].copy()
    gap = (pg["lag"] - pg["lag_pg"]).clip(lower=0, upper=GAP_MAX).astype(int)
    G = np.zeros(GAP_MAX + 1)
    if pg["valor"].sum() > 0:
        for k, v in pg.groupby(gap)["valor"].sum().items():
            G[int(k)] = v / pg["valor"].sum()
    else:
        G[2] = 1.0
    return {
        "conta": conta, "p": p, "q": q, "G": G, "lags": lags, "base": base,
        "n_boletos": int(s["id_recebimento_recb"].nunique()),
        "ini": ini + pd.Timedelta(days=1), "fim": cut,
        "nunca": float(max(0.0, 1.0 - p.sum())),
    }


def resumo_curva(c: dict) -> pd.DataFrame:
    """Faixas para a caixa de regra: antes de D0, D0, D+1... D+7, cauda e nunca."""
    p, lags = c["p"], c["lags"]
    at = lambda a, b: float(p[(lags >= a) & (lags <= b)].sum())
    linhas = [("Antes do D0", at(LAG_MIN, -1))]
    linhas += [("D0" if k == 0 else f"D+{k}", at(k, k)) for k in range(0, 8)]
    linhas += [("D+8 a D+14", at(8, 14)), ("D+15 a D+21", at(15, 21)), (f"D+22 a D+{LAG_MAX}", at(22, LAG_MAX)),
               ("Não recebido", c["nunca"])]
    return pd.DataFrame(linhas, columns=["faixa", "pct"])


# ─────────────────────────────────────────────
# Projeção — boletos
# ─────────────────────────────────────────────
def dias_futuros(as_of: pd.Timestamp, fim: pd.Timestamp) -> pd.DatetimeIndex:
    """Dias úteis em (as_of, fim]."""
    idx = pd.date_range(as_of + pd.Timedelta(days=1), fim, freq="D")
    return idx[is_bd(idx)] if len(idx) else idx


def _matriz_condicional(curva: dict) -> tuple[np.ndarray, int, int]:
    """M[e, j]: P(crédito no lag j | boleto ainda não pago após o lag de pagamento e).

    e (estado) vai de LAG_MIN-1 (nada decorrido) até LAG_MAX; j de LAG_MIN até LAG_MAX+GAP_MAX.
    Crédito = pagamento + intervalo (convolução q * G, ambos em dias úteis).
    """
    q, G = curva["q"], curva["G"]
    n_e = LAG_MAX - (LAG_MIN - 1) + 1
    n_j = (LAG_MAX + GAP_MAX) - LAG_MIN + 1
    M = np.zeros((n_e, n_j))
    for ie in range(n_e):
        e = LAG_MIN - 1 + ie
        qm = q.copy()
        qm[: max(0, e - LAG_MIN + 1)] = 0.0              # pagamentos até o lag e já ocorreram
        surv = 1.0 - q[: max(0, e - LAG_MIN + 1)].sum()
        if surv <= 1e-6:
            continue
        M[ie, :] = np.convolve(qm, G)[:n_j] / surv
    return M, LAG_MIN - 1, LAG_MIN


def projetar_boletos(b: pd.DataFrame, curva: dict, as_of: pd.Timestamp, dias: pd.DatetimeIndex,
                     hoje: pd.Timestamp) -> pd.DataFrame:
    """Caixa por dia útil de `dias`: coluna 'agendado' (certo) + 'esperado' (probabilístico)."""
    out = pd.DataFrame(0.0, index=dias, columns=["agendado", "esperado"])
    if len(dias) == 0:
        return out
    c = b[b["conta"] == curva["conta"]]
    # 1) créditos já agendados (cliente pagou, dinheiro entra no futuro)
    ag = c[c["receb"].notna() & (c["receb"] >= hoje)]
    if not ag.empty:
        rec = pd.to_datetime(next_bd(ag["receb"]))
        s = ag.assign(_t=rec).groupby("_t")["valor"].sum()
        out["agendado"] = s.reindex(dias).fillna(0.0).values
    # 2) boletos em aberto: curva condicionada
    ab = c[c["receb"].isna()]
    if ab.empty:
        return out
    M, e0, j0 = _matriz_condicional(curva)
    e = bd_lag(ab["d0"], np.full(len(ab), as_of.to_datetime64()))
    ie = (np.clip(e, e0, LAG_MAX) - e0).astype(int)
    v = ab["valor"].values
    for t in dias:
        j = bd_lag(ab["d0"], np.full(len(ab), t.to_datetime64()))
        valid = (j >= LAG_MIN) & (j <= LAG_MAX + GAP_MAX)
        pj = np.zeros(len(ab))
        pj[valid] = M[ie[valid], (j[valid] - j0).astype(int)]
        out.loc[t, "esperado"] = float((v * pj).sum())
    return out


# ─────────────────────────────────────────────
# Projeção — meios de pagamento (Intermediação)
# ─────────────────────────────────────────────
def accrual_diario(interm: pd.DataFrame) -> pd.Series:
    """Espalha cada crédito (dia útil t) nos dias corridos de (dia útil anterior, t]."""
    s = interm.assign(receb=pd.to_datetime(interm["receb"])).groupby("receb")["valor"].sum()
    acc = {}
    for t, v in s.items():
        ini = pd.Timestamp(prev_bd_strict(t)) + pd.Timedelta(days=1)
        rng = pd.date_range(ini, t, freq="D")
        for d in rng:
            acc[d] = acc.get(d, 0.0) + float(v) / len(rng)
    return pd.Series(acc).sort_index()


def perfil_intermediacao(interm: pd.DataFrame, as_of: pd.Timestamp, janela_meses: int) -> pd.Series:
    """Média por dia do mês (1..31) nos `janela_meses` meses fechados anteriores a as_of."""
    acc = accrual_diario(interm)
    m_fim = as_of.to_period("M")                 # mês corrente fica de fora (incompleto)
    m_ini = m_fim - janela_meses
    sel = acc[(acc.index.to_period("M") >= m_ini) & (acc.index.to_period("M") < m_fim)]
    if sel.empty:
        return pd.Series(0.0, index=range(1, 32))
    return sel.groupby(sel.index.day).mean().reindex(range(1, 32)).fillna(0.0)


def razao_custo_intermediacao(interm: pd.DataFrame, as_of: pd.Timestamp, janela_meses: int) -> dict:
    """Custo (3.3.1) / receita bruta (1.2.4) por mês fechado da janela; usa o MAIOR mês (decisão do Davi).

    Só entram os dias em que a taxa foi lançada (antes de abr/2026 não existia a linha 3.3.1 e os valores
    provavelmente já vinham líquidos). Meses fechados = os `janela_meses` meses anteriores ao de as_of.
    """
    d = interm.assign(receb=pd.to_datetime(interm["receb"]))
    m_fim = as_of.to_period("M")
    per = d["receb"].dt.to_period("M")
    d = d[(per >= m_fim - janela_meses) & (per < m_fim) & (d["custo"] > 0)].copy()
    d["mes"] = d["receb"].dt.to_period("M")
    g = d.groupby("mes")[["custo", "valor"]].sum()
    g = g[g["valor"] > 0]
    por_mes = (g["custo"] / g["valor"]).sort_index()
    if por_mes.empty:
        return {"razao": None, "mes_max": None, "por_mes": {}, "dias": 0, "custo": 0.0, "receita": 0.0}
    mes_max = por_mes.idxmax()
    return {"razao": float(por_mes.max()), "mes_max": mes_max, "por_mes": {m: float(v) for m, v in por_mes.items()},
            "dias": int(len(d)), "custo": float(g["custo"].sum()), "receita": float(g["valor"].sum())}


def projetar_intermediacao(perfil: pd.Series, dias: pd.DatetimeIndex) -> pd.Series:
    out = pd.Series(0.0, index=dias)
    for t in dias:
        ini = pd.Timestamp(prev_bd_strict(t)) + pd.Timedelta(days=1)
        out[t] = float(sum(perfil[d.day] for d in pd.date_range(ini, t, freq="D")))
    return out


# ─────────────────────────────────────────────
# Despesas (contas a pagar — API Superlógica)
# ─────────────────────────────────────────────
# Regras de exclusão de despesas (decisão do Davi). Valem enquanto o contas a pagar não remover o item.
EXCLUSOES_DESPESAS = [
    {
        "nome": "Parcelas Eduzz (negociado não pagar em 2026)",
        "fornecedor_contem": "eduzz",
        "historico_regex": r"Parcela \d+ de \d+",
        "venc_ate": pd.Timestamp("2026-12-31"),
    },
]


def _aplicar_exclusoes(desp: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """Remove itens cobertos por EXCLUSOES_DESPESAS. Devolve (restante, resumo por regra)."""
    resumo, fora = [], pd.Series(False, index=desp.index)
    for r in EXCLUSOES_DESPESAS:
        m = (desp["fornecedor"].str.contains(r["fornecedor_contem"], case=False, na=False)
             & desp["historico"].str.contains(r["historico_regex"], regex=True, na=False)
             & (desp["venc"] <= r["venc_ate"]) & ~fora)
        resumo.append({"nome": r["nome"], "n": int(m.sum()), "valor": float(desp.loc[m, "valor"].sum()),
                       "itens": desp.loc[m]})
        fora |= m
    return desp[~fora], resumo


def projetar_despesas(desp: pd.DataFrame, dias: pd.DatetimeIndex, hoje: pd.Timestamp,
                      incluir_atrasadas: bool = False) -> dict:
    """Saída de caixa por dia útil. Sem curva: vale o vencimento e o valor do contas a pagar.

    Vencimento em dia não útil paga no próximo dia útil. Atrasadas (venc < hoje, ainda em aberto) ficam
    de fora por padrão — são mostradas à parte; incluí-las as paga no primeiro dia útil >= hoje.
    Itens cobertos por EXCLUSOES_DESPESAS saem antes de tudo (inclusive das atrasadas).
    """
    vazio = pd.DataFrame(columns=["pagto", "valor", "categoria", "fornecedor", "historico", "centro_custo", "atrasada"])
    if desp is None or desp.empty or len(dias) == 0:
        return {"serie": pd.Series(0.0, index=dias), "itens": vazio, "atrasadas_valor": 0.0, "atrasadas_n": 0,
                "excluidas": []}
    d, excluidas = _aplicar_exclusoes(desp)
    d = d.copy()
    d["atrasada"] = d["venc"] < hoje
    d["pagto"] = pd.to_datetime(next_bd(d["venc"].where(~d["atrasada"], hoje))) if len(d) else pd.NaT
    atr = d[d["atrasada"]]
    d = d if incluir_atrasadas else d[~d["atrasada"]]
    d = d[(d["pagto"] >= dias[0]) & (d["pagto"] <= dias[-1])]
    serie = d.groupby("pagto")["valor"].sum().reindex(dias).fillna(0.0)
    for e in excluidas:      # quanto da exclusão cai na janela mostrada (informativo)
        it = e.pop("itens")
        it = it[it["venc"] >= hoje]                       # só o que venceria dentro da projeção (não as atrasadas)
        pg = pd.to_datetime(next_bd(it["venc"])) if len(it) else pd.Series(dtype="datetime64[ns]")
        e["valor_janela"] = float(it.loc[(pg >= dias[0]) & (pg <= dias[-1]), "valor"].sum()) if len(it) else 0.0
    return {"serie": serie, "itens": d[vazio.columns], "atrasadas_valor": float(atr["valor"].sum()),
            "atrasadas_n": int(len(atr)), "excluidas": excluidas}


# ─────────────────────────────────────────────
# Orquestração
# ─────────────────────────────────────────────
def calcular_fluxo(df_boletos: pd.DataFrame, df_interm: pd.DataFrame, hoje: pd.Timestamp,
                   janela_meses: int = 4, horizonte_dias: int = 25, as_of: pd.Timestamp | None = None,
                   backtest: bool = False) -> dict:
    if as_of is None:
        as_of = min(pd.to_datetime(df_boletos["liq"]).max(), hoje)   # último dia com pagamentos carregados
    as_of = pd.Timestamp(as_of)
    b = preparar_boletos(df_boletos, as_of, censurar=backtest)
    fim = hoje + pd.Timedelta(days=horizonte_dias)
    i2 = df_interm.copy()
    i2["receb"] = pd.to_datetime(i2["receb"])
    i2 = i2[i2["receb"] <= hoje]
    interm_ate = i2["receb"].max()                    # a Intermediação costuma chegar ao BQ com atraso
    dias = dias_futuros(min(as_of, interm_ate), pd.Timestamp(next_bd(fim)))

    curvas = {c: curva_recebimento(b, c, as_of, janela_meses) for c in CONTAS}
    fluxo = pd.DataFrame(index=dias)
    agendado = pd.Series(0.0, index=dias)
    for c, nome in CONTAS.items():
        pr = projetar_boletos(b, curvas[c], as_of, dias, hoje)
        fluxo[nome] = pr["agendado"] + pr["esperado"]
        agendado += pr["agendado"]
    perfil = perfil_intermediacao(i2, interm_ate, janela_meses)
    fluxo["Meios de pagamento"] = projetar_intermediacao(perfil, dias)
    fluxo["Total"] = fluxo.sum(axis=1)
    fluxo["já agendado"] = agendado
    fluxo = fluxo[fluxo.index >= hoje].copy()          # mostra de hoje em diante
    fluxo["Acumulado"] = fluxo["Total"].cumsum()
    fluxo.index.name = "dia"
    return {"fluxo": fluxo, "curvas": curvas, "perfil_interm": perfil,
            "custo_interm": razao_custo_intermediacao(i2, interm_ate, janela_meses), "as_of": as_of, "interm_ate": interm_ate, "fim": fim,
            "boletos_abertos": b[b["receb"].isna()]}
