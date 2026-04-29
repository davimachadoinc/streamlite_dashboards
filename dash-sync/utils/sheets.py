"""
utils/sheets.py
Leitura de dados do Google Sheets (DASH SYNC).
"""
import json
import re
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1s1q0XH3XwD95qLX4plSQgiIcXY5jad4f90oBepbuvJg"
_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

# ── Status → cor ───────────────────────────────────────────────────────
STATUS_COLOR = {
    "🟢": "#6eda2c",
    "🟡": "#f5c518",
    "🟠": "#f5a318",
    "🔴": "#e63946",
}

def _get_client() -> gspread.Client:
    raw = st.secrets["connections"]["bigquery_tech"]["credentials"]
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(creds)


@st.cache_data(ttl=300, show_spinner=False)
def load_raw(sheet_name: str) -> list[list[str]]:
    gc = _get_client()
    ws = gc.open_by_key(SPREADSHEET_ID).worksheet(sheet_name)
    return ws.get_all_values()


# ── Parsing numérico ──────────────────────────────────────────────────
_RE_NUM = re.compile(r"[R$\s]")

def parse_value(v: str) -> float | None:
    """Converte '19,80%', 'R$ 1.234,56', '66' para float. Retorna None se inválido."""
    if not v or v.strip() in ("", "-", "#VALUE!", "#N/A", "em breve"):
        return None
    s = _RE_NUM.sub("", v).replace(".", "").replace(",", ".").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_meta(v: str) -> float | None:
    return parse_value(v)


# ── Painel Performance ────────────────────────────────────────────────
def load_performance() -> list[dict]:
    """
    Retorna lista de indicadores com:
      area, name, meta, unit, status_color, dates (list), values (list)
    """
    rows = load_raw("Painel Performance")
    if not rows:
        return []

    header = rows[0]
    # Colunas de data começam no índice 20 (col U)
    date_start = 20
    date_cols = [
        (i, header[i])
        for i in range(date_start, len(header))
        if header[i].strip()
    ]
    # Últimas 10 com data
    date_cols = date_cols[-10:]

    indicators = []
    for row in rows[1:]:
        # Normaliza comprimento
        r = row + [""] * (max(21, len(header)) - len(row))
        area = r[0].strip()
        indicator = r[2].strip()   # col C
        meta_raw = r[5].strip()    # col F
        unit = r[12].strip()       # col M
        status_emoji = r[14].strip()  # col O

        if not area or not indicator:
            continue

        dates = []
        values = []
        for col_idx, date_label in date_cols:
            val = r[col_idx] if col_idx < len(r) else ""
            parsed = parse_value(val)
            if parsed is not None:
                dates.append(date_label)
                values.append(parsed)

        if not values:
            continue

        color = STATUS_COLOR.get(status_emoji, "#a0a0a0")
        indicators.append({
            "area": area,
            "name": indicator,
            "meta": parse_meta(meta_raw),
            "meta_raw": meta_raw,
            "unit": unit,
            "status_emoji": status_emoji,
            "status_color": color,
            "dates": dates,
            "values": values,
        })

    return indicators


# ── Painel Operacional ────────────────────────────────────────────────
def load_operacional() -> list[dict]:
    """
    Retorna lista de indicadores com:
      area, name, limite, unit, status_color, dates (list), values (list)
    """
    rows = load_raw("Painel Operacional")
    if not rows:
        return []

    header = rows[0]
    # Colunas de data começam no índice 16 (col Q)
    date_start = 16
    date_cols = [
        (i, header[i])
        for i in range(date_start, len(header))
        if header[i].strip()
    ]
    date_cols = date_cols[-10:]

    indicators = []
    for row in rows[1:]:
        r = row + [""] * (max(17, len(header)) - len(row))
        area = r[0].strip()
        indicator = r[1].strip()   # col B
        limite_raw = r[4].strip()  # col E
        unit = r[6].strip()        # col G
        status_emoji = r[11].strip()  # col L

        if not area or not indicator:
            continue

        dates = []
        values = []
        for col_idx, date_label in date_cols:
            val = r[col_idx] if col_idx < len(r) else ""
            parsed = parse_value(val)
            if parsed is not None:
                dates.append(date_label)
                values.append(parsed)

        if not values:
            continue

        color = STATUS_COLOR.get(status_emoji, "#a0a0a0")
        indicators.append({
            "area": area,
            "name": indicator,
            "limite": parse_meta(limite_raw),
            "limite_raw": limite_raw,
            "unit": unit,
            "status_emoji": status_emoji,
            "status_color": color,
            "dates": dates,
            "values": values,
        })

    return indicators
