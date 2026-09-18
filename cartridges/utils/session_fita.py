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

import colorsys
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


# O módulo conta o brilho de 0 a 1000; gente conta de 0 a 100. A conversão mora
# aqui, num lugar só, e as telas falam sempre em porcentagem.
BRILHO_CHEIO = 1000

# O mínimo que ainda acende. Abaixo disto o módulo apaga, e "1%" na tela tem de
# continuar sendo luz.
BRILHO_MINIMO = 10


def por_cento(brilho: int) -> int:
    """O brilho do módulo (0–1000) como a tela mostra (0–100)."""
    return round(brilho * 100 / BRILHO_CHEIO)


def de_por_cento(valor: float) -> int:
    """O caminho de volta, sem deixar a fita pedir um brilho que apaga."""
    return max(BRILHO_MINIMO, min(BRILHO_CHEIO, round(valor * BRILHO_CHEIO / 100)))


def brilho_padrao() -> int:
    return shared.schema.get_int("fita-brilho-padrao")


def cor_do_jogo(game: "Game", ignorar_escolha: bool = False) -> Cor:
    """A cor que este jogo veste: a escolhida, a da capa, ou o roxo do app.

    ``ignorar_escolha`` pula o sidecar e devolve o automático mesmo havendo
    escolha gravada. É o que a tela de detalhes precisa mostrar depois do clique
    em "voltar ao automático": ali a escolha ainda está em disco, e só o Aplicar
    a apaga.
    """
    dados = None if ignorar_escolha else _ler_sidecar(game.game_id)
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


def cor_para_rgba(cor: Cor) -> Any:
    """A cor do módulo como o GTK mostra num seletor.

    O seletor mostra a cor cheia, não a cor no brilho da fita: um roxo a 18%
    aparece quase preto no quadradinho, e ninguém escolhe cor assim.
    """
    from gi.repository import Gdk  # noqa: PLC0415

    vermelho, verde, azul = colorsys.hsv_to_rgb(cor.matiz / 360, cor.saturacao / 1000, 1)
    return Gdk.RGBA(red=vermelho, green=verde, blue=azul, alpha=1.0)


def rgba_para_cor(rgba: Any, brilho: int) -> Cor:
    """O caminho de volta, descartando o brilho que o seletor mostrou."""
    matiz, saturacao, _valor = colorsys.rgb_to_hsv(rgba.red, rgba.green, rgba.blue)
    return Cor(round(matiz * 360) % 360, round(saturacao * 1000), brilho)


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
    #
    # Persistente: a conexão fica aberta enquanto o app vive. Abrir custa uns
    # 225 ms por comando e mandar pela conexão aberta, uns 11 — é a diferença
    # entre o brilho acompanhar o dedo no controle e correr atrás dele.
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


# O intervalo do batimento, que mantém as conexões vivas. Os módulos derrubam
# conexão parada em torno de trinta segundos; dez dá margem de sobra, e menos
# que isso seria só pacote a mais sem ganho nenhum.
BATIMENTO = 10

# Quantas falhas seguidas até a fita ser dada como fora do ar. Uma só pode ser
# engasgo da rede; três é fita desligada da tomada. Suspensa, ela para de custar
# o ESPERA do soquete a cada troca de cor.
FALHAS_PARA_SUSPENDER = 3

# As conexões abertas, por id da fita, com o IP em que foram abertas: se a
# varredura achar a fita num endereço novo, a conexão velha não serve mais.
_conexoes: dict[str, tuple[str, Any]] = {}
_falhas: dict[str, int] = {}
_suspensas: set[str] = set()
_TRAVA_CONEXOES = threading.Lock()

# Cada leva de conexões tem um número. O batimento de uma leva morre sozinho
# quando o número muda — é assim que fechar tudo desliga também o batimento, sem
# precisar esperar a thread acordar.
_geracao = 0
_batimento_vivo = False


# Uma conversa de cada vez com cada módulo, e não uma de cada vez no total: as
# três fitas falam ao mesmo tempo, cada uma com a sua trava. O módulo Tuya
# aceita uma sessão por vez, então dois comandos simultâneos para a MESMA fita
# disputam o soquete e voltam com erro de endereço em uso.
_TRAVAS_FITA: dict[str, threading.Lock] = {}
_TRAVA_DAS_TRAVAS = threading.Lock()


