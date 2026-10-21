"""
utils/superlogica.py
Cliente mínimo da API Superlógica (Gestão) para contas a pagar.

Endpoint: GET https://api.superlogica.net/v2/financeiro/caixa
  flcreditodebito=2 (despesas), dtInicio/dtFim em mm/dd/yyyy (filtram o vencimento).
Auth: headers app_token e access_token (secrets.toml -> [superlogica]).

Pegadinhas confirmadas na prática (2026-10-21):
  - flstatus NÃO filtra só os em aberto: 0 devolve pagos e abertos. Filtrar no cliente por fl_status_mov == "0".
  - pagina/itensPorPagina são ignorados (vem tudo).
  - janela grande (> ~18 meses) estoura a memória do servidor PHP e devolve texto de erro com HTTP 200
    -> buscar em blocos mensais.
"""
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

URL = "https://api.superlogica.net/v2/financeiro/caixa"
COLS = ["id_contabanco_mov", "venc", "venc_orig", "valor", "fornecedor", "historico", "categoria",
        "forma_pagamento", "centro_custo"]


def _get(app_token: str, access_token: str, ini: pd.Timestamp, fim: pd.Timestamp) -> list:
    q = urllib.parse.urlencode({
        "flcreditodebito": 2, "flstatus": 0, "comApropriacoes": 0,
        "dtInicio": ini.strftime("%m/%d/%Y"), "dtFim": fim.strftime("%m/%d/%Y"),
    })
    req = urllib.request.Request(f"{URL}?{q}", headers={"app_token": app_token, "access_token": access_token})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read().decode("utf-8")
    try:
        data = json.loads(raw)
    except ValueError:
        raise RuntimeError(f"Superlógica devolveu resposta não-JSON: {raw[:160]}")
    if not isinstance(data, list):
        raise RuntimeError(f"Superlógica devolveu formato inesperado: {str(data)[:160]}")
    return data


def _blocos_mensais(ini: pd.Timestamp, fim: pd.Timestamp) -> list:
    out, cur = [], ini.replace(day=1)
    while cur <= fim:
        out.append((max(cur, ini), min(cur + pd.offsets.MonthEnd(0), fim)))
        cur = cur + pd.offsets.MonthBegin(1)
    return out


def _normalizar(rows: list) -> pd.DataFrame:
    recs = []
    for r in rows:
        if r.get("fl_status_mov") != "0":                  # só em aberto
            continue
        if r.get("fl_transferencia_trans") == "1" or r.get("isrecebimento") == "1":
            continue                                       # transferência entre contas / recebimento
        hist = (r.get("st_historico_mov") or "").strip()
        cc = r.get("centro_de_custo") or []
        recs.append({
            "id_contabanco_mov": r.get("id_contabanco_mov"),
            "venc": pd.to_datetime(r.get("dt_vencimento_mov"), format="%m/%d/%Y", errors="coerce"),
            "venc_orig": pd.to_datetime(r.get("dt_vencimentooriginal_mov"), format="%m/%d/%Y", errors="coerce"),
            "valor": abs(pd.to_numeric(r.get("vl_valor_mov"), errors="coerce")),
            "fornecedor": (r.get("st_fantasia_fav") or r.get("st_nome_fav") or "").strip(),
            "historico": hist,
            "categoria": hist.split(" - ")[0].strip().title() if hist else "Sem categoria",
            "forma_pagamento": r.get("st_forma_pag") or "",
            "centro_custo": (cc[0].get("st_descricao_cc") if cc and isinstance(cc[0], dict) else "") or "Sem centro de custo",
        })
    df = pd.DataFrame(recs, columns=COLS)
    return df.drop_duplicates("id_contabanco_mov").dropna(subset=["venc", "valor"]).reset_index(drop=True)


def buscar_despesas_abertas(app_token: str, access_token: str, hoje: pd.Timestamp,
                            meses_atras: int = 9, dias_a_frente: int = 60) -> pd.DataFrame:
    """Despesas em aberto (fl_status_mov = 0) com vencimento de hoje - meses_atras até hoje + dias_a_frente."""
    ini = (hoje - pd.DateOffset(months=meses_atras)).replace(day=1)
    fim = hoje + pd.Timedelta(days=dias_a_frente)
    blocos = _blocos_mensais(ini, fim)
    with ThreadPoolExecutor(max_workers=4) as ex:
        partes = list(ex.map(lambda b: _get(app_token, access_token, b[0], b[1]), blocos))
    return _normalizar([r for p in partes for r in p])
