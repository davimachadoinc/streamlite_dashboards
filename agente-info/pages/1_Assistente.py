"""
pages/1_Assistente.py
Interface conversacional do Dashboard Agente de Informação.
Workflow 1 (modo catálogo) + Workflow 2 (sem-match, solicitar ao BI, Modo
SQL Livre com guardrails). Ver [BI] Dashboard_Agente_Informacao.md.
"""
from datetime import datetime

import streamlit as st

st.set_page_config(page_title="Agente de Informação | InChurch", page_icon="🤖", layout="wide")

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "agente_info"

from utils.style import inject_css
from utils.workflow1 import responder
from utils.log import registrar_uso, registrar_solicitacao_bi, registrar_sql_livre
from utils.notify import notify_bi_chat
from utils.sql_livre import gerar_sql, executar_sql_livre

inject_css()

with st.sidebar:
    st.markdown("---")
    if st.button("🗑️ Limpar conversa", use_container_width=True):
        st.session_state["mensagens"] = []
        st.session_state["pendente"] = None
        st.rerun()
    st.caption(
        "Modo padrão responde só com base no catálogo de queries pré-aprovadas e "
        "testadas. Perguntas fora do catálogo oferecem solicitar ao BI ou tentar "
        "o Modo SQL Livre (sem garantia, sem revisão humana)."
    )

st.markdown("<h1>Agente de <span>Informação</span></h1>", unsafe_allow_html=True)
st.caption("Pergunte sobre clientes, MRR, TPV, churn, inadimplência, igrejas e mais.")

if "mensagens" not in st.session_state:
    st.session_state["mensagens"] = []
if "pendente" not in st.session_state:
    st.session_state["pendente"] = None


def _parse_valor(texto: str, tipo: str):
    texto = texto.strip()
    try:
        if tipo == "int":
            return int(texto)
        if tipo == "float":
            return float(texto.replace(",", "."))
        if tipo == "date":
            return datetime.strptime(texto, "%Y-%m-%d").date().isoformat() if len(texto) == 10 else texto
        return texto
    except ValueError:
        return texto


def _renderizar_resultado(r):
    if r.status == "respondida":
        st.markdown(r.texto)
        if r.df is not None and not r.df.empty and len(r.df) > 1:
            with st.expander(f"Ver dados completos ({len(r.df)} linhas)"):
                st.dataframe(r.df, use_container_width=True)
        st.caption(
            f"📊 Fonte dos dados: **{r.fonte_dados}** · consulta [{r.entry.id}] {r.entry.titulo} "
            f"· custo ${r.custo_total_usd:.6f}"
        )
    elif r.status == "sem_sql_template":
        st.error(f"⚠️ {r.erro}")
    elif r.status == "erro":
        st.error(f"⚠️ Erro ao executar: {r.erro}")


def _renderizar_sql_livre(resultado, custo_total: float):
    st.warning(
        "⚠️ **Resposta gerada por IA, sem revisão humana.** Este dado pode estar "
        "incorreto. Se for usar isso para decisão de negócio, peça verificação "
        "do time de Business Intelligence antes."
    )
    with st.expander("Ver SQL gerado", expanded=(resultado.status != "ok")):
        st.code(resultado.sql, language="sql")
    if resultado.status == "ok":
        st.dataframe(resultado.df, use_container_width=True)
        st.caption(
            f"{len(resultado.df)} linha(s) (prévia limitada) · "
            f"{resultado.bytes_processed / 2**20:.1f} MB processados · custo ${custo_total:.6f}"
        )
    elif resultado.status == "bloqueado_guardrail":
        st.error(f"🚫 Bloqueado por guardrail de segurança: {resultado.motivo}")
    elif resultado.status == "custo_excedido":
        st.error(f"🚫 {resultado.motivo}")
    else:
        st.error(f"⚠️ Erro ao executar: {resultado.motivo}")


for msg in st.session_state["mensagens"]:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant" and "resultado" in msg:
            _renderizar_resultado(msg["resultado"])
        elif msg["role"] == "assistant" and "sql_livre" in msg:
            _renderizar_sql_livre(msg["sql_livre"], msg.get("custo_total", 0.0))
        else:
            st.markdown(msg["content"])

pend = st.session_state["pendente"]

# --- estado pendente: ambiguidade (botões) ---
if pend and pend["tipo"] == "ambiguo":
    with st.chat_message("assistant"):
        st.markdown("Encontrei mais de uma possibilidade parecida. Qual delas você quis dizer?")
        for entry, score in pend["candidatos"]:
            if st.button(f"{entry.titulo}", key=f"amb_{entry.id}"):
                r = responder(pend["pergunta_original"], entry_id_escolhido=entry.id)
                registrar_uso(pend["pergunta_original"], st.user.email, r)
                st.session_state["mensagens"].append({"role": "assistant", "content": r.texto or "", "resultado": r})
                st.session_state["pendente"] = None
                st.rerun()

