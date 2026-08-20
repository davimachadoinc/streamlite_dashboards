"""
pages/1_Assistente.py
Interface conversacional do Dashboard Agente de Informação.
Workflow 1 (modo catálogo) + Workflow 2 (sem-match, solicitar ao BI, Modo
SQL Livre com guardrails). Ver [BI] Dashboard_Agente_Informacao.md.
"""
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Agente de Informação | InChurch", page_icon="🤖", layout="wide")

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "agente_info"

from utils.style import inject_css
from utils.workflow1 import responder, RespostaWorkflow1
from utils.log import registrar_uso, registrar_solicitacao_bi, registrar_sql_livre
from utils.notify import notify_bi_chat
from utils.sql_livre import gerar_sql, executar_sql_livre
from utils.esclarecimento import (
    ParEsclarecimento, MAX_RODADAS_ESCLARECIMENTO,
    gerar_pergunta_esclarecimento, reavaliar,
)

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
    st.markdown("---")
    st.markdown("**💡 Dica para evitar resposta errada**")
    st.caption(
        "Seja detalhista: quanto mais específico, menor a chance de má "
        "interpretação.\n\n"
        "- **Diga o período** (\"em julho\", \"últimos 90 dias\") em vez de deixar implícito\n"
        "- **Diga o nome ou código da igreja/cliente**, não só \"essa igreja\"\n"
        "- **Se souber de onde quer o dado, diga**: *\"cliente\"/\"contratado\" → "
        "Superlógica (quem paga); *\"igreja\"/\"realmente ativo\"* → produto/Backend "
        "(quem usa de verdade)\n\n"
        "Quando a pergunta permitir mais de uma leitura, o assistente pergunta antes "
        "de responder — mas quanto mais detalhe você já der, menos idas e vindas."
    )

st.markdown("<h1>Agente de <span>Informação</span></h1>", unsafe_allow_html=True)
st.caption("Pergunte sobre clientes, MRR, TPV, churn, inadimplência, igrejas e mais.")

if "mensagens" not in st.session_state:
    st.session_state["mensagens"] = []
if "pendente" not in st.session_state:
    st.session_state["pendente"] = None

if not st.session_state["mensagens"] and not st.session_state["pendente"]:
    st.info(
        "💡 **Dica:** seja detalhista pra evitar má interpretação — diga o período "
        "(\"em julho\"), o nome/código da igreja ou cliente, e se souber, de onde "
        "quer o dado (*\"cliente\"* = Superlógica/quem paga; *\"igreja\"/\"ativo de "
        "verdade\"* = produto/Backend/quem usa). Quando a pergunta permitir mais de "
        "uma leitura, eu pergunto antes de responder.",
        icon="💡",
    )


def _somar_custo_esclarecimento(r, pend: dict) -> None:
    """
    Soma o custo acumulado das rodadas de esclarecimento (ADR-015) na
    resposta final, sem ratear -- tudo atribuido a pergunta inicial, pedido
    explicito do usuario. So faz efeito se pend tiver os campos acumulados
    (isto e, se a resposta veio do fluxo de esclarecimento).
    """
    r.tokens_embedding += pend.get("tokens_embedding_acumulado", 0)
    r.tokens_llm_input += pend.get("tokens_llm_input_acumulado", 0)
    r.tokens_llm_output += pend.get("tokens_llm_output_acumulado", 0)
    r.custo_embedding_usd += pend.get("custo_embedding_acumulado", 0.0)
    r.custo_llm_usd += pend.get("custo_llm_acumulado", 0.0)
    r.custo_total_usd += pend.get("custo_embedding_acumulado", 0.0) + pend.get("custo_llm_acumulado", 0.0)


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


_PALETTE = ["#6eda2c", "#57d124", "#a0a0a0", "#8ae650", "#3ba811", "#cccccc"]


