# assistente.py
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

"""O assistente da primeira abertura: pasta dos jogos, capas e o resto do essencial. Cada controle grava na hora."""

import dataclasses
import logging
import threading
import weakref
from functools import partial
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QWindow

from cartridges import conquista_aviso, shared
from cartridges.aplicativo import _animacoes_do_sistema
from cartridges.fita_wizard import FitaWizard
from cartridges.modelos import big_picture
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.modelos.contas import ContasDasLojas
from cartridges.utils import backup, open_uri, session_fita, window_geometry
from cartridges.utils.thread_principal import na_thread_principal

_log = logging.getLogger(__name__)

# A animação da capa (ms): placeholder parado, desliza e some, capa sozinha, capa some e o placeholder volta.
_PARADO = 1000
_DESLIZE = 700
_SOZINHA = 2000
_TROCA = 300
_CICLO = _PARADO + _DESLIZE + _SOZINHA + 2 * _TROCA
_DESLOCAMENTO = 60  # px que o placeholder anda para a esquerda

_DATA = Path(__file__).resolve().parent.parent / "data"
PAGINAS = ("boas_vindas", "jogos", "capas", "conquistas", "iluminacao", "controle", "monitores", "pronto")
# Os interruptores das telas; nenhuma outra chave é gravada pelo `definir`.
_INTERRUPTORES = ("big-picture-ao-conectar", "session-move-window", "session-wallpaper")


def _url(caminho: Path) -> str:
    return QUrl.fromLocalFile(str(caminho)).toString()


def _em_thread(tarefa: Callable[[], None]) -> None:
    """Roda ``tarefa`` fora da interface; os testes trocam por uma chamada direta."""
    threading.Thread(target=tarefa, daemon=True).start()


def precisa_mostrar() -> bool:
    """O assistente deve abrir? Só na primeira abertura; quem já tem jogos (atualização ou backup restaurado) é marcado como concluído."""
    if shared.schema.get_boolean("assistente-concluido"):
        return False
    if shared.games_dir.is_dir() and any(shared.games_dir.iterdir()):
        shared.schema.set_boolean("assistente-concluido", True)
        return False
    return True


def quadro_das_capas(instante: float) -> tuple[float, float, float]:
    """Um quadro do ciclo em ``instante`` (ms): (deslocamento do placeholder, opacidade do placeholder, opacidade da capa)."""
    deslize_fim = _PARADO + _DESLIZE
    sozinha_fim = deslize_fim + _SOZINHA
    x, vazia, capa = 0.0, 1.0, 1.0
    if instante >= sozinha_fim + _TROCA:
        vazia, capa = (instante - sozinha_fim - _TROCA) / _TROCA, 0.0
    elif instante >= sozinha_fim:
        vazia, capa = 0.0, 1 - (instante - sozinha_fim) / _TROCA
        x = -_DESLOCAMENTO
    elif instante >= deslize_fim:
        vazia, x = 0.0, -_DESLOCAMENTO
    elif instante >= _PARADO:
        progresso = (instante - _PARADO) / _DESLIZE
        vazia = 1 - progresso
        x = -_DESLOCAMENTO * (1 - (1 - progresso) ** 3)
    return x, min(1.0, max(0.0, vazia)), min(1.0, max(0.0, capa))


def _preparar_backup(eu: "weakref.ref[Assistente]", caminho: Path) -> None:
    """Na thread: valida e agenda o backup; o resultado volta à principal (``ok``, ``invalido`` ou ``falhou``)."""
    try:
        backup.validar(caminho)
        backup.agendar(caminho)
    except backup.BackupInvalido:
        resultado = "invalido"
    except Exception:  # noqa: BLE001
        logging.exception("Não foi possível agendar a restauração do backup")
        resultado = "falhou"
    else:
        resultado = "ok"
    na_thread_principal(_entregar_backup, eu, resultado)


def _entregar_backup(eu: "weakref.ref[Assistente]", resultado: str) -> None:
    if (assistente := eu()) is not None:
        assistente._backup_preparado(resultado)  # noqa: SLF001


