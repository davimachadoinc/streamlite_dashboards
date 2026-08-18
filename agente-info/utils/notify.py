"""
utils/notify.py
Notificacao ao time de BI via Google Chat -- reaproveita o endpoint interno
do backoffice ja usado em outro fluxo (n8n, node "disparo_grupo_dados").
Ver ADR-010 em [BI] Dashboard_Agente_Informacao.md.

Endpoint e space ID ficam em secrets.toml (nao no codigo) -- repositorio
GitHub e publico e esse endpoint nao exige autenticacao, entao deixar fixo
no codigo versionado permitiria qualquer pessoa mandar mensagem pro Chat
do BI so de achar o repo. Confirmado com o usuario 2026-08-18.
"""
from __future__ import annotations

import requests
import streamlit as st


def notify_bi_chat(texto: str) -> bool:
    """Best-effort: falha ao notificar nunca deve quebrar a resposta pro usuario."""
    try:
        cfg = st.secrets["bi_chat"]
        r = requests.post(
            cfg["url"],
            headers={"Content-Type": "application/json"},
            json={"space": cfg["space"], "text": texto},
            timeout=10,
        )
        return r.status_code < 400
    except Exception as e:
        st.warning(f"Não foi possível notificar o time de BI: {e}")
        return False