def _grafico_serie_12m(df_serie: pd.DataFrame, saida_kpi: list[str]):
    """
    Gráfico dos últimos 12 meses (pedido do usuário 2026-08-19). Deriva
    coluna de mês e métrica principal automaticamente -- métrica principal
    é a que casa com o nome de saída do KPI original, quando existe; senão
    pega a última coluna numérica. Se houver coluna categórica extra (ex:
    'plano'), quebra em uma linha por categoria.
    """
    col_mes = next((c for c in df_serie.columns if c.startswith("mes")), None)
    if not col_mes:
        return None
    col_categoria = next(
        (c for c in df_serie.columns if c != col_mes and df_serie[c].dtype == object), None
    )
    numericas = [c for c in df_serie.columns if c not in (col_mes, col_categoria) and pd.api.types.is_numeric_dtype(df_serie[c])]
    if not numericas:
        return None
    col_valor = next((c for c in numericas if c in saida_kpi), numericas[-1])

    fig = go.Figure()
    if col_categoria:
        for i, cat in enumerate(sorted(df_serie[col_categoria].dropna().unique())):
            sub = df_serie[df_serie[col_categoria] == cat].sort_values(col_mes)
            fig.add_trace(go.Scatter(
                x=sub[col_mes], y=sub[col_valor], name=str(cat), mode="lines+markers",
                line=dict(color=_PALETTE[i % len(_PALETTE)], width=2),
            ))
    else:
        sub = df_serie.sort_values(col_mes)
        fig.add_trace(go.Scatter(
            x=sub[col_mes], y=sub[col_valor], name=col_valor, mode="lines+markers",
            line=dict(color=_PALETTE[0], width=2), fill="tozeroy", fillcolor="rgba(110,218,44,0.08)",
        ))

    fig.update_layout(
        height=280, template="plotly_dark",
        margin=dict(l=4, r=4, t=24, b=4),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Outfit, sans-serif", color="#ffffff", size=12),
        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
        xaxis=dict(showgrid=True, gridcolor="#292929", title=""),
        yaxis=dict(showgrid=True, gridcolor="#292929", title=""),
    )
    return fig


def _renderizar_resultado(r):
    if r.status == "respondida":
        st.markdown(r.texto)
        if r.df_serie is not None and not r.df_serie.empty:
            fig = _grafico_serie_12m(r.df_serie, r.entry.saida)
            if fig:
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
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

# --- estado pendente: ambiguidade (botões) -- fallback depois de esgotar as
# rodadas de esclarecimento (ou direto, se o mecanismo nao rodou por algum motivo) ---
if pend and pend["tipo"] == "ambiguo":
    with st.chat_message("assistant"):
        st.markdown("Encontrei mais de uma possibilidade parecida. Qual delas você quis dizer?")
        for entry, score in pend["candidatos"]:
            if st.button(f"{entry.titulo}", key=f"amb_{entry.id}"):
                with st.spinner("🤔 Pensando..."):
                    r = responder(pend["pergunta_original"], entry_id_escolhido=entry.id)
                _somar_custo_esclarecimento(r, pend)
                registrar_uso(
                    pend["pergunta_original"], st.user.email, r,
                    qtd_perguntas_esclarecimento=pend.get("rodada", 0),
                )
                st.session_state["mensagens"].append({"role": "assistant", "content": r.texto or "", "resultado": r})
                st.session_state["pendente"] = None
                st.rerun()
        if st.button("↩️ Nenhuma opção acima, recomeçar com uma explicação mais detalhada", key="amb_recomecar"):
            if pend.get("rodada"):
                r_abandonado = RespostaWorkflow1(status="sem_match")
                _somar_custo_esclarecimento(r_abandonado, pend)
                registrar_uso(
                    pend["pergunta_original"], st.user.email, r_abandonado,
                    qtd_perguntas_esclarecimento=pend["rodada"],
                )
            st.session_state["mensagens"].append({
                "role": "assistant",
                "content": (
                    "Sem problemas! Tenta reformular com mais detalhe — o período, o "
                    "nome/código da igreja ou cliente, e de onde você quer o dado "
                    "(cliente/contratado = Superlógica; igreja/realmente ativo = Backend)."
                ),
            })
            st.session_state["pendente"] = None
            st.rerun()

