"""
pages/2_Igrejas.py
Igrejas locais ordenadas pelo último login no painel; ao selecionar uma, lista quem logou nela.
"""
import streamlit as st

st.set_page_config(page_title="Igrejas | Admins do Painel", page_icon="🛡️", layout="wide")

from utils.auth import require_access

require_access()

from utils.style import inject_css
from utils.data import load_admins, load_igrejas, load_logins_por_igreja, filtrar_codigos

inject_css()

with st.sidebar:
    st.markdown("---")
    if st.button("🔄 Limpar cache", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption(
        "Lista todas as igrejas locais (ativas ou não), da que logou mais recentemente no painel "
        "para a mais antiga. Igrejas sem nenhum login ficam no fim. Só contam **administradores** "
        "(Admin, Admin de equipe, Regional e Membro de equipe com registro em `view_admin_access`).\n\n"
        "Clique numa linha para ver quem logou naquela igreja."
    )

st.markdown("<h1>Igrejas <span>Locais</span></h1>", unsafe_allow_html=True)

with st.spinner("Carregando dados..."):
    igrejas = load_igrejas()
    logins = load_logins_por_igreja()
    admins = load_admins()

# só administradores (regra em load_admins): quem logou no painel mas não é administrador fica de fora
logins = logins[logins["usuario_id"].isin(admins["usuario_id"])]

resumo = (
    logins.groupby("cod_local")
    .agg(ultimo_login=("ultimo_login", "max"), usuarios=("usuario_id", "nunique"))
    .reset_index()
)
ig = igrejas.merge(resumo, on="cod_local", how="left")
ig["usuarios"] = ig["usuarios"].fillna(0).astype(int)
ig["situacao"] = ig.apply(
    lambda r: "Bloqueada" if r["bloqueada"] else ("Ativa" if r["ativa"] else "Inativa"), axis=1
)

c1, c2, _ = st.columns([1, 1, 2])
cod_local = c1.text_input("Código Local", placeholder="Ex.: 32187", key="filtro_local_igrejas")
cod_denom = c2.text_input("Código de Denominação", placeholder="Ex.: 3987", key="filtro_denom_igrejas")
ig = filtrar_codigos(ig, cod_local, cod_denom).sort_values("ultimo_login", ascending=False, na_position="last")

evento = st.dataframe(
    ig[["cod_local", "igreja", "denominacao", "cod_denominacao", "situacao", "ultimo_login", "usuarios"]],
    use_container_width=True,
    hide_index=True,
    height=420,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "cod_local": st.column_config.NumberColumn("Cód. Local", format="%d"),
        "igreja": "Igreja",
        "denominacao": "Denominação",
        "cod_denominacao": st.column_config.NumberColumn("Cód. Denominação", format="%d"),
        "situacao": "Situação",
        "ultimo_login": st.column_config.DateColumn("Último login no painel", format="DD/MM/YYYY"),
        "usuarios": st.column_config.NumberColumn("Usuários que logaram", format="%d"),
    },
)

linhas = evento.selection.rows
if not linhas:
    st.info("Selecione uma igreja na tabela acima para ver quem logou no painel.", icon="👆")
    st.stop()

sel = ig.iloc[linhas[0]]
st.markdown(
    f"### {sel['igreja']} · <span style='color:#a0a0a0'>cód. {int(sel['cod_local'])}</span>",
    unsafe_allow_html=True,
)

det = logins[logins["cod_local"] == sel["cod_local"]].merge(
    admins[["usuario_id", "nome", "email", "tipo", "nivel"]], on="usuario_id", how="left"
)
det = det.sort_values("ultimo_login", ascending=False)
st.dataframe(
    det[["nome", "email", "tipo", "nivel", "ultimo_login", "qtd_logins"]],
    use_container_width=True,
    hide_index=True,
    column_config={
        "nome": "Nome",
        "email": "E-mail",
        "tipo": "Tipo",
        "nivel": "Nível de acesso",
        "ultimo_login": st.column_config.DateColumn("Último login no painel", format="DD/MM/YYYY"),
        "qtd_logins": st.column_config.NumberColumn("Dias com login", format="%d"),
    },
)
