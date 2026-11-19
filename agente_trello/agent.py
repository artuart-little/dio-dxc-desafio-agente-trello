from google.adk.agents.llm_agent import Agent

import os
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.adk.agents import Agent
from trello import TrelloClient

# Carrega o .env da própria pasta do agente (funciona tanto no `adk web` quanto em testes diretos)
CAMINHO_ENV = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=CAMINHO_ENV)

# Fuso horário de Brasília (UTC-3) sem depender de pacotes externos de timezone no Windows
FUSO_BRASILIA = timezone(timedelta(hours=-3))
QUADRO_PADRAO = "DIO_DesafioDXC"

DIAS_SEMANA_PT = [
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
]


# =============================================================================
# FUNÇÕES AUXILIARES (Conexão única, NLP básico e busca segura)
# =============================================================================

def obter_cliente_trello() -> TrelloClient:
    """Centraliza a validação de credenciais e a conexão com a API do Trello."""
    api_key = os.getenv("TRELLO_API_KEY")
    api_secret = os.getenv("TRELLO_API_SECRET")
    token = os.getenv("TRELLO_TOKEN")

    if not all([api_key, api_secret, token]):
        raise EnvironmentError(
            "Credenciais do Trello incompletas. Verifique TRELLO_API_KEY, "
            "TRELLO_API_SECRET e TRELLO_TOKEN no arquivo .env."
        )

    return TrelloClient(api_key=api_key, api_secret=api_secret, token=token)


def normalizar_texto(texto: str) -> str:
    """Remove acentos, espaços extras e converte para minúsculas para comparação flexível."""
    if not texto:
        return ""
    sem_acento = (
        unicodedata.normalize("NFKD", texto)
        .encode("ASCII", "ignore")
        .decode("utf-8")
    )
    return sem_acento.strip().lower()


def obter_quadro_trello(nome_quadro: str = QUADRO_PADRAO):
    """Localiza um quadro aberto pelo nome (ignorando acentos e maiúsculas/minúsculas)."""
    cliente = obter_cliente_trello()
    alvo = normalizar_texto(nome_quadro)

    for quadro in cliente.list_boards(board_filter="open"):
        if normalizar_texto(quadro.name) == alvo:
            return quadro

    raise ValueError(f"Quadro '{nome_quadro}' não encontrado na conta do Trello.")


def obter_lista_trello(nome_lista: str, nome_quadro: str = QUADRO_PADRAO):
    """Localiza uma lista específica dentro do quadro informado, tolerando variações de acento."""
    quadro = obter_quadro_trello(nome_quadro)
    alvo = normalizar_texto(nome_lista)

    for lista in quadro.list_lists(list_filter="open"):
        if normalizar_texto(lista.name) == alvo:
            return lista

    nomes_disponiveis = [lista.name for lista in quadro.list_lists(list_filter="open")]
    raise ValueError(
        f"Lista '{nome_lista}' não encontrada no quadro '{quadro.name}'. "
        f"Listas disponíveis: {', '.join(nomes_disponiveis)}."
    )


def buscar_card_por_nome(nome_tarefa: str, nome_quadro: str = QUADRO_PADRAO):
    """Procura um card pelo título em todas as listas abertas do quadro."""
    quadro = obter_quadro_trello(nome_quadro)
    alvo = normalizar_texto(nome_tarefa)

    for lista in quadro.list_lists(list_filter="open"):
        for card in lista.list_cards():
            if normalizar_texto(card.name) == alvo:
                return card, lista

    return None, None


# =============================================================================
# FERRAMENTAS DO AGENTE (Tools registradas no Google ADK)
# =============================================================================

def obter_data_atual() -> str:
    """
    Retorna a data e o dia da semana atuais no horário de Brasília (UTC-3).
    Use sempre no início da conversa e para calcular prazos relativos como 'hoje' ou 'amanhã'.
    """
    try:
        agora = datetime.now(FUSO_BRASILIA)
        dia_semana = DIAS_SEMANA_PT[agora.weekday()]
        return (
            f"Hoje é {dia_semana}, {agora.strftime('%d/%m/%Y')} "
            f"(formato ISO: {agora.strftime('%Y-%m-%d')})."
        )
    except Exception as erro:
        return f"Erro ao obter data atual: {erro}"


def listar_quadros() -> str:
    """
    Lista todos os quadros abertos disponíveis na conta do Trello do usuário.
    Útil quando o usuário quiser organizar tarefas em um quadro diferente do padrão 'DIO'.
    """
    try:
        cliente = obter_cliente_trello()
        quadros = cliente.list_boards(board_filter="open")
        if not quadros:
            return "Nenhum quadro aberto foi encontrado na conta do Trello."

        nomes = [f"- {quadro.name}" for quadro in quadros]
        return "Quadros disponíveis no Trello:\n" + "\n".join(nomes)
    except Exception as erro:
        return f"Erro ao listar quadros: {erro}"


def criar_tarefa(
    nome: str,
    descricao: str = "",
    data_vencimento: str = "",
    nome_quadro: str = QUADRO_PADRAO,
) -> str:
    """
    Cria um novo card na lista 'A fazer' do quadro especificado no Trello.

    Args:
        nome: Título curto e claro da tarefa.
        descricao: Detalhes adicionais sobre o que precisa ser feito.
        data_vencimento: Data de entrega opcional no formato YYYY-MM-DD (ex: '2026-11-18').
        nome_quadro: Nome do quadro no Trello (padrão: 'DIO').
    """
    try:
        lista_a_fazer = obter_lista_trello("A fazer", nome_quadro=nome_quadro)
        prazo_iso = "null"

        if data_vencimento.strip():
            # Valida o formato e fixa em 15:00 UTC (12:00 BRT) para impedir que o
            # fuso horário brasileiro exiba a tarefa com um dia a menos no Trello.
            data_validada = datetime.strptime(data_vencimento.strip(), "%Y-%m-%d")
            prazo_iso = data_validada.strftime("%Y-%m-%dT15:00:00.000Z")

        lista_a_fazer.add_card(name=nome.strip(), desc=descricao.strip(), due=prazo_iso)
        aviso_data = f" com prazo para {data_vencimento}" if data_vencimento.strip() else ""
        return (
            f"Sucesso: tarefa '{nome}' criada na lista 'A fazer' "
            f"do quadro '{nome_quadro}'{aviso_data}."
        )
    except ValueError as erro_validacao:
        return f"Erro de validação ao criar tarefa: {erro_validacao}"
    except Exception as erro:
        return f"Erro ao criar tarefa no Trello: {erro}"


