"""
utils/workflow1.py
Orquestra o Workflow 1 completo (ver [BI] Dashboard_Agente_Informacao.md):
pergunta -> match (ADR-013, 2 patamares) -> extracao de parametro -> execucao
de SQL pre-aprovado -> resposta em linguagem natural.

Cada resultado carrega os dados de custo/uso (tokens, bytes) prontos pra virar
uma linha na tabela de log (Workflow 4) quando ela existir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from utils.matching import CatalogEntry, MatchResult, buscar_match, LIMIAR_AMBIGUO
from utils.data import executar_query_catalogo
from utils.llm import extrair_parametros, formatar_resposta, custo_usd, PARAMS_ENTIDADE
from utils.resolucao_cliente import buscar_por_nome, MAX_RESULTADOS


_LABEL_FONTE = {
    "superlogica_data": "Superlógica",
    "backend_data": "Backend (App/Site — BQ_TECH)",
}


def identificar_fontes(sql: str | None) -> str:
    """
    Deriva a(s) fonte(s) de dado direto do SQL que realmente rodou -- nunca
    do texto gerado pelo LLM, pra garantir que sempre aparece e nunca erra
    (pedido do usuario 2026-08-18: sempre mostrar de onde veio a informacao).
    """
    if not sql:
        return "—"
    fontes = [label for chave, label in _LABEL_FONTE.items() if chave in sql]
    return " + ".join(fontes) if fontes else "—"


@dataclass
class RespostaWorkflow1:
    status: Literal["respondida", "faltando_parametro", "ambiguo", "sem_match", "sem_sql_template", "erro"]
    texto: str | None = None
    df: pd.DataFrame | None = None
    df_serie: pd.DataFrame | None = None
    entry: CatalogEntry | None = None
    fonte_dados: str = "—"
    candidatos_ambiguo: list[tuple[CatalogEntry, float]] = field(default_factory=list)
    parametros_faltando: list[str] = field(default_factory=list)
    erro: str | None = None
    # custo/uso, pra log (Workflow 4)
    tokens_embedding: int = 0
    tokens_llm_input: int = 0
    tokens_llm_output: int = 0
    bytes_processed: int = 0
    tempo_resposta_ms: int = 0
    custo_embedding_usd: float = 0.0
    custo_llm_usd: float = 0.0
    custo_bq_usd: float = 0.0
    custo_total_usd: float = 0.0


def _responder_multiplos_clientes(
    entry: CatalogEntry,
    candidatos: list,
    param_entidade: str,
    valores_base: dict,
    nome_buscado: str,
    tokens_embedding: int,
    custo_embedding: float,
    tokens_llm_input: int,
    tokens_llm_output: int,
    custo_llm_ate_aqui: float,
) -> "RespostaWorkflow1":
    """
    Pedido do usuario 2026-08-21: quando um nome bate em varios clientes
    (ex: "Sara Nossa Terra" -- denominacao com varias igrejas filhas), em vez
    de perguntar qual deles, roda a MESMA entrada pra cada candidato e junta
    tudo numa unica tabela -- o usuario ve o que existe pra cada um de uma
    vez, sem rodada extra de confirmacao.
    """
    precisa_identificacao = "nome_igreja" not in entry.saida and "codigo_igreja_local" not in entry.saida
    dfs = []
    bytes_total = 0
    tempo_total = 0
    for c in candidatos:
        valor_id = c.id_sacado_sac if param_entidade == "id_cliente" else c.codigo_igreja_local
        if valor_id is None:
            continue  # cliente sem codigo de igreja valido -- pula, nao trava os outros
        valores = {**valores_base, param_entidade: valor_id}
        try:
            resultado = executar_query_catalogo(entry, valores)
        except Exception:
            continue  # 1 cliente com erro nao derruba a resposta dos outros
        df = resultado.df.copy()
        if precisa_identificacao:
            df.insert(0, "codigo_igreja_local", c.codigo_igreja_local)
            df.insert(0, "nome_igreja", c.nome_igreja)
        dfs.append(df)
        bytes_total += resultado.bytes_processed
        tempo_total += resultado.tempo_resposta_ms

    if not dfs:
        return RespostaWorkflow1(
            status="erro",
            erro=f"Encontrei {len(candidatos)} clientes com o nome '{nome_buscado}', mas não consegui buscar o dado pra nenhum deles.",
            entry=entry,
            tokens_embedding=tokens_embedding, tokens_llm_input=tokens_llm_input, tokens_llm_output=tokens_llm_output,
            custo_embedding_usd=custo_embedding, custo_llm_usd=custo_llm_ate_aqui,
            custo_total_usd=custo_embedding + custo_llm_ate_aqui,
        )

    df_combinado = pd.concat(dfs, ignore_index=True)
    custo_bq = bytes_total / (2**40) * 6.25
    texto = (
        f"'{nome_buscado}' bateu com {len(dfs)} clientes ativos no Superlógica — "
        f"trouxe o resultado de cada um pra você comparar."
    )
    return RespostaWorkflow1(
        status="respondida", texto=texto, df=df_combinado, entry=entry,
        fonte_dados=identificar_fontes(entry.sql_template),
        tokens_embedding=tokens_embedding, tokens_llm_input=tokens_llm_input, tokens_llm_output=tokens_llm_output,
        bytes_processed=bytes_total, tempo_resposta_ms=tempo_total,
        custo_embedding_usd=custo_embedding, custo_llm_usd=custo_llm_ate_aqui, custo_bq_usd=custo_bq,
        custo_total_usd=custo_embedding + custo_llm_ate_aqui + custo_bq,
    )


def responder(
    pergunta: str,
    parametros_confirmados: dict | None = None,
    entry_id_escolhido: str | None = None,
) -> RespostaWorkflow1:
    """
    entry_id_escolhido: quando o usuario resolve uma ambiguidade clicando
    numa das sugestoes, pula o matching e usa essa entrada direto.
    parametros_confirmados: valores ja resolvidos (ex: usuario informou o
    codigo que faltava numa rodada anterior da conversa).
    """
    if entry_id_escolhido:
        from utils.matching import carregar_catalogo
        entries = carregar_catalogo()
        entry = next((e for e in entries if e.id == entry_id_escolhido), None)
        if entry is None:
            return RespostaWorkflow1(status="erro", erro=f"Entrada '{entry_id_escolhido}' nao encontrada.")
        custo_embedding = 0.0
        tokens_embedding = 0
    else:
        match = buscar_match(pergunta)
        custo_embedding = custo_usd("text-embedding-3-small", match.tokens_embedding, 0)
        tokens_embedding = match.tokens_embedding

        if match.status == "sem_match":
            return RespostaWorkflow1(
                status="sem_match", tokens_embedding=tokens_embedding,
                custo_embedding_usd=custo_embedding, custo_total_usd=custo_embedding,
            )

        if match.status == "ambiguo":
            # Pedido do usuario: mostrar pelo menos 5 opcoes (as mais bem
            # rankeadas), mas so as que realmente passam do limiar de
            # ambiguidade -- nunca oferecer um candidato fraco so pra
            # completar a lista.
            candidatos_acima_limiar = [
                (entry, score) for entry, score in match.candidatos if score >= LIMIAR_AMBIGUO
            ]
            return RespostaWorkflow1(
                status="ambiguo", candidatos_ambiguo=candidatos_acima_limiar,
                tokens_embedding=tokens_embedding,
                custo_embedding_usd=custo_embedding, custo_total_usd=custo_embedding,
            )

        entry = match.candidatos[0][0]

    if entry.tipo != "simples" or not entry.sql_template:
        return RespostaWorkflow1(
            status="sem_sql_template",
            entry=entry,
            erro=f"Entrada '{entry.id}' ainda nao tem SQL executavel (tipo={entry.tipo}).",
            tokens_embedding=tokens_embedding,
            custo_embedding_usd=custo_embedding, custo_total_usd=custo_embedding,
        )

    extracao = extrair_parametros(pergunta, entry.parametros)
    if parametros_confirmados:
        extracao.valores.update(parametros_confirmados)
        extracao.faltando_obrigatorio = [
            n for n in extracao.faltando_obrigatorio if extracao.valores.get(n) is None
        ]

    custo_extracao = extracao.custo_usd

    # Resolucao de nome -> ID (pedido do usuario 2026-08-21): quando falta um
    # identificador de cliente/igreja mas o usuario mencionou um NOME em vez
    # de codigo, busca no Superlogica antes de pedir o codigo pro usuario --
    # ninguem sabe o id_sacado_sac de cabeca.
    param_entidade = next((p for p in extracao.faltando_obrigatorio if p in PARAMS_ENTIDADE), None)
    if param_entidade and extracao.nome_mencionado:
        candidatos = buscar_por_nome(extracao.nome_mencionado)

        if len(candidatos) == 0:
            return RespostaWorkflow1(
                status="erro",
                erro=f"Não encontrei nenhum cliente ativo com o nome '{extracao.nome_mencionado}' no Superlógica. Tenta um nome diferente ou o código da igreja.",
                entry=entry,
                tokens_embedding=tokens_embedding, tokens_llm_input=extracao.tokens_input, tokens_llm_output=extracao.tokens_output,
                custo_embedding_usd=custo_embedding, custo_llm_usd=custo_extracao,
                custo_total_usd=custo_embedding + custo_extracao,
            )

        if len(candidatos) > MAX_RESULTADOS:
            return RespostaWorkflow1(
                status="erro",
                erro=f"'{extracao.nome_mencionado}' bateu com mais de {MAX_RESULTADOS} clientes — seja mais específico (nome completo ou código da igreja).",
                entry=entry,
                tokens_embedding=tokens_embedding, tokens_llm_input=extracao.tokens_input, tokens_llm_output=extracao.tokens_output,
                custo_embedding_usd=custo_embedding, custo_llm_usd=custo_extracao,
                custo_total_usd=custo_embedding + custo_extracao,
            )

        if len(candidatos) == 1:
            valor_resolvido = candidatos[0].id_sacado_sac if param_entidade == "id_cliente" else candidatos[0].codigo_igreja_local
            extracao.valores[param_entidade] = valor_resolvido
            extracao.faltando_obrigatorio = [n for n in extracao.faltando_obrigatorio if n != param_entidade]
        else:
            return _responder_multiplos_clientes(
                entry, candidatos, param_entidade, extracao.valores, extracao.nome_mencionado,
                tokens_embedding, custo_embedding, extracao.tokens_input, extracao.tokens_output, custo_extracao,
            )

    if extracao.faltando_obrigatorio:
        return RespostaWorkflow1(
            status="faltando_parametro",
            entry=entry,
            parametros_faltando=extracao.faltando_obrigatorio,
            tokens_embedding=tokens_embedding,
            tokens_llm_input=extracao.tokens_input,
            tokens_llm_output=extracao.tokens_output,
            custo_embedding_usd=custo_embedding, custo_llm_usd=custo_extracao,
            custo_total_usd=custo_embedding + custo_extracao,
        )

    try:
        resultado_query = executar_query_catalogo(entry, extracao.valores)
    except Exception as e:
        return RespostaWorkflow1(
            status="erro", entry=entry, erro=str(e),
            tokens_embedding=tokens_embedding,
            tokens_llm_input=extracao.tokens_input, tokens_llm_output=extracao.tokens_output,
            custo_embedding_usd=custo_embedding, custo_llm_usd=custo_extracao,
            custo_total_usd=custo_embedding + custo_extracao,
        )

    custo_bq = resultado_query.bytes_processed / (2**40) * 6.25
    resposta = formatar_resposta(pergunta, entry.titulo, entry.limitacoes, resultado_query.df)
    custo_llm_total = custo_extracao + resposta.custo_usd
    bytes_total = resultado_query.bytes_processed

    # grafico automatico dos ultimos 12 meses (pedido do usuario 2026-08-19): se a
    # entrada tem um par de serie historica cadastrado, busca junto -- sem custo de
    # LLM (so mais uma query BQ, ja documentada/validada, sem parametro nenhum)
    df_serie = None
    if entry.serie_historica_id:
        from utils.matching import carregar_catalogo
        entries = carregar_catalogo()
        entry_serie = next((e for e in entries if e.id == entry.serie_historica_id), None)
        if entry_serie and entry_serie.sql_template:
            try:
                resultado_serie = executar_query_catalogo(entry_serie, {})
                df_serie = resultado_serie.df
                bytes_total += resultado_serie.bytes_processed
                custo_bq += resultado_serie.bytes_processed / (2**40) * 6.25
            except Exception:
                df_serie = None  # grafico e um extra -- nunca quebra a resposta principal

    return RespostaWorkflow1(
        status="respondida",
        texto=resposta.texto,
        df=resultado_query.df,
        df_serie=df_serie,
        entry=entry,
        fonte_dados=identificar_fontes(entry.sql_template),
        tokens_embedding=tokens_embedding,
        tokens_llm_input=extracao.tokens_input + resposta.tokens_input,
        tokens_llm_output=extracao.tokens_output + resposta.tokens_output,
        bytes_processed=bytes_total,
        tempo_resposta_ms=resultado_query.tempo_resposta_ms,
        custo_embedding_usd=custo_embedding, custo_llm_usd=custo_llm_total, custo_bq_usd=custo_bq,
        custo_total_usd=custo_embedding + custo_llm_total + custo_bq,
    )
