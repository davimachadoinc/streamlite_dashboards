import json

import pandas as pd
import requests
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Configuração da API do Google Sheets
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
credential_json = st.secrets["credentials"]
CREDENTIALS = json.loads(credential_json)
SPREADSHEET_ID = '1n-VTjTz90GBmtmLU8cxYtBtmTwn234NZT7UKFkl6eqY'

# Autenticação e criação do serviço
creds = Credentials.from_service_account_info(CREDENTIALS, scopes=SCOPES)
service = build('sheets', 'v4', credentials=creds)


def chats_people(message, email):
    url =  'https://backoffice-dot-operations-407517.rj.r.appspot.com/api/v1/chats/direct-message/'  # noqa
    headers = {
        'Content-Type': 'application/json',
    }
    data = {
        "email": email,
        "text": message
    }
    requests.post(url, headers=headers, json=data)


def chats_channel(message):
    url = 'https://chat.googleapis.com/v1/spaces/AAQALAab39o/messages?key=AIzaSyDdI0hCZtE6vySjMm-WEfRq3CPzqKqqsHI&token=yW5wgfP7tBz5e4n6yxfjkPwB9KGoCueM5dEO6rmElng'  # noqa
    headers = {
        'Content-Type': 'application/json',
    }
    data = {
        "text": message,
    }
    requests.post(url, headers=headers, json=data)


# Funções para ler dados no Google Sheets
def ler_dados(nome_aba, intervalo):
    try:
        resultado = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f'{nome_aba}!{intervalo}'
        ).execute()
        valores = resultado.get('values', [])
        return valores
    except Exception as e:
        st.error(f"Erro ao ler dados: {e}")
        return []


# Função para escrever dados no Google Sheets
def escrever_dados(nome_aba, intervalo, valores):
    try:
        body = {'values': valores}
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f'{nome_aba}!{intervalo}',
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        print("Dados escritos com sucesso.")
    except Exception as e:
        print(f"Erro ao escrever dados: {e}")


# Carregar dados marcações
marcados = ler_dados("Marcações", "A1:P400")
marcacoes = pd.DataFrame(marcados[1:], columns=marcados[0])
# Filtrar coluna O (Validado) para mostrar apenas as marcações que não foram reprovadas # noqa
marcacoes_validas = marcacoes[marcacoes["Validado por DP"] != "Reprovado"]
# Verificar se tem alterações e tirar da lista as que já foram alteradas # noqa
alteradas = marcacoes_validas[marcacoes_validas["Alteração"] != ""]
marcacoes_validas = marcacoes_validas[~marcacoes_validas["ID"].isin(
    alteradas["Alteração"])]
# Tirar ids vazios
marcacoes_validas = marcacoes_validas[marcacoes_validas["ID"] != ""]

# Carregar dados iniciais
dados_principal = ler_dados('colaboradores', 'A1:L400')
principal = pd.DataFrame(dados_principal[1:], columns=dados_principal[0])
# Garantir que o contrato esteja ativo
principal = principal[principal['Situação do Contrato'] == 'ATIVO']
# Converte a coluna "Último prazo" para datetime (se ainda não for)
# principal['Último prazo'] = pd.to_datetime(
#     principal['Último prazo'], errors='coerce')