def listar_tarefas(status: str = "", nome_quadro: str = QUADRO_PADRAO) -> str:
    """
    Lista as tarefas do quadro especificado, podendo filtrar por uma lista (status).

    Args:
        status: Opcional. Ex: 'A fazer', 'Em andamento' ou 'Concluído' (aceita sem acento).
        nome_quadro: Nome do quadro no Trello (padrão: 'DIO').
    """
    try:
        quadro = obter_quadro_trello(nome_quadro)
        filtro = normalizar_texto(status) if status else None
        linhas = []

        for lista in quadro.list_lists(list_filter="open"):
            if filtro and normalizar_texto(lista.name) != filtro:
                continue

            cards = lista.list_cards()
            linhas.append(f"\n[{lista.name.upper()}]")
            if not cards:
                linhas.append("  (sem tarefas)")
                continue

            for card in cards:
                prazo = card.due[:10] if card.due else "sem prazo"
                linhas.append(f"  - {card.name} (Prazo: {prazo})")

        if not linhas:
            return f"Nenhuma lista correspondente ao status '{status}' foi encontrada no quadro '{quadro.name}'."

        return f"Tarefas do quadro '{quadro.name}':" + "\n".join(linhas)
    except Exception as erro:
        return f"Erro ao listar tarefas: {erro}"


def mover_tarefa(
    nome_tarefa: str,
    novo_status: str,
    nome_quadro: str = QUADRO_PADRAO,
) -> str:
    """
    Move um card existente para outra lista (status) no Trello.

    Args:
        nome_tarefa: Nome exato (ou aproximado em acentuação/caixa) da tarefa a mover.
        novo_status: Lista de destino ('A fazer', 'Em andamento' ou 'Concluído').
        nome_quadro: Nome do quadro no Trello (padrão: 'DIO').
    """
    try:
        card, lista_atual = buscar_card_por_nome(nome_tarefa, nome_quadro=nome_quadro)
        if not card:
            return f"Tarefa '{nome_tarefa}' não encontrada no quadro '{nome_quadro}'."

        lista_destino = obter_lista_trello(novo_status, nome_quadro=nome_quadro)
        card.change_list(lista_destino.id)
        return (
            f"Sucesso: tarefa '{card.name}' movida de '{lista_atual.name}' "
            f"para '{lista_destino.name}' no quadro '{nome_quadro}'."
        )
    except Exception as erro:
        return f"Erro ao mover tarefa: {erro}"


def remover_tarefa(nome_tarefa: str, nome_quadro: str = QUADRO_PADRAO) -> str:
    """
    Exclui permanentemente um card do quadro do Trello.

    Args:
        nome_tarefa: Nome da tarefa que deve ser removida.
        nome_quadro: Nome do quadro no Trello (padrão: 'DIO').
    """
    try:
        card, lista_atual = buscar_card_por_nome(nome_tarefa, nome_quadro=nome_quadro)
        if not card:
            return f"Tarefa '{nome_tarefa}' não encontrada no quadro '{nome_quadro}'."

        nome_real = card.name
        card.delete()
        return (
            f"Sucesso: tarefa '{nome_real}' removida permanentemente da lista "
            f"'{lista_atual.name}' no quadro '{nome_quadro}'."
        )
    except Exception as erro:
        return f"Erro ao remover tarefa: {erro}"


# =============================================================================
# DEFINIÇÃO DO ROOT AGENT (Obrigatório para descoberta pelo Google ADK)
# =============================================================================

INSTRUCAO_AGENTE = """
Você é um assistente pessoal de produtividade focado em organizar tarefas diárias no Trello
(estudos de Ciência de Dados e IA, entregas da faculdade, trabalho e projetos de tecnologia).

Regras de comportamento:
1. Na primeira interação da conversa, chame obrigatoriamente a ferramenta `obter_data_atual`,
   informe a data de hoje ao usuário e pergunte quais são as tarefas do dia.
2. Utilize o quadro 'DIO' como padrão, a menos que o usuário peça para consultar ou usar outro quadro
   (neste caso, use `listar_quadros` para confirmar o nome exato).
3. Antes de criar tarefas com datas relativas ("hoje", "amanhã", "sexta"), consulte `obter_data_atual`
   e converta o prazo para o formato YYYY-MM-DD.
4. Ao receber pedidos para mover ou excluir tarefas, execute a ferramenta correspondente e confirme
   o resultado de forma objetiva. Antes de remover uma tarefa, só peça confirmação se houver ambiguidade.
5. Responda sempre em português, de forma direta e organizada.
"""

root_agent = Agent(
    model='gemini-flash-lite-latest',
    name="agente_tarefas_trello",
    description="Agente de IA para gerenciar tarefas diárias em quadros do Trello via conversa.",
    instruction=INSTRUCAO_AGENTE,
    tools=[
        obter_data_atual,
        listar_quadros,
        criar_tarefa,
        listar_tarefas,
        mover_tarefa,
        remover_tarefa,
    ],
)