# backup_da_biblioteca.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O backup da biblioteca e a Zona de perigo das Preferências, sem tela: exportar, importar, a pasta dos saves,
"Restaurar saves de todos os jogos" e o Redefinir.

O trabalho pesado roda em threads e volta por `na_thread_principal` com referência fraca: um resultado que chega depois de
este objeto ser coletado é descartado. Só na thread principal.
"""

import logging
import threading
import time
import weakref
from datetime import date
from pathlib import Path
from typing import Any

import shiboken6
from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from cartridges import shared
from cartridges.modelos import tarefas
from cartridges.saves import backup_de_saves, pasta
from cartridges.utils import backup, redefinir
from cartridges.utils.thread_principal import na_thread_principal

_log = logging.getLogger(__name__)

_agora = time.monotonic  # trocável nos testes

# Com o app fechando, a exportação que passa tempo demais sem gravar nada é dada como presa.
PRAZO_SEM_PROGRESSO_S = 120


class _Exportacao:
    """O que a thread da exportação e a tela dividem: o último progresso e se o prazo já venceu."""

    def __init__(self, tarefa: Any, avisos: Any) -> None:
        self.tarefa = tarefa
        self.avisos = avisos
        self.aviso: Any = None
        self.ultimo = _agora()
        self.vencida = False

    def avancar(self) -> None:
        self.ultimo = _agora()  # atribuição simples: sem trava entre a thread e o timer


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
    """A confirmação destrutiva; ``ao_confirmar()`` só se a pessoa confirmou."""
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
        # Uma exportação e um preparo de cada vez: o segundo pedido cai em `_aguarde()`.
        self._exportando = False
        self._preparando = False
        self._exportacao: _Exportacao | None = None
        # Sem o modelo não há prazo; em produção ele vive o app todo (`Preferencias`), então só os testes o perdem.
        self._relogio_exportacao = QTimer(self)
        self._relogio_exportacao.setInterval(1000)
        self._relogio_exportacao.timeout.connect(self._conferir_exportacao)

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

    @Slot(QUrl)
    def exportar(self, url: QUrl) -> None:
        destino = _caminho(url)
        if destino is None:
            return
        if self._exportando:
            self._aguarde()
            return
        configuracoes = backup.ler_configuracoes()  # na principal (lê o schema)
        avisos = weakref.ref(self._avisos) if self._avisos is not None else None
        eu = weakref.ref(self)
        # A tarefa conta em `em_andamento()`: fechar o app, importar e redefinir esperam o fim da exportação.
        tarefa = backup_de_saves.comecar_tarefa(_("Exportando backup…"), 1)
        estado = _Exportacao(tarefa, avisos)

        def trabalho() -> None:
            # Qualquer erro volta para a tela: o aviso de progresso não pode ficar pendurado.
            try:
                sem_saves = backup.exportar(destino, configuracoes, progresso=estado.avancar)
            except Exception as erro:  # noqa: BLE001
                _log.exception("Não foi possível exportar o backup")
                na_thread_principal(_exportacao_acabou, estado, eu, erro, None)
            else:
                na_thread_principal(_exportacao_acabou, estado, eu, None, sem_saves)

        self._exportando = True
        try:
            estado.aviso = self._avisar(_("Exportando backup…"), segundos=0)
            self._exportacao = estado
            self._relogio_exportacao.start()
            threading.Thread(target=trabalho, daemon=True).start()
        except BaseException:
            # Sem thread não há quem termine a tarefa: a contagem não pode ficar presa.
            self._exportando = False
            self._relogio_exportacao.stop()
            self._exportacao = None
            backup_de_saves.terminar_tarefa(tarefa)
            _dispensar(avisos, estado.aviso)
            raise

    def _conferir_exportacao(self) -> None:
        """Só com o app fechando (a principal escondida à espera da exportação) e sem progresso há `PRAZO_SEM_PROGRESSO_S`:
        cancela o fechamento, solta a tarefa e avisa. A thread presa não morre (`_exportando` segue até ela voltar; o
        resultado de então é descartado em `_exportacao_acabou`); o backup anterior fica intacto: a thread só grava num
        `.tmp` e troca no fim.
        """
        estado = self._exportacao
        if estado is None or estado.vencida or not tarefas.fechamento_esperando():
            return
        if _agora() - estado.ultimo <= PRAZO_SEM_PROGRESSO_S:
            return
        estado.vencida = True
        self._relogio_exportacao.stop()
        _log.warning("A exportação do backup ficou %s s sem progresso", PRAZO_SEM_PROGRESSO_S)
        _terminar_exportacao(estado, mostrar=True)
        _dialogo(_("Não foi possível exportar"), _texto_do_destino())

    @Slot(QUrl)
    def importar(self, url: QUrl) -> None:
        origem = _caminho(url)
        if origem is None:
            return
        # A restauração fecha o app e troca a pasta dos saves: não pode cair no meio de um backup ou de uma restauração.
        if backup_de_saves.em_andamento() or self._preparando:
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
        if self._preparando:  # a pergunta pode ter ficado aberta enquanto outro preparo corria
            self._aguarde()
            return
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

        self._preparando = True
        try:
            threading.Thread(target=trabalho, daemon=True).start()
        except BaseException:
            self._preparando = False
            _dispensar(avisos, aviso)
            raise

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

    @Slot()
    def redefinir(self) -> None:
        eu = weakref.ref(self)
        _perguntar(
            _("Redefinir o Kyron?"),
            _(
                "Tem certeza que deseja redefinir o Kyron? Todos os jogos, configurações, contas conectadas "
                "e cópias dos saves armazenadas na pasta do aplicativo serão excluídos, e o aplicativo será "
                "reiniciado. Esta ação é irreversível."
            ),
            _("Redefinir"),
            lambda: (m := eu()) and m._redefinir_confirmado(),  # noqa: SLF001
        )

    def _redefinir_confirmado(self) -> None:
        # A limpeza é na abertura seguinte (`utils/redefinir.py`); um backup dos saves no meio gravaria na pasta que ela apaga.
        if backup_de_saves.em_andamento() or self._preparando:
            self._aguarde()
            return
        try:
            redefinir.agendar()
        except OSError:
            _log.exception("Não foi possível agendar a redefinição")
            self._avisar(_("Não foi possível redefinir o Kyron"))
            return
        _reiniciar()


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


def _terminar_exportacao(estado: _Exportacao, mostrar: bool) -> None:
    """Tira a exportação da contagem, sempre. Com um diálogo a mostrar (``mostrar``), o fechamento em espera é cancelado
    ANTES de a tarefa sair da contagem: senão o app sai primeiro."""
    if mostrar:
        try:
            tarefas.cancelar_fechamento()
        except Exception:  # noqa: BLE001
            _log.exception("Não foi possível cancelar o fechamento")
    try:
        backup_de_saves.terminar_tarefa(estado.tarefa)
    except Exception:  # noqa: BLE001
        _log.exception("Não foi possível terminar a tarefa da exportação")
    _dispensar(estado.avisos, estado.aviso)


def _texto_do_destino() -> str:
    return _(
        "Não foi possível gravar o arquivo. Verifique se a pasta "
        "de destino está acessível e se há espaço livre em disco."
    )


def _exportacao_acabou(
    estado: _Exportacao, eu: Any, erro: Exception | None, sem_saves: str | None
) -> None:
    modelo = _vivo(eu)
    if estado.vencida:
        # O prazo já avisou e soltou a tarefa: só a trava de "uma exportação de cada vez" se desfaz.
        _log.warning("A exportação presa voltou depois do prazo (%r); resultado descartado", erro or sem_saves)
        if modelo is not None:
            modelo._exportando = False  # noqa: SLF001
        return
    # Antes de qualquer guarda: com o modelo morto a tarefa ainda tem de acabar, ou o app não fecha mais.
    _terminar_exportacao(estado, mostrar=modelo is not None and (erro is not None or sem_saves in ("ausente", "vazia")))
    if modelo is None:
        return
    modelo._relogio_exportacao.stop()  # noqa: SLF001
    modelo._exportacao = None  # noqa: SLF001
    modelo._exportando = False  # noqa: SLF001
    if isinstance(erro, backup.SavesInacessiveis):
        _dialogo(
            _("Não foi possível exportar"),
            _(
                "Não foi possível ler as cópias dos saves. Verifique se a pasta "
                "dos saves está acessível e tente novamente."
            ),
        )
    elif erro is not None:
        _dialogo(_("Não foi possível exportar"), _texto_do_destino())
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
    modelo._preparando = False  # noqa: SLF001
    if resultado == "invalido":
        _dialogo(_("Backup inválido"), _("O arquivo não é um backup válido do Kyron."))
    elif resultado == "falhou":
        _dialogo(_("Não foi possível restaurar"), _("Não foi possível restaurar o backup. Tente novamente."))
    # Confere de novo: a preparação leva segundos e a pessoa pode ter começado um backup ou restauração de saves; o backup
    # já copiado é desfeito para não ser aplicado por surpresa numa abertura futura.
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