def enviar_chats(p1_inicio_str, p1_fim_str, p2_inicio_str, p2_fim_str, p3_inicio_str, p3_fim_str):  # noqa
    chats_colaborador = email_colaborador
    chats_marcador = email_input
    chats_gestor = email_gestor

    try:
        chats_channel(f"{ferias[ferias["Email Corporativo"] == email_colaborador]["Nome Completo"].values[0]} teve suas férias marcadas por {nome_marcador}.")  # noqa
        chats_people(f"Olá, {ferias[ferias["Email Corporativo"] == email_colaborador]["Nome Completo"].values[0]}!\nVocê teve suas férias marcadas por {nome_marcador}.", chats_colaborador)  # noqa
        if p2_inicio_str is None:
            chats_people(f"Período: {p1_inicio_str} a {p1_fim_str}.", chats_colaborador)  # noqa
        elif p3_inicio_str is None:
            chats_people(f"Período: {p1_inicio_str} a {p1_fim_str} e {p2_inicio_str} a {p2_fim_str}.", chats_colaborador)  # noqa
        else:
            chats_people(f"Período: {p1_inicio_str} a {p1_fim_str}, {p2_inicio_str} a {p2_fim_str} e {p3_inicio_str} a {p3_fim_str}.", chats_colaborador)  # noqa

        if chats_marcador == chats_gestor:
            chats_people(f"Olá, {ferias[ferias['Email Corporativo'] == email_colaborador]['GESTOR IMEDIATO'].values[0]}!\n{nome_marcador} marcou férias para {  # noqa
                  ferias[ferias['Email Corporativo'] == email_colaborador]['Nome Completo'].values[0]}.", chats_marcador)  # noqa
        else:
            chats_people(f"Olá, {nome_marcador}!\nVocê marcou férias para {ferias[ferias['Email Corporativo'] == email_colaborador]['Nome Completo'].values[0]}.", chats_marcador)  # noqa
            chats_people(f"Olá, {ferias[ferias['Email Corporativo'] == email_colaborador]['GESTOR IMEDIATO'].values[0]}!\n{nome_marcador} marcou férias para {ferias[ferias['Email Corporativo'] == email_colaborador]['Nome Completo'].values[0]}.", chats_gestor)  # noqa
    except Exception as e:
        st.error(f"Erro ao enviar mensagem no Chats: {e}")
        chats_channel(f"Erro ao enviar mensagem no Chats: {e}.\nEmail do colaborador: {email_colaborador}.\nNome de quem marcou: {nome_marcador}")  # noqa


