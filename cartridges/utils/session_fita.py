# session_fita.py
#
# Copyright 2026 kramo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As fitas de LED atrás dos monitores, acompanhando o app e a sessão.

O ciclo tem quatro momentos: o app abre e as fitas acendem no roxo dele, o jogo
abre e elas vestem a cor daquele jogo, o jogo fecha e elas voltam ao roxo, o app
fecha e elas voltam exatamente ao que eram antes de tudo — inclusive apagadas.

O estado de antes fica no GSettings, e não em memória, pela mesma razão do papel
de parede de sessão: o app morto no meio da sessão deixaria as três fitas
vestidas de um jogo que já acabou, e só o arranque seguinte pode desfazer isso.

A conversa é local. A nuvem da Tuya entra uma única vez, no assistente, para
buscar a chave de cada módulo; daí em diante é o PC falando direto com a fita.
"""

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, NamedTuple, Optional, TYPE_CHECKING

from cartridges import shared
from cartridges.utils.cor_da_capa import dominante

if TYPE_CHECKING:
    from cartridges.game import Game

# Matiz e saturação do #9141ac, o roxo da paleta do app. O brilho não entra:
# ele é do usuário.
ROXO_DO_APP = (284, 620)


class Fita(NamedTuple):
    """Um módulo Tuya, do jeito que ele fica no `fitas.json`."""

    nome: str
    id: str
    ip: str
    key: str
    versao: str = "3.3"


class Cor(NamedTuple):
    """Matiz (0–359), saturação (0–1000) e brilho (0–1000)."""

    matiz: int
    saturacao: int
    brilho: int


def _gravar_json(caminho: Path, dados: dict[str, Any]) -> None:
    """Grava um JSON num temporário e troca, para não perder o arquivo se a
    energia cair no meio.

    Nunca levanta: quem chama está na thread de UI, e um enfeite de sessão não
    pode derrubar a tela. A pasta entra no mesmo ``try`` da escrita porque ela
    falha pelo mesmo motivo — permissão negada, disco cheio, caminho ocupado.
    """
    temporario = caminho.with_name(caminho.name + ".tmp")
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario.write_text(json.dumps(dados), encoding="utf-8")
        temporario.replace(caminho)
    except OSError as erro:
        logging.warning("Não foi possível gravar %s: %s", caminho.name, erro)


# region Configuração


def fitas() -> list[Fita]:
    """As fitas configuradas. Lista vazia quando não há configuração válida."""
    try:
        dados = json.loads(shared.fitas_arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(dados, dict):
        return []
    achadas = []
    for item in dados.get("fitas", []):
        try:
            achadas.append(
                Fita(
                    str(item["nome"]),
                    str(item["id"]),
                    str(item["ip"]),
                    str(item["key"]),
                    str(item.get("versao", "3.3")),
                )
            )
        except (KeyError, TypeError):
            logging.warning("Fita ignorada por estar incompleta no arquivo")
    return achadas


def gravar_fitas(lista: list[Fita]) -> None:
    """Grava a configuração das fitas."""
    conteudo = {"fitas": [fita._asdict() for fita in lista]}
    _gravar_json(shared.fitas_arquivo, conteudo)


# endregion
# region Cor por jogo


def _sidecar(game_id: str):
    return shared.fitas_dir / f"{game_id}.json"


def _ler_sidecar(game_id: str) -> Optional[dict[str, Any]]:
    try:
        dados = json.loads(_sidecar(game_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return dados if isinstance(dados, dict) else None


def escolhida(game_id: str) -> bool:
    """Se a cor deste jogo foi escolhida por gente, e não pela capa."""
    dados = _ler_sidecar(game_id)
    return bool(dados and dados.get("locked"))


def salvar_cor(game_id: str, name: str, cor: Cor) -> None:
    """Guarda a escolha manual de um jogo.

    Pelo temporário como o resto: um sidecar truncado por uma queda no meio da
    escrita é lido como corrompido, e o jogo voltaria em silêncio para a cor
    automática — o usuário perderia a escolha sem nenhum aviso.
    """
    dados = {
        "name": name,
        "matiz": cor.matiz,
        "saturacao": cor.saturacao,
        "brilho": cor.brilho,
        "locked": True,
        "timestamp": int(time.time()),
    }
    _gravar_json(_sidecar(game_id), dados)


def redefinir(game_id: str) -> None:
    """Devolve o jogo à cor automática."""
    try:
        _sidecar(game_id).unlink(missing_ok=True)
    except OSError as erro:
        logging.warning("Não foi possível apagar a cor da fita: %s", erro)


def brilho_padrao() -> int:
    return shared.schema.get_int("fita-brilho-padrao")


def cor_do_jogo(game: "Game") -> Cor:
    """A cor que este jogo veste: a escolhida, a da capa, ou o roxo do app."""
    dados = _ler_sidecar(game.game_id)
    if dados and dados.get("locked"):
        return Cor(
            int(dados.get("matiz", ROXO_DO_APP[0])),
            int(dados.get("saturacao", ROXO_DO_APP[1])),
            int(dados.get("brilho", brilho_padrao())),
        )

    capa = game.get_cover_path()
    da_capa = dominante(capa) if capa else None
    matiz, saturacao = da_capa if da_capa else ROXO_DO_APP
    return Cor(matiz, saturacao, brilho_padrao())


# endregion
# region Conversa com o módulo

# Os pontos de dado do controlador RGB, medidos nos módulos: 20 liga e desliga,
# 21 é o modo ("colour" é cor fixa, contra "scene" e "music"), 24 é a cor como
# matiz, saturação e brilho em hexadecimal de quatro dígitos cada.
DP_LIGADA = "20"
DP_MODO = "21"
DP_COR = "24"

# Cinco segundos é folgado para uma resposta que costuma vir em milissegundos, e
# curto o bastante para a thread não ficar pendurada quando a fita sumiu.
ESPERA = 5


def hsv_hex(cor: Cor) -> str:
    """A cor do jeito que o módulo aceita: HHHHSSSSVVVV."""
    return f"{cor.matiz:04x}{cor.saturacao:04x}{cor.brilho:04x}"


def cor_de_hex(valor: str) -> Optional[Cor]:
    """O caminho de volta, para ler o que o módulo respondeu."""
    if len(valor) != 12:
        return None
    try:
        return Cor(int(valor[0:4], 16), int(valor[4:8], 16), int(valor[8:12], 16))
    except ValueError:
        return None


def _dispositivo(fita: Fita) -> Any:
    """O objeto da tinytuya para esta fita. Trocado nos testes.

    Importado aqui dentro de propósito: a biblioteca só faz falta quando há
    fita configurada, e o resto do app (e os testes) não paga por ela.
    """
    import tinytuya  # noqa: PLC0415

    # Sem retentativa: a tinytuya tenta cinco vezes com cinco segundos entre
    # elas, e uma fita que não respondeu na primeira não vai responder na
    # quinta. O caminho de fechamento do app é síncrono — insistir custaria
    # dezenas de segundos de encerramento travado por uma fita fora da tomada.
    # Com isto, o teto por fita é o ESPERA do soquete.
    modulo = tinytuya.BulbDevice(
        fita.id,
        fita.ip,
        fita.key,
        version=float(fita.versao),
        persist=False,
        connection_retry_limit=1,
        connection_retry_delay=0,
    )
    modulo.set_socketTimeout(ESPERA)
    return modulo


def ler_estado(fita: Fita) -> Optional[dict[str, Any]]:
    """Se a fita está acesa e em que cor. ``None`` quando ela não responde."""
    try:
        resposta = _dispositivo(fita).status()
    except Exception as erro:  # a tinytuya levanta de tudo: socket, struct, json
        logging.warning("Fita %s não respondeu: %s", fita.nome, erro)
        return None

    dps = (resposta or {}).get("dps")
    if not isinstance(dps, dict):
        logging.warning("Fita %s respondeu %s", fita.nome, (resposta or {}).get("Error"))
        return None
    return {
        "ligada": bool(dps.get(DP_LIGADA, False)),
        "cor": str(dps.get(DP_COR, "")),
    }


def aplicar(fita: Fita, ligada: bool, cor_hex: str) -> bool:
    """Manda cor e estado para uma fita. Nunca levanta; devolve se deu certo."""
    valores = {DP_LIGADA: ligada, DP_MODO: "colour", DP_COR: cor_hex}
    try:
        resposta = _dispositivo(fita).set_multiple_values(valores)
    except Exception as erro:
        logging.warning("Fita %s recusou o comando: %s", fita.nome, erro)
        return False

    if isinstance(resposta, dict) and resposta.get("Error"):
        logging.warning("Fita %s recusou o comando: %s", fita.nome, resposta["Error"])
        return False
    return True


# endregion
# region Ciclo de vida

CHAVE_ESTADO = "fita-estado-anterior"

# Quanto o fechamento do app pode esperar pela devolução. Três fitas mudas
# custam três vezes o ESPERA do soquete, e ninguém deve sentir o app demorar a
# sumir da tela por causa de um módulo fora da tomada. Estourado o prazo, quem
# termina o serviço é o arranque seguinte.
PRAZO_FECHAMENTO = 4


def ligada() -> bool:
    """Se há o que fazer: recurso ligado nas Preferências e fita configurada."""
    return bool(shared.schema.get_boolean("session-fita") and fitas())


def _em_thread(tarefa: Any) -> threading.Thread:
    """Toda conversa com as fitas sai da thread de UI por aqui."""
    linha = threading.Thread(target=tarefa, daemon=True)
    linha.start()
    return linha


def _vestir(cor: Cor) -> None:
    """Acende todas as fitas na cor pedida. Síncrono; nunca levanta."""
    cor_hex = hsv_hex(cor)
    for fita in fitas():
        aplicar(fita, True, cor_hex)


def _roxo() -> Cor:
    """O roxo do app no brilho que o usuário escolheu."""
    return Cor(ROXO_DO_APP[0], ROXO_DO_APP[1], brilho_padrao())


def _guardar_e_vestir() -> None:
    """Guarda o estado de cada fita e acende todas no roxo do app.

    O que não respondeu fica de fora do que foi guardado: devolver uma fita ao
    estado que só foi chutado seria pior que não devolver nada.
    """
    if not ligada():
        return

    estado = {}
    for fita in fitas():
        lido = ler_estado(fita)
        if lido is not None:
            estado[fita.id] = lido
    shared.schema.set_string(CHAVE_ESTADO, json.dumps(estado))

    _vestir(_roxo())


def _devolver() -> None:
    """Devolve cada fita ao estado guardado e limpa a chave."""
    guardado = shared.schema.get_string(CHAVE_ESTADO)
    if not guardado:
        return

    try:
        estados = json.loads(guardado)
    except ValueError:
        estados = {}
    if not isinstance(estados, dict):
        estados = {}

    por_id = {fita.id: fita for fita in fitas()}
    for identificador, estado in estados.items():
        fita = por_id.get(identificador)
        if fita is None:
            continue
        aplicar(fita, bool(estado.get("ligada")), str(estado.get("cor", "")))

    # Limpa mesmo quando alguma fita não respondeu: a chave diz "há uma troca
    # pendente", e insistir eternamente numa fita que saiu da tomada deixaria o
    # app tentando desfazer isso em todo arranque.
    shared.schema.set_string(CHAVE_ESTADO, "")


def abrir() -> None:
    """O app abriu: guarda o estado e acende no roxo. Chamar da thread de UI."""
    if not ligada():
        return
    _em_thread(_guardar_e_vestir)


def comecar(game: "Game") -> None:
    """A sessão começou: veste a cor do jogo. Chamar da thread de UI.

    A cor é calculada dentro da thread, e não antes dela: tirar a cor da capa
    abre e quantiza uma imagem, e isso não pode acontecer enquanto o jogo abre.
    """
    if not ligada():
        return
    _em_thread(lambda: _vestir(cor_do_jogo(game)))


def voltar() -> None:
    """A sessão acabou: de volta ao roxo do app. Chamar da thread de UI."""
    if not ligada():
        return
    _em_thread(lambda: _vestir(_roxo()))


def fechar() -> None:
    """O app está fechando: devolve o estado de antes, com hora marcada.

    Aqui se espera, ao contrário dos outros: é a última janela em que ainda há
    processo para desfazer. Mas não se espera para sempre. Estourado o
    ``PRAZO_FECHAMENTO``, o app sai assim mesmo — a chave continua gravada e o
    ``restaurar_orfaos`` do próximo arranque termina o serviço. É exatamente
    para isso que a chave existe.
    """
    linha = _em_thread(_devolver)
    linha.join(PRAZO_FECHAMENTO)
    if linha.is_alive():
        logging.info(
            "Fitas não devolvidas dentro de %ss; fica para o próximo arranque",
            PRAZO_FECHAMENTO,
        )


def restaurar_orfaos() -> None:
    """Desfaz no arranque a troca que uma execução anterior não desfez."""
    if shared.schema.get_string(CHAVE_ESTADO):
        logging.info("Fitas de uma sessão anterior encontradas; desfazendo")
        _devolver()


# endregion