def _trava_da(fita: Fita) -> threading.Lock:
    """A trava daquela fita, criada na primeira vez que alguém fala com ela."""
    with _TRAVA_DAS_TRAVAS:
        return _TRAVAS_FITA.setdefault(fita.id, threading.Lock())


def _conexao(fita: Fita) -> tuple[Any, bool]:
    """A conexão aberta desta fita, e se ela já existia.

    Abre na primeira vez, e de novo quando o IP da fita mudou. Quem chama
    precisa saber se a conexão é nova: falha numa conexão guardada costuma ser
    soquete que morreu em silêncio, e vale abrir outra na hora; falha numa
    conexão recém-aberta é a fita que não responde, e insistir só dobraria a
    espera.
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


def _descartar(fita: Fita) -> None:
    """Joga fora a conexão desta fita; a próxima conversa abre outra."""
    with _TRAVA_CONEXOES:
        guardada = _conexoes.pop(fita.id, None)
    if guardada is not None:
        _fechar_conexao(guardada[1])


def _conversar(fita: Fita, acao: Any) -> Optional[Any]:
    """Uma conversa com a fita pela conexão aberta. ``None`` quando falha.

    Conexão guardada que falha é descartada e tentada de novo uma vez, já com
    uma conexão nova — é o caso do roteador que reiniciou ou do PC que voltou
    da suspensão, e o comando segue de onde parou. Três falhas seguidas
    suspendem a fita até a varredura achá-la, o botão "Testar" pedir, ou o app
    abrir de novo.
    """
    if fita.id in _suspensas:
        return None

    for _tentativa in range(2):
        guardada = False
        try:
            with _trava_da(fita):
                modulo, guardada = _conexao(fita)
                resposta = acao(modulo)
        except Exception as erro:  # a tinytuya levanta de tudo: socket, struct, json
            resposta = {"Error": str(erro)}

        if not (isinstance(resposta, dict) and resposta.get("Error")):
            _falhas.pop(fita.id, None)
            return resposta

        _descartar(fita)
        if not guardada:
            break

    logging.warning("Fita %s não respondeu: %s", fita.nome, resposta.get("Error"))
    _contar_falha(fita)
    return None


def _contar_falha(fita: Fita) -> None:
    _falhas[fita.id] = _falhas.get(fita.id, 0) + 1
    if _falhas[fita.id] >= FALHAS_PARA_SUSPENDER and fita.id not in _suspensas:
        _suspensas.add(fita.id)
        logging.info(
            "Fita %s suspensa depois de %s falhas seguidas", fita.nome, _falhas[fita.id]
        )


def retomar(ids: Optional[set[str]] = None) -> None:
    """Tira fitas da suspensão. Sem argumento, tira todas.

    Chamado pela varredura (com as fitas que ela achou na rede) e pelo botão
    "Testar", onde o usuário pediu para tentar de novo.
    """
    alvo = set(_suspensas) if ids is None else ids & _suspensas
    for identificador in alvo:
        _suspensas.discard(identificador)
        _falhas.pop(identificador, None)


def _bater(geracao: int) -> None:
    """Mantém as conexões vivas enquanto esta leva de conexões existir."""
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
            # Fita ocupada numa conversa de verdade não precisa de batimento: a
            # própria conversa mantém a conexão viva.
            if trava is None or not trava.acquire(blocking=False):
                continue
            try:
                modulo.heartbeat(nowait=True)
            except Exception:
                with _TRAVA_CONEXOES:
                    _conexoes.pop(identificador, None)
                _fechar_conexao(modulo)
            finally:
                trava.release()


def fechar_conexoes() -> None:
    """Fecha todas as conexões e desliga o batimento. Seguro chamar à toa."""
    global _geracao, _batimento_vivo  # noqa: PLW0603

    with _TRAVA_CONEXOES:
        abertas = list(_conexoes.values())
        _conexoes.clear()
        _geracao += 1
        _batimento_vivo = False
    for _ip, modulo in abertas:
        _fechar_conexao(modulo)


def ler_estado(fita: Fita) -> Optional[dict[str, Any]]:
    """Se a fita está acesa e em que cor. ``None`` quando ela não responde."""
    resposta = _conversar(fita, lambda modulo: modulo.status())
    dps = (resposta or {}).get("dps") if isinstance(resposta, dict) else None
    if not isinstance(dps, dict):
        return None
    return {
        "ligada": bool(dps.get(DP_LIGADA, False)),
        "cor": str(dps.get(DP_COR, "")),
    }


def aplicar(fita: Fita, ligada: bool, cor_hex: str) -> bool:
    """Manda cor e estado para uma fita. Nunca levanta; devolve se deu certo.

    Sem cor, só o liga/desliga vai. A fita que estava apagada às vezes não
    reporta o ponto da cor, e o estado guardado dela sai com a cor vazia;
    mandar ``24: ""`` faz o módulo recusar o comando inteiro — e aí a fita não
    apaga, que é justamente o que a devolução do fechamento promete.

    Acender vai em dois passos, a cor antes do liga: a fita guarda a última cor
    que teve, e mandar tudo junto deixa o módulo acender no vermelho de ontem,
    no brilho de ontem, antes de obedecer à cor de agora. A piscada dura um
    piscar de olhos e é justamente o que se vê num quarto escuro.
    """
    if not cor_hex:
        return _mandar(fita, {DP_LIGADA: ligada})
    if not ligada:
        return _mandar(fita, {DP_MODO: "colour", DP_COR: cor_hex, DP_LIGADA: False})
    return _mandar(fita, {DP_MODO: "colour", DP_COR: cor_hex}) and _mandar(
        fita, {DP_LIGADA: True}
    )


def _mandar(fita: Fita, valores: dict[str, Any]) -> bool:
    """Um comando para uma fita. Nunca levanta; devolve se deu certo."""
    return _conversar(fita, lambda modulo: modulo.set_multiple_values(valores)) is not None


# A varredura é broadcast: ela acha a fita mesmo com o IP do arquivo errado, ao
# contrário da conexão, que fala com um endereço só. Doze segundos é o que basta
# para todo mundo responder — o padrão da tinytuya é dezoito. Custa caro e roda
# só depois de alguma fita ter falhado.
ESPERA_VARREDURA = 12

# Piso entre duas varreduras. Uma fita fora da tomada não responde a nenhuma
# quantidade de tentativas, e sem este piso ela custaria doze segundos de
# broadcast a cada jogo aberto e a cada jogo fechado, para sempre. Cinco minutos
# é folgado para o caso que a varredura existe para resolver — o IP que o DHCP
# trocou — e curto perto de uma sessão de jogo.
INTERVALO_VARREDURA = 300

# Quando a última varredura rodou, no relógio monotônico. ``None`` é "nunca".
_ultima_varredura: Optional[float] = None

# Uma varredura de cada vez no processo inteiro. Ela abre um soquete de
# broadcast numa porta fixa, e o Windows não tem `SO_REUSEPORT`: duas ao mesmo
# tempo — o arranque e o botão "Testar", por exemplo — fazem a segunda morrer
# com "apenas uma utilização de cada endereço de soquete". Quem chega depois
# espera, e aí quase sempre nem precisa varrer: o piso de tempo abaixo já
# responde por ela.
_TRAVA_VARREDURA = threading.Lock()


def ips_da_varredura(achados: dict[str, Any]) -> dict[str, str]:
    """O que a varredura encontrou, como um mapa de id do módulo para IP."""
    mapa = {}
    for ip, dados in (achados or {}).items():
        identificador = (dados or {}).get("gwId")
        if identificador:
            mapa[str(identificador)] = str(ip)
    return mapa


def _redescobrir_ips(forcar: bool = False) -> None:
    """Conserta no arquivo os IPs que o DHCP trocou, casando pelo id.

    Sem enquete: ``poll=True`` iria perguntar o estado de cada aparelho achado —
    inclusive dos que não são nossos — e aqui só o endereço interessa.

    Desiste cedo quando a última varredura foi há menos que o
    ``INTERVALO_VARREDURA``. ``forcar`` é só do arranque: a fita que o
    assistente acabou de gravar entra sem IP nenhum, de propósito, e ali a
    varredura é a única maneira de achá-la — mesmo que outra tenha rodado há
    pouco.
    """
    global _ultima_varredura  # noqa: PLW0603

    # O piso é conferido DEPOIS de pegar a trava, e não antes: quem esperou a
    # varredura do outro terminar não tem mais o que varrer, e é esse o caso
    # comum de duas chamadas próximas.
    with _TRAVA_VARREDURA:
        agora = time.monotonic()
        if (
            not forcar
            and _ultima_varredura is not None
            and agora - _ultima_varredura < INTERVALO_VARREDURA
        ):
            logging.info(
                "Varredura das fitas pulada: a última foi há menos de %ss",
                INTERVALO_VARREDURA,
            )
            return
        _ultima_varredura = agora
        _varrer_e_gravar()


def _varrer_e_gravar() -> None:
    """A varredura em si, já com a trava na mão."""

    try:
        import tinytuya  # noqa: PLC0415

        achados = tinytuya.deviceScan(False, ESPERA_VARREDURA, poll=False)
        mapa = ips_da_varredura(achados)
    except Exception as erro:  # a tinytuya levanta de tudo: socket, struct, json
        logging.warning("Varredura das fitas falhou: %s", erro)
        return

    # Fita que respondeu ao broadcast está na tomada: se estava suspensa por
    # falhas, volta a valer.
    retomar(set(mapa))

    atuais = fitas()
    novas = [fita._replace(ip=mapa.get(fita.id, fita.ip)) for fita in atuais]
    if novas != atuais:
        logging.info("IP de fita mudou; arquivo atualizado")
        gravar_fitas(novas)


# endregion
# region Ciclo de vida

CHAVE_ESTADO = "fita-estado-anterior"

# Quanto o fechamento do app pode esperar pela devolução. Com as fitas falando
# ao mesmo tempo, o custo do conjunto é o da mais lenta, e a mais lenta possível
# é uma fita muda: o ESPERA do soquete. O prazo fica um segundo acima disso, e
# não abaixo — com quatro segundos, uma única fita fora da tomada fazia o
# fechamento desistir e as três ficavam com a cor do app até o arranque
# seguinte. Estourado o prazo, quem termina o serviço ainda é o arranque.
PRAZO_FECHAMENTO = ESPERA + 1

# Um arranque de cada vez. Guardar o estado é "lê a chave, conversa com as
# fitas, grava a chave", e o miolo disso leva segundos de rede: sem a trava,
# dois arranques próximos leriam a chave vazia ao mesmo tempo e o segundo
# gravaria por cima o roxo que o primeiro acabou de pintar.
_TRAVA_ARRANQUE = threading.Lock()


def ligada() -> bool:
    """Se há o que fazer: recurso ligado nas Preferências e fita configurada."""
    return bool(shared.schema.get_boolean("session-fita") and fitas())


def _em_thread(tarefa: Any) -> threading.Thread:
    """Toda conversa com as fitas sai da thread de UI por aqui."""
    linha = threading.Thread(target=tarefa, daemon=True)
    linha.start()
    return linha


def _em_paralelo(itens: list[Any], tarefa: Any) -> list[Any]:
    """Roda ``tarefa`` para cada item ao mesmo tempo e espera todas.

    As fitas têm de mudar juntas. Em fila, cada uma só começa depois de a
    anterior ter aberto conexão, mandado o comando e respondido — e a troca de
    cor corre visivelmente de um monitor para o outro, que é exatamente o que a
    imersão não pode ter. Em paralelo, o custo do conjunto é o da fita mais
    lenta, e não a soma delas.

    Cada fita tem a sua trava lá embaixo, então o paralelo aqui nunca faz duas
    conversas com o mesmo módulo.
    """
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


def _vestir(cor: Cor, varrer: bool = True) -> None:
    """Acende todas as fitas na cor pedida. Síncrono; nunca levanta.

    Quem não responde na primeira tentativa costuma ter trocado de IP: uma
    varredura conserta o arquivo e a segunda tentativa usa o endereço novo. A
    varredura roda no máximo uma vez por chamada — fita fora da tomada não
    responde a nenhuma quantidade de tentativas.

    ``varrer=False`` é para quem já varreu nesta mesma rodada: duas varreduras
    a poucos segundos uma da outra, na mesma rede, não acham mais que uma.
    """
    cor_hex = hsv_hex(cor)
    alvos = fitas()
    respostas = _em_paralelo(alvos, lambda fita: aplicar(fita, True, cor_hex))
    mudas = [fita for fita, deu in zip(alvos, respostas) if not deu]
    if not mudas or not varrer:
        return

    _redescobrir_ips()
    por_id = {fita.id: fita for fita in fitas()}
    _em_paralelo(
        [por_id.get(muda.id, muda) for muda in mudas],
        lambda fita: aplicar(fita, True, cor_hex),
    )


def _pintar(cor: Cor) -> None:
    """Só a cor, sem mexer no liga/desliga. Para a prévia ao vivo."""
    cor_hex = hsv_hex(cor)
    _em_paralelo(
        fitas(), lambda fita: _mandar(fita, {DP_MODO: "colour", DP_COR: cor_hex})
    )


# A cor que a prévia ainda deve mostrar, e a thread que a serve. Arrastar o
# controle do brilho gera dezenas de valores por segundo, e cada um deles é uma
# conversa de rede com três fitas: em vez de enfileirar todos, guardamos só o
# último e a thread pega o valor mais recente quando termina o anterior. Os
# passos do meio se perdem, que é exatamente o que se quer — o olho só precisa
# ver onde o controle parou.
_previa_alvo: Optional[Cor] = None
_previa_viva = False
_PREVIA = threading.Condition()


def previa(cor: Cor) -> None:
    """Mostra esta cor nas fitas agora. Chamar da thread de UI, à vontade."""
    global _previa_alvo, _previa_viva  # noqa: PLW0603

    if not ligada():
        return
    with _PREVIA:
        _previa_alvo = cor
        if not _previa_viva:
            _previa_viva = True
            _em_thread(_servir_previa)


def _servir_previa() -> None:
    """Pinta o alvo mais recente até não haver mais nada novo."""
    global _previa_alvo, _previa_viva  # noqa: PLW0603

    while True:
        with _PREVIA:
            cor = _previa_alvo
            _previa_alvo = None
            if cor is None:
                _previa_viva = False
                return
        _pintar(cor)


def roxo() -> Cor:
    """O roxo do app no brilho que o usuário escolheu.

    Pública porque as Preferências e a tela de detalhes precisam da mesma cor:
    enquanto ela era privada, as duas remontavam o ``Cor(*ROXO_DO_APP, …)`` à
    mão e o roxo do app vivia escrito em três lugares.
    """
    return Cor(ROXO_DO_APP[0], ROXO_DO_APP[1], brilho_padrao())


def _estado_de_todas() -> dict[str, dict[str, Any]]:
    """O estado de cada fita configurada, por id.

    Quem não respondeu fica de fora: devolver uma fita ao estado que só foi
    chutado seria pior que não devolver nada.
    """
    alvos = fitas()
    lidos = _em_paralelo(alvos, ler_estado)
    return {
        fita.id: lido for fita, lido in zip(alvos, lidos) if lido is not None
    }


def _guardar_e_vestir() -> None:
    """Guarda o estado de cada fita e acende todas no roxo do app."""
    if not ligada():
        return

    varreu = False
    # Grava só quando a chave está vazia. Chave preenchida quer dizer que uma
    # troca já está em curso, e o estado a devolver é o primeiro — não o roxo
    # que o próprio app acabou de pintar por cima. Vale de verdade porque o
    # `do_activate` dispara outra vez quando uma segunda instância é
    # encaminhada para a viva; sem a guarda, as fitas ficariam roxas para
    # sempre.
    if not shared.schema.get_string(CHAVE_ESTADO):
        estado = _estado_de_todas()
        # Ninguém responder costuma ser endereço velho, e não fita apagada: a
        # que o assistente acabou de gravar entra sem IP nenhum, de propósito,
        # porque é a descoberta por broadcast que acha o endereço dela. Sem
        # esta releitura o estado original se perderia justamente na estreia do
        # recurso — o `_vestir` conserta o arquivo logo abaixo e acende a fita,
        # mas aí já é tarde para saber como ela estava.
        #
        # Só quando NINGUÉM respondeu: uma fita muda entre três é fita fora da
        # tomada, e a varredura custa caro demais para rodar por causa dela.
        #
        # Forçada: é o único caminho em que a varredura não é uma tentativa a
        # mais, e sim a única maneira de saber o estado de antes. O piso entre
        # varreduras não pode calar justamente a estreia do recurso.
        if not estado:
            _redescobrir_ips(forcar=True)
            varreu = True
            estado = _estado_de_todas()
        shared.schema.set_string(CHAVE_ESTADO, json.dumps(estado))

    _vestir(roxo(), varrer=not varreu)


def _estados_guardados() -> dict[str, Any]:
    """A chave lida como dicionário. Chave mexida à mão vira dicionário vazio."""
    try:
        estados = json.loads(shared.schema.get_string(CHAVE_ESTADO) or "{}")
    except ValueError:
        return {}
    return estados if isinstance(estados, dict) else {}


def _repor(fita: Fita, estado: Any) -> None:
    """Devolve uma fita ao estado guardado dela.

    Estado que não é dicionário é chave mexida à mão, e não pode virar
    ``AttributeError`` cru aqui dentro.
    """
    if not isinstance(estado, dict):
        return
    aplicar(fita, bool(estado.get("ligada")), str(estado.get("cor", "")))


def devolver_removidas(removidas: list[Fita]) -> None:
    """Devolve ao estado guardado as fitas que saem da configuração.

    Sem isto, a fita desmarcada no assistente some do arquivo e, com ela, a
    única referência que o fechamento do app tinha para devolvê-la: ela ficaria
    na cor do Cartridges para sempre. É rede — chamar de fora da thread de UI.
    """
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
    """Devolve cada fita ao estado guardado e limpa a chave."""
    if not shared.schema.get_string(CHAVE_ESTADO):
        return

    por_id = {fita.id: fita for fita in fitas()}
    devolver = [
        (por_id[identificador], estado)
        for identificador, estado in _estados_guardados().items()
        if identificador in por_id
    ]
    _em_paralelo(devolver, lambda par: _repor(par[0], par[1]))

    # Limpa mesmo quando alguma fita não respondeu: a chave diz "há uma troca
    # pendente", e insistir eternamente numa fita que saiu da tomada deixaria o
    # app tentando desfazer isso em todo arranque.
    shared.schema.set_string(CHAVE_ESTADO, "")


def restaurar_orfaos() -> None:
    """Desfaz a troca que uma execução anterior não desfez.

    Síncrona: ``_devolver`` conversa com cada fita, e isso é rede. Chamar de
    dentro da thread do arranque (é o que ``_arrancar`` faz), nunca da thread
    de UI — ali seguraria a tela por segundos toda vez que houvesse órfão.
    """
    if shared.schema.get_string(CHAVE_ESTADO):
        logging.info("Fitas de uma sessão anterior encontradas; desfazendo")
        _devolver()


def _arrancar() -> None:
    """Os dois passos do arranque, já fora da thread de UI.

    A trava não espera: um segundo arranque enquanto o primeiro corre não tem
    o que fazer, e esperar só empilharia threads. ``do_activate`` dispara de
    novo quando uma segunda instância do app é encaminhada para esta.
    """
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
    """O app abriu: desfaz o que ficou de antes e acende no roxo.

    Chamar da thread de UI. Os dois passos correm na MESMA thread, e nesta
    ordem: o estado que uma execução anterior deixou pendurado precisa ser
    devolvido antes de guardarmos o estado novo, senão o roxo do próprio app
    viraria "o estado de antes" do usuário.
    """
    # A devolução de órfãos acontece mesmo com o recurso desligado nas
    # Preferências: quem desligou a opção no meio do caminho continua com as
    # fitas vestidas de uma sessão que já acabou.
    if not ligada() and not shared.schema.get_string(CHAVE_ESTADO):
        return
    _em_thread(_arrancar)


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
    _em_thread(lambda: _vestir(roxo()))


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
        # A devolução ainda está usando as conexões: fechar agora a derrubaria
        # no meio. O processo está saindo e leva os soquetes junto.
        return
    fechar_conexoes()


# endregion