# --- estado pendente: parametro faltando (pede na proxima mensagem) ---
elif pend and pend["tipo"] == "faltando_parametro":
    with st.chat_message("assistant"):
        faltando = pend["faltando"][0]
        descricao = pend["entry"].parametros.get(faltando, {}).get("descricao", faltando)
        st.markdown(f"Preciso de mais uma informação: **{descricao}**")

# --- estado pendente: sem-match, escolher entre solicitar ao BI ou tentar SQL Livre ---
elif pend and pend["tipo"] == "sem_match_escolha":
    with st.chat_message("assistant"):
        st.warning("Essa pergunta ainda não está documentada em nosso catálogo de queries validadas.")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📩 Solicitar ao time de BI", use_container_width=True):
                notify_bi_chat(
                    f"📩 Pergunta sem match no catálogo do Agente de Informação.\n"
                    f"Colaborador: {st.user.email}\nPergunta: {pend['pergunta_original']}"
                )
                registrar_solicitacao_bi(pend["pergunta_original"], st.user.email)
                st.session_state["mensagens"].append({
                    "role": "assistant",
                    "content": "✅ Solicitação enviada ao time de BI. Eles vão avaliar se vale formalizar essa consulta no catálogo.",
                })
                st.session_state["pendente"] = None
                st.rerun()
        with col2:
            if st.button("🔍 Tentar buscar mesmo assim", use_container_width=True):
                st.session_state["pendente"] = {"tipo": "sql_livre_confirmar", "pergunta_original": pend["pergunta_original"]}
                st.rerun()

# --- estado pendente: confirmacao de risco do Modo SQL Livre (ADR-006) ---
elif pend and pend["tipo"] == "sql_livre_confirmar":
    with st.chat_message("assistant"):
        st.markdown(
            "Podemos tentar pesquisar na base de dados, porém **não é um dado validado** "
            "e pode haver risco de inconsistência. Deseja continuar mesmo assim?"
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Sim, continuar", use_container_width=True):
                pergunta_sl = pend["pergunta_original"]
                with st.spinner("Gerando e validando SQL..."):
                    gerado = gerar_sql(pergunta_sl)
                    resultado = executar_sql_livre(gerado.sql)
                # ADR-006: notificacao ao BI automatica, nao opcional, sempre que a busca roda
                notify_bi_chat(
                    f"🔍 Busca SQL Livre executada (sem revisão humana).\n"
                    f"Colaborador: {st.user.email}\nPergunta: {pergunta_sl}\n"
                    f"Status: {resultado.status}\nSQL:\n{resultado.sql}"
                )
                custo_total = gerado.custo_usd + (
                    resultado.bytes_processed / (2**40) * 6.25 if resultado.bytes_processed else 0.0
                )
                registrar_sql_livre(
                    pergunta_sl, st.user.email, resultado,
                    gerado.tokens_input, gerado.tokens_output, gerado.custo_usd,
                )
                st.session_state["mensagens"].append({
                    "role": "assistant", "content": "", "sql_livre": resultado, "custo_total": custo_total,
                })
                st.session_state["pendente"] = None
                st.rerun()
        with col2:
            if st.button("❌ Não", use_container_width=True):
                st.session_state["mensagens"].append({
                    "role": "assistant",
                    "content": "Tudo bem, não tentei a busca. Se quiser, posso solicitar ao time de BI.",
                })
                st.session_state["pendente"] = None
                st.rerun()

pergunta = st.chat_input("Digite sua pergunta...")

if pergunta:
    st.session_state["mensagens"].append({"role": "user", "content": pergunta})

    if pend and pend["tipo"] == "faltando_parametro":
        faltando = pend["faltando"][0]
        tipo = pend["entry"].parametros.get(faltando, {}).get("tipo", "string")
        valor = _parse_valor(pergunta, tipo)
        r = responder(pend["pergunta_original"], parametros_confirmados={faltando: valor})
        pergunta_para_log = pend["pergunta_original"]
        st.session_state["pendente"] = None
        registrar_uso(pergunta_para_log, st.user.email, r)
        st.session_state["mensagens"].append({"role": "assistant", "content": r.texto or "", "resultado": r})
        st.rerun()
    else:
        r = responder(pergunta)
        if r.status == "ambiguo":
            st.session_state["pendente"] = {
                "tipo": "ambiguo", "pergunta_original": pergunta, "candidatos": r.candidatos_ambiguo,
            }
            registrar_uso(pergunta, st.user.email, r)
            st.rerun()
        elif r.status == "faltando_parametro":
            st.session_state["pendente"] = {
                "tipo": "faltando_parametro", "pergunta_original": pergunta,
                "entry": r.entry, "faltando": r.parametros_faltando,
            }
            st.rerun()
        elif r.status == "sem_match":
            st.session_state["pendente"] = {"tipo": "sem_match_escolha", "pergunta_original": pergunta}
            registrar_uso(pergunta, st.user.email, r)
            st.rerun()
        else:
            registrar_uso(pergunta, st.user.email, r)
            st.session_state["mensagens"].append({"role": "assistant", "content": r.texto or "", "resultado": r})
            st.rerun()
