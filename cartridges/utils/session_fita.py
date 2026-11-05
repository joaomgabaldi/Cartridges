# session_fita.py
#
# Copyright 2026 joaomgabaldi
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

O app abre e as fitas acendem na cor dele; o jogo abre e elas vestem a do jogo; o jogo fecha e voltam à do app; o app fecha e voltam exatamente ao que eram antes, inclusive apagadas. O estado de antes fica no GSettings, não em memória: o app morto no meio da sessão deixaria as fitas vestidas, e o arranque seguinte desfaz. A nuvem da Tuya entra uma vez, no assistente, para buscar a chave de cada módulo; o resto é local.
"""

import colorsys
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, NamedTuple, Optional, TYPE_CHECKING

from cartridges import shared
from cartridges.utils import calibracao as calibracao_mod
from cartridges.utils import tela_do_jogo
from cartridges.utils.cor_da_capa import dominante
from cartridges.utils.ler_json import ler_json

if TYPE_CHECKING:
    from cartridges.game import Game

# Matiz e saturação do #158AFF, o azul do Kyron: o padrão da "cor do app" (a das fitas sem jogo), trocável nas Preferências. O brilho é do usuário.
COR_PADRAO_DO_APP = (210, 918)
# O padrão de antes do Kyron (#9141ac): só ele e o "Restaurar padrão" antigo gravavam (284, 620); a amostra roxa da paleta grava (285, 622).
ROXO_ANTIGO = (284, 620)


class Fita(NamedTuple):
    """Um módulo Tuya, do jeito que ele fica no `fitas.json`."""

    nome: str
    id: str
    ip: str
    key: str
    versao: str = "3.3"
    # O teto deste dispositivo, em porcentagem: o brilho do app e o de cada jogo valem sobre ele (50% num dispositivo em 50 acende a 25).
    brilho: int = 100
    # A correção do assistente de calibração, como no arquivo (``calibracao.para_json``); ``None``: nunca calibrado.
    calibracao: Optional[dict[str, Any]] = None


class Cor(NamedTuple):
    """Matiz (0–359), saturação (0–1000) e brilho (0–1000)."""

    matiz: int
    saturacao: int
    brilho: int


def _gravar_json(caminho: Path, dados: dict[str, Any]) -> None:
    """Grava um JSON num temporário e troca, para não perder o arquivo se a energia cair. Nunca levanta (thread de UI); a pasta entra no mesmo ``try`` porque falha pelos mesmos motivos."""
    temporario = caminho.with_name(caminho.name + ".tmp")
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario.write_text(json.dumps(dados), encoding="utf-8")
        temporario.replace(caminho)
    except OSError as erro:
        logging.warning("Não foi possível gravar %s: %s", caminho.name, erro)



def fitas() -> list[Fita]:
    try:
        dados = json.loads(shared.fitas_arquivo.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as erro:
        logging.warning("Lista de fitas ilegível (%s): %s", shared.fitas_arquivo.name, erro)
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
                    _teto(item.get("brilho")),
                    item.get("calibracao") if isinstance(item.get("calibracao"), dict) else None,
                )
            )
        except (KeyError, TypeError):
            logging.warning("Fita ignorada por estar incompleta no arquivo")
    return achadas


def _teto(valor: Any) -> int:
    """O brilho por dispositivo lido do arquivo; valor mexido à mão vale 100 e não tira o dispositivo da lista."""
    try:
        return max(1, min(100, int(valor)))
    except (TypeError, ValueError):
        return 100


def gravar_fitas(lista: list[Fita]) -> None:
    conteudo = {"fitas": [fita._asdict() for fita in lista]}
    _gravar_json(shared.fitas_arquivo, conteudo)



def _sidecar(game_id: str):
    return shared.fitas_dir / f"{game_id}.json"


def _ler_sidecar(game_id: str) -> Optional[dict[str, Any]]:
    try:
        dados = ler_json(_sidecar(game_id))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as erro:
        logging.warning("Cor da fita ilegível (%s): %s", _sidecar(game_id).name, erro)
        return None
    return dados if isinstance(dados, dict) else None


def escolhida(game_id: str) -> bool:
    dados = _ler_sidecar(game_id)
    return bool(dados and dados.get("locked"))


def cor_escolhida(game_id: str) -> Optional[Cor]:
    """A cor manual gravada para ``game_id``, ou ``None`` se for automática (segue a capa). Usado pelo backup."""
    dados = _ler_sidecar(game_id)
    if not dados or not dados.get("locked"):
        return None
    try:
        return Cor(int(dados["matiz"]), int(dados["saturacao"]), int(dados["brilho"]))
    except (KeyError, TypeError, ValueError):
        return None


def salvar_cor(game_id: str, name: str, cor: Cor) -> None:
    """Guarda a escolha manual de um jogo, pelo temporário: um sidecar truncado lido como corrompido faria o jogo voltar em silêncio à cor automática."""
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
    """Devolve o jogo à cor automática; o brilho da escolha fica, como brilho próprio."""
    dados = _ler_sidecar(game_id)
    if dados and not dados.get("locked"):
        return  # só brilho próprio: não há cor escolhida a desfazer
    brilho = _brilho_de(dados) if dados else None
    if brilho is not None and brilho != brilho_padrao():
        salvar_brilho(game_id, str(dados.get("name", "")), brilho)
        return
    _apagar_sidecar(game_id)


def _apagar_sidecar(game_id: str) -> None:
    try:
        _sidecar(game_id).unlink(missing_ok=True)
    except OSError as erro:
        logging.warning("Não foi possível apagar a cor da fita: %s", erro)


def _brilho_de(dados: dict[str, Any]) -> Optional[int]:
    """O brilho gravado, ou ``None`` se não estiver lá ou for ilegível (sidecar mexido à mão)."""
    try:
        return max(BRILHO_MINIMO, min(BRILHO_CHEIO, int(dados["brilho"])))
    except (KeyError, TypeError, ValueError):
        return None


def brilho_gravado(game_id: str) -> Optional[int]:
    """O brilho no arquivo do jogo, da cor escolhida ou o próprio, sem tocar na capa (a edição precisa dele sem uma segunda leitura da imagem)."""
    dados = _ler_sidecar(game_id)
    return _brilho_de(dados) if dados else None


def brilho_escolhido(game_id: str) -> Optional[int]:
    """O brilho próprio de um jogo com cor automática, ou ``None``. É separado da cor: mexer nele não tira o jogo da cor automática; com cor escolhida à mão o brilho está na escolha e aqui volta ``None``."""
    dados = _ler_sidecar(game_id)
    if not dados or dados.get("locked"):
        return None
    return _brilho_de(dados)


def salvar_brilho(game_id: str, name: str, brilho: int) -> None:
    """Guarda o brilho próprio de um jogo com cor automática; o padrão não é guardado (o jogo segue o padrão)."""
    if brilho == brilho_padrao():
        _apagar_sidecar(game_id)
        return
    _gravar_json(
        _sidecar(game_id),
        {"name": name, "brilho": brilho, "locked": False, "timestamp": int(time.time())},
    )


# O módulo conta o brilho de 0 a 1000; as telas falam em porcentagem.
BRILHO_CHEIO = 1000

# O mínimo que ainda acende: abaixo disto o módulo apaga.
BRILHO_MINIMO = 10


def por_cento(brilho: int) -> int:
    return round(brilho * 100 / BRILHO_CHEIO)


def de_por_cento(valor: float) -> int:
    """O caminho de volta, sem pedir um brilho que apaga."""
    return max(BRILHO_MINIMO, min(BRILHO_CHEIO, round(valor * BRILHO_CHEIO / 100)))


def brilho_padrao() -> int:
    return shared.schema.get_int("fita-brilho-padrao")


def na_fita(
    cor: Cor,
    fita: Fita,
    teto: Optional[int] = None,
    calibracao: Optional[calibracao_mod.Calibracao] = None,
) -> Cor:
    """A cor que este dispositivo recebe: corrigida pela calibração e com o brilho proporcional ao teto (toda cor que vai a uma fita passa por aqui).

    ``teto`` e ``calibracao`` trocam os do arquivo, para as prévias mostrarem o que ainda não foi salvo.
    """
    teto = fita.brilho if teto is None else teto
    if calibracao is None and fita.calibracao is not None:
        calibracao = calibracao_mod.de_json(fita.calibracao)
    if calibracao is not None:
        cor = calibracao_mod.corrigir(cor, calibracao)
    return cor._replace(brilho=max(BRILHO_MINIMO, round(cor.brilho * teto / 100)))


def cor_do_jogo(game: "Game") -> Cor:
    """A cor que este jogo veste: a escolhida, a da capa ou a do app."""
    dados = _ler_sidecar(game.game_id)
    if dados and dados.get("locked"):
        # Sidecar mexido à mão (``"matiz": null``) não pode levantar aqui (thread de UI): vale o automático.
        try:
            return Cor(
                int(dados.get("matiz", tom_do_app()[0])),
                int(dados.get("saturacao", tom_do_app()[1])),
                int(dados.get("brilho", brilho_padrao())),
            )
        except (TypeError, ValueError):
            logging.warning("Cor da fita de %s ilegível; vale a automática", game.game_id)

    brilho = _brilho_de(dados) if dados and not dados.get("locked") else None
    return cor_da_capa(game.get_cover_path(), brilho)


def cor_da_capa(capa: Optional[Path], brilho: Optional[int] = None) -> Cor:
    """A cor automática desta capa, ou a do app sem capa ou sem cor útil, no brilho próprio do jogo (``brilho``) ou no padrão.

    Separada de ``cor_do_jogo`` para a tela de detalhes, que mostra a capa ainda não aplicada.
    """
    da_capa = dominante(capa) if capa else None
    matiz, saturacao = da_capa if da_capa else tom_do_app()
    return Cor(matiz, saturacao, brilho_padrao() if brilho is None else brilho)


def cor_para_rgb(cor: Cor) -> tuple[float, float, float]:
    """A cor do módulo como o seletor a mostra (RGB de 0 a 1): cheia, não no brilho da fita (um roxo a 18% apareceria quase preto)."""
    return colorsys.hsv_to_rgb(cor.matiz / 360, cor.saturacao / 1000, 1)


def rgb_para_cor(vermelho: float, verde: float, azul: float, brilho: int) -> Cor:
    matiz, saturacao, _valor = colorsys.rgb_to_hsv(vermelho, verde, azul)
    return Cor(round(matiz * 360) % 360, round(saturacao * 1000), brilho)



# Pontos de dado do controlador RGB, medidos nos módulos: 20 liga/desliga, 21 o modo ("colour" é cor fixa, contra "scene" e "music"), 24 a cor (matiz, saturação e brilho em hex de 4 dígitos).
DP_LIGADA = "20"
DP_MODO = "21"
DP_COR = "24"

# Folgado para uma resposta de milissegundos e curto para a thread não ficar pendurada quando a fita sumiu.
ESPERA = 5


def hsv_hex(cor: Cor) -> str:
    return f"{cor.matiz:04x}{cor.saturacao:04x}{cor.brilho:04x}"


def cor_de_hex(valor: str) -> Optional[Cor]:
    if len(valor) != 12:
        return None
    try:
        return Cor(int(valor[0:4], 16), int(valor[4:8], 16), int(valor[8:12], 16))
    except ValueError:
        return None


def _dispositivo(fita: Fita) -> Any:
    """O objeto da tinytuya para esta fita (trocado nos testes). Importada aqui dentro: só faz falta com fita configurada."""
    import tinytuya  # noqa: PLC0415

    # Sem retentativa: a tinytuya tenta cinco vezes com cinco segundos entre elas, e o fechamento do app é síncrono (uma fita fora da
    # tomada travaria o encerramento por dezenas de segundos). O teto por fita é o ESPERA do soquete.
    #
    # Persistente: abrir custa ~225 ms por comando, mandar pela conexão aberta ~11: é o que faz o brilho acompanhar o dedo no controle.
    modulo = tinytuya.BulbDevice(
        fita.id,
        fita.ip,
        fita.key,
        version=float(fita.versao),
        persist=True,
        connection_retry_limit=1,
        connection_retry_delay=0,
    )
    modulo.set_socketTimeout(ESPERA)
    return modulo


# Intervalo do batimento que mantém as conexões vivas: os módulos derrubam conexão parada em ~30 s.
BATIMENTO = 10

# Falhas seguidas até a fita ser dada como fora do ar (uma pode ser engasgo da rede; três, fita desligada). Suspensa, ela para de custar o ESPERA a cada troca.
FALHAS_PARA_SUSPENDER = 3

# As conexões abertas por id da fita, com o IP em que foram abertas (um endereço novo invalida a velha).
_conexoes: dict[str, tuple[str, Any]] = {}
_falhas: dict[str, int] = {}
_suspensas: set[str] = set()
# Desde quando cada fita suspensa está fora do ar, e quanto ficou na sessão em curso (``fitas_fora_do_ar``).
_suspensa_em: dict[str, float] = {}
_fora_do_ar: dict[str, float] = {}
_fitas_da_sessao: set[str] = set()
_TRAVA_CONEXOES = threading.Lock()


def _agora() -> float:
    return time.monotonic()

# Cada leva de conexões tem um número; o batimento de uma leva morre quando ele muda (fechar tudo desliga o batimento sem esperar a thread acordar).
_geracao = 0
_batimento_vivo = False


# Uma conversa de cada vez com cada módulo (as fitas falam ao mesmo tempo, cada uma com sua trava): o módulo Tuya aceita uma sessão por vez, e dois comandos
# simultâneos para a MESMA fita voltam com erro de endereço em uso. Reentrante porque o fade segura a fita do primeiro degrau ao comando final.
_TRAVAS_FITA: dict[str, threading.RLock] = {}
_TRAVA_DAS_TRAVAS = threading.Lock()


def _trava_da(fita: Fita) -> threading.RLock:
    with _TRAVA_DAS_TRAVAS:
        return _TRAVAS_FITA.setdefault(fita.id, threading.RLock())


def _conexao(fita: Fita) -> tuple[Any, bool]:
    """A conexão aberta desta fita e se ela já existia (abre na primeira vez e quando o IP mudou).

    Falha numa conexão guardada costuma ser soquete morto em silêncio, e vale abrir outra; numa recém-aberta é a fita que não responde, e insistir só dobraria a espera.
    """
    global _batimento_vivo  # noqa: PLW0603

    with _TRAVA_CONEXOES:
        guardada = _conexoes.get(fita.id)
        if guardada is not None and guardada[0] == fita.ip:
            return guardada[1], True

    if guardada is not None:
        _fechar_conexao(guardada[1])
    nova = _dispositivo(fita)
    with _TRAVA_CONEXOES:
        _conexoes[fita.id] = (fita.ip, nova)
        if not _batimento_vivo:
            _batimento_vivo = True
            _em_thread(lambda geracao=_geracao: _bater(geracao))
    return nova, False


def _fechar_conexao(modulo: Any) -> None:
    try:
        modulo.close()
    except Exception:  # fechar uma conexão já morta não é erro de ninguém
        pass


def _esvaziar(modulo: Any) -> None:
    """Joga fora o que chegou no soquete sem ninguém pedir (chamar com a trava da fita).

    A tinytuya lê a resposta mais antiga sem conferir o pedido: uma mensagem sobrando (um aviso de troca feita pelo Smart Life) vira a resposta do comando seguinte e, daí em diante, toda resposta é a do anterior ("Testar" diz que a fita não respondeu); o fechamento sai com a resposta do último comando por ler (o Windows fecha com RST e a fita joga fora o comando).
    """
    soquete = getattr(modulo, "socket", None)
    if soquete is None:
        return
    espera = soquete.gettimeout()
    soquete.settimeout(0)
    try:
        while soquete.recv(4096):
            pass
    except OSError:  # BlockingIOError: acabou o que havia por ler
        pass
    finally:
        soquete.settimeout(espera)


def _descartar(fita: Fita, modulo: Any) -> None:
    """Joga fora esta conexão da fita; a próxima conversa abre outra.

    Chamar com a trava da fita, e só tira do mapa se a guardada ainda for esta: fora dela, o batimento pegaria o objeto no meio do descarte e a tinytuya reabriria um soquete que ninguém fecharia.
    """
    with _TRAVA_CONEXOES:
        guardada = _conexoes.get(fita.id)
        if guardada is not None and guardada[1] is modulo:
            del _conexoes[fita.id]
    _fechar_conexao(modulo)


def _conversar(fita: Fita, acao: Any) -> Optional[Any]:
    """Uma conversa com a fita pela conexão aberta; ``None`` quando falha.

    Conexão guardada que falha é descartada e tentada uma vez com conexão nova (roteador reiniciado, PC que voltou da suspensão). Três falhas seguidas
    suspendem a fita até o "Testar", o fechamento do app ou a próxima abertura.
    """
    if fita.id in _suspensas:
        return None

    # Nunca entregar uma fita sem IP à tinytuya: ela varreria por conta própria, e três varreduras em paralelo disputam a porta de broadcast
    # ("apenas uma utilização de cada endereço de soquete"). Quem acha o IP é a nossa varredura, com trava. Não conta como falha.
    if not fita.ip:
        logging.info("Fita %s ainda sem endereço na rede", fita.nome)
        return None

    for _tentativa in range(2):
        guardada = False
        with _trava_da(fita):
            modulo = None
            try:
                modulo, guardada = _conexao(fita)
                _esvaziar(modulo)
                resposta = acao(modulo)
            except Exception as erro:  # a tinytuya levanta de tudo: socket, struct, json
                resposta = {"Error": str(erro)}
            falhou = isinstance(resposta, dict) and bool(resposta.get("Error"))
            if falhou and modulo is not None:
                _descartar(fita, modulo)

        if not falhou:
            _falhas.pop(fita.id, None)
            return resposta
        if not guardada:
            break

    logging.warning("Fita %s não respondeu: %s", fita.nome, resposta.get("Error"))
    _contar_falha(fita)
    return None


def _contar_falha(fita: Fita) -> None:
    _falhas[fita.id] = _falhas.get(fita.id, 0) + 1
    if _falhas[fita.id] >= FALHAS_PARA_SUSPENDER and fita.id not in _suspensas:
        _suspensas.add(fita.id)
        _suspensa_em[fita.id] = _agora()
        logging.info(
            "Fita %s suspensa depois de %s falhas seguidas", fita.nome, _falhas[fita.id]
        )


def retomar(ids: Optional[set[str]] = None) -> None:
    """Tira fitas da suspensão (sem argumento, todas). Chamado pelo "Testar" e pelo fechamento do app: a fita suspensa no meio do jogo ainda tem um estado de antes para receber."""
    alvo = set(_suspensas) if ids is None else ids & _suspensas
    for identificador in alvo:
        _suspensas.discard(identificador)
        _falhas.pop(identificador, None)
        desde = _suspensa_em.pop(identificador, None)
        if desde is not None:
            _fora_do_ar[identificador] = (
                _fora_do_ar.get(identificador, 0.0) + _agora() - desde
            )


def _bater(geracao: int) -> None:
    global _batimento_vivo  # noqa: PLW0603

    while True:
        time.sleep(BATIMENTO)
        with _TRAVA_CONEXOES:
            if geracao != _geracao or not _conexoes:
                if geracao == _geracao:
                    _batimento_vivo = False
                return
            abertas = list(_conexoes.items())
        for identificador, (_ip, modulo) in abertas:
            trava = _TRAVAS_FITA.get(identificador)
            # Fita numa conversa de verdade não precisa de batimento.
            if trava is None or not trava.acquire(blocking=False):
                continue
            # Uma consulta e não o `heartbeat` da tinytuya: ele não lê a resposta, que sobrava no soquete (`_esvaziar`); a consulta a lê e diz se a fita sumiu.
            try:
                # Reconferido com a trava: a conexão pode ter sido descartada, e usar o objeto fechado faria a tinytuya reabrir um soquete que ninguém fecharia.
                with _TRAVA_CONEXOES:
                    if _conexoes.get(identificador, (None, None))[1] is not modulo:
                        continue
                _esvaziar(modulo)
                resposta = modulo.status()
                if isinstance(resposta, dict) and resposta.get("Error"):
                    raise ConnectionError(resposta["Error"])
            except Exception:  # a tinytuya levanta de tudo
                with _TRAVA_CONEXOES:
                    _conexoes.pop(identificador, None)
                _fechar_conexao(modulo)
            finally:
                trava.release()


def fechar_conexoes() -> None:
    global _geracao, _batimento_vivo  # noqa: PLW0603

    with _TRAVA_CONEXOES:
        abertas = list(_conexoes.values())
        _conexoes.clear()
        _geracao += 1
        _batimento_vivo = False
    for _ip, modulo in abertas:
        _fechar_conexao(modulo)


def ler_estado(fita: Fita) -> Optional[dict[str, Any]]:
    """Se a fita está acesa e em que cor; ``None`` se não responde. Espera a resposta da consulta pelo tipo, não a primeira mensagem: no arranque com órfãos,
    a segunda cópia do último aviso ainda está a caminho, e um aviso só com a cor, lido como estado, faria a fita acesa passar por apagada."""

    def consultar(modulo: Any) -> Any:
        resposta = modulo.status(nowait=True)
        if isinstance(resposta, dict) and resposta.get("Error"):
            return resposta
        dps = _esperar(modulo, lambda cmd, _dps: cmd in RESPOSTAS_DA_CONSULTA)
        return {"Error": "a fita não respondeu à consulta"} if dps is None else {"dps": dps}

    resposta = _conversar(fita, consultar)
    dps = (resposta or {}).get("dps") if isinstance(resposta, dict) else None
    if not isinstance(dps, dict):
        return None
    estado = {
        "ligada": bool(dps.get(DP_LIGADA, False)),
        "cor": str(dps.get(DP_COR, "")),
    }
    _mostrada[fita.id] = (estado["ligada"], estado["cor"])
    return estado


def aplicar(fita: Fita, ligada: bool, cor_hex: str) -> bool:
    """Manda cor e estado para uma fita; nunca levanta e devolve se deu certo.

    Sem cor, só o liga/desliga vai (mandar ``24: ""`` faz o módulo recusar o comando todo). Apagar vai em dois passos, o desliga antes da cor (junto, a fita piscava no brilho de antes); a cor vai depois para ela não guardar o último degrau do fade, a 1%. Acender vai com a cor antes do liga (a fita guarda a última cor e, junto, acenderia no vermelho de ontem antes de obedecer).
    """
    if not cor_hex:
        feito = _mandar(fita, {DP_LIGADA: ligada})
    elif not ligada:
        feito = _mandar(fita, {DP_LIGADA: False}) and _mandar(
            fita, {DP_MODO: "colour", DP_COR: cor_hex}
        )
    else:
        feito = _mandar(fita, {DP_MODO: "colour", DP_COR: cor_hex}) and _mandar(
            fita, {DP_LIGADA: True}
        )

    # Falha no meio: não se sabe o que a fita mostra, e o próximo fade vai direto.
    if feito:
        _mostrada[fita.id] = (ligada, cor_hex or _mostrada.get(fita.id, (False, ""))[1])
    else:
        _mostrada.pop(fita.id, None)
    return feito


def _mandar(fita: Fita, valores: dict[str, Any]) -> bool:
    """Um comando para uma fita; nunca levanta e devolve se deu certo. Confirmado pelo aviso em que a fita diz estar nestes valores, não pela resposta da tinytuya (``_esperar``): fechar a conexão depois não perde nada."""

    def mandar(modulo: Any) -> Any:
        # De vez em quando a fita joga fora um comando, sem aviso (mais após um fade); reenviar pega (medido).
        for _envio in range(ENVIOS):
            resposta = modulo.set_multiple_values(valores, nowait=True)
            if isinstance(resposta, dict) and resposta.get("Error"):
                return resposta
            if _alcancou(modulo, valores, ESPERA_AVISO / ENVIOS):
                return True
        return {"Error": "a fita não avisou que aplicou o comando"}

    return _conversar(fita, mandar) is not None


# A fita não faz fade sozinha (o ponto 28 "gradiente" é aceito e ignorado): o app manda as cores do meio, sem esperar resposta. Medido com as três fitas: a 30
# degraus/s acompanham com meio segundo de atraso constante; a 40 o atraso cresce e jogam degraus fora; a 60 param no meio. O degrau perdido não aparece;
# o fim não pode se perder, por isso vai sempre num comando que espera resposta.
RITMO_FADE = 30
DURACAO_FADE = 2
# O brilho do fade de entrada sobe por esta curva (o andado elevado a ela): o olho nota 1% a 10% e quase nada de 60% a 100%, e em linha reta a fita parecia acesa em meio
# segundo e o fade de entrada parecia mais curto que o de saída (medido). O de saída fica em linha reta: a parte que o olho nota já cai no fim.
CURVA_DA_ENTRADA = 2.2

# O que cada fita mostra agora, por id (acesa e cor em hex): sem isso o fade não tem de onde partir, e ler a fita custaria uma volta de rede a cada play. Fita ausente muda direto.
_mostrada: dict[str, tuple[bool, str]] = {}

# Cada troca pedida para uma fita ganha um número; o fade que o vê mudar para de mandar degraus (outra troca chegou) e a nova parte de onde este parou.
_geracoes: dict[str, int] = {}


def _degraus(origem: Cor, destino: Cor, passos: int) -> list[str]:
    """As cores do caminho, sem a origem e com o destino, em hex.

    O caminho é a mistura das duas cores (duas luzes que se dissolvem), não um giro pela roda: a troca entre o azul (~200°) e o vermelho ou laranja
    passava por roxo, magenta e rosa vivos, as "cores aleatórias" do meio; a mistura passa por um tom de pouca saturação. O brilho vai em linha reta
    (a mistura sozinha escureceria o meio).
    """
    return [cor_hex for _passo, cor_hex in _degraus_no_passo(origem, destino, passos)]


def _degraus_no_passo(
    origem: Cor, destino: Cor, passos: int, curva: float = 1.0
) -> list[tuple[int, str]]:
    """Os degraus de ``_degraus`` com o número do passo (1 a ``passos``), sem repetidos: quem quer a duração inteira agenda cada um pelo passo. ``curva`` entorta só o brilho (``CURVA_DA_ENTRADA``)."""
    de_rgb = colorsys.hsv_to_rgb(origem.matiz / 360, origem.saturacao / 1000, 1)
    para_rgb = colorsys.hsv_to_rgb(destino.matiz / 360, destino.saturacao / 1000, 1)
    caminho = []
    anterior = hsv_hex(origem)
    for passo in range(1, passos + 1):
        andado = passo / passos
        misturada = [a + (b - a) * andado for a, b in zip(de_rgb, para_rgb)]
        matiz, saturacao, _valor = colorsys.rgb_to_hsv(*misturada)
        cor_hex = hsv_hex(
            Cor(
                round(matiz * 360) % 360,
                round(saturacao * 1000),
                round(origem.brilho + (destino.brilho - origem.brilho) * andado**curva),
            )
        )
        # Degrau igual ao anterior não muda a fita, e o fim do fade é reconhecido pelo aviso do último: repetido, o da primeira cópia pareceria o do fim.
        if cor_hex != anterior:
            caminho.append((passo, cor_hex))
            anterior = cor_hex
    return caminho


def _vigente(fita: Fita, geracao: int) -> bool:
    return _geracoes.get(fita.id) == geracao


# Quanto o fade interrompido ainda espera a fita: a espera inteira (ESPERA_AVISO) seguraria o pulso por até 3 s; sem espera, o comando chegaria antes de a fita aplicar os degraus e a confirmação estouraria.
ESPERA_NA_INTERRUPCAO = 0.6

# Códigos de mensagem do protocolo Tuya: o aviso de estado após aplicar um comando (``STATUS`` da tinytuya) e a resposta a uma consulta (``DP_QUERY`` (10) até a 3.3, ``DP_QUERY_NEW`` (16) da 3.4 em diante). Os "recebi" são 7.
AVISO_DE_ESTADO = 8
RESPOSTAS_DA_CONSULTA = (10, 16)

# Quanto esperar pela mensagem certa. Medido a 30 degraus/s com as três fitas: o aviso do último degrau chega até meio segundo após a rajada (uma vez, 1,75 s); um comando solto, em bem menos de um segundo, por isso o comando divide a espera em três envios.
ESPERA_AVISO = 3
ENVIOS = 3


def _esperar(
    modulo: Any, aceita: Any, prazo: float = ESPERA_AVISO
) -> Optional[dict[str, Any]]:
    """Lê o que a fita manda até chegar a mensagem que ``aceita(cmd, dps)`` reconhece e devolve os valores dela; ``None`` fora do prazo.

    Leitura crua e não a da tinytuya, que pega a mensagem mais antiga (a fita manda cada aviso duas vezes, e a segunda cópia virava a resposta do pedido seguinte): o que não é a procurada é pulado.
    """
    soquete = modulo.socket
    espera = soquete.gettimeout()
    limite = time.monotonic() + prazo
    try:
        while (falta := limite - time.monotonic()) > 0:
            soquete.settimeout(falta)
            mensagem = modulo._receive()
            if not mensagem.payload:
                continue
            dps = (modulo._decode_payload(mensagem.payload) or {}).get("dps") or {}
            if aceita(mensagem.cmd, dps):
                return dps
    except Exception:  # prazo do soquete, ou mensagem que não se deixou ler
        pass
    finally:
        soquete.settimeout(espera)
    return None


def _alcancou(
    modulo: Any, valores: dict[str, Any], prazo: float = ESPERA_AVISO
) -> bool:
    """Lê o que a fita manda até ela avisar que está nestes valores.

    Os avisos chegam na ordem dos comandos. O aviso não traz tudo (o modo, 21, nunca vem): vale o que traz algum dos valores e em que todos os que traz batem; a cópia de um comando anterior traz outro valor e é pulada.
    """

    def aceita(cmd: int, dps: dict[str, Any]) -> bool:
        trazidos = [chave for chave in valores if chave in dps]
        return (
            cmd == AVISO_DE_ESTADO
            and bool(trazidos)
            and all(str(dps[chave]).lower() == str(valores[chave]).lower() for chave in trazidos)
        )

    return _esperar(modulo, aceita, prazo) is not None


def _rajada(
    fita: Fita, caminho: list[str], geracao: int, momentos: Optional[list[float]] = None
) -> None:
    """Manda os degraus no ritmo do fade, sem esperar resposta; no fim espera a fita alcançar o último degrau.

    Ela aplica mais devagar do que recebe e avisa aos lotes, até 1 s depois do último (medido): sem a espera o comando final entraria na fila atrás dos degraus e estouraria a própria espera. O marco é o aviso do último degrau (nem o silêncio nem uma consulta servem). Se a fita joga fora o fim da rajada, segue-se: o comando final é reenviado até ser avisado.
    """

    def degraus(modulo: Any) -> Any:
        inicio = time.monotonic()
        ultimo = None
        enviados = 0
        for indice, cor_hex in enumerate(caminho):
            if not _vigente(fita, geracao):
                # Outra troca tomou a vez: só um instante para a fita aplicar o que recebeu (ESPERA_NA_INTERRUPCAO).
                if ultimo is not None:
                    _alcancou(modulo, {DP_COR: ultimo}, ESPERA_NA_INTERRUPCAO)
                logging.info(
                    "Fade de %s interrompido depois de %s de %s degraus",
                    fita.nome, enviados, len(caminho),
                )
                return True
            resposta = modulo.set_multiple_values({DP_COR: cor_hex}, nowait=True)
            if isinstance(resposta, dict) and resposta.get("Error"):
                return resposta
            ultimo = cor_hex
            enviados += 1
            _mostrada[fita.id] = (True, cor_hex)
            momento = momentos[indice] if momentos else (indice + 1) / RITMO_FADE
            falta = inicio + momento - time.monotonic()
            if falta > 0:
                time.sleep(falta)
        confirmou = ultimo is not None and _alcancou(modulo, {DP_COR: ultimo})
        # Uma linha por fita e por fade, para investigar perda de sincronismo: quando começou, terminou e se avisou o último degrau.
        logging.info(
            "Fade de %s: %s degraus em %.1f s, %s",
            fita.nome,
            enviados,
            time.monotonic() - inicio,
            "confirmou" if confirmou else "não confirmou o último degrau",
        )
        return True

    _conversar(fita, degraus)


def _reservar(alvos: list[Fita]) -> dict[str, int]:
    """O número da próxima troca de cada fita, tirado agora: quem pede na thread de UI reserva ali, e a ordem é a dos pedidos, não a de quem calculou a cor primeiro."""
    with _TRAVA_DAS_TRAVAS:
        for fita in alvos:
            _geracoes[fita.id] = _geracoes.get(fita.id, 0) + 1
        return {fita.id: _geracoes[fita.id] for fita in alvos}


def _transitar(
    fita: Fita, ligada: bool, cor_hex: str, geracao: Optional[int] = None
) -> bool:
    """Leva a fita ao estado pedido deslizando e confirma o fim. Síncrona: segura a fita do primeiro degrau ao comando final, para duas trocas não se misturarem.

    Falso se o fim falhou ou se outra troca tomou o lugar. ``geracao`` é o número de ``_reservar``; sem ele, tira agora.
    """
    if geracao is None:
        geracao = _reservar([fita])[fita.id]

    with _trava_da(fita):
        if not _vigente(fita, geracao):
            return False

        passos = round(DURACAO_FADE * RITMO_FADE)
        antes = _mostrada.get(fita.id)
        alvo = cor_de_hex(cor_hex)
        origem = cor_de_hex(antes[1]) if antes is not None and antes[0] else None
        # Acender do escuro é o espelho do apagar: liga já na cor de destino, no brilho mínimo, e só com a fita acesa e confirmada o brilho sobe (a primeira tentativa
        # deixava a fita apagada: os degraus iam com ela ainda desligada). Se o liga no mínimo não pega, nenhum degrau vai, mas a cor final ainda é tentada.
        # Fita de estado desconhecido acende direto.
        if (
            passos
            and ligada
            and antes is not None
            and not antes[0]
            and alvo is not None
            and alvo.brilho > BRILHO_MINIMO
        ):
            inicio = alvo._replace(brilho=BRILHO_MINIMO)
            if aplicar(fita, True, hsv_hex(inicio)) and _vigente(fita, geracao):
                # Cada degrau no momento do passo dele: com a curva os primeiros se repetem e caem fora, e agendar pela posição encurtaria o fade.
                no_passo = _degraus_no_passo(inicio, alvo, passos, CURVA_DA_ENTRADA)
                _rajada(
                    fita,
                    [cor for _passo, cor in no_passo],
                    geracao,
                    [passo / RITMO_FADE for passo, _cor in no_passo],
                )
        elif passos and origem is not None:
            destino = alvo if ligada else origem._replace(brilho=BRILHO_MINIMO)
            if destino is not None and destino != origem:
                _rajada(fita, _degraus(origem, destino, passos), geracao)

        if not _vigente(fita, geracao):
            return False
        return aplicar(fita, ligada, cor_hex)



# A varredura é broadcast e só o assistente a usa, uma vez, para achar o endereço de cada fita (o IP é fixo; se mudar, roda-se o assistente). Doze segundos bastam; o padrão da tinytuya é dezoito.
ESPERA_VARREDURA = 12

# Uma varredura por vez no processo: ela abre um soquete de broadcast numa porta fixa e o Windows não tem `SO_REUSEPORT` (a segunda morre com "apenas uma utilização de cada endereço de soquete").
_TRAVA_VARREDURA = threading.Lock()


def ips_da_varredura(achados: dict[str, Any]) -> dict[str, str]:
    mapa = {}
    for ip, dados in (achados or {}).items():
        identificador = (dados or {}).get("gwId")
        if identificador:
            mapa[str(identificador)] = str(ip)
    return mapa


def versoes_da_varredura(achados: dict[str, Any]) -> dict[str, str]:
    """A versão do protocolo de cada módulo achado, por id: o assistente grava a fita com ela (um módulo 3.4 ou 3.5 falado como 3.3 nunca responde)."""
    mapa = {}
    for dados in (achados or {}).values():
        identificador = (dados or {}).get("gwId")
        versao = (dados or {}).get("version")
        if identificador and versao:
            mapa[str(identificador)] = str(versao)
    return mapa


def enderecos_na_rede() -> tuple[dict[str, str], dict[str, str]]:
    """O endereço e a versão do protocolo de cada módulo Tuya que respondeu na rede, em mapas por id. Sem ``poll=True`` (perguntaria o estado de aparelhos que não são nossos). Nunca levanta; sem rede ou biblioteca, dois mapas vazios."""
    with _TRAVA_VARREDURA:
        try:
            # Dentro do `try`: sem a biblioteca, o `ImportError` derrubaria a thread do assistente e a tela ficaria em "Buscando…" para sempre.
            import tinytuya  # noqa: PLC0415

            achados = tinytuya.deviceScan(False, ESPERA_VARREDURA, poll=False)
            return ips_da_varredura(achados), versoes_da_varredura(achados)
        except Exception as erro:  # a tinytuya levanta de tudo: socket, struct, json
            logging.warning("Varredura das fitas falhou: %s", erro)
            return {}, {}

CHAVE_ESTADO = "fita-estado-anterior"

# Quanto o fechamento pode esperar pela devolução: o custo do conjunto é o da fita mais lenta, uma fita muda (o ESPERA do soquete), e o prazo fica um segundo
# acima disso (com quatro segundos, uma fita fora da tomada fazia o fechamento desistir e as três ficavam com a cor do app). O fade entra na conta. Estourado, o arranque termina o serviço.
PRAZO_FECHAMENTO = ESPERA + DURACAO_FADE + 1

# Um arranque por vez: guardar o estado é "lê a chave, conversa com as fitas, grava a chave" (segundos de rede); sem a trava, dois arranques leriam a chave vazia juntos e o segundo gravaria por cima a cor que o primeiro pintou.
_TRAVA_ARRANQUE = threading.Lock()


def ligada() -> bool:
    return bool(shared.schema.get_boolean("session-fita") and fitas())


def _em_thread(tarefa: Any) -> threading.Thread:
    linha = threading.Thread(target=tarefa, daemon=True)
    linha.start()
    return linha


def _em_paralelo(itens: list[Any], tarefa: Any) -> list[Any]:
    """Roda ``tarefa`` para cada item ao mesmo tempo e espera todas. As fitas têm de mudar juntas: em fila, a troca de cor correria visivelmente de um monitor ao outro, e o custo seria a soma e não o da fita mais lenta.
    Cada fita tem a sua trava, então o paralelo nunca faz duas conversas com o mesmo módulo."""
    if not itens:
        return []

    resultados: dict[int, Any] = {}

    def correr(indice: int, item: Any) -> None:
        resultados[indice] = tarefa(item)

    linhas = [
        threading.Thread(target=correr, args=(indice, item), daemon=True)
        for indice, item in enumerate(itens)
    ]
    for linha in linhas:
        linha.start()
    for linha in linhas:
        linha.join()
    return [resultados.get(indice) for indice in range(len(itens))]


def _vestir(
    cor: Cor,
    alvos: Optional[list[Fita]] = None,
    geracoes: Optional[dict[str, int]] = None,
) -> None:
    """Acende as fitas na cor pedida, ao mesmo tempo e deslizando. Síncrono; nunca levanta.

    Sem ``alvos``, todas as configuradas. ``geracoes`` são os números de ``_reservar`` na hora do pedido; sem eles, cada fita tira o seu. Fita que não responde fica como está e, após três falhas, é suspensa para não atrasar as outras.
    """
    _em_paralelo(
        fitas() if alvos is None else alvos,
        lambda fita: _transitar(
            fita, True, hsv_hex(na_fita(cor, fita)), (geracoes or {}).get(fita.id)
        ),
    )


def _pintar_fita(
    fita: Fita,
    cor: Cor,
    tetos: Optional[dict[str, int]] = None,
    calibracoes: Optional[dict[str, calibracao_mod.Calibracao]] = None,
) -> None:
    cor_hex = hsv_hex(
        na_fita(cor, fita, (tetos or {}).get(fita.id), (calibracoes or {}).get(fita.id))
    )
    if _mandar(fita, {DP_MODO: "colour", DP_COR: cor_hex}) and fita.id in _mostrada:
        _mostrada[fita.id] = (_mostrada[fita.id][0], cor_hex)


# A cor que a prévia ainda deve mostrar em cada fita e as fitas com thread servindo. Arrastar o brilho gera dezenas de valores por segundo, cada um uma conversa de rede: guarda-se só o último e a thread pega o mais recente ao terminar o anterior. Uma thread por fita (uma muda leva segundos para desistir).
# A fita vai junto do pedido, não a da thread, que pintaria com a calibração de antes do Concluir do assistente.
_previa_alvos: dict[
    str, tuple[Fita, Cor, Optional[dict[str, int]], Optional[dict[str, Any]]]
] = {}
_previa_vivas: set[str] = set()
_PREVIA = threading.Lock()


def previa(
    cor: Cor,
    tetos: Optional[dict[str, int]] = None,
    calibracoes: Optional[dict[str, calibracao_mod.Calibracao]] = None,
) -> None:
    """Mostra esta cor nas fitas agora (thread de UI, à vontade). ``tetos`` troca o brilho por dispositivo do arquivo (id → porcentagem) e ``calibracoes`` a calibração em edição."""
    _previa_em({fita.id: cor for fita in fitas()}, tetos, calibracoes)


def previa_calibracao(
    id_da_fita: str, cor: Cor, calibracoes: dict[str, calibracao_mod.Calibracao]
) -> None:
    """A prévia do assistente de calibração (thread de UI): só este dispositivo acende na cor, com a calibração em edição; os outros ficam no brilho mínimo, para não contaminar a comparação. Ninguém é desligado: o liga/desliga é do ciclo do app."""
    apagada = Cor(cor.matiz, 0, BRILHO_MINIMO)
    _previa_em(
        {fita.id: cor if fita.id == id_da_fita else apagada for fita in fitas()},
        None,
        calibracoes,
    )


def _previa_em(
    cores: dict[str, Cor],
    tetos: Optional[dict[str, int]],
    calibracoes: Optional[dict[str, calibracao_mod.Calibracao]],
) -> None:
    if not ligada():
        return
    with _PREVIA:
        for fita in fitas():
            if fita.id not in cores:
                continue
            _previa_alvos[fita.id] = (fita, cores[fita.id], tetos, calibracoes)
            if fita.id not in _previa_vivas:
                _previa_vivas.add(fita.id)
                _em_thread(lambda fita=fita: _servir_previa(fita))


def _servir_previa(fita: Fita) -> None:
    while True:
        with _PREVIA:
            alvo = _previa_alvos.pop(fita.id, None)
            if alvo is None:
                _previa_vivas.discard(fita.id)
                return
        _pintar_fita(*alvo)


def tom_do_app() -> tuple[int, int]:
    return (
        shared.schema.get_int("fita-matiz-app"),
        shared.schema.get_int("fita-saturacao-app"),
    )


def salvar_tom_do_app(matiz: int, saturacao: int) -> None:
    shared.schema.set_int("fita-matiz-app", matiz % 360)
    shared.schema.set_int("fita-saturacao-app", max(0, min(1000, saturacao)))


def redefinir_tom_do_app() -> None:
    """Volta a cor do app ao azul de fábrica."""
    salvar_tom_do_app(*COR_PADRAO_DO_APP)


def migrar_roxo_antigo() -> None:
    """Quem ficou com o roxo de fábrica de antes do Kyron passa ao azul; outra cor não muda."""
    if tom_do_app() == ROXO_ANTIGO:
        salvar_tom_do_app(*COR_PADRAO_DO_APP)


def cor_do_app() -> Cor:
    """A cor das fitas quando não há jogo correndo, no brilho padrão (pública: as Preferências e os detalhes precisam da mesma)."""
    return Cor(*tom_do_app(), brilho_padrao())


def _estado_de(alvos: list[Fita]) -> dict[str, dict[str, Any]]:
    """O estado de cada uma destas fitas, por id; quem não respondeu fica de fora (devolver a um estado chutado seria pior que não devolver)."""
    lidos = _em_paralelo(alvos, ler_estado)
    return {
        fita.id: lido for fita, lido in zip(alvos, lidos) if lido is not None
    }


def _guardar_e_vestir() -> None:
    """Guarda o estado das fitas que ainda não têm um e acende na cor do app as que têm (com a ``_TRAVA_ARRANQUE``).

    Só se lê a fita que falta na chave: relê-la gravaria por cima a cor que o app pintou, e o fechamento devolveria as fitas à cor do app para sempre. Só se pinta a fita que está na chave (uma que não respondeu à leitura ficaria na cor do app sem estado para voltar). Nenhuma lida, nada é gravado: a chave nunca vira ``"{}"``.
    """
    if not ligada():
        return

    configuradas = fitas()
    estados = _estados_guardados()
    novos = _estado_de([fita for fita in configuradas if fita.id not in estados])
    if novos:
        estados.update(novos)
        shared.schema.set_string(CHAVE_ESTADO, json.dumps(estados))

    _vestir(cor_do_app(), [fita for fita in configuradas if fita.id in estados])


def _estados_guardados() -> dict[str, Any]:
    try:
        estados = json.loads(shared.schema.get_string(CHAVE_ESTADO) or "{}")
    except ValueError:
        return {}
    return estados if isinstance(estados, dict) else {}


def _guardadas() -> list[Fita]:
    """As fitas com estado de antes guardado: as únicas que o app pinta, por serem as únicas que o fechamento sabe devolver."""
    estados = _estados_guardados()
    return [fita for fita in fitas() if fita.id in estados]


def _repor(fita: Fita, estado: Any) -> None:
    """Devolve uma fita ao estado guardado, deslizando. Estado que não é dicionário é chave mexida à mão e não pode virar ``AttributeError``."""
    if not isinstance(estado, dict):
        return
    _transitar(fita, bool(estado.get("ligada")), str(estado.get("cor", "")))


def devolver_removidas(removidas: list[Fita]) -> None:
    """Devolve ao estado guardado as fitas que saem da configuração: a desmarcada no assistente some do arquivo, e com ela a única referência para devolvê-la (ficaria na cor do app para sempre). É rede: fora da thread de UI.

    Com a ``_TRAVA_ARRANQUE``: o reacender disparado ao fechar o assistente também lê e grava a chave, e a última gravação apagaria a outra.
    """
    with _TRAVA_ARRANQUE:
        estados = _estados_guardados()
        if not estados:
            return

        saindo = [(fita, estados.pop(fita.id, None)) for fita in removidas]
        _em_paralelo(
            [par for par in saindo if par[1] is not None],
            lambda par: _repor(par[0], par[1]),
        )

        shared.schema.set_string(CHAVE_ESTADO, json.dumps(estados) if estados else "")


def _devolver() -> None:
    if not shared.schema.get_string(CHAVE_ESTADO):
        return

    por_id = {fita.id: fita for fita in fitas()}
    devolver = [
        (por_id[identificador], estado)
        for identificador, estado in _estados_guardados().items()
        if identificador in por_id
    ]
    _em_paralelo(devolver, lambda par: _repor(par[0], par[1]))

    # Limpa mesmo se alguma fita não respondeu: insistir numa fita fora da tomada deixaria o app tentando desfazer em todo arranque.
    shared.schema.set_string(CHAVE_ESTADO, "")


def restaurar_orfaos() -> None:
    """Desfaz a troca que uma execução anterior não desfez. Síncrona (rede): chamar da thread do arranque (``_arrancar``), nunca da de UI."""
    if shared.schema.get_string(CHAVE_ESTADO):
        logging.info("Fitas de uma sessão anterior encontradas; desfazendo")
        _devolver()


def _arrancar() -> None:
    """Os dois passos do arranque, fora da thread de UI. A trava não espera: se alguém a segura, é outra conversa do ciclo em curso (devolução das fitas removidas, reacender)."""
    if not _TRAVA_ARRANQUE.acquire(blocking=False):
        logging.info("Arranque das fitas já em curso; segunda chamada ignorada")
        return
    try:
        restaurar_orfaos()
        if ligada():
            _guardar_e_vestir()
    finally:
        _TRAVA_ARRANQUE.release()


def abrir() -> None:
    """O app abriu: desfaz o que ficou de antes e acende na cor do app (thread de UI). Só para o arranque; com o app aberto quem religa o ciclo chama ``reacender``.

    Os dois passos correm na MESMA thread e nesta ordem: o estado pendurado por uma execução anterior é devolvido antes de guardar o novo, senão a cor do app viraria "o estado de antes".
    """
    # A devolução de órfãos acontece mesmo com o recurso desligado: quem desligou no meio do caminho segue com as fitas vestidas de uma sessão que acabou.
    if not ligada() and not shared.schema.get_string(CHAVE_ESTADO):
        return
    _em_thread(_arrancar)


def _reacender() -> None:
    with _TRAVA_ARRANQUE:
        _guardar_e_vestir()


def reacender() -> None:
    """O ciclo foi religado com o app aberto (interruptor ligado ou assistente fechado; thread de UI).

    Não desfaz órfão (a chave é desta execução, e devolvê-la faria as fitas piscarem no estado de antes): guarda o estado das fitas sem um e veste a cor do app.
    A trava espera aqui, ao contrário do arranque: o reacender junto da devolução das fitas removidas tem trabalho a fazer depois dela.
    """
    if not ligada():
        return
    _em_thread(_reacender)


# O jogo da sessão em curso, para o pulso de conquista saber se ainda há sessão. Só a thread de UI escreve (`comecar`, `voltar`); a do pulso lê antes de cada passo.
_jogo_da_sessao: Optional["Game"] = None


class _TesteDoPulso:
    """Marcador de um teste do pulso: um novo a cada clique em "Testar"."""


# O teste do pulso em vigor, ou None. Como ``_jogo_da_sessao``: só a thread de UI escreve, sob ``_TRAVA_PULSO``.
_teste_do_pulso: Optional[_TesteDoPulso] = None


def comecar(game: "Game") -> None:
    """A sessão começou: veste a cor do jogo (thread de UI). A cor é calculada dentro da thread (tirá-la da capa abre e quantiza uma imagem, o que não pode ocorrer enquanto o jogo abre); a vez de cada fita é tirada aqui, para um "Já terminei" logo depois vencer a cor ainda em cálculo."""
    global _jogo_da_sessao, _teste_do_pulso  # noqa: PLW0603
    alvos = _guardadas() if ligada() else None
    # A sessão e a vez de cada fita mudam juntas, sob a trava do pulso (um pulso que vê a sessão antiga não reserva depois). Um teste do pulso em curso também acaba: a sessão é dona das fitas.
    global _acompanhamento, _cor_ambiente, _teto_da_sessao, _amostras_validas, _amostras_bloqueadas  # noqa: PLW0603
    global _fitas_da_sessao, _candidata, _ultima_troca  # noqa: PLW0603
    with _TRAVA_PULSO:
        _jogo_da_sessao = game
        _teste_do_pulso = None
        _limpar_fila_de_pulsos()
        geracoes = _reservar(alvos) if alvos is not None else {}
        # Um marcador novo por sessão: o acompanhamento de uma sessão acabada (ainda dormindo a fatia) nunca fala pela seguinte, nem do mesmo jogo.
        _acompanhamento = sessao = object()
        # A conta do tempo fora do ar é da sessão: a fita já suspensa começa a contar agora.
        _fora_do_ar.clear()
        _fitas_da_sessao = {fita.id for fita in alvos} if alvos is not None else set()
        for identificador in list(_suspensa_em):
            _suspensa_em[identificador] = _agora()
        _cor_ambiente = _teto_da_sessao = _candidata = _ultima_troca = None
        _amostras_validas = _amostras_bloqueadas = 0
    if alvos is None:
        return
    _em_thread(lambda: _vestir_o_jogo(game, alvos, geracoes, sessao))
    _comecar_vigia(sessao)
    if acompanha_tela() and not escolhida(game.game_id):
        _em_thread(lambda: _acompanhar(sessao))


def _vestir_o_jogo(
    game: "Game", alvos: list[Fita], geracoes: dict[str, int], sessao: object
) -> None:
    global _cor_ambiente, _teto_da_sessao  # noqa: PLW0603
    cor = cor_do_jogo(game)
    with _TRAVA_PULSO:
        if _acompanhamento is sessao:
            _cor_ambiente = cor
            _teto_da_sessao = cor.brilho
    _vestir(cor, alvos, geracoes)


def voltar() -> None:
    """A sessão acabou: de volta à cor do app (thread de UI)."""
    # Antes de tudo: o pulso no meio para no próximo passo e a fila vai fora. A vez de cada fita sai da mesma trava: depois dela nenhum pulso reserva, e a volta nunca é atropelada por um passo dourado.
    alvos = _guardadas() if ligada() else None
    geracoes = _encerrar_pulsos(alvos)
    if alvos is None:
        return
    _em_thread(lambda: _vestir(cor_do_app(), alvos, geracoes or {}))


# A cada quantos segundos a tela é amostrada. A luz acompanha a cena, não a ação (uma explosão não vira clarão). A confirmação (``_decidir``) exige duas amostras seguidas, então este intervalo diz quanto uma cena precisa durar para trocar a luz (com 3 s, uns 3 a 6 s); com 6 s de amostra, confirmação e fade, a cor nova chegava uns 20 s depois. Cada amostra custa ~30 ms de captura.
INTERVALO_DA_TELA = 3

# O fade da troca, o dobro do resto do app: a cor nova chega sem que se perceba quando começou. Medido: 3 s com troca a cada 10 s deram dor de cabeça; 6 s com confirmação deixavam a cor atrasada.
FADE_DA_TELA = 4

# A troca só vale com duas amostras seguidas concordando (``_decidir``) e no máximo uma a cada 15 s: sem isso a luz trocou umas 50 vezes em 12 minutos, pulando entre o vermelho e o azul da mesma cena e seguindo quadros de transição;
# com 30 s, a espera somava atraso à cor nova. Contado da decisão, não do fim do fade.
INTERVALO_MINIMO_ENTRE_TROCAS = 15

# Degraus por segundo do fade da tela, metade dos do resto do app: num fade de 4 s o olho não separa 15/s, e a 30/s a fita perdia o fim da rajada e o comando final a fazia pular até a cor.
RITMO_DA_TELA = 15

# A troca grande de matiz desliza direto, pelo lado curto do círculo, como a pequena: passar pelo escuro chamou mais atenção que o roxo no meio do caminho.

# Saturação mínima da luz: na tela, saturação média já é cor, mas numa fita de LED parece branca (um amarelo forte virou luz branca); com o piso em 60%, vermelho virou rosa (e na fita rosa parece roxo).
# A faixa aceita da tela (0,25 a 1) vai para 850–1000.
SATURACAO_MINIMA_DA_TELA = 850

# O brilho do jogo é o teto, e a cena escura o reduz até 40% dele; luminosidade média a partir de 35% já ganha o teto (uma cena normal fica entre 20% e 40%).
PISO_DO_BRILHO = 0.4
LUZ_PLENA = 0.35

# Quanto a cor nova precisa se afastar da atual para a luz mudar (abaixo disso trocar só chamaria atenção). Matiz em graus, pelo lado curto do círculo; saturação de 0 a 1000.
LIMIAR_MATIZ = 20
LIMIAR_SATURACAO = 250
# O brilho, em fração do teto: abaixo de 15% a fita oscilaria a cada nuvem que passa.
LIMIAR_BRILHO = 0.15

# Quantas amostras bloqueadas, sem nenhuma boa, fazem o aviso do fim da sessão (uma só pode ser a tela preta de carregamento).
BLOQUEADAS_PARA_AVISAR = 2

# O marcador da sessão acompanhada (``comecar``), a cor que as fitas vestem nela e quantas amostras vieram com imagem e quantas bloqueadas. Escritos sob ``_TRAVA_PULSO``.
_acompanhamento: Optional[object] = None
_cor_ambiente: Optional[Cor] = None
_teto_da_sessao: Optional[int] = None
# A troca que a última amostra pediu e espera confirmação, e quando foi a última da sessão (relógio de ``_agora``).
_candidata: Optional[Cor] = None
_ultima_troca: Optional[float] = None
_amostras_validas = 0
_amostras_bloqueadas = 0


def acompanha_tela() -> bool:
    return shared.schema.get_boolean("fita-acompanha-tela")


def _saturacao_da_luz(saturacao: int) -> int:
    """A saturação da tela (250–1000, a faixa aceita como cor) levada à da luz (``SATURACAO_MINIMA_DA_TELA``–1000)."""
    andado = (max(250, min(1000, saturacao)) - 250) / 750
    return round(SATURACAO_MINIMA_DA_TELA + (1000 - SATURACAO_MINIMA_DA_TELA) * andado)


def _brilho_da_cena(luz: float, teto: int) -> int:
    fator = PISO_DO_BRILHO + (1 - PISO_DO_BRILHO) * min(1.0, luz / LUZ_PLENA)
    return max(BRILHO_MINIMO, round(teto * fator))


def _proxima_cor(atual: Cor, amostra: "tela_do_jogo.Amostra", teto: int) -> Optional[Cor]:
    """A cor nova se for diferente de verdade da atual; senão ``None``. Amostra "sem_cor" (cena preta ou cinza) só mexe no brilho; sem a luz da cena, o brilho é o teto."""
    brilho = teto if amostra.luz is None else _brilho_da_cena(amostra.luz, teto)
    if amostra.tipo == "cor" and amostra.cor:
        matiz, saturacao = amostra.cor[0], _saturacao_da_luz(amostra.cor[1])
    elif amostra.tipo == "sem_cor":
        matiz, saturacao = atual.matiz, atual.saturacao
    else:
        return None
    nova = Cor(matiz, saturacao, brilho)
    return nova if _difere(atual, nova, teto) else None


def _difere(uma: Cor, outra: Cor, teto: int) -> bool:
    distancia = abs((outra.matiz - uma.matiz + 180) % 360 - 180)
    return (
        distancia > LIMIAR_MATIZ
        or abs(outra.saturacao - uma.saturacao) > LIMIAR_SATURACAO
        or abs(outra.brilho - uma.brilho) > LIMIAR_BRILHO * teto
    )


def _decidir(pedida: Optional[Cor], teto: int) -> Optional[Cor]:
    """A troca que vale agora, ou ``None`` (com ``_TRAVA_PULSO``). ``pedida`` é a troca desta amostra (``None``: a cena segue com a luz de agora e a candidata vai fora).

    Vale quando a amostra concorda com a candidata da anterior e já passou o intervalo mínimo desde a última; vai para a cor desta amostra, a mais recente.
    """
    global _candidata, _ultima_troca  # noqa: PLW0603
    if pedida is None:
        _candidata = None
        return None
    confirmada = _candidata is not None and not _difere(_candidata, pedida, teto)
    _candidata = pedida
    if not confirmada:
        return None
    if _ultima_troca is not None and _agora() - _ultima_troca < INTERVALO_MINIMO_ENTRE_TROCAS:
        return None
    _candidata = None
    _ultima_troca = _agora()
    return pedida


def _segue(sessao: object) -> bool:
    return _acompanhamento is sessao and acompanha_tela()


def _dormir(segundos: float, continua: Any) -> bool:
    limite = time.monotonic() + segundos
    while True:
        if not continua():
            return False
        falta = limite - time.monotonic()
        if falta <= 0:
            return True
        time.sleep(min(_FATIA, falta))


def _dormir_na_sessao(sessao: object) -> bool:
    """Dorme o intervalo; ``False`` assim que a sessão acaba ou o interruptor desliga."""
    return _dormir(INTERVALO_DA_TELA, lambda: _segue(sessao))


def _acompanhar(sessao: object) -> None:
    """A thread da sessão: amostra a tela a cada intervalo e desliza até a cor nova quando muda de verdade. Nunca levanta.

    A iluminação desligada no meio encerra o acompanhamento, como o pulso. As fitas são relidas a cada amostra (a removida no assistente já foi devolvida e não pode ser pintada); conferido aqui e não em ``_dormir_na_sessao``, pois ``ligada`` lê o arquivo e o sono confere dez vezes por segundo.
    """
    while _dormir_na_sessao(sessao):
        alvos = _guardadas() if ligada() else []
        if not alvos:
            return
        try:
            _uma_amostra(sessao, alvos)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao acompanhar a cor da tela", exc_info=True)


def _uma_amostra(sessao: object, alvos: list[Fita]) -> None:
    global _cor_ambiente, _amostras_validas, _amostras_bloqueadas  # noqa: PLW0603
    amostra = tela_do_jogo.cor_da_tela()
    # A conferência da sessão, a do pulso e a reserva são uma coisa só, sob a trava (o fim da sessão ou uma conquista não cabem entre elas). Com pulso tocando, a amostra fica para a rodada seguinte: uma troca no meio dele seria atropelada.
    with _TRAVA_PULSO:
        if _acompanhamento is not sessao:
            return
        if amostra.tipo in ("cor", "sem_cor"):
            _amostras_validas += 1
        elif amostra.tipo == "bloqueada":
            _amostras_bloqueadas += 1
        pedida = nova = None
        confirmada = False
        if (
            amostra.tipo in ("cor", "sem_cor")
            and _cor_ambiente is not None
            and _teto_da_sessao is not None
            and not _pulsando
        ):
            pedida = _proxima_cor(_cor_ambiente, amostra, _teto_da_sessao)
            confirmada = (
                pedida is not None
                and _candidata is not None
                and not _difere(_candidata, pedida, _teto_da_sessao)
            )
            nova = _decidir(pedida, _teto_da_sessao)
        brilho = None
        if amostra.luz is not None and _teto_da_sessao is not None:
            brilho = _brilho_da_cena(amostra.luz, _teto_da_sessao)
        _registrar(amostra, pedida, nova, _pulsando, brilho, confirmada)
        if nova is None:
            return
        _cor_ambiente = nova
        geracoes = _reservar(alvos)
    _em_paralelo(
        alvos, lambda fita: _deslizar_da_tela(fita, nova, geracoes[fita.id])
    )


def _registrar(
    amostra: "tela_do_jogo.Amostra",
    pedida: Optional[Cor],
    nova: Optional[Cor],
    pulsando: bool,
    brilho: Optional[int],
    confirmada: bool = False,
) -> None:
    """Uma linha por amostra, para calibrar os números acima jogando (o que a tela deu, o que a luz fez e quanto a captura custou)."""
    if amostra.tipo == "ignorada":
        return
    if nova is not None:
        decisao = f"trocou para {nova.matiz}/{nova.saturacao}/{nova.brilho}"
    elif pedida is not None and confirmada:
        decisao = (
            f"confirmada {pedida.matiz}/{pedida.saturacao}/{pedida.brilho}, "
            "aguardando o intervalo"
        )
    elif pedida is not None:
        decisao = f"candidata {pedida.matiz}/{pedida.saturacao}/{pedida.brilho}"
    else:
        decisao = "manteve (pulso)" if pulsando else "manteve"
    logging.info(
        "Tela: %s cor=%s luz=%s brilho=%s, %s (%s ms)",
        amostra.tipo,
        amostra.cor,
        "-" if amostra.luz is None else f"{amostra.luz:.2f}",
        "-" if brilho is None else brilho,
        decisao,
        amostra.ms,
    )


def captura_bloqueada() -> bool:
    """Se a sessão que acabou tentou acompanhar a tela e não viu imagem alguma (tela cheia exclusiva). Zera a contagem: o aviso é um só."""
    global _amostras_validas, _amostras_bloqueadas  # noqa: PLW0603
    with _TRAVA_PULSO:
        bloqueada = _amostras_bloqueadas >= BLOQUEADAS_PARA_AVISAR and _amostras_validas == 0
        _amostras_validas = _amostras_bloqueadas = 0
    return bloqueada




# A cada quantos segundos a fita suspensa é tentada de novo na sessão (a suspensão poupa a espera de uma fita fora da tomada, mas um soluço do Wi-Fi suspendeu uma fita por 40 minutos de jogo). Fora de sessão a suspensão segue.
RETENTATIVA = 15

FORA_DO_AR_PARA_AVISAR = 60


def _comecar_vigia(sessao: object) -> None:
    _em_thread(lambda: _vigiar_fitas(sessao))


def _vigiar_fitas(sessao: object) -> None:
    while _dormir(RETENTATIVA, lambda: _acompanhamento is sessao):
        try:
            if not _retentar_suspensas(sessao):
                return
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao tentar de novo as fitas suspensas", exc_info=True)


def _retentar_suspensas(sessao: object) -> bool:
    """Uma rodada: cada fita suspensa volta à cor ambiente, acesa (a que voltou da tomada pode ter voltado apagada). A que não responder volta à suspensão na hora, sem esperar três falhas, senão cada troca esperaria por ela.
    ``False`` se a sessão acabou ou a iluminação foi desligada. Com pulso tocando, fica para a próxima: a tentativa numa fita muda a seguraria pela espera inteira e o pulso pararia.
    """
    if not ligada():
        return False
    candidatas = [fita for fita in _guardadas() if fita.id in _suspensas]
    with _TRAVA_PULSO:
        if _acompanhamento is not sessao:
            return False
        cor = _cor_ambiente
        if not candidatas or cor is None or _pulsando:
            return True
        geracoes = _reservar(candidatas)
    # O relógio é lido antes: o tempo da tentativa que falhar também foi fora do ar.
    inicio = _agora()
    retomar({fita.id for fita in candidatas})

    def tentar(fita: Fita) -> None:
        if _transitar(fita, True, hsv_hex(na_fita(cor, fita)), geracoes[fita.id]):
            logging.info("Fita %s voltou a responder", fita.nome)
            return
        if not _falhas.get(fita.id) and not _vigente(fita, geracoes[fita.id]):
            # Outra troca tomou a vez e a fita não falhou: fica fora da suspensão (devolvê-la somaria tempo fora do ar que não houve, e daria o aviso falso no fim).
            return
        _suspensas.add(fita.id)
        _suspensa_em[fita.id] = inicio

    _em_paralelo(candidatas, tentar)
    return True


def fitas_fora_do_ar() -> list[str]:
    """Os nomes das fitas que ficaram mais de ``FORA_DO_AR_PARA_AVISAR`` segundos fora do ar na sessão que acabou. Zera a conta: o aviso é um só."""
    agora = _agora()
    total = dict(_fora_do_ar)
    for identificador, desde in list(_suspensa_em.items()):
        total[identificador] = total.get(identificador, 0.0) + agora - desde
        _suspensa_em[identificador] = agora
    _fora_do_ar.clear()
    nomes = {fita.id: fita.nome for fita in fitas()}
    return [
        nomes[identificador]
        for identificador, segundos in total.items()
        if segundos > FORA_DO_AR_PARA_AVISAR
        and identificador in nomes
        and identificador in _fitas_da_sessao
    ]



# A cor de fábrica do pulso: dourado no brilho máximo de cada dispositivo (o teto vale). A escolhida sai de ``cor_do_pulso``.
TOM_DO_OURO = (45, 1000)
OURO = Cor(*TOM_DO_OURO, BRILHO_CHEIO)


class Passo(NamedTuple):
    """Um passo do pulso: a cor (``pulso`` ou ``base``, a de antes), quanto tempo ela segura e em quantos segundos chega deslizando (0 = direto)."""

    alvo: str
    segura: float
    desliza: float = 0.0


_RESPIRAR = [Passo("pulso", 0.4, 0.8), Passo("base", 0.0, 0.8)]
# 0,2 s + 0,2 s: 2,5 piscadas por segundo, abaixo das 3 que as normas de acessibilidade tratam como risco para quem é sensível a luz.
_RAPIDO = [Passo("pulso", 0.2), Passo("base", 0.2)]

# Os passos de cada estilo, por tipo; depois do último, a fita desliza de volta à cor de base.
ESTILOS_DO_PULSO: dict[str, dict[str, list[Passo]]] = {
    "piscar": {
        "normal": [Passo("pulso", 1.5)],
        "rara": [Passo("pulso", 0.6), Passo("base", 0.5), Passo("pulso", 0.6)],
        "completo": [Passo("pulso", 0.5), Passo("base", 0.4)] * 3 + [Passo("pulso", 2.0)],
    },
    "respirar": {
        "normal": _RESPIRAR,
        "rara": _RESPIRAR * 2,
        "completo": _RESPIRAR * 3 + [Passo("pulso", 2.0, 0.8)],
    },
    "rapido": {"normal": _RAPIDO * 4, "rara": _RAPIDO * 8, "completo": _RAPIDO * 16},
    "longo": {
        "normal": [Passo("pulso", 3.0)],
        "rara": [Passo("pulso", 5.0)],
        "completo": [Passo("pulso", 8.0)],
    },
}
ESTILO_PADRAO = "respirar"


def tom_do_pulso() -> tuple[int, int]:
    return (
        shared.schema.get_int("conquistas-pulso-matiz"),
        shared.schema.get_int("conquistas-pulso-saturacao"),
    )


def salvar_tom_do_pulso(matiz: int, saturacao: int) -> None:
    shared.schema.set_int("conquistas-pulso-matiz", matiz % 360)
    shared.schema.set_int("conquistas-pulso-saturacao", max(0, min(1000, saturacao)))


def redefinir_tom_do_pulso() -> None:
    salvar_tom_do_pulso(*TOM_DO_OURO)


def cor_do_pulso() -> Cor:
    return Cor(*tom_do_pulso(), BRILHO_CHEIO)


def estilo_do_pulso() -> str:
    estilo = shared.schema.get_string("conquistas-pulso-estilo")
    return estilo if estilo in ESTILOS_DO_PULSO else ESTILO_PADRAO


FORCA_DOS_PULSOS = ("normal", "rara", "completo")

# Uma thread só serve os pulsos. Uma rajada de conquistas é um pulso só: o pedido durante um pulso é absorvido, menos o "completo" (100%), que espera e toca depois. No máximo UM pedido espera (conquista só o promove ao tipo mais forte, um teste novo toma o lugar da fila).
# Esta trava guarda a sessão, o teste, a fila, o tipo em curso e a vez de cada fita: nenhum passo reserva depois de o dono perder a validade. Dentro dela só entram a conferência, a reserva (``_TRAVA_DAS_TRAVAS``, nunca o contrário) e a fila: nada de rede, nunca com a trava de uma fita.
_TRAVA_PULSO = threading.Lock()
_fila_de_pulsos: list[tuple[object, str]] = []
_pulsando = False
# O tipo e o dono do pulso em curso, ou None. O dono conta na absorção: o pulso de uma sessão acabada (ainda dormindo num passo) não fala pela seguinte.
_tipo_em_curso: Optional[str] = None
_dono_em_curso: object = None
# Quanto o pulso dorme de cada vez num passo: o de uma sessão acabada para logo, em vez de segurar a fila até o fim (8 s no "Brilho longo").
_FATIA = 0.1


def _limpar_fila_de_pulsos() -> None:
    """Nada esperando, nada em curso. Chamar com ``_TRAVA_PULSO``."""
    global _tipo_em_curso, _dono_em_curso  # noqa: PLW0603  # pylint: disable=global-statement
    _fila_de_pulsos.clear()
    _tipo_em_curso = _dono_em_curso = None


def _encerrar_pulsos(alvos: Optional[list[Fita]] = None) -> Optional[dict[str, int]]:
    """A sessão acabou (ou o app vai fechar): o pulso em curso para no próximo passo e a fila vai fora. Com ``alvos``, devolve a vez de cada um, tirada na mesma trava."""
    global _jogo_da_sessao, _teste_do_pulso, _acompanhamento, _cor_ambiente, _teto_da_sessao  # noqa: PLW0603
    global _candidata, _ultima_troca  # noqa: PLW0603
    with _TRAVA_PULSO:
        _jogo_da_sessao = None
        _teste_do_pulso = None
        # Os contadores das amostras ficam: ``captura_bloqueada`` os lê depois.
        _acompanhamento = _cor_ambiente = _teto_da_sessao = _candidata = _ultima_troca = None
        _limpar_fila_de_pulsos()
        return _reservar(alvos) if alvos is not None else None


def _dono_vale(dono: object) -> bool:
    """O pulso deste dono ainda vale? Chamar com ``_TRAVA_PULSO``."""
    if dono is _jogo_da_sessao:
        return dono is not None
    return dono is _teste_do_pulso and _jogo_da_sessao is None


def pulsar_conquista(tipo: str) -> None:
    """Uma conquista saiu: as fitas piscam na cor do pulso e voltam à do jogo (thread de UI). Sem efeito fora de sessão, com o recurso desligado ou com tipo fora de ``FORCA_DOS_PULSOS``; durante um pulso, só o "completo" espera a vez."""
    global _pulsando  # noqa: PLW0603
    jogo = _jogo_da_sessao
    if jogo is None or tipo not in FORCA_DOS_PULSOS or not ligada():
        return
    with _TRAVA_PULSO:
        if not _dono_vale(jogo):
            return
        if _fila_de_pulsos:
            esperando = _fila_de_pulsos[0][1]
            if FORCA_DOS_PULSOS.index(tipo) > FORCA_DOS_PULSOS.index(esperando):
                _fila_de_pulsos[0] = (jogo, tipo)
        elif (
            _pulsando
            and _dono_vale(_dono_em_curso)
            and (tipo != "completo" or _tipo_em_curso == "completo")
        ):
            return  # a mesma rajada: o pulso em curso basta
        else:
            _fila_de_pulsos.append((jogo, tipo))
        if _pulsando:
            return
        _pulsando = True
    _servir_em_thread("Não foi possível iniciar o pulso de conquista")


def _servir_em_thread(mensagem_de_falha: str) -> None:
    """Põe `_servir_pulsos` numa thread (quem chama já marcou `_pulsando`); se não der, desfaz a marca e esvazia a fila, para o próximo pulso tentar de novo."""
    global _pulsando  # noqa: PLW0603
    try:
        _em_thread(_servir_pulsos)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning(mensagem_de_falha, exc_info=True)
        with _TRAVA_PULSO:
            _pulsando = False
            _limpar_fila_de_pulsos()


def _servir_pulsos() -> None:
    global _pulsando, _tipo_em_curso, _dono_em_curso  # noqa: PLW0603
    while True:
        with _TRAVA_PULSO:
            if not _fila_de_pulsos:
                _pulsando = False
                _tipo_em_curso = _dono_em_curso = None
                return
            dono, tipo = _fila_de_pulsos.pop(0)
            _tipo_em_curso, _dono_em_curso = tipo, dono
        try:
            _pulsar(dono, tipo)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha no pulso de conquista", exc_info=True)


def _tingir(fita: Fita, cor: Cor, geracao: int) -> None:
    with _trava_da(fita):
        if not _vigente(fita, geracao):
            return
        cor_hex = hsv_hex(na_fita(cor, fita))
        if _mandar(fita, {DP_MODO: "colour", DP_COR: cor_hex}):
            _mostrada[fita.id] = (True, cor_hex)
        else:
            _mostrada.pop(fita.id, None)


def _deslizar(fita: Fita, cor: Cor, segundos: float, geracao: int) -> None:
    """A cor chegando aos poucos, no ritmo do fade, e o comando direto no fim. Fita sem cor conhecida (``_mostrada``) vai direto."""
    with _trava_da(fita):
        if not _vigente(fita, geracao):
            return
        destino = na_fita(cor, fita)
        antes = _mostrada.get(fita.id)
        origem = cor_de_hex(antes[1]) if antes is not None and antes[0] else None
        passos = round(segundos * RITMO_FADE)
        if passos and origem is not None and origem != destino:
            _rajada(fita, _degraus(origem, destino, passos), geracao)
        _tingir(fita, cor, geracao)


def _rajada_da_tela(fita: Fita, degraus: list[tuple[int, str]], geracao: int) -> None:
    _rajada(
        fita,
        [cor_hex for _passo, cor_hex in degraus],
        geracao,
        [passo / RITMO_DA_TELA for passo, _cor_hex in degraus],
    )


def _deslizar_da_tela(fita: Fita, cor: Cor, geracao: int) -> None:
    """A troca da cor da tela: ``FADE_DA_TELA`` a ``RITMO_DA_TELA``. Cada degrau sai no momento do passo dele, não no ritmo dos que sobraram (25° no mesmo brilho dão uns 25 degraus, e a 15/s o fade de 4 s duraria menos de 2)."""
    with _trava_da(fita):
        if not _vigente(fita, geracao):
            return
        destino = na_fita(cor, fita)
        antes = _mostrada.get(fita.id)
        origem = cor_de_hex(antes[1]) if antes is not None and antes[0] else None
        passos = round(FADE_DA_TELA * RITMO_DA_TELA)
        if passos and origem is not None and origem != destino:
            _rajada_da_tela(fita, _degraus_no_passo(origem, destino, passos), geracao)
        _tingir(fita, cor, geracao)


def _vez_do_pulso(dono: object, alvos: list[Fita]) -> Optional[dict[str, int]]:
    """A vez de cada fita para o próximo passo do pulso, ou ``None`` se a sessão acabou, o teste foi interrompido ou o recurso desligado (o pulso para).

    Conferência do dono e reserva são uma coisa só, sob a trava: senão o fim da sessão caberia entre as duas e o passo dourado, com a vez maior, tomaria o lugar da volta à cor do app.
    """
    if not ligada():
        return None
    with _TRAVA_PULSO:
        if not _dono_vale(dono):
            return None
        return _reservar(alvos)


def _esperar_o_passo(dono: object, segundos: float) -> bool:
    restante = segundos
    while True:
        fatia = min(_FATIA, restante)
        time.sleep(fatia)
        restante -= fatia
        with _TRAVA_PULSO:
            if not _dono_vale(dono):
                return False
        if restante <= 0:
            return True


def _base_do_pulso(dono: object) -> Cor:
    """A cor de antes do pulso: a do app no teste; na sessão, a que a tela deu por último, ou a do jogo."""
    if isinstance(dono, _TesteDoPulso):
        return cor_do_app()
    return _cor_ambiente or cor_do_jogo(dono)


def _pulsar(dono: object, tipo: str) -> None:
    alvos = _guardadas()
    if not alvos:
        return
    cor_base = _base_do_pulso(dono)
    cor_pulso = cor_do_pulso()
    for passo in ESTILOS_DO_PULSO[estilo_do_pulso()][tipo]:
        geracoes = _vez_do_pulso(dono, alvos)
        if geracoes is None:
            return
        cor = cor_pulso if passo.alvo == "pulso" else cor_base
        if passo.desliza > 0:
            _em_paralelo(
                alvos,
                lambda fita, c=cor, s=passo.desliza, g=geracoes: _deslizar(fita, c, s, g[fita.id]),
            )
        else:
            _em_paralelo(alvos, lambda fita, c=cor, g=geracoes: _tingir(fita, c, g[fita.id]))
        if not _esperar_o_passo(dono, passo.segura):
            return
    geracoes = _vez_do_pulso(dono, alvos)
    if geracoes is None:
        return
    _em_paralelo(
        alvos,
        lambda fita: _transitar(fita, True, hsv_hex(na_fita(cor_base, fita)), geracoes[fita.id]),
    )


def testar_pulso() -> None:
    """Toca o pulso normal com a cor e o estilo escolhidos (thread de UI). Numa sessão é o pulso normal do jogo; fora dela, parte da cor do app e volta a ela.
    Um clique novo toma o lugar do teste anterior (que para no próximo passo); uma sessão que começa ou o app fechando o interrompem do mesmo jeito.
    """
    global _teste_do_pulso, _pulsando  # noqa: PLW0603
    if _jogo_da_sessao is not None:
        pulsar_conquista("normal")
        return
    if not ligada():
        return
    with _TRAVA_PULSO:
        if _jogo_da_sessao is not None:
            return
        _teste_do_pulso = dono = _TesteDoPulso()
        _fila_de_pulsos[:] = [(dono, "normal")]
        if _pulsando:
            return
        _pulsando = True
    _servir_em_thread("Não foi possível iniciar o teste do pulso")




def _devolver_no_fechamento() -> None:
    """A devolução do fechamento, na vez dela: espera um arranque ou reacender em curso (junto, o vestir dele e a devolução disputariam cada fita, e se o vestir vencesse a fita ficaria na cor do app com a chave já limpa).
    A espera cabe no prazo do fechamento; estourado, a chave fica para o próximo arranque. As fitas suspensas também são tentadas: é a última chance de devolvê-las antes de a chave ser limpa.
    """
    if not _TRAVA_ARRANQUE.acquire(timeout=PRAZO_FECHAMENTO):
        return
    try:
        retomar()
        _devolver()
    finally:
        _TRAVA_ARRANQUE.release()


def fechar() -> None:
    """O app está fechando: devolve o estado de antes, com hora marcada. Aqui se espera (é a última janela com processo para desfazer), mas não para sempre: estourado o ``PRAZO_FECHAMENTO``, o app sai e o ``restaurar_orfaos`` do próximo arranque termina o serviço."""
    # Antes de devolver: o app fecha sem passar por ``voltar``, e um pulso vivo tiraria uma vez maior que a da devolução e deixaria a fita dourada, com a chave limpa.
    _encerrar_pulsos()
    linha = _em_thread(_devolver_no_fechamento)
    linha.join(PRAZO_FECHAMENTO)
    if linha.is_alive():
        logging.info(
            "Fitas não devolvidas dentro de %ss; fica para o próximo arranque",
            PRAZO_FECHAMENTO,
        )
        # A devolução ainda usa as conexões: fechar agora a derrubaria no meio; o processo está saindo e leva os soquetes.
        return
    fechar_conexoes()


