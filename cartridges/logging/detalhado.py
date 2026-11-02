# detalhado.py
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

"""Log detalhado: grava no log toda chamada de função do pacote ``cartridges``.

Usa ``sys.monitoring`` (PEP 669). Cada entrada, saída (com o valor devolvido e
o tempo) e exceção vira uma linha DEBUG do logger ``cartridges.rastreio``, com
a profundidade da chamada. Nenhum valor é filtrado: o log pode conter dados
sensíveis, por decisão do usuário.

Telas do QML: o Qt não avisa a criação de um item, só o ``ChildAdded`` do pai, e
tocar no filho nesse instante quebra o wrapper do PySide. Por isso o filtro só
liga os sinais quando varre a árvore já pronta: ao mostrar uma janela
(``Show``), ao carregar um ``Loader`` e ao trocar a página de uma ``StackView``.
Nessa varredura, todo item de tipo QML do app ganha o ``visibleChanged``, e a
tela que só alterna ``visible`` vira "apareceu"/"sumiu".

Limites conhecidos: um item criado depois da varredura e que não passa por um
``Loader`` nem pela ``StackView`` (por exemplo, o delegate de uma lista, ou um
``Component.createObject`` solto) não é vigiado; e um ``Popup`` só é ligado
quando recebe um filho ou quando a varredura o encontra.
"""

import logging
import os
import sys
import threading
import time

from PySide6.QtCore import SIGNAL, QEvent, QObject, QTimer
from PySide6.QtQuick import QQuickItem, QQuickWindow

# Liga o log detalhado por padrão. A variável de ambiente CARTRIDGES_LOG_DETALHADO
# ("1" ou "0") vence esta constante.
ATIVO = True

_VARIAVEL = "CARTRIDGES_LOG_DETALHADO"
_LIMITE = 500

_log = logging.getLogger("cartridges.rastreio")
_mon = sys.monitoring
_EV = _mon.events
_FERRAMENTA = _mon.PROFILER_ID

# Por thread: a pilha de horários de início e a trava de reentrada.
_estado = threading.local()


def ativo() -> bool:
    """Diz se o rastreio deve ser ligado: a variável de ambiente vence ``ATIVO``."""
    valor = os.environ.get(_VARIAVEL)
    if valor == "1":
        return True
    if valor == "0":
        return False
    return ATIVO


def _e_do_app(code, frame) -> bool:  # type: ignore
    """Se o código pertence ao app (e não ao próprio rastreio nem a terceiros).

    Usa o ``__name__`` dos globais, e não ``co_filename``, que muda no app
    instalado a partir de ``.pyc``.
    """
    # Sem cache por `code`: ele compara por valor, e funções idênticas de um
    # módulo de terceiros e do app colidiriam.
    nome = frame.f_globals.get("__name__", "")
    return nome.startswith("cartridges.") and not nome.startswith("cartridges.logging")


def _valor(obj) -> str:  # type: ignore
    """O ``repr`` do valor, cortado; ele já escapa a quebra de linha."""
    try:
        texto = repr(obj)
    except Exception:  # pylint: disable=broad-exception-caught
        return "<repr falhou>"
    if len(texto) > _LIMITE:
        return texto[:_LIMITE] + f"...<cortado, {len(texto)} caracteres>"
    return texto


def _argumentos(code, frame) -> str:  # type: ignore
    """Os parâmetros da função com os valores recebidos, como ``a=1, b=2``."""
    quantos = code.co_argcount + code.co_kwonlyargcount
    if code.co_flags & 0x04:  # *args
        quantos += 1
    if code.co_flags & 0x08:  # **kwargs
        quantos += 1
    locais = frame.f_locals
    return ", ".join(f"{n}={_valor(locais[n])}" for n in code.co_varnames[:quantos] if n in locais)


def _pilha():  # type: ignore
    if not hasattr(_estado, "pilha"):
        _estado.pilha = []
        _estado.trava = False
    return _estado.pilha


def _rotulo(code, frame) -> str:  # type: ignore
    return f"{frame.f_globals.get('__name__', '?')}.{code.co_qualname}"


def _evento(empilha: bool, desempilha: bool, texto, desliga: bool = False):  # type: ignore
    """Monta o callback de um evento.

    ``texto(code, frame, profundidade, duracao, extra)`` devolve a linha, ou
    ``None`` para só mexer na pilha. Todo callback engole qualquer falha: o
    rastreio nunca levanta dentro do código rastreado. ``desliga`` marca os
    eventos que aceitam ``DISABLE`` para o código de terceiros.
    """

    def callback(code, _offset, *extra):  # type: ignore
        try:
            pilha = _pilha()
            if _estado.trava:
                return None
            frame = sys._getframe(1)  # pylint: disable=protected-access
            if not _e_do_app(code, frame):
                return _mon.DISABLE if desliga else None
            _estado.trava = True
            try:
                duracao = 0.0
                if empilha:
                    pilha.append(time.perf_counter())
                profundidade = len(pilha)
                if desempilha and pilha:
                    duracao = (time.perf_counter() - pilha.pop()) * 1000
                if texto is not None and _log.isEnabledFor(logging.DEBUG):
                    _log.debug(texto(code, frame, profundidade, duracao, extra))
            finally:
                _estado.trava = False
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        return None

    return callback