def marcar_ferias():
    if email_colaborador != 'Todos':
        # Verificar o contrato do colaborador
        contrato_colaborador = ferias[ferias["Email Corporativo"]  # noqa
                                    == email_colaborador]["Contrato"].values[0]  # noqa

        if contrato_colaborador == 'PJ':
            dias_abono = None
            abono = 'SEM abono'  # Para PJ, férias sempre sem abono # noqa
            # Mostrar saldo de dias que o PJ tem para tirar férias
            saldo = int(principal[principal["Email Corporativo"] == email_colaborador]["Saldo de dias"].values[0])  # noqa
            st.info(f"Saldo de dias para férias: {saldo} dias.")
            st.info(
                "Para PJ, as férias poderão durar de 5 a 30 dias.")  # noqa
            janelas = st.radio("Escolha a janela de férias:", [
                "janela única", "janela dupla", "janela tripla"])  # noqa

            if janelas == "janela única":
                p1_inicio = st.date_input("Início das férias P1:")
                opcoes_p1 = list(range(5, 31))
                p1_duração = st.selectbox(
                    "Duração das férias P1:", opcoes_p1)
                p1_fim = p1_inicio + \
                    pd.Timedelta(days=p1_duração - 1)  # type: ignore
                st.success(f"Último dia das férias P1: {p1_fim}")
                p2_inicio = None
                p2_fim = None
                p3_inicio = None
                p3_fim = None
                # Mostrar como ficará o saldo de dias após as férias
                saldo -= (p1_duração)
                if saldo < 0:
                    st.warning(f"Saldo de dias após férias:  {saldo} dias. ATENÇÃO: O colaborador está com saldo negativo. Favor verificar com DP.")  # noqa
                else:
                    st.success(f"Saldo de dias após férias: {saldo} dias.")

            elif janelas == "janela dupla":
                p1_inicio = st.date_input("Início das férias P1:")
                opcoes_p1 = list(range(5, 26))
                p1_duração = st.selectbox(
                    "Duração das férias P1:", opcoes_p1)
                p1_fim = p1_inicio + \
                    pd.Timedelta(days=p1_duração - 1)  # type: ignore
                st.success(f"Último dia das férias P1: {p1_fim}")
                p2_inicio = st.date_input("Início das férias P2:")
                opcoes_p2 = list(range(5, 31 - p1_duração))
                p2_duração = st.selectbox(
                    "Duração das férias P2:", opcoes_p2)
                p2_fim = p2_inicio + \
                    pd.Timedelta(days=p2_duração - 1)  # type: ignore
                st.warning(f"Duração P2: {p2_duração} dias.")
                st.success(f"Último dia das férias P2: {p2_fim}")
                p3_inicio = None
                p3_fim = None
                # Mostrar como ficará o saldo de dias após as férias
                saldo -= (p1_duração + p2_duração)
                if saldo < 0:
                    st.warning(f"Saldo de dias após férias:  {saldo} dias. ATENÇÃO: O colaborador está com saldo negativo. Favor verificar com DP.")  # noqa
                else:
                    st.success(f"Saldo de dias após férias: {saldo} dias.")

            else:
                p1_inicio = st.date_input("Início das férias P1:")
                # Duração de 5 a 20 dias
                opcoes_p1 = list(range(5, 21))
                p1_duração = st.selectbox(
                    "Duração das férias P1:", opcoes_p1)
                p1_fim = p1_inicio + \
                    pd.Timedelta(days=p1_duração - 1)  # type: ignore
                st.success(f"Último dia das férias P1: {p1_fim}")
                p2_inicio = st.date_input("Início das férias P2:")
                opcoes_p2 = list(range(5, 26 - p1_duração))
                p2_duração = st.selectbox(
                    "Duração das férias P2:", opcoes_p2)
                p2_fim = p2_inicio + \
                    pd.Timedelta(days=p2_duração - 1)  # type: ignore
                st.success(f"Último dia das férias P2: {p2_fim}")
                p3_inicio = st.date_input("Início das férias P3:")
                p3_opcoes = list(range(5, 31 - p1_duração - p2_duração))
                p3_duração = st.selectbox(
                    "Duração das férias P3:", p3_opcoes)
                p3_fim = p3_inicio + \
                    pd.Timedelta(days=p3_duração - 1)  # type: ignore
                st.warning(f"Duração P3: {p3_duração} dias.")
                st.success(f"Último dia das férias P3: {p3_fim}")
                # Mostrar como ficará o saldo de dias após as férias
                saldo -= (p1_duração + p2_duração + p3_duração)
                if saldo < 0:
                    st.warning(f"Saldo de dias após férias:  {saldo} dias. ATENÇÃO: O colaborador está com saldo negativo. Favor verificar com DP.")  # noqa
                else:
                    st.success(f"Saldo de dias após férias: {saldo} dias.")

        else:
            # Verificar se o a data atual já é maior que "Fim PA1" da aba principal # noqa
            fim_pa1 = principal[principal["Email Corporativo"] == email_colaborador]["Fim PA1"].values[0]  # noqa
            fim_pa1_raw = pd.to_datetime(fim_pa1, errors='coerce', dayfirst=True)
            if pd.isna(fim_pa1_raw):
                fim_pa1 = None
            elif fim_pa1_raw.tzinfo is not None:
                fim_pa1 = fim_pa1_raw.tz_convert(None)
            else:
                fim_pa1 = fim_pa1_raw.tz_localize(None)

            # Garante que o 'agora' também não tenha fuso horário e faz a comparação
            if fim_pa1 is not None and pd.Timestamp.now().tz_localize(None) < fim_pa1:
           
                st.warning(f"Você não pode marcar férias para este colaborador. O período atual ainda não está completo. A marcação poderá ser feita a partir de: {fim_pa1 + pd.Timedelta(days=1)}. Para mais informações, entre em contato com DP.")  # noqa
            else:
                abono = st.radio("Escolha o ABONO (abono é a conversão de um terço das férias em dinheiro):", [  # noqa
                    "COM abono", "SEM abono"])

                if abono == "COM abono":
                    st.info(
                        "Para férias com abono, a duração total deve ser 20 ou 25 dias.")  # noqa
                    janelas = st.radio("Escolha a janela de férias:", [
                    "janela única", "janela dupla"])  # noqa

                    dias_abono = st.selectbox("Escolha a quantidade de dias para abono:", [5, 10])  # noqa

                    if janelas == "janela única":
                        p1_inicio = st.date_input(
                            "Início das férias P1:")
                        # Incremento de 1 dia
                        p1_duração = 30 - dias_abono  # Duração total menos os dias de abono  # noqa
                        p1_fim = p1_inicio + \
                            pd.Timedelta(days=p1_duração - 1)  # type: ignore
                        st.success(f"Último dia das férias P1: {p1_fim}")

                        p2_inicio = None
                        p2_fim = None
                        p3_inicio = None
                        p3_fim = None

                    else:  # Janela dupla
                        p1_inicio = st.date_input(
                            "Início das férias P1:")
                        # Incremento de 1 dia
                        if dias_abono == 5:
                            opcoes_p1 = list(range(5, 21 - dias_abono))
                        else:  # dias_abono == 10
                            opcoes_p1 = list([4, 5, 14, 15])
                        p1_duração = st.selectbox(
                            "Duração das férias P1:", opcoes_p1)
                        p1_fim = p1_inicio + \
                            pd.Timedelta(days=p1_duração - 1)  # type: ignore
                        st.success(f"Último dia das férias P1: {p1_fim}")

                        p2_inicio = st.date_input(
                            "Início das férias P2:")
                        p2_duração = 30 - p1_duração - dias_abono  # Duração total menos os dias de abono  # noqa
                        p2_fim = p2_inicio + \
                            pd.Timedelta(days=p2_duração - 1)  # type: ignore
                        st.warning(f"Duração P2: {p2_duração} dias.")
                        st.success(f"Último dia das férias P2: {p2_fim}")

                        p3_inicio = None
                        p3_fim = None

                else:  # Sem abono
                    dias_abono = None
                    st.info(
                        "Para férias sem abono, a duração total deve ser 30 dias.")  # noqa
                    janelas = st.radio("Escolha a janela de férias:", [
                    "janela única", "janela dupla", "janela tripla"])  # noqa

                    if janelas == "janela única":
                        p1_inicio = st.date_input(
                            "Início das férias P1:")
                        p1_duração = 30
                        p1_fim = p1_inicio + \
                            pd.Timedelta(days=p1_duração - 1)  # type: ignore
                        st.success(f"Último dia das férias P1: {p1_fim}")
                        p2_inicio = None
                        p2_fim = None
                        p3_inicio = None
                        p3_fim = None

                    elif janelas == "janela dupla":
                        p1_inicio = st.date_input(
                            "Início das férias P1:")
                        opcoes_p1 = list(range(5, 26))
                        p1_duração = st.selectbox(
                            "Duração das férias P1:", opcoes_p1)
                        p1_fim = p1_inicio + \
                            pd.Timedelta(days=p1_duração - 1)  # type: ignore
                        st.success(f"Último dia das férias P1: {p1_fim}")
                        p2_inicio = st.date_input(
                            "Início das férias P2:")
                        p2_duração = 30 - p1_duração
                        p2_fim = p2_inicio + \
                            pd.Timedelta(days=p2_duração - 1)  # type: ignore
                        st.warning(f"Duração P2: {p2_duração} dias.")
                        st.success(f"Último dia das férias P2: {p2_fim}")
                        p3_inicio = None
                        p3_fim = None

                    else:  # Janela tripla
                        p1_inicio = st.date_input(
                            "Início das férias P1:")
                        opcoes_p1 = list(range(5, 21))
                        p1_duração = st.selectbox(
                            "Duração das férias P1:", opcoes_p1)
                        p1_fim = p1_inicio + \
                            pd.Timedelta(days=p1_duração - 1)  # type: ignore
                        st.success(f"Último dia das férias P1: {p1_fim}")
                        p2_inicio = st.date_input(
                            "Início das férias P2:")
                        opcoes_p2 = list(range(5, 26 - p1_duração))
                        p2_duração = st.selectbox(
                            "Duração das férias P2:", opcoes_p2)
                        p2_fim = p2_inicio + \
                            pd.Timedelta(days=p2_duração - 1)  # type: ignore
                        st.success(f"Último dia das férias P2: {p2_fim}")
                        p3_inicio = st.date_input(
                            "Início das férias P3:")
                        p3_duração = 30 - p1_duração - p2_duração
                        p3_fim = p3_inicio + \
                            pd.Timedelta(days=p3_duração - 1)  # type: ignore
                        st.warning(f"Duração P3: {p3_duração} dias.")
                        st.success(f"Último dia das férias P3: {p3_fim}")

        if st.button("Marcar Férias"):
            data_marcação = pd.Timestamp.now()  # Data da marcação
            data_marcacao = data_marcação.strftime("%d/%m/%Y")
            # pegar o tamanho da coluna "ID"
            tamanho = marcacoes["ID"].tolist()
            id = len(tamanho)
            try:
                # Converte as datas para strings no formato 'YYYY-MM-DD' # noqa
                p1_inicio_str = p1_inicio.strftime(  # type: ignore # noqa
                    "%d/%m/%Y")
                p1_fim_str = p1_fim.strftime("%d/%m/%Y")
                if p2_inicio:
                    p2_inicio_str = p2_inicio.strftime(  # type: ignore # noqa
                        "%d/%m/%Y")
                    p2_fim_str = p2_fim.strftime("%d/%m/%Y")  # type: ignore # noqa
                else:
                    p2_inicio_str = None
                    p2_fim_str = None
                if p3_inicio:
                    p3_inicio_str = p3_inicio.strftime(  # type: ignore # noqa
                        "%d/%m/%Y"
                    )
                    p3_fim_str = p3_fim.strftime(  # type: ignore # noqa
                        "%d/%m/%Y")
                else:
                    p3_inicio_str = None
                    p3_fim_str = None

                # Cria a lista de dados para salvar
                dados_marcacao = [
                    id,
                    data_marcacao,
                    email_input,
                    email_colaborador,
                    ferias[ferias["Email Corporativo"] ==
                        email_colaborador]["Nome Completo"].values[0],  # noqa
                    ferias[ferias["Email Corporativo"] ==
                        email_colaborador]["Time"].values[0],  # noqa
                    abono,
                    dias_abono,
                    p1_inicio_str,
                    p1_fim_str,
                    p2_inicio_str,
                    p2_fim_str,
                    p3_inicio_str,
                    p3_fim_str,
                    alteracao
                ]

                # Ver o tamanho da coluna "id" para saber onde inserir
                num_linhas_existentes = len(tamanho) + 1

                # Define o intervalo
                intervalo = f"A{num_linhas_existentes +
                                1}:N{num_linhas_existentes + 1}"  # noqa

                # Insere os dados no intervalo correto
                escrever_dados("Marcações", intervalo,
                                [dados_marcacao])  # noqa
                st.success("Férias marcadas com sucesso!")

                # Enviar mensagem para o Slack
                enviar_chats(p1_inicio_str, p1_fim_str, p2_inicio_str, p2_fim_str, p3_inicio_str, p3_fim_str)  # noqa

            except Exception as e:
                st.error(f"Erro ao marcar férias: {e}. Fale com Igor Oliveira, do time de BI.")  # noqa
                chats_channel(f"Erro ao marcar férias: {e}. Marcador {email_input}")  # noqa