# --- estado pendente: esclarecimento por perguntas (ADR-015) -- pergunta do
# LLM fica visivel, resposta do usuario vem na proxima mensagem do chat ---
elif pend and pend["tipo"] == "esclarecimento":
    with st.chat_message("assistant"):
        st.markdown(pend["pergunta_llm_atual"])
        st.caption(f"Pergunta {pend['rodada']} de {MAX_RODADAS_ESCLARECIMENTO}, pra entender melhor o que você precisa.")

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
        with st.spinner("🤔 Pensando..."):
            r = responder(pend["pergunta_original"], parametros_confirmados={faltando: valor})
        pergunta_para_log = pend["pergunta_original"]
        st.session_state["pendente"] = None
        registrar_uso(pergunta_para_log, st.user.email, r)
        st.session_state["mensagens"].append({"role": "assistant", "content": r.texto or "", "resultado": r})
        st.rerun()

    # --- resposta do usuario a 1 rodada do mecanismo de esclarecimento (ADR-015) ---
    elif pend and pend["tipo"] == "esclarecimento":
        historico = pend["historico"] + [ParEsclarecimento(pergunta=pend["pergunta_llm_atual"], resposta=pergunta)]
        with st.spinner("🤔 Pensando..."):
            reavaliacao = reavaliar(pend["pergunta_original"], historico)

        tokens_embedding_acumulado = pend["tokens_embedding_acumulado"] + reavaliacao.tokens_embedding
        custo_embedding_acumulado = pend["custo_embedding_acumulado"] + reavaliacao.custo_embedding_usd

        # Criterio de resolucao = ESTABILIDADE, nao score absoluto (ver
        # utils/esclarecimento.py): resolve quando o candidato do topo se
        # repete na rodada seguinte, sinal de que mais uma resposta nao
        # mudou a classificacao.
        top_atual = reavaliacao.top
        top_atual_id = top_atual[0].id if top_atual else None
        estabilizou = top_atual_id is not None and top_atual_id == pend.get("top_id_anterior")

        if estabilizou:
            with st.spinner("🤔 Pensando..."):
                r = responder(pend["pergunta_original"], entry_id_escolhido=top_atual_id)
            pend_para_custo = {
                **pend,
                "tokens_embedding_acumulado": tokens_embedding_acumulado,
                "custo_embedding_acumulado": custo_embedding_acumulado,
            }
            _somar_custo_esclarecimento(r, pend_para_custo)
            registrar_uso(pend["pergunta_original"], st.user.email, r, qtd_perguntas_esclarecimento=pend["rodada"])
            st.session_state["mensagens"].append({"role": "assistant", "content": r.texto or "", "resultado": r})
            st.session_state["pendente"] = None
            st.rerun()
        elif pend["rodada"] >= MAX_RODADAS_ESCLARECIMENTO:
            # esgotou as rodadas sem bater o limiar -- cai no fallback de botoes,
            # carregando o custo acumulado pra ser logado quando o usuario decidir
            st.session_state["pendente"] = {
                "tipo": "ambiguo",
                "pergunta_original": pend["pergunta_original"],
                "candidatos": reavaliacao.candidatos or pend["candidatos_atual"],
                "rodada": pend["rodada"],
                "tokens_embedding_acumulado": tokens_embedding_acumulado,
                "tokens_llm_input_acumulado": pend["tokens_llm_input_acumulado"],
                "tokens_llm_output_acumulado": pend["tokens_llm_output_acumulado"],
                "custo_embedding_acumulado": custo_embedding_acumulado,
                "custo_llm_acumulado": pend["custo_llm_acumulado"],
            }
            st.rerun()
        else:
            with st.spinner("🤔 Pensando..."):
                proxima = gerar_pergunta_esclarecimento(
                    pend["pergunta_original"], historico, reavaliacao.candidatos or pend["candidatos_atual"],
                )
            st.session_state["pendente"] = {
                "tipo": "esclarecimento",
                "pergunta_original": pend["pergunta_original"],
                "historico": historico,
                "rodada": pend["rodada"] + 1,
                "pergunta_llm_atual": proxima.texto,
                "candidatos_atual": reavaliacao.candidatos or pend["candidatos_atual"],
                "top_id_anterior": top_atual_id,
                "tokens_embedding_acumulado": tokens_embedding_acumulado,
                "tokens_llm_input_acumulado": pend["tokens_llm_input_acumulado"] + proxima.tokens_input,
                "tokens_llm_output_acumulado": pend["tokens_llm_output_acumulado"] + proxima.tokens_output,
                "custo_embedding_acumulado": custo_embedding_acumulado,
                "custo_llm_acumulado": pend["custo_llm_acumulado"] + proxima.custo_usd,
            }
            st.rerun()

    else:
        with st.spinner("🤔 Pensando..."):
            r = responder(pergunta)
        if r.status == "ambiguo":
            # Pedido do usuario 2026-08-20: antes de mostrar os botoes, tenta
            # resolver com ate 5 perguntas de esclarecimento em linguagem de
            # negocio (ver utils/esclarecimento.py, ADR-015).
            with st.spinner("🤔 Pensando..."):
                primeira = gerar_pergunta_esclarecimento(pergunta, [], r.candidatos_ambiguo)
            st.session_state["pendente"] = {
                "tipo": "esclarecimento",
                "pergunta_original": pergunta,
                "historico": [],
                "rodada": 1,
                "pergunta_llm_atual": primeira.texto,
                "candidatos_atual": r.candidatos_ambiguo,
                # None de proposito (nao o top pre-pergunta): estabilidade so
                # deve comparar resposta contra resposta -- a rodada 1 nunca
                # resolve sozinha, sempre pede pelo menos 1 confirmacao real
                # (bug encontrado em teste 2026-08-20: comparar contra o
                # palpite inicial sem nenhuma resposta gerava falso positivo).
                "top_id_anterior": None,
                "tokens_embedding_acumulado": r.tokens_embedding,
                "tokens_llm_input_acumulado": primeira.tokens_input,
                "tokens_llm_output_acumulado": primeira.tokens_output,
                "custo_embedding_acumulado": r.custo_embedding_usd,
                "custo_llm_acumulado": primeira.custo_usd,
            }
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