def _entrada(code, frame, profundidade, _duracao, _extra):  # type: ignore
    return "%d > %s(%s)" % (profundidade, _rotulo(code, frame), _argumentos(code, frame))


def _retomada(code, frame, profundidade, _duracao, _extra):  # type: ignore
    return "%d > %s(retomado)" % (profundidade, _rotulo(code, frame))


def _saida(code, frame, profundidade, duracao, extra):  # type: ignore
    return "%d < %s = %s (%.1f ms)" % (profundidade, _rotulo(code, frame), _valor(extra[0]), duracao)


def _levantou(code, frame, profundidade, _duracao, extra):  # type: ignore
    return "%d ! %s levantou %s" % (profundidade, _rotulo(code, frame), _valor(extra[0]))


# Sem DISABLE em RAISE/PY_UNWIND/PY_THROW: eles não aceitam. PY_THROW (um
# gerador abandonado recebendo `close()`) empilha, para o PY_UNWIND seguinte
# não desempilhar a chamada de outra função.
_CALLBACKS = {
    _EV.PY_START: _evento(True, False, _entrada, True),
    _EV.PY_RESUME: _evento(True, False, _retomada, True),
    _EV.PY_THROW: _evento(True, False, _retomada),
    _EV.PY_RETURN: _evento(False, True, _saida, True),
    _EV.PY_YIELD: _evento(False, True, _saida, True),
    _EV.RAISE: _evento(False, False, _levantou),
    _EV.PY_UNWIND: _evento(False, True, None),
}
_instalado = False


def instalar_rastreio() -> None:
    """Liga o rastreio em todas as threads. Não faz nada se já estiver ligado."""
    global _instalado  # pylint: disable=global-statement
    if _instalado:
        return
    _mon.use_tool_id(_FERRAMENTA, "cartridges-rastreio")
    _instalado = True
    for evento, callback in _CALLBACKS.items():
        _mon.register_callback(_FERRAMENTA, evento, callback)
    _mon.set_events(_FERRAMENTA, sum(_CALLBACKS))
    _mon.restart_events()


def remover_rastreio() -> None:
    """Desliga o rastreio e devolve a ferramenta do ``sys.monitoring``."""
    global _instalado  # pylint: disable=global-statement
    if not _instalado:
        return
    _mon.set_events(_FERRAMENTA, 0)
    for evento in _CALLBACKS:
        _mon.register_callback(_FERRAMENTA, evento, None)
    _mon.free_tool_id(_FERRAMENTA)
    _instalado = False


# --- Eventos do Qt --------------------------------------------------------------

_log_ui = logging.getLogger("cartridges.interface")
_ET = QEvent.Type
_EVENTOS_DA_INTERFACE = {
    _ET.MouseButtonPress: "clique",
    _ET.MouseButtonRelease: "soltou o clique",
    _ET.MouseButtonDblClick: "clique duplo",
    _ET.KeyPress: "tecla",
    _ET.Wheel: "roda do mouse",
    _ET.Show: "mostrou",
    _ET.Hide: "escondeu",
    _ET.Close: "fechou",
}


def _nome(objeto) -> str:  # type: ignore
    """O nome da classe sem o sufixo ``_QMLTYPE_n`` que o QML acrescenta aos tipos do app."""
    return objeto.metaObject().className().split("_QML")[0]


def _quem(objeto) -> str:  # type: ignore
    """Identifica o alvo: classe, nome, texto (se houver) e a tela que o contém.

    Ex.: ``BotaoDoDialogo('botaoCancelar') texto='Cancelar' dentro de Dialogo('confirmacao')``.
    """
    texto = f"{_nome(objeto)}({objeto.objectName()!r})"
    rotulo = objeto.property("text")
    if isinstance(rotulo, str) and rotulo:
        texto += f" texto={rotulo[:60]!r}"
    if isinstance(objeto, QQuickItem):
        pai = objeto.parentItem()
        while pai is not None:
            if pai.objectName() or "_QMLTYPE_" in pai.metaObject().className():
                return texto + f" dentro de {_nome(pai)}({pai.objectName()!r})"
            pai = pai.parentItem()
    return texto


def _detalhe(evento) -> str:  # type: ignore
    tipo = evento.type()
    if tipo in (_ET.MouseButtonPress, _ET.MouseButtonRelease, _ET.MouseButtonDblClick):
        return f" botao={evento.button().name}"
    if tipo == _ET.KeyPress:
        return f" tecla={evento.key()} texto={evento.text()!r}"
    return ""