# Interface Streamlit
st.logo("https://inchurch.com.br/wp-content/uploads/2024/09/inchurch-logo-svg.svg")  # noqa
st.title("Gerenciamento de Férias")

if not st.user.is_logged_in:
    st.info("Faça login com sua conta Google @inchurch.com.br para continuar.")
    st.login()
    st.stop()

email_input = st.user.email.lower()
emails = principal["Email Corporativo"].tolist()
if email_input not in emails:
    st.error(f"O email **{email_input}** não tem acesso a este app. Entre em contato com o DP.")
    st.logout()
    st.stop()

nome_marcador = principal[principal["Email Corporativo"]
                          == email_input]["Nome Completo"].values[0]

with st.sidebar:
    st.write(f"Logado como **{nome_marcador}**")
    st.logout()

# Mostrar opções de "Consultar Férias" ou "Marcar Novas Férias"
opcao = st.radio("O que você deseja fazer?", [
                 "Consultar Férias", "Marcar Novas Férias ou Alterar Férias Marcadas"])  # noqa

if opcao == "Consultar Férias":
    # Seleção do Time
    times = ['Todos'] + list(marcacoes_validas["Time"].unique())
    time = st.selectbox("Selecione o time:", times, index=0)

    # Filtrar os dados com base no Time selecionado
    if time != 'Todos':
        ferias = marcacoes_validas[marcacoes_validas["Time"] == time]
    else:
        ferias = marcacoes_validas

    # Seleção do Colaborador (Filtro com base no Time, ou "Todos")
    colaboradores = ['Todos'] + \
        list(ferias["Email do colaborador"].unique())
    email = st.selectbox(
        "Selecione o Email do colaborador:", colaboradores, index=0)

    # Filtrar os dados com base no Colaborador selecionado
    if email != 'Todos':
        ferias = ferias[ferias["Email do colaborador"] == email]

    # Exibir todas as colunas exceto "email do colaborador"
    st.dataframe(ferias.drop(
        columns=["Email do colaborador", "Alteração"]))

