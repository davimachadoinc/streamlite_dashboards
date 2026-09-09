"""
utils/data.py
Helpers de dados para o dashboard de Funis de Vendas — funil de SDR
(business-intelligence-467516.hubspot_data).
"""
from __future__ import annotations

import json
import pandas as pd
import streamlit as st
from google.oauth2 import service_account
from google.cloud import bigquery


PALETTE_GREEN = "#6eda2c"
PALETTE_GREEN_LIGHT = "#c3f2a0"
COLOR_ABERTO = "#f0a020"
COLOR_DESQ = "#e74c3c"
CHART_TEMPLATE = "plotly_dark"

_DATASET = "business-intelligence-467516.hubspot_data"

# Ordem oficial do funil (dim_pipeline_stage.stage_order)
STAGE_ORDER = [
    ("new-stage-id", "Entrada"),
    ("attempting-stage-id", "Tentando Contato"),
    ("connected-stage-id", "Em Contato"),
    ("qualified-stage-id", "Reunião Agendada"),
]
UNQUALIFIED_ID = "unqualified-stage-id"
STAGE_NAME = dict(STAGE_ORDER + [(UNQUALIFIED_ID, "Desqualificado")])


# ─────────────────────────────────────────────
# CONEXÃO BIGQUERY
# ─────────────────────────────────────────────
def _get_bq_client(project_key: str) -> bigquery.Client:
    cfg = st.secrets["connections"][project_key]
    project = cfg["project"]
    creds_raw = cfg["credentials"]
    creds_dict = json.loads(creds_raw) if isinstance(creds_raw, str) else dict(creds_raw)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/bigquery"],
    )
    return bigquery.Client(project=project, credentials=credentials)


@st.cache_resource
def _bq_client_bi() -> bigquery.Client:
    return _get_bq_client("bigquery_bi")


def _bq_query(query: str) -> pd.DataFrame:
    try:
        return _bq_client_bi().query(query).to_dataframe()
    except Exception as e:
        st.error(f"Erro ao consultar BigQuery: {e}")
        return pd.DataFrame()


# ─────────────────────────────────────────────
# HELPERS DE FORMATAÇÃO
# ─────────────────────────────────────────────
def fmt_pct(value, decimals: int = 1) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{value:.{decimals}f}%".replace(".", ",")


