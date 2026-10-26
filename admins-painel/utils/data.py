"""
utils/data.py
Carga de dados (BQ_BI, dataset backend_data) para o dashboard de administradores do painel de controle.
"""
import json

import pandas as pd
import streamlit as st
from google.cloud import bigquery
from google.oauth2 import service_account

DS = "`business-intelligence-467516.backend_data`"
# 'panel' e 'control-panel' são variantes raras (20 linhas no total) do canal oficial 'control_panel'
CANAIS_PAINEL = "('control_panel', 'control-panel', 'panel')"

NIVEIS = {
    "subgroup": "Denominação",
    "regional": "Regional",
    "tertiarygroup": "Igreja",
    "cell": "Célula",
    "event_admin": "Evento",
    "team_member": "Equipe",
    "group": "Grupo",
}


@st.cache_resource
def _bq_client() -> bigquery.Client:
    cfg = st.secrets["connections"]["bigquery_bi"]
    raw = cfg["credentials"]
    info = json.loads(raw) if isinstance(raw, str) else dict(raw)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/bigquery"]
    )
    return bigquery.Client(project=cfg["project"], credentials=creds)


def _query(sql: str) -> pd.DataFrame:
    return _bq_client().query(sql).to_dataframe(create_bqstorage_client=False)


@st.cache_data(ttl=3600, show_spinner=False)
def load_admins() -> pd.DataFrame:
    """Um registro por usuário com acesso ao painel (view_admin_access), com último login no painel."""
    sql = f"""
    WITH acesso AS (
      SELECT basic_user_id,
             ARRAY_AGG(level ORDER BY level_rank LIMIT 1)[OFFSET(0)] AS nivel,
             MIN(level_rank) AS nivel_rank
      FROM {DS}.view_admin_access
      GROUP BY basic_user_id
    ),
    login AS (
      SELECT basic_user_id, MAX(date) AS ultimo_login
      FROM {DS}.view_user_login_log
      WHERE LOWER(channel) IN {CANAIS_PAINEL}
      GROUP BY basic_user_id
    )
    SELECT u.basicuser_id AS usuario_id,
           TRIM(CONCAT(IFNULL(u.first_name, ''), ' ', IFNULL(u.last_name, ''))) AS nome,
           u.email,
           u.tertiarygroup_id AS cod_local,
           u.subgroup_id AS cod_denominacao,
           a.nivel, a.nivel_rank,
           l.ultimo_login
    FROM acesso a
    JOIN {DS}.view_user_info u ON u.basicuser_id = a.basic_user_id
    LEFT JOIN login l ON l.basic_user_id = a.basic_user_id
    """
    df = _query(sql)
    df["nivel"] = df["nivel"].map(NIVEIS).fillna(df["nivel"])
    df["ultimo_login"] = pd.to_datetime(df["ultimo_login"])
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_logins_por_igreja() -> pd.DataFrame:
    """Último login no painel por (igreja do login, usuário)."""
    sql = f"""
    SELECT tertiarygroup_id AS cod_local, basic_user_id AS usuario_id,
           MAX(date) AS ultimo_login, COUNT(DISTINCT date) AS qtd_logins
    FROM {DS}.view_user_login_log
    WHERE LOWER(channel) IN {CANAIS_PAINEL} AND tertiarygroup_id IS NOT NULL
    GROUP BY 1, 2
    """
    df = _query(sql)
    df["ultimo_login"] = pd.to_datetime(df["ultimo_login"])
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_igrejas() -> pd.DataFrame:
    """Todas as igrejas locais (ativas ou não) com denominação."""
    sql = f"""
    SELECT tertiarygroup_id AS cod_local, tertiarygroup_name AS igreja,
           subgroup_id AS cod_denominacao, subgroup_name AS denominacao,
           tertiarygroup_is_active AS ativa, is_blocked AS bloqueada
    FROM {DS}.view_company_list
    """
    return _query(sql)


def filtrar_codigos(df: pd.DataFrame, cod_local: str, cod_denominacao: str) -> pd.DataFrame:
    """Filtra por 'contém' em cod_local e/ou cod_denominacao (os dois, quando ambos preenchidos)."""
    for col, termo in (("cod_local", cod_local), ("cod_denominacao", cod_denominacao)):
        termo = (termo or "").strip()
        if termo:
            df = df[df[col].astype("string").str.contains(termo, regex=False, na=False)]
    return df