class FiltroDeEventos(QObject):
    """Filtro de eventos do app: grava cliques, teclas, janelas e telas do QML.

    Nunca consome o evento (devolve sempre ``False``) e nunca levanta.
    """

    def eventFilter(self, destino, evento):  # type: ignore  # pylint: disable=invalid-name
        try:
            tipo = evento.type()
            if (nome := _EVENTOS_DA_INTERFACE.get(tipo)) is not None:
                _log_ui.debug("%s em %s%s", nome, _quem(destino), _detalhe(evento))
            elif tipo == _ET.ChildAdded:
                _ligar_tela(destino)  # nunca toca no filho: ele ainda está no construtor da base
            if tipo == _ET.Show and isinstance(destino, QQuickWindow):
                _varrer(destino.contentItem())
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        return False


def _ligar_tela(alvo) -> None:  # type: ignore
    """Liga os sinais de um popup ou loader do QML, quando ele recebe um filho.

    O Qt não avisa a criação do Popup ou Loader em si, só a dos filhos dele
    (ChildAdded no pai). O filho nunca é tocado nem guardado: no ChildAdded ele
    ainda está no construtor da base, e segurar o ponteiro faz o PySide
    registrar um wrapper errado para ele.
    """
    if alvo.property("_logLigado"):
        return
    if alvo.inherits("QQuickPopup"):
        alvo.setProperty("_logLigado", True)
        alvo.connect(SIGNAL("opened()"), lambda: _tentar(lambda: _log_ui.debug("popup aberto: %s", _quem(alvo))))
        alvo.connect(SIGNAL("closed()"), lambda: _tentar(lambda: _log_ui.debug("popup fechado: %s", _quem(alvo))))
    elif alvo.inherits("QQuickLoader"):
        alvo.setProperty("_logLigado", True)
        alvo.connect(SIGNAL("loaded()"), lambda: _tentar(lambda: _tela_carregada(alvo)))
    elif alvo.inherits("QQuickStackView"):
        alvo.setProperty("_logLigado", True)
        alvo.connect(SIGNAL("currentItemChanged()"), lambda: _tentar(lambda: _pilha_mudou(alvo)))


def _tela_carregada(loader) -> None:  # type: ignore
    origem = loader.property("source")
    item = loader.property("item")
    # Com `sourceComponent` a origem é vazia e não diz nada: nomeia-se o item carregado.
    destino = f" source={origem.toString()!r}" if origem is not None and not origem.isEmpty() else ""
    if item is not None:
        destino += f" item={_quem(item)}"
    _log_ui.debug("tela carregada: %s%s", _quem(loader), destino)
    if item is not None:
        _varrer(item)


# Itens cuja visibilidade mudou desde o último despejo (o despejo roda no próximo ciclo do laço de eventos).
_mudancas: list = []


def _visibilidade_mudou(item) -> None:  # type: ignore
    """Junta as mudanças do ciclo: esconder um pai dispara o sinal em todos os descendentes."""
    if not _mudancas:
        QTimer.singleShot(0, lambda: _tentar(_despejar))
    _mudancas.append(item)


def _despejar() -> None:
    itens = _mudancas[:]
    _mudancas.clear()
    for item in itens:
        try:
            pai = item.parentItem()
            while pai is not None and pai not in itens:
                pai = pai.parentItem()
            if pai is None:  # só a raiz da mudança: os descendentes vão junto
                _log_ui.debug("%s: %s", "apareceu" if item.isVisible() else "sumiu", _quem(item))
        except Exception:  # pylint: disable=broad-exception-caught
            pass


def _pilha_mudou(pilha) -> None:  # type: ignore
    atual = pilha.property("currentItem")
    _log_ui.debug("tela na pilha: %s", _quem(atual) if atual is not None else "(vazia)")
    if atual is not None:
        _varrer(atual)


def _varrer(raiz) -> None:  # type: ignore
    """Liga o rastreio de visibilidade em tudo o que está sob ``raiz``, uma vez só por item.

    Roda sobre a árvore já construída (nunca no ``ChildAdded``). Cada item
    entra numa guarda por propriedade dinâmica, para não ligar duas vezes.
    """
    pendentes = [raiz]
    while pendentes:
        item = pendentes.pop()
        try:
            pendentes.extend(item.childItems())
            for filho in item.children():
                if filho.inherits("QQuickPopup"):
                    _ligar_tela(filho)
            _ligar_tela(item)
            if "_QMLTYPE_" in item.metaObject().className() and not item.property("_logVisivel"):
                item.setProperty("_logVisivel", True)
                item.visibleChanged.connect(lambda i=item: _tentar(lambda: _visibilidade_mudou(i)))
        except Exception:  # pylint: disable=broad-exception-caught
            pass


def _tentar(funcao) -> None:  # type: ignore
    try:
        funcao()
    except Exception:  # pylint: disable=broad-exception-caught
        pass


def instalar_filtro(app):  # type: ignore
    """Instala o filtro no ``app``; devolve ``None`` com o modo desligado."""
    if not ativo():
        return None
    filtro = FiltroDeEventos(app)
    app.installEventFilter(filtro)
    return filtro