def fmt_int(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return f"{int(value):,}".replace(",", ".")


# ─────────────────────────────────────────────
# CARGA BASE — todas as transições do funil de SDR
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_lead_stage() -> pd.DataFrame:
    """
    Carga bruta de hubspot_lead_stage + nome legível de lead_source.
    Cache de 1h — dataset fora do padrão Splgc/backend_bi.
    """
    query = f"""
        SELECT
            f.lead_id,
            f.new_status,
            f.transition_timestamp,
            f.sdr_owner,
            f.lead_source,
            ls.lead_source_name,
            f.disqualification_reason,
            f.inserted_at
        FROM `{_DATASET}.hubspot_lead_stage` f
        LEFT JOIN `{_DATASET}.dim_lead_source` ls
          ON f.lead_source = ls.lead_source_value
        ORDER BY f.lead_id, f.transition_timestamp
    """
    df = _bq_query(query)
    if df.empty:
        return df
    df["transition_timestamp"] = pd.to_datetime(df["transition_timestamp"], utc=True)
    df["sdr_owner"] = df["sdr_owner"].astype("Int64")
    return df


def _cohort_month(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona `_mes_entrada_ord`/`_mes_entrada_fmt` = mês da 1ª 'Entrada' de cada lead_id."""
    primeira_entrada = (
        df[df["new_status"] == "new-stage-id"]
        .groupby("lead_id")["transition_timestamp"]
        .min()
        .rename("ts_primeira_entrada")
    )
    # Leads sem evento "Entrada" (nascem numa etapa mais avançada) — usa o 1º evento que existir
    sem_entrada = df.groupby("lead_id")["transition_timestamp"].min().rename("ts_primeiro_evento")
    cohort = primeira_entrada.combine_first(sem_entrada).rename("ts_cohort").reset_index()
    cohort["_mes_entrada_ord"] = cohort["ts_cohort"].dt.to_period("M")
    cohort["_mes_entrada_fmt"] = cohort["ts_cohort"].dt.strftime("%b/%y").str.capitalize()
    return df.merge(cohort[["lead_id", "_mes_entrada_ord", "_mes_entrada_fmt"]], on="lead_id", how="left")


@st.cache_data(ttl=3600)
def load_lead_stage_with_cohort() -> pd.DataFrame:
    df = load_lead_stage()
    if df.empty:
        return df
    return _cohort_month(df)


def month_options(df: pd.DataFrame, col_fmt: str = "_mes_entrada_fmt", col_ord: str = "_mes_entrada_ord") -> list[str]:
    return (
        df[[col_fmt, col_ord]]
        .dropna()
        .drop_duplicates()
        .sort_values(col_ord)[col_fmt]
        .tolist()
    )


def add_event_month(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona `_mes_evento_ord`/`_mes_evento_fmt` = mês da própria transition_timestamp (não coorte)."""
    df = df.copy()
    df["_mes_evento_ord"] = df["transition_timestamp"].dt.to_period("M")
    df["_mes_evento_fmt"] = df["transition_timestamp"].dt.strftime("%b/%y").str.capitalize()
    return df


# ─────────────────────────────────────────────
# MÉTRICAS DO FUNIL (por etapa) — semântica "alguma vez" (cumulativa)
# ─────────────────────────────────────────────
def compute_funnel_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    df: subconjunto já filtrado (coorte de mês, SDR, lead_source) de load_lead_stage_with_cohort().
    Retorna 1 linha por etapa principal (ordem do funil) com:
      - alcancou: leads que alguma vez chegaram na etapa
      - pct_entrada: % sobre a etapa 'Entrada'
      - pct_etapa_anterior: % conversão vs etapa anterior
      - desqualificado: leads desqualificados saindo dessa etapa (status anterior = essa etapa)
      - em_aberto: leads que pararam nessa etapa (não avançaram, sem nenhuma desqualificação)
      - retorno_n: quantos leads visitaram a mesma etapa mais de uma vez
    """
    if df.empty:
        return pd.DataFrame()

    ordered = df.sort_values("transition_timestamp")
    prev_status = ordered.groupby("lead_id")["new_status"].shift(1)
    saiu_para_desq = ordered.loc[ordered["new_status"] == UNQUALIFIED_ID].copy()
    saiu_para_desq["status_anterior"] = prev_status.loc[saiu_para_desq.index]

    # última ocorrência de cada lead (status atual) — usada pra achar "em aberto"
    last_idx = ordered.groupby("lead_id")["transition_timestamp"].idxmax()
    atual = ordered.loc[last_idx, ["lead_id", "new_status"]].set_index("lead_id")["new_status"]
    teve_desq = set(ordered.loc[ordered["new_status"] == UNQUALIFIED_ID, "lead_id"])

    rows = []
    for stage_id, stage_name in STAGE_ORDER:
        alcancou_ids = set(ordered.loc[ordered["new_status"] == stage_id, "lead_id"])
        alcancou = len(alcancou_ids)

        desq_dessa_etapa = int((saiu_para_desq["status_anterior"] == stage_id).sum())

        em_aberto = int(
            atual.reindex(list(alcancou_ids))
            .to_frame("atual")
            .assign(sem_desq=lambda d: ~d.index.isin(teve_desq))
            .loc[lambda d: (d["atual"] == stage_id) & d["sem_desq"]]
            .shape[0]
        )

        retorno_n = int(
            ordered[ordered["new_status"] == stage_id]
            .groupby("lead_id")
            .size()
            .gt(1)
            .sum()
        )

        rows.append(dict(
            stage_id=stage_id,
            stage_name=stage_name,
            alcancou=alcancou,
            desqualificado=desq_dessa_etapa,
            em_aberto=em_aberto,
            retorno_n=retorno_n,
        ))

    out = pd.DataFrame(rows)
    total_entrada = out.loc[out["stage_id"] == "new-stage-id", "alcancou"]
    total_entrada = int(total_entrada.iloc[0]) if not total_entrada.empty else 0
    out["pct_entrada"] = out["alcancou"] / total_entrada * 100 if total_entrada else 0.0
    out["pct_etapa_anterior"] = out["alcancou"] / out["alcancou"].shift(1) * 100
    out.loc[out.index[0], "pct_etapa_anterior"] = 100.0
    out["pct_desqualificado"] = out["desqualificado"] / out["alcancou"] * 100
    out["pct_em_aberto"] = out["em_aberto"] / out["alcancou"] * 100
    return out


# ─────────────────────────────────────────────
# PÁGINA 3 — TEMPO ENTRE ETAPAS
# ─────────────────────────────────────────────
# Só os 6 pares principais (3 de avanço + 3 de saída p/ Desqualificado) — ver
# Documentacoes/[VND] Dashboard_Funis_Vendas.md, seção Página 3.
TRANSITION_PAIRS = [
    ("new-stage-id", "attempting-stage-id", "Entrada → Tentando Contato"),
    ("attempting-stage-id", "connected-stage-id", "Tentando Contato → Em Contato"),
    ("connected-stage-id", "qualified-stage-id", "Em Contato → Reunião Agendada"),
    ("new-stage-id", UNQUALIFIED_ID, "Entrada → Desqualificado"),
    ("attempting-stage-id", UNQUALIFIED_ID, "Tentando Contato → Desqualificado"),
    ("connected-stage-id", UNQUALIFIED_ID, "Em Contato → Desqualificado"),
]
_PAIR_LABEL = {(a, b): label for a, b, label in TRANSITION_PAIRS}
WEEKDAYS_PT = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def compute_transitions(df: pd.DataFrame) -> pd.DataFrame:
    """
    1 linha por transição consecutiva (de → para) de cada lead_id, restrita aos 6 pares
    principais do funil. Coluna `horas` = tempo entre as duas transições.
    """
    if df.empty:
        return pd.DataFrame()

    ordered = df.sort_values("transition_timestamp").copy()
    ordered["next_status"] = ordered.groupby("lead_id")["new_status"].shift(-1)
    ordered["next_ts"] = ordered.groupby("lead_id")["transition_timestamp"].shift(-1)
    ordered = ordered.dropna(subset=["next_status"])

    valid_pairs = set(_PAIR_LABEL.keys())
    mask = ordered.apply(lambda r: (r["new_status"], r["next_status"]) in valid_pairs, axis=1)
    out = ordered.loc[mask].copy()
    if out.empty:
        return out

    out["pair"] = out.apply(lambda r: _PAIR_LABEL[(r["new_status"], r["next_status"])], axis=1)
    out["horas"] = (out["next_ts"] - out["transition_timestamp"]).dt.total_seconds() / 3600
    out["dias"] = out["horas"] / 24
    return out[[
        "lead_id", "pair", "horas", "dias", "sdr_owner", "lead_source_name",
        "transition_timestamp", "next_ts",
    ]]


def transition_summary(transitions: pd.DataFrame) -> pd.DataFrame:
    """Média/mediana/p25/p75/p95 (em dias) por par, na ordem definida em TRANSITION_PAIRS."""
    if transitions.empty:
        return pd.DataFrame()
    order = [label for _, _, label in TRANSITION_PAIRS]
    g = transitions.groupby("pair")["dias"]
    out = pd.DataFrame({
        "leads": g.count(),
        "media_dias": g.mean(),
        "mediana_dias": g.median(),
        "p25_dias": g.quantile(0.25),
        "p75_dias": g.quantile(0.75),
        "p95_dias": g.quantile(0.95),
    })
    out.index.name = "pair"
    out = out.reindex(order).dropna(how="all").reset_index()
    return out


def truncate_at_p95(transitions: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Retorna (dentro_do_p95, outliers) — outliers = linhas acima do p95 da própria transição (pair).
    Usado pro boxplot (só dentro_do_p95) + nota de quantos ficaram de fora + tabela de outliers.
    """
    if transitions.empty:
        return transitions, transitions
    p95 = transitions.groupby("pair")["dias"].transform(lambda s: s.quantile(0.95))
    dentro = transitions[transitions["dias"] <= p95].copy()
    fora = transitions[transitions["dias"] > p95].copy()
    return dentro, fora


def velocity_vs_conversion(df: pd.DataFrame) -> pd.DataFrame:
    """
    Para o par Entrada→Tentando Contato: bucket de tempo até o 1º contato x
    % desses leads que alguma vez chegaram em 'Reunião Agendada'.
    """
    if df.empty:
        return pd.DataFrame()

    transitions = compute_transitions(df)
    primeiro_contato = (
        transitions[transitions["pair"] == "Entrada → Tentando Contato"]
        .sort_values("horas")
        .drop_duplicates("lead_id", keep="first")
        .set_index("lead_id")["horas"]
    )
    if primeiro_contato.empty:
        return pd.DataFrame()

    bins = [-0.01, 1, 24, 24 * 7, float("inf")]
    labels = ["< 1h", "1h - 24h", "1 - 7 dias", "7+ dias"]
    bucket = pd.cut(primeiro_contato, bins=bins, labels=labels)

    reuniao_ids = set(df.loc[df["new_status"] == "qualified-stage-id", "lead_id"])
    resultado = pd.DataFrame({"bucket": bucket})
    resultado["chegou_reuniao"] = resultado.index.isin(reuniao_ids)

    out = (
        resultado.groupby("bucket", observed=True)
        .agg(leads=("chegou_reuniao", "size"), chegaram=("chegou_reuniao", "sum"))
        .reindex(labels)
        .dropna(how="all")
        .reset_index()
        .rename(columns={"index": "bucket"})
    )
    out["taxa_conversao"] = out["chegaram"] / out["leads"] * 100
    return out


def aging_em_aberto(df: pd.DataFrame) -> pd.DataFrame:
    """
    Leads parados hoje (sem avanço, sem desqualificação) — dias corridos desde a última
    transition_timestamp até agora, por lead, com a etapa atual.
    """
    if df.empty:
        return pd.DataFrame()

    ordered = df.sort_values("transition_timestamp")
    last_idx = ordered.groupby("lead_id")["transition_timestamp"].idxmax()
    atual = ordered.loc[last_idx, ["lead_id", "new_status", "transition_timestamp", "sdr_owner", "lead_source_name"]]
    teve_desq = set(ordered.loc[ordered["new_status"] == UNQUALIFIED_ID, "lead_id"])

    stage_ids = [s for s, _ in STAGE_ORDER]
    aberto = atual[
        atual["new_status"].isin(stage_ids) & ~atual["lead_id"].isin(teve_desq)
    ].copy()
    if aberto.empty:
        return aberto

    agora = pd.Timestamp.now(tz="UTC")
    aberto["dias_parado"] = (agora - aberto["transition_timestamp"]).dt.total_seconds() / 86400
    aberto["stage_name"] = aberto["new_status"].map(STAGE_NAME)
    return aberto.sort_values("dias_parado", ascending=False)


def time_to_contact_by_weekday(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tempo até o 1º contato (Entrada→Tentando Contato), por dia da semana da Entrada.
    Traz média E mediana em horas: a mediana fica achatada perto de zero em todos os dias
    (dominada por transições automáticas quase instantâneas), enquanto a média captura a
    cauda mais lenta — é onde a diferença fim de semana vs. dia útil aparece de verdade.
    """
    if df.empty:
        return pd.DataFrame()

    transitions = compute_transitions(df)
    primeiro_contato = (
        transitions[transitions["pair"] == "Entrada → Tentando Contato"]
        .sort_values("horas")
        .drop_duplicates("lead_id", keep="first")
        .copy()
    )
    if primeiro_contato.empty:
        return pd.DataFrame()

    primeiro_contato["dia_semana"] = primeiro_contato["transition_timestamp"].dt.dayofweek.map(
        dict(enumerate(WEEKDAYS_PT))
    )
    grp = primeiro_contato.groupby("dia_semana")["horas"]
    out = pd.DataFrame({
        "leads": grp.count(),
        "media_horas": grp.mean(),
        "mediana_horas": grp.median(),
    })
    out.index.name = "dia_semana"
    out = out.reindex(WEEKDAYS_PT).reset_index()
    return out


# ─────────────────────────────────────────────
# PÁGINA 4 — CONVERSÕES DE MARKETING (business-intelligence-467516.marketing_data)
# ─────────────────────────────────────────────
_DATASET_MKT = "business-intelligence-467516.marketing_data"

# Trava rígida de janela de carga — fonte tem histórico desde 2021-04-20, mas a
# página só carrega os últimos N anos (decisão do usuário 2026-09-09, pra ficar
# mais leve). Mudar aqui muda a janela em toda a página de uma vez.
MKT_JANELA_ANOS = 3

# Labels de exibição de `campanha_forms` — valores reais da fonte são só "MEIO"
# e "TOPO" (sem "FUNDO"). ~5% das linhas não têm campanha classificada (nulo)
# — vira uma 3ª caixa própria no filtro, nunca escondida dentro de outra opção.
CAMPANHA_LABELS = {"MEIO": "Meio", "TOPO": "Topo"}
CAMPANHA_NAO_CLASSIFICADO = "Não Classificado"

# Campos com valor não-nulo contam pra "completude" de um registro de lead —
# usado no desempate de qual conversão representa o lead quando "lead único" está
# ativo. Ver Documentacoes/[VND] Dashboard_Funis_Vendas.md, seção Página 4.
_MKT_COMPLETUDE_COLS = [
    "nome", "telefone", "cargo", "tamanho_igreja", "nome_igreja",
    "decisor", "cliente_inchurch",
]


# DE-PARA de `cargo` — cobre as variantes com volume relevante (grafia, gênero,
# abreviação, typo). Cauda longa de respostas de texto livre (< 20 ocorrências
# cada, incluindo múltipla-escolha concatenada com "|") cai em "Outros" — ver
# achado completo (139 valores distintos) em
# G:/Meu Drive/Obisidian/Davi/_claude/marketing-data-dicionario.md.
CARGO_DEPARA = {
    "pastor principal": "Pastor Principal",
    "pastor_principal_": "Pastor Principal",
    "pastor_principal": "Pastor Principal",
    "pastora principal": "Pastor Principal",
    "pr principal": "Pastor Principal",
    "pastor auxiliar": "Pastor Auxiliar",
    "pastor_auxiliar_": "Pastor Auxiliar",
    "pastor_auxiliar": "Pastor Auxiliar",
    "pastor aux.": "Pastor Auxiliar",
    "pastora auxiliar": "Pastor Auxiliar",
    "pr auxiliar": "Pastor Auxiliar",
    "associate pastor": "Pastor Auxiliar",
    "pastor presidente": "Pastor Presidente",
    "pastor  presidente": "Pastor Presidente",
    "pastora presidente": "Pastor Presidente",
    "pastor-presidente": "Pastor Presidente",
    "pr presidente": "Pastor Presidente",
    "pastor presidente temporário": "Pastor Presidente",
    "bispo presidente": "Pastor Presidente",
    "pastora titular": "Pastor Presidente",
    "pastor titular": "Pastor Presidente",
    "pr. titular": "Pastor Presidente",
    "pastor sênior": "Pastor Presidente",
    "pastor senior": "Pastor Presidente",
    "pr senior": "Pastor Presidente",
    "pr gestão": "Pastor Presidente",
    "pastor geral": "Pastor Presidente",
    "lead pastor": "Pastor Presidente",
    "pastor": "Pastor (Genérico)",
    "pastora": "Pastor (Genérico)",
    "not found": "Não Informado",
    "não sou pastor": "Não é Pastor",
    "líder de ministério": "Líder De Ministério",
    "líder_de_ministério_": "Líder De Ministério",
    "lider de ministério": "Líder De Ministério",
    "líder de ministérios": "Líder De Ministério",
    "ministry leader": "Líder De Ministério",
    "líder outro ministério": "Líder De Ministério",
    "lider comunicação": "Líder De Comunicação",
    "líder de comunicação": "Líder De Comunicação",
    "líder da comunicação": "Líder De Comunicação",
    "comunicação": "Líder De Comunicação",
    "líder de célula": "Líder De Célula",
    "líder de células": "Líder De Célula",
    "célula": "Líder De Célula",
    "líder de kids": "Líder De Kids",
    "líder do kids": "Líder De Kids",
    "líder ministério infantil": "Líder De Kids",
    "líder de jovens": "Líder De Jovens",
    "líder de jovem": "Líder De Jovens",
    "vice líder de jovens": "Líder De Jovens",
    "líder do financeiro": "Líder Financeiro",
    "líder financeiro": "Líder Financeiro",
    "membro": "Membro",
    "member": "Membro",
    "funcionário": "Funcionário",
    "funcionária": "Funcionário",
    "funcinário": "Funcionário",
    "funcionã¡rio": "Funcionário",
}


# DE-PARA de `tamanho_igreja` — normaliza só variantes de FORMATO/pontuação do
# mesmo intervalo numérico (traço vs. en-dash, separador de milhar, "Até 50" ==
# "1-50"). Intervalos genuinamente diferentes (ex.: "101-250" vs "101-300" vs
# "101-200", de versões distintas do formulário ao longo do tempo) são mantidos
# como categorias distintas — forçar num único intervalo distorceria o dado.
# Valor não mapeado aqui (não deveria ocorrer, mas por segurança) passa direto
# sem alteração, nunca é descartado.
TAMANHO_DEPARA = {
    "1-50": "1-50", "1 – 50": "1-50", "até 50": "1-50",
    "51-100": "51-100", "51 – 100": "51-100", "51 - 100": "51-100",
    "1-100": "1-100", "0-100": "1-100",
    "101-250": "101-250", "101 – 250": "101-250",
    "101-300": "101-300", "100-300": "101-300",
    "101-200": "101-200", "101 - 200": "101-200",
    "251-500": "251-500", "251 – 500": "251-500",
    "301-500": "301-500",
    "201 - 400": "201-400",
    "401 - 600": "401-600",
    "501-1000": "501-1000", "501 – 1.000": "501-1000", "501-1.000": "501-1000",
    "500 até 1000 membros": "501-1000",
    "601 - 1000": "601-1000",
    "500+": "500+",
    "1001-2500": "1001-2500", "1.001 – 2.500": "1001-2500",
    "1001-2000": "1001-2000", "1001 - 2000": "1001-2000",
    "1000 até 2000 membros": "1001-2000",
    "+1.000": "1000+",
    "2501-5000": "2501-5000", "2.501 – 5.000": "2501-5000",
    "2001-5000": "2001-5000", "2001 - 5000": "2001-5000",
    "1001-3000": "1001-3000",
    "5000+": "5000+", "5.000+": "5000+", "5000": "5000+", "+ 5000": "5000+",
    "+ 3000": "3000+",
}


def normalize_cargo(s: pd.Series) -> pd.Series:
    """Aplica CARGO_DEPARA; vazio/nulo -> 'Não Informado'; não mapeado -> 'Outros'."""
    raw = s.fillna("").astype(str).str.strip()
    key = raw.str.lower()
    out = key.map(CARGO_DEPARA)
    out = out.fillna("Outros")
    out[raw == ""] = "Não Informado"
    return out


def normalize_tamanho_igreja(s: pd.Series) -> pd.Series:
    """Aplica TAMANHO_DEPARA (lookup case-insensitive); vazio/nulo -> 'Não Informado';
    não mapeado -> mantém valor bruto (nunca descarta, ver comentário no dict)."""
    raw = s.fillna("").astype(str).str.strip()
    key = raw.str.lower()
    out = key.map(TAMANHO_DEPARA)
    out = out.fillna(raw)
    out[raw == ""] = "Não Informado"
    return out


@st.cache_data(ttl=3600)
def load_marketing_conversoes() -> pd.DataFrame:
    """
    Carga bruta de VW_CONVERSOES (leads/conversões de formulário de marketing).
    Schema completo e achados de qualidade de dado documentados em
    G:/Meu Drive/Obisidian/Davi/_claude/marketing-data-dicionario.md.
    Cache de 1h — mesmo padrão das outras cargas deste dashboard.

    ⚠️ Trava RÍGIDA de janela — só carrega os últimos MKT_JANELA_ANOS anos
    (decisão do usuário 2026-09-09, pra manter a página leve: fonte tem
    histórico completo desde 2021-04-20, mas essa página nunca vê além da
    janela). Efeitos colaterais assumidos: o desempate de "lead único" por
    primeira conversão (ver mkt_lead_unico) considera só a primeira DENTRO da
    janela, não a da vida toda do lead se ele for mais antigo que isso; mesma
    ressalva pra `ordem_conversao_lead`/`total_conversoes_lead`, que continuam
    corretos em relação ao histórico REAL do lead (calculados pela view sobre
    a base completa), mas a primeira linha desse histórico pode não estar
    presente aqui se cair fora da janela.
    """
    query = f"""
        SELECT
          conversao_id, data_conversao, data_conversao_br, data_br, mes_br,
          nome, email, telefone, cargo, tamanho_igreja, nome_igreja,
          decisor, cliente_inchurch, id_formulario, campanha_forms, canal,
          utm_source, utm_source_grupo, utm_source_detalhe, utm_medium,
          utm_campaign, utm_content,
          ordem_conversao_lead, total_conversoes_lead
        FROM `{_DATASET_MKT}.VW_CONVERSOES`
        WHERE data_br >= DATE_SUB(CURRENT_DATE('America/Sao_Paulo'), INTERVAL {MKT_JANELA_ANOS} YEAR)
    """
    df = _bq_query(query)
    if df.empty:
        return df
    df["data_conversao_br"] = pd.to_datetime(df["data_conversao_br"])
    df["data_br"] = pd.to_datetime(df["data_br"])
    df["cargo_norm"] = normalize_cargo(df["cargo"])
    df["tamanho_igreja_norm"] = normalize_tamanho_igreja(df["tamanho_igreja"])
    df["campanha_forms_disp"] = df["campanha_forms"].map(CAMPANHA_LABELS).fillna(CAMPANHA_NAO_CLASSIFICADO)
    return df


def mkt_options(df: pd.DataFrame, col: str) -> list[str]:
    """Valores distintos não-nulos de `col`, ordenados, pra popular multiselect."""
    return sorted(df[col].dropna().unique().tolist())


def mkt_lead_unico(
    dfv: pd.DataFrame, df_full: pd.DataFrame, active_filters: dict[str, list]
) -> tuple[pd.DataFrame, int]:
    """
    Dedup por e-mail — semântica decidida em `/grill-me` 2026-09-09
    (Documentacoes/[VND] Dashboard_Funis_Vendas.md, Página 4):

    1. `dfv` já veio filtrada no nível de conversão (período + filtros ativos) —
       um lead aparece se QUALQUER conversão dele bateu no filtro (semântica
       EXISTS, obtida de graça ao filtrar em nível de linha antes de agrupar).
    2. Pra cada e-mail em `dfv`, o registro exibido é o de maior completude
       (mais campos não-nulos entre _MKT_COMPLETUDE_COLS) dentre as conversões
       QUE BATERAM no filtro — não do histórico inteiro do lead. Empate:
       conversão mais ANTIGA (data_conversao) entre as empatadas.
    3. Nota de overlap: conta quantos desses leads têm, no histórico COMPLETO
       (`df_full`, sem filtro de período), pelo menos uma conversão com algum
       valor DIFERENTE do selecionado em algum filtro categórico ativo — ou
       seja, não são exclusivos daquele valor de filtro. Período não entra
       nessa checagem (só os filtros categóricos em `active_filters`).

    Retorna (dedup_df, n_leads_com_overlap).
    """
    if dfv.empty:
        return dfv, 0

    d = dfv.copy()
    d["_completude"] = d[_MKT_COMPLETUDE_COLS].notna().sum(axis=1)
    d = d.sort_values(["_completude", "data_conversao"], ascending=[False, True])
    dedup = d.drop_duplicates(subset="email", keep="first").drop(columns="_completude")

    n_overlap = 0
    if active_filters:
        leads = dedup["email"].unique()
        historico = df_full[df_full["email"].isin(leads)]
        mask_fora = pd.Series(False, index=historico.index)
        for col, valores in active_filters.items():
            mask_fora = mask_fora | (~historico[col].isin(valores))
        n_overlap = historico.loc[mask_fora, "email"].nunique()

    return dedup, n_overlap
