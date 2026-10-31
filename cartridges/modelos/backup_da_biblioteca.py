# backup_da_biblioteca.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O backup da biblioteca e a Zona de perigo das Preferências (D80), sem tela.

Exportar, importar, a pasta dos saves, "Restaurar saves de todos os jogos" e o Redefinir. O trabalho pesado roda em
threads e volta por `na_thread_principal` com referência fraca a este objeto: um resultado que chega depois de ele
ser coletado é descartado. As perguntas e os diálogos vão pelo `Aplicativo` (D72), o reinício por `pedir_reinicio`
(D75). Só na thread principal.
"""

import logging
import threading
import weakref
from datetime import date
from pathlib import Path
from typing import Any

import shiboken6
from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from cartridges import shared
from cartridges.saves import backup_de_saves, pasta
from cartridges.utils import backup, redefinir
from cartridges.utils.thread_principal import na_thread_principal

_log = logging.getLogger(__name__)


def _caminho(url: QUrl) -> Path | None:
    """O arquivo ou a pasta do seletor; uma escolha vazia (diálogo cancelado) é ``None``."""
    return Path(url.toLocalFile()) if not url.isEmpty() and url.toLocalFile() else None


def _aplicativo() -> Any:
    return getattr(shared, "aplicativo", None)


def _dialogo(titulo: str, corpo: str) -> None:
    aplicativo = _aplicativo()
    if aplicativo is None:
        _log.warning("%s: %s", titulo, corpo)
        return
    aplicativo.pedir_dialogo(titulo, corpo, [], lambda: None)


def _perguntar(titulo: str, corpo: str, rotulo: str, ao_confirmar: Any) -> None:
    """A confirmação destrutiva (D72); ``ao_confirmar()`` só se a pessoa confirmou."""
    aplicativo = _aplicativo()
    if aplicativo is None:
        _log.warning("%s: %s", titulo, corpo)
        return
    aplicativo.pedir_confirmacao(titulo, corpo, rotulo, lambda confirmou: confirmou and ao_confirmar(), destrutivo=True)


class BackupDasPreferencias(QObject):
    alterado = Signal()

    def __init__(self, avisos: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._avisos = avisos
        self._saves = False
        self._pasta = ""
        self._padrao = True
        self._trocando = False

    # region Estado

    @Property(bool, notify=alterado)
    def savesDisponiveis(self) -> bool:  # noqa: N802
        return self._saves

    @Property(str, notify=alterado)
    def pastaDosSaves(self) -> str:  # noqa: N802
        return self._pasta

    @Property(bool, notify=alterado)
    def pastaPadrao(self) -> bool:  # noqa: N802
        return self._padrao

    @Property(bool, notify=alterado)
    def trocandoPasta(self) -> bool:  # noqa: N802
        return self._trocando

    @Property(str, notify=alterado)
    def nomeDoArquivo(self) -> str:  # noqa: N802
        return f"cartridges-backup-{date.today().isoformat()}.zip"

    @Slot()
    def reler(self) -> None:
        """As Preferências abriram (ou a troca da pasta acabou): lê o Ludusavi e a pasta dos saves."""
        self._saves = backup_de_saves.disponivel()
        atual = pasta.atual()
        # O `os.sep` deste Python é "/"; o Windows mostra a pasta com "\".
        self._pasta = str(atual).replace("/", "\\")
        self._padrao = atual == pasta.padrao()
        self.alterado.emit()

    def _avisar(self, texto: str, **kwargs: Any) -> Any:
        return self._avisos.adicionar(texto, **kwargs) if self._avisos is not None else None

    def _aguarde(self) -> None:
        self._avisar(_("Aguarde o fim do backup ou da restauração dos saves e tente novamente."))

    # endregion
    # region Exportar

    @Slot(QUrl)
    def exportar(self, url: QUrl) -> None:
        destino = _caminho(url)
        if destino is None:
            return
        configuracoes = backup.ler_configuracoes()  # na principal (lê o schema)
        avisos = weakref.ref(self._avisos) if self._avisos is not None else None
        aviso = self._avisar(_("Exportando backup…"), segundos=0)
        eu = weakref.ref(self)

        def trabalho() -> None:
            # Qualquer erro volta para a tela: o aviso de progresso não pode ficar pendurado.
            try:
                sem_saves = backup.exportar(destino, configuracoes)
            except Exception as erro:  # noqa: BLE001
                _log.exception("Não foi possível exportar o backup")
                na_thread_principal(_exportacao_acabou, eu, avisos, aviso, erro, None)
            else:
                na_thread_principal(_exportacao_acabou, eu, avisos, aviso, None, sem_saves)

        threading.Thread(target=trabalho, daemon=True).start()

    # endregion
    # region Importar

    @Slot(QUrl)
    def importar(self, url: QUrl) -> None:
        origem = _caminho(url)
        if origem is None:
            return
        # A restauração fecha o app e troca a pasta dos saves: não pode cair no meio de um backup ou de uma restauração.
        if backup_de_saves.em_andamento():
            self._aguarde()
            return
        eu = weakref.ref(self)
        _perguntar(
            _("Restaurar este backup?"),
            _("Tem certeza que deseja restaurar este backup? Esta ação é irreversível."),
            _("Restaurar"),
            lambda: (m := eu()) and m._preparar(origem),  # noqa: SLF001
        )

    def _preparar(self, origem: Path) -> None:
        """Valida e copia o .zip fora da thread principal (centenas de capas levam segundos)."""
        avisos = weakref.ref(self._avisos) if self._avisos is not None else None
        aviso = self._avisar(_("Preparando a restauração…"), segundos=0)
        eu = weakref.ref(self)

        def trabalho() -> None:
            try:
                backup.validar(origem)
                backup.agendar(origem)
            except backup.BackupInvalido:
                resultado = "invalido"
            except Exception:  # noqa: BLE001
                _log.exception("Não foi possível agendar a restauração do backup")
                resultado = "falhou"
            else:
                resultado = ""
            na_thread_principal(_preparo_acabou, eu, avisos, aviso, resultado)

        threading.Thread(target=trabalho, daemon=True).start()

    # endregion
    # region Pasta dos saves

    @Slot(QUrl)
    def escolherPastaDosSaves(self, url: QUrl) -> None:  # noqa: N802
        nova = _caminho(url)
        if nova is not None:
            self._trocar_pasta(nova)

    @Slot()
    def usarPastaPadrao(self) -> None:  # noqa: N802
        self._trocar_pasta(pasta.padrao())

    def _trocar_pasta(self, nova: Path) -> None:
        """A troca espera a trava dos saves e copia arquivos: fora da tela."""
        if self._trocando:
            return
        self._trocando = True
        self.alterado.emit()
        eu = weakref.ref(self)

        def trabalho() -> None:
            try:
                backup_de_saves.trocar_pasta(nova)
            except pasta.TrocaRecusada as recusa:
                aviso = str(recusa)
            except Exception:  # noqa: BLE001
                _log.exception("Não foi possível trocar a pasta dos saves")
                aviso = _("Não foi possível trocar a pasta dos saves.")
            else:
                aviso = None
            na_thread_principal(_troca_acabou, eu, aviso)

        threading.Thread(target=trabalho, daemon=True).start()

    @Slot()
    def restaurarTodos(self) -> None:  # noqa: N802
        _perguntar(
            _("Restaurar os saves de todos os jogos?"),
            _(
                "Tem certeza que deseja restaurar os saves de todos os jogos? "
                "Os saves atuais de cada jogo serão guardados como uma nova versão antes da restauração."
            ),
            _("Restaurar"),
            backup_de_saves.restaurar_todos,
        )

    # endregion
    # region Zona de perigo

    @Slot()
    def redefinir(self) -> None:
        eu = weakref.ref(self)
        _perguntar(
            _("Redefinir o Cartridges?"),
            _(
                "Tem certeza que deseja redefinir o Cartridges? Todos os jogos, configurações, contas conectadas "
                "e cópias dos saves armazenadas na pasta do aplicativo serão excluídos, e o aplicativo será "
                "reiniciado. Esta ação é irreversível."
            ),
            _("Redefinir"),
            lambda: (m := eu()) and m._redefinir_confirmado(),  # noqa: SLF001
        )

    def _redefinir_confirmado(self) -> None:
        # A limpeza é na abertura seguinte (`utils/redefinir.py`); um backup dos saves no meio gravaria na pasta que ela apaga.
        if backup_de_saves.em_andamento():
            self._aguarde()
            return
        try:
            redefinir.agendar()
        except OSError:
            _log.exception("Não foi possível agendar a redefinição")
            self._avisar(_("Não foi possível redefinir o Cartridges"))
            return
        _reiniciar()

    # endregion


def _reiniciar() -> None:
    aplicativo = _aplicativo()
    if aplicativo is not None:
        aplicativo.pedir_reinicio()


def _vivo(fraco: Any) -> Any:
    """O objeto de uma referência fraca, ou ``None`` se foi coletado ou o lado C++ já morreu."""
    objeto = fraco() if fraco is not None else None
    return objeto if objeto is not None and shiboken6.isValid(objeto) else None


def _dispensar(avisos: Any, aviso: Any) -> None:
    fila = _vivo(avisos)
    if fila is not None and aviso is not None:
        fila.dispensar(aviso)


def _exportacao_acabou(eu: Any, avisos: Any, aviso: Any, erro: Exception | None, sem_saves: str | None) -> None:
    _dispensar(avisos, aviso)
    modelo = _vivo(eu)
    if modelo is None:
        return
    if isinstance(erro, backup.SavesInacessiveis):
        _dialogo(
            _("Não foi possível exportar"),
            _(
                "Não foi possível ler as cópias dos saves. Verifique se a pasta "
                "dos saves está acessível e tente novamente."
            ),
        )
    elif erro is not None:
        _dialogo(
            _("Não foi possível exportar"),
            _(
                "Não foi possível gravar o arquivo. Verifique se a pasta "
                "de destino está acessível e se há espaço livre em disco."
            ),
        )
    elif sem_saves == "ausente":
        _dialogo(
            _("Backup exportado sem os saves"),
            _(
                "A pasta dos saves não foi encontrada, então as cópias dos saves "
                "não foram incluídas no backup. Verifique se a pasta está "
                "acessível e exporte novamente."
            ),
        )
    elif sem_saves == "vazia":
        _dialogo(
            _("Backup exportado sem os saves"),
            _(
                "A pasta dos saves escolhida não tem nenhuma cópia de save, então "
                "nenhuma foi incluída no backup. Verifique se a pasta escolhida "
                "em Preferências é a correta."
            ),
        )
    else:
        modelo._avisar(_("Backup exportado"))  # noqa: SLF001


def _preparo_acabou(eu: Any, avisos: Any, aviso: Any, resultado: str) -> None:
    _dispensar(avisos, aviso)
    modelo = _vivo(eu)
    if modelo is None:
        return
    if resultado == "invalido":
        _dialogo(_("Backup inválido"), _("O arquivo não é um backup válido do Cartridges."))
    elif resultado == "falhou":
        _dialogo(_("Não foi possível restaurar"), _("Não foi possível restaurar o backup. Tente novamente."))
    # Confere de novo: a preparação leva segundos, e a pessoa pode ter começado um backup ou uma restauração dos saves
    # nesse meio tempo. O backup já copiado é desfeito, para não ser aplicado por surpresa numa abertura futura.
    elif backup_de_saves.em_andamento():
        try:
            backup.cancelar_agendado()
        except OSError:
            _log.exception("Não foi possível desfazer o agendamento da restauração")
        modelo._aguarde()  # noqa: SLF001
    else:
        _reiniciar()


def _troca_acabou(eu: Any, aviso: str | None) -> None:
    modelo = _vivo(eu)
    if modelo is None:
        return
    modelo._trocando = False  # noqa: SLF001
    modelo.reler()
    if aviso:
        modelo._avisar(aviso)  # noqa: SLF001