# Marcar Novas Férias
if opcao == "Marcar Novas Férias ou Alterar Férias Marcadas":
    alteracao = None
    dias_abono = None
    # Seleção do Time
    times = ['Todos'] + list(principal["Time"].unique())
    time = st.selectbox("Selecione o time:", times, index=0)

    # Filtrar os dados com base no Time selecionado
    if time != 'Todos':
        ferias = principal[principal["Time"] == time]
    else:
        ferias = principal

    # Seleção do Colaborador
    colaboradores = ['Todos'] + \
        list(ferias["Email Corporativo"].unique())
    email_colaborador = st.selectbox(
        "Selecione o Email do colaborador:", colaboradores, index=0)

    if email_colaborador != 'Todos':
        nome_gestor = ferias[ferias["Email Corporativo"] == email_colaborador]["GESTOR IMEDIATO"].values[0]  # noqa
        email_gestor = principal[principal["Nome Completo"] == nome_gestor]["Email Corporativo"].values[0]  # noqa
    else:
        nome_gestor = None
        email_gestor = None

    # Verificar se o gestor do colaborador é o marcador
    if nome_gestor != None and nome_gestor != nome_marcador:  # noqa

        resposta = st.selectbox(
            "Você não é o gestor imediato deste colaborador. Tem certeza que deseja continuar?",  # noqa
            ["Não", "Sim"]
        )
        if resposta == "Sim":
            st.info(
                "Ok, você marcará férias de um colaborador sem ser o gestor dele.")  # noqa
            continuar = True
        else:
            continuar = False
    else:
        continuar = True  # É o gestor, pode continuar

    if continuar == False:  # noqa
        st.info("Selecione outro colaborador.")
    else:
        # Verificar se colaborador já tem férias marcadas
        if email_colaborador in marcacoes_validas["Email do colaborador"].values:  # noqa
            st.warning(
                "Este colaborador já tem férias marcadas. Deseja alterá-las ou marcar novas?.")  # noqa
            alterar = st.radio("Escolha uma opção:", ["Alterar", "Marcar Novas"])  # noqa

            if alterar == "Marcar Novas":
                alteracao = None
                marcar_ferias()
            else:
                st.dataframe(marcacoes_validas[marcacoes_validas["Email do colaborador"] == email_colaborador])  # noqa
                alteracao = st.selectbox("Selecione o ID da marcação que deseja alterar:",  # noqa
                                         marcacoes_validas[marcacoes_validas["Email do colaborador"] == email_colaborador]["ID"].tolist())  # noqa
                alterar = marcacoes_validas[marcacoes_validas["ID"] == alteracao]  # noqa

                # Verificar se é com abono ou sem:
                abono = alterar["Abono"].values[0]
                if abono == "COM abono":
                    periodo = st.radio("Qual período deseja alterar?", ["P1", "P2"])  # noqa

                    agora = pd.Timestamp.now().tz_localize(None)
                    data_inicio = pd.to_datetime(alterar[f"Início {periodo}"].values[0], errors='coerce', dayfirst=True).tz_localize(None)

                    if agora > data_inicio:
                        st.warning("Você não pode alterar férias que já começaram.")  # noqa
                    else:
                        inicio = st.date_input(f"Início das férias {periodo}:")  # noqa
                        duração = pd.to_datetime(alterar[f"Fim {periodo}"].values[0], errors='coerce', dayfirst=True) - pd.to_datetime(alterar[f"Início {periodo}"].values[0], errors='coerce', dayfirst=True)  # noqa
                        fim = inicio + pd.Timedelta(duração)  # type: ignore # noqa
                        st.success(f"Duração das férias: {duração.days + 1} dias.")  # noqa
                        st.success(f"Último dia das férias {periodo}: {fim}")  # noqa
                        if periodo == "P1":
                            p1_inicio = inicio
                            p1_fim = fim
                            if alterar["Início P2"].values[0] == "":  # noqa
                                p2_inicio = None
                                p2_fim = None
                            else:
                                p2_inicio = pd.to_datetime(alterar["Início P2"].values[0], errors='coerce', dayfirst=True)  # noqa
                                p2_fim = pd.to_datetime(alterar["Fim P2"].values[0], errors='coerce', dayfirst=True)  # noqa
                            if alterar["Início P3"].values[0] == "":  # noqa
                                p3_inicio = None
                                p3_fim = None
                        elif periodo == "P2":
                            p1_inicio = pd.to_datetime(alterar["Início P1"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p1_fim = pd.to_datetime(alterar["Fim P1"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p2_inicio = inicio
                            p2_fim = fim
                            if alterar["Início P3"].values[0] == "":  # noqa
                                p3_inicio = None
                                p3_fim = None

                else:
                    st.info("Para férias sem abono, a duração total deve ser 30 dias.")  # noqa
                    # Perguntar QUAIS períodos deseja alterar:
                    periodo = st.radio("Qual período deseja alterar?", ["P1", "P2", "P3"])  # noqa

                    if pd.Timestamp.now() > pd.to_datetime(alterar[f"Início {periodo}"].values[0], errors='coerce', dayfirst=True):  # noqa
                        st.warning("Você não pode alterar férias que já começaram.")  # noqa
                    else:
                        inicio = st.date_input(f"Início das férias {periodo}:")  # noqa
                        duração = st.selectbox(f"Duração das férias {periodo}:", list(range(5, 31)))  # noqa
                        fim = inicio + pd.Timedelta(days=duração - 1)  # type: ignore # noqa
                        st.success(f"Último dia das férias {periodo}: {fim}")  # noqa
                        if periodo == "P1":
                            p1_inicio = inicio
                            p1_fim = fim
                            if alterar["Início P2"].values[0] == "":  # noqa
                                p2_inicio = None
                                p2_fim = None
                            else:
                                p2_inicio = pd.to_datetime(alterar["Início P2"].values[0], errors='coerce', dayfirst=True)  # noqa
                                p2_fim = pd.to_datetime(alterar["Fim P2"].values[0], errors='coerce', dayfirst=True)  # noqa
                            if alterar["Início P3"].values[0] == "":  # noqa
                                p3_inicio = None
                                p3_fim = None
                            else:
                                p3_inicio = pd.to_datetime(alterar["Início P2"].values[0], errors='coerce', dayfirst=True)  # noqa
                                p3_fim = pd.to_datetime(alterar["Fim P2"].values[0], errors='coerce', dayfirst=True)  # noqa

                        elif periodo == "P2":
                            p1_inicio = pd.to_datetime(alterar["Início P1"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p1_fim = pd.to_datetime(alterar["Fim P1"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p2_inicio = inicio
                            p2_fim = fim
                            if alterar["Início P3"].values[0] == "":  # noqa
                                p3_inicio = None
                                p3_fim = None
                            else:
                                p3_inicio = pd.to_datetime(alterar["Início P2"].values[0], errors='coerce', dayfirst=True)  # noqa
                                p3_fim = pd.to_datetime(alterar["Fim P2"].values[0], errors='coerce', dayfirst=True)  # noqa

                        else:
                            p1_inicio = pd.to_datetime(alterar["Início P1"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p1_fim = pd.to_datetime(alterar["Fim P1"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p2_inicio = pd.to_datetime(alterar["Início P2"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p2_fim = pd.to_datetime(alterar["Fim P2"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p3_inicio = inicio
                            p3_fim = fim

                if st.button("Salvar Alteração"):
                    data_marcação = pd.Timestamp.now()  # Data da marcação # noqa
                    data_marcacao = data_marcação.strftime("%d/%m/%Y")  # noqa
                    # pegar o tamanho da coluna "ID"
                    tamanho = marcacoes["ID"].tolist()
                    id = len(tamanho)

                    print(p1_inicio, p1_fim, p2_inicio, p2_fim, p3_inicio, p3_fim)  # noqa

                    try:
                        # Converte as datas para strings no formato 'YYYY-MM-DD' # noqa
                        p1_inicio_str = p1_inicio.strftime(  # type: ignore # noqa
                            "%d/%m/%Y")
                        p1_fim_str = p1_fim.strftime("%d/%m/%Y")  # noqa
                        if p2_inicio and p2_inicio is not None:  # Existe e não está vazio # noqa
                            p2_inicio_str = p2_inicio.strftime(  # type: ignore # noqa
                                "%d/%m/%Y")
                            p2_fim_str = p2_fim.strftime("%d/%m/%Y")  # type: ignore # noqa
                        else:
                            p2_inicio_str = None
                            p2_fim_str = None
                        if p3_inicio and p3_inicio is not None:  # Existe e não está vazio # noqa
                            p3_inicio_str = p3_inicio.strftime(  # type: ignore # noqa
                                "%d/%m/%Y"
                            )
                            p3_fim_str = p3_fim.strftime(  # type: ignore # noqa
                                "%d/%m/%Y")
                        else:
                            p3_inicio_str = None
                            p3_fim_str = None

                        # Cria a lista de dados para salvar
                        dados_marcacao = [
                            id,
                            data_marcacao,
                            email_input,
                            email_colaborador,
                            ferias[ferias["Email Corporativo"] ==  # noqa
                                email_colaborador]["Nome Completo"].values[0],  # noqa
                            ferias[ferias["Email Corporativo"] ==  # noqa
                                email_colaborador]["Time"].values[0],  # noqa
                            abono,
                            dias_abono,
                            p1_inicio_str,
                            p1_fim_str,
                            p2_inicio_str,
                            p2_fim_str,
                            p3_inicio_str,
                            p3_fim_str,
                            alteracao
                        ]

                        # Ver o tamanho da coluna "id" para saber onde inserir # noqa
                        num_linhas_existentes = len(tamanho) + 1  # noqa

                        # Define o intervalo
                        intervalo = f"A{num_linhas_existentes + 1}:N{num_linhas_existentes + 1}"  # noqa

                        # Insere os dados no intervalo correto
                        escrever_dados("Marcações", intervalo,
                                        [dados_marcacao])  # noqa
                        st.success("Férias marcadas com sucesso!")  # noqa

                        # Enviar mensagem para o Chats
                        enviar_chats(p1_inicio_str, p1_fim_str, p2_inicio_str, p2_fim_str, p3_inicio_str, p3_fim_str)  # noqa

                    except Exception as e:
                        st.error(f"Erro ao marcar férias: {e}. Fale com Igor Oliveira, do time de BI.")  # noqa
                        chats_channel(f"Erro ao marcar férias: {e}. Marcador {email_input}")  # noqa

        else:
            marcar_ferias()