class Assistente(QObject):
    """As regras do assistente; a `JanelaDoAssistente.qml` só desenha. Só na thread principal.

    Saídas, cada uma fecha as contas uma vez: `concluir`, o X (`fecharNoX`, sem marca) e o backup agendado (`ao_restaurar`).
    """

    alterado = Signal()
    animarMudou = Signal()  # noqa: N815
    dialogoPedido = Signal(str, str)  # noqa: N815  # título e corpo de um aviso com "Dispensar"

    def __init__(
        self, ao_terminar: Callable[[], None], ao_restaurar: Callable[[], None], parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._ao_terminar = ao_terminar
        self._ao_restaurar = ao_restaurar
        self._indice = 0
        self._preparando = False
        self._saindo = False
        self._aviso_da_restauracao: int | None = None
        self._janela: QWindow | None = None
        self._config: FitaWizard | None = None
        self._animar = _animacoes_do_sistema()
        self._avisos = FilaDeAvisos(self)
        # O texto do grupo, que as Preferências mostram, a página do assistente já explica: a tela o esconde.
        self._contas = ContasDasLojas(self._avisos, parent=self)
        self._monitores = window_geometry.monitores_da_sessao()
        self._paginas = [p for p in PAGINAS if p != "monitores" or self._monitores]
        self._rotulos: list[str] = []
        self._escolhido = 0
        if self._monitores:
            self._rotulos, self._escolhido = window_geometry.escolha_de_monitor(
                self._monitores, shared.schema.get_string("session-monitor")
            )
            # Gravado já na montagem: nada escolhido ainda, a lista mostra o primeiro, que passa a valer.
            if shared.schema.get_string("session-monitor") != (chave := self._monitores[self._escolhido].key):
                shared.schema.set_string("session-monitor", chave)
        aviso = dataclasses.replace(
            conquista_aviso.Aviso.exemplo(2.3),
            titulo=_("Lenda das ruas"),
            descricao=_("Vença todas as corridas em primeiro lugar."),
        )
        self._cartao = {
            "rotulo": aviso.rotulo,
            "titulo": aviso.titulo,
            "descricao": aviso.descricao,
            "icone": _url(_DATA / "conquista_de_exemplo.svg"),
        }

    paginas = Property("QStringList", lambda self: list(self._paginas), notify=alterado)
    indice = Property(int, lambda self: self._indice, notify=alterado)
    # A primeira e a última telas têm botões próprios; os do rodapé somem.
    rodapeVisivel = Property(bool, lambda self: 0 < self._indice < len(self._paginas) - 1, notify=alterado)  # noqa: N815
    avisos = Property(QObject, lambda self: self._avisos, constant=True)
    contas = Property(QObject, lambda self: self._contas, constant=True)
    configuracaoDasFitas = Property(QObject, lambda self: self._config, notify=alterado)  # noqa: N815
    # Relido a cada troca de tela: o ajuste do Windows pode mudar com a janela aberta.
    animar = Property(bool, lambda self: self._animar, notify=animarMudou)
    cartao = Property("QVariantMap", lambda self: self._cartao, constant=True)
    imagens = Property(
        "QVariantMap",
        lambda _self: {
            "logo": _url(_DATA / "icons" / "hicolor" / "scalable" / "apps" / f"{shared.APP_ID}.svg"),
            "capa": _url(_DATA / "capa_de_exemplo.svg"),
            "vazia": _url(_DATA / "library_placeholder.svg"),
        },
        constant=True,
    )
    ciclo = Property(int, lambda _self: _CICLO, constant=True)
    instanteParado = Property(int, lambda _self: _PARADO + _DESLIZE + _TROCA, constant=True)  # noqa: N815  # a capa, sozinha
    monitores = Property("QStringList", lambda self: self._rotulos, notify=alterado)
    monitorEscolhido = Property(int, lambda self: self._escolhido, notify=alterado)  # noqa: N815
    chaveSgdb = Property(str, lambda _self: shared.schema.get_string("sgdb-key"), notify=alterado)  # noqa: N815
    capasAnimadas = Property(bool, lambda _self: shared.schema.get_boolean("sgdb-animated"), notify=alterado)  # noqa: N815
    chaveSteam = Property(str, lambda _self: shared.schema.get_string("conquistas-chave-steam"), notify=alterado)  # noqa: N815
    bigPictureAoConectar = Property(  # noqa: N815
        bool, lambda _self: shared.schema.get_boolean("big-picture-ao-conectar"), notify=alterado
    )
    moverJanela = Property(bool, lambda _self: shared.schema.get_boolean("session-move-window"), notify=alterado)  # noqa: N815
    papelDeParede = Property(bool, lambda _self: shared.schema.get_boolean("session-wallpaper"), notify=alterado)  # noqa: N815

    @Property(bool, notify=alterado)
    def podeContinuar(self) -> bool:  # noqa: N802
        return self._paginas[self._indice] != "jogos" or bool(shared.schema.get_string("shortcuts-location"))

    @Property(str, notify=alterado)
    def subtituloDaPasta(self) -> str:  # noqa: N802
        # Mesmo formato das Preferências: barras invertidas. A tela mostra em texto puro (um "&" vai como está).
        local = shared.schema.get_string("shortcuts-location")
        return local.replace("/", "\\") if local else _("Nenhuma pasta selecionada")

    preparando = Property(bool, lambda self: self._preparando, notify=alterado)

    def _ir_para(self, indice: int) -> None:
        if 0 <= indice < len(self._paginas) and indice != self._indice:
            # Antes do índice: o `Behavior` do carrossel lê `animar` no instante em que a posição muda.
            animar = _animacoes_do_sistema()
            if animar != self._animar:
                self._animar = animar
                self.animarMudou.emit()
            self._indice = indice
            self.alterado.emit()

    @Slot()
    def avancar(self) -> None:
        self._ir_para(self._indice + 1)

    @Slot()
    def voltar(self) -> None:
        self._ir_para(self._indice - 1)

    def definir_janela(self, janela: QWindow) -> None:
        """A janela do assistente: sem renderizador 3D, a tela do controle (o Big Picture) sai."""
        self._janela = janela
        self._rever_3d()
        sinal = getattr(janela, "sceneGraphInitialized", None)
        if sinal is not None:  # o renderizador só existe depois do primeiro quadro (na thread de render)
            sinal.connect(self._rever_3d, Qt.ConnectionType.QueuedConnection)

    @Slot()
    def _rever_3d(self) -> None:
        janela = self._janela
        if janela is None or janela.rendererInterface() is None or "controle" not in self._paginas:
            return
        if big_picture.tem_3d(janela):
            return
        atual = self._paginas[self._indice]
        self._paginas.remove("controle")
        self._indice = self._paginas.index(atual) if atual in self._paginas else min(self._indice, len(self._paginas) - 1)
        self.alterado.emit()

    def _sair(self) -> None:
        """Uma vez só, em qualquer das três saídas: um login pendente não fica preso a uma janela que sai."""
        self._saindo = True
        self._contas.fechar()

    @Slot()
    def concluir(self) -> None:
        """Fecha o assistente de vez ("Pular configuração" e "Abrir a biblioteca"); quem fecha a janela é o `ao_terminar`."""
        # Um segundo clique não abre a biblioteca duas vezes; com o backup sendo preparado, quem sai é a restauração.
        if self._saindo or self._preparando:
            return
        shared.schema.set_boolean("assistente-concluido", True)
        self._sair()
        self._ao_terminar()

    @Slot(result=bool)
    def fecharNoX(self) -> bool:  # noqa: N802
        """O X cancela os logins em andamento; a marca não é gravada. ``False`` recusa o fechamento."""
        if self._saindo:
            return True
        # Com o backup sendo preparado, fechar deixaria a cópia pela metade ou a restauração agendada sem a janela.
        if self._preparando:
            return False
        self._sair()
        return True

    @Slot(QUrl)
    def restaurarBackup(self, url: QUrl) -> None:  # noqa: N802
        """Valida e agenda o backup numa thread; sem confirmação, pois não há nada a perder.

        Os botões da tela 0 ficam inativos (`preparando`): um segundo clique restauraria duas vezes.
        """
        if self._preparando or self._saindo or url.isEmpty() or not url.toLocalFile():
            return
        self._preparando = True
        # "Aguarde" porque o X também fica sem efeito até terminar (`fecharNoX`); sai em todos os ramos.
        self._aviso_da_restauracao = self._avisos.adicionar(_("Preparando a restauração. Aguarde…"), segundos=0)
        self.alterado.emit()
        _em_thread(partial(_preparar_backup, weakref.ref(self), Path(url.toLocalFile())))

    def _backup_preparado(self, resultado: str) -> None:
        self._preparando = False
        if self._aviso_da_restauracao is not None:
            self._avisos.dispensar(self._aviso_da_restauracao)
            self._aviso_da_restauracao = None
        self.alterado.emit()
        if resultado == "ok":
            if self._saindo:  # já saiu por outra via: a restauração não abre a biblioteca de novo
                return
            shared.schema.set_boolean("assistente-concluido", True)
            self._sair()
            self._ao_restaurar()
        elif resultado == "invalido":
            self.dialogoPedido.emit(_("Backup inválido"), _("O arquivo não é um backup válido do Kyron."))
        else:
            self.dialogoPedido.emit(
                _("Não foi possível restaurar"), _("Não foi possível restaurar o backup. Tente novamente.")
            )

    @Slot(QUrl)
    def escolherPasta(self, url: QUrl) -> None:  # noqa: N802
        if url.isEmpty() or not url.toLocalFile():
            return
        shared.schema.set_string("shortcuts-location", str(Path(url.toLocalFile())))
        # Sem a importação ligada a pasta escolhida não traria nenhum jogo.
        shared.schema.set_boolean("auto-import", True)
        self.alterado.emit()

    @Slot(str)
    def definirChaveSgdb(self, texto: str) -> None:  # noqa: N802
        chave = texto.strip()
        shared.schema.set_string("sgdb-key", chave)
        shared.schema.set_boolean("sgdb", bool(chave))
        self.alterado.emit()

    @Slot(bool)
    def definirCapasAnimadas(self, ligado: bool) -> None:  # noqa: N802
        # Uma sem a outra não tem efeito visível.
        shared.schema.set_boolean("sgdb-animated", ligado)
        shared.schema.set_boolean("cover-autoplay", ligado)
        self.alterado.emit()

    @Slot(str)
    def definirChaveSteam(self, texto: str) -> None:  # noqa: N802
        shared.schema.set_string("conquistas-chave-steam", texto.strip())
        self.alterado.emit()

    @Slot(str)
    def abrirEndereco(self, url: str) -> None:  # noqa: N802
        """Os links "Obtenha aqui" (texto nosso); só http/https chega ao navegador."""
        open_uri.abrir_url(url)

    @Slot(str, bool)
    def definir(self, chave: str, valor: bool) -> None:
        if chave not in _INTERRUPTORES:
            _log.warning("Preferência fora da lista do assistente recusada: %r", chave)
            return
        shared.schema.set_boolean(chave, bool(valor))
        self.alterado.emit()

    @Slot(int)
    def escolherMonitor(self, indice: int) -> None:  # noqa: N802
        if 0 <= indice < len(self._monitores):
            self._escolhido = indice
            shared.schema.set_string("session-monitor", self._monitores[indice].key)
            self.alterado.emit()

    @Slot()
    def identificarMonitores(self) -> None:  # noqa: N802
        window_geometry.identificar_monitores()

    @Slot()
    def configurarIluminacao(self) -> None:  # noqa: N802
        if self._config is not None or self._saindo:
            return
        self._config = FitaWizard(self)
        self._config.fechado.connect(self._config_fechou)
        self.alterado.emit()

    def _config_fechou(self) -> None:
        config, self._config = self._config, None
        if config is not None:
            config.deleteLater()  # filho daqui: o QML ainda pode estar no clique que o fechou
        # Sem isso nada acenderia: o recurso nasce desligado. Só grava: as fitas acendem com a biblioteca aberta.
        if session_fita.fitas():
            shared.schema.set_boolean("session-fita", True)
        self.alterado.emit()

    @Slot(float, result="QVariantList")
    def quadro(self, instante: float) -> list[Any]:
        return list(quadro_das_capas(instante))
