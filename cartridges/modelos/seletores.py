# seletores.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Os seletores de capa e de logo do SteamGridDB (D41, camada 2; o desenho é `SeletorDeImagens.qml`).

Cada um é uma lista de miniaturas: a busca devolve os endereços, as linhas aparecem "carregando" e as
miniaturas chegam uma a uma. Escolher baixa a imagem original e a entrega ao diálogo de edição
(`entregar_capa_baixada`, `entregar_logo_baixado`, `usar_titulo_no_logo`). Só na thread principal; as
threads (busca, miniaturas, download) entregam por `na_thread_principal` e o que chega a um seletor que já
fechou, ou que já buscou outra coisa, é descartado (e o arquivo, apagado).

Todo arquivo do seletor mora numa pasta própria em %TEMP%, apagada em `fechar`. O original baixado vai para
fora dela: é de quem o recebe.
"""

import logging
import os
import shutil
import tempfile
import threading
import weakref
from enum import IntEnum
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from uuid import uuid4

import requests
from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QCoreApplication,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QUrl,
    Qt,
    Signal,
    Slot,
)

from cartridges import shared
from cartridges.utils import game_logo
from cartridges.utils.busca_do_seletor import BuscaDoSeletor, tamanho_baixado
from cartridges.utils.download import (
    MAX_ANIMATED_IMAGE_BYTES,
    MAX_IMAGE_BYTES,
    DownloadCancelado,
    download_bytes,
)
from cartridges.utils.logo_arquivos import IMAGE_SUFFIXES
from cartridges.utils.name_cleaner import clean_game_name
from cartridges.utils.steamgriddb import SgdbAuthError, SgdbError, SgdbHelper
from cartridges.utils.thread_principal import na_thread_principal

# Quantas miniaturas carregar: a janela fica leve mesmo com muitos resultados.
MAX_RESULTS = 30
# Capas animadas: a miniatura é a própria imagem, então são menos.
MAX_ANIMATED_RESULTS = 12
MAX_LOGOS = 24

# As extensões com que uma miniatura pode ser gravada; qualquer outra na URL vira ".png".
_PREVIEW_SUFFIXES = (".png", ".apng", ".jpg", ".jpeg", ".webp", ".gif")

# Dimensões das capas retrato no SteamGridDB. Sem o filtro a API devolve também as capas horizontais; só
# 600x900 elimina quase todas as animadas, que costumam usar os outros tamanhos retrato.
PORTRAIT_DIMENSIONS = "600x900,342x482,660x930"


def _largar_arquivos_abertos() -> None:
    # O ``AnimatedImage`` só larga o arquivo quando destrói o filme, num ``deleteLater``.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _sufixo_da_url(url: str, aceitos: tuple[str, ...]) -> str:
    sufixo = Path(urlparse(url).path).suffix.lower()
    return sufixo if sufixo in aceitos else ".png"


class _SeletorDoSteamGridDB(BuscaDoSeletor, QAbstractListModel):
    """O que o seletor de capas e o de logos têm em comum; cada um dá o que busca e a quem entrega."""

    class Papel(IntEnum):
        Miniatura = Qt.ItemDataRole.UserRole + 1
        Animada = Qt.ItemDataRole.UserRole + 2
        Carregando = Qt.ItemDataRole.UserRole + 3

    abertoChanged = Signal()  # noqa: N815
    buscaChanged = Signal()  # noqa: N815
    estadoChanged = Signal()  # noqa: N815
    baixandoChanged = Signal()  # noqa: N815
    progressoChanged = Signal()  # noqa: N815

    # O que cada tipo diz quando não acha nada ou o download falha.
    _prefixo_da_pasta = "cartridges_sgdb_"
    _texto_de_nada = ""
    _texto_de_falha = ""

    def __init__(self, destino: Any, parent: Any = None) -> None:
        super().__init__(parent)
        # Referência fraca: o destino é o `ModeloDaEdicao`, pai deste modelo. Um ciclo entre os dois seria
        # recolhido pelo coletor de ciclos do Python numa thread qualquer (a que estiver alocando, como uma
        # thread de busca ou um Timer), finalizando um QObject fora da thread principal: access violation.
        # Sem ciclo, a destruição é por contagem de referências. `_destino` pode, então, ser None.
        self._destino_fraco = weakref.ref(destino)
        self.sgdb = SgdbHelper()
        self._linhas: list[dict[str, Any]] = []
        self._aberto = False
        # Uma busca nova, uma escolha ou o fechamento invalidam tudo o que as threads ainda entregam.
        self._generation = 0
        self._closed = True
        self._last_query: Optional[str] = None
        self._busca = ""
        self._pasta: Optional[Path] = None
        self._buscando = False
        self._vazio = False
        self._erro = False
        self._titulo = ""
        self._descricao = ""
        self._baixando = False
        self._progresso = 0.0
        self._progresso_texto = ""

    @property
    def _destino(self) -> Any:
        return self._destino_fraco()

    # -- o modelo --------------------------------------------------------------------------------

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802
        return {
            self.Papel.Miniatura: QByteArray(b"miniatura"),
            self.Papel.Animada: QByteArray(b"animada"),
            self.Papel.Carregando: QByteArray(b"carregando"),
        }

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._linhas)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._linhas):
            return None
        linha = self._linhas[index.row()]
        match role:
            case self.Papel.Miniatura:
                return linha["miniatura"]
            case self.Papel.Animada:
                return linha["animada"]
            case self.Papel.Carregando:
                return linha["carregando"]
        return None

    # -- propriedades ----------------------------------------------------------------------------

    @Property(bool, notify=abertoChanged)
    def aberto(self) -> bool:
        return self._aberto

    @Property(str, notify=buscaChanged)
    def busca(self) -> str:
        return self._busca

    @busca.setter
    def busca(self, texto: str) -> None:
        if self._aberto and texto != self._busca:
            self._busca = texto
            self.buscaChanged.emit()
            self._on_search_changed()

    @Property(bool, notify=estadoChanged)
    def buscando(self) -> bool:
        """A busca ainda corre: a lista, as miniaturas ou o aviso de nada achado ainda não é definitivo."""
        return self._buscando

    @Property(bool, notify=estadoChanged)
    def vazio(self) -> bool:
        """A tela mostra o aviso (`tituloDoEstado`) no lugar da grade."""
        return self._vazio

    @Property(bool, notify=estadoChanged)
    def erro(self) -> bool:
        """O aviso é de uma falha (chave, conexão, download), e não de uma busca sem resultado."""
        return self._erro

    @Property(str, notify=estadoChanged)
    def tituloDoEstado(self) -> str:  # noqa: N802
        return self._titulo

    @Property(str, notify=estadoChanged)
    def descricaoDoEstado(self) -> str:  # noqa: N802
        return self._descricao

    @Property(bool, notify=baixandoChanged)
    def baixando(self) -> bool:
        return self._baixando

    @Property(float, notify=progressoChanged)
    def progresso(self) -> float:
        """Da escolha que baixa: de 0 a 1, ou -1 quando o servidor não informa o tamanho."""
        return self._progresso

    @Property(str, notify=progressoChanged)
    def textoDoProgresso(self) -> str:  # noqa: N802
        """"4,4 MB de 21,0 MB" (ou só o recebido, sem o total); vazio até chegar o primeiro dado."""
        return self._progresso_texto

    # -- buscar ----------------------------------------------------------------------------------

    def _buscar(self, consulta: str, animada: bool) -> list[tuple[str, str]]:
        """Na thread de busca: ``(url da original, url da miniatura)`` de cada resultado. Pode levantar."""
        raise NotImplementedError

    def _animada(self) -> bool:
        return False

    def _sufixo(self, url: str) -> str:
        return _sufixo_da_url(url, _PREVIEW_SUFFIXES)

    def _entregar(self, arquivo: Path) -> None:
        raise NotImplementedError

    def _primeiro_id(self, consulta: str) -> Any:
        jogos = self.sgdb.search_games(consulta)
        # .get, não [ ]: um item sem "id" (200 de shape inesperado) não pode matar a thread.
        return jogos[0].get("id") if jogos and isinstance(jogos[0], dict) else None

    @Slot(str)
    def abrir(self, nome: str) -> None:
        if self._aberto:
            self.fechar()
        self._closed = False
        self._aberto = True
        self._pasta = Path(tempfile.mkdtemp(prefix=self._prefixo_da_pasta))
        self._busca = clean_game_name(nome)
        self._abrir_mais()
        self.abertoChanged.emit()
        self.buscaChanged.emit()
        self.search()

    def _abrir_mais(self) -> None:
        """Gancho: o que só um tipo reinicia ao abrir."""

    @Slot()
    def buscarAgora(self) -> None:  # noqa: N802
        """Enter no campo: busca já, sem esperar o atraso."""
        if self._aberto and not self._baixando:
            self.search()

    def search(self) -> None:
        self._generation += 1
        geracao = self._generation
        self._cancelar_debounce()
        self._limpar()
        self._baixando = False
        consulta = self._busca.strip()
        self._last_query = consulta
        if not consulta:
            self._show_empty(_("Digite o nome de um jogo"))
            return
        if not shared.schema.get_string("sgdb-key"):
            self._show_empty(
                _("Chave da API não configurada"),
                # shortcut: sem o botão "Preferências" no aviso, a tela de preferências é do plano 7 (D42).
                _("Configure a chave da API do SteamGridDB nas Preferências."),
            )
            return
        self._vazio = self._erro = False
        self._buscando = True
        self.estadoChanged.emit()
        self.baixandoChanged.emit()
        args = (consulta, self._animada(), geracao, self._pasta)
        threading.Thread(target=self._thread_da_busca, args=args, daemon=True).start()

    def _show_empty(self, titulo: str, descricao: str = "", generation: Optional[int] = None, erro: bool = False) -> None:
        if generation is not None and generation != self._generation:
            return
        self._titulo, self._descricao = titulo, descricao
        self._vazio, self._erro = True, erro
        self._buscando = self._baixando = False
        self.estadoChanged.emit()
        self.baixandoChanged.emit()

    def _thread_da_busca(self, consulta: str, animada: bool, geracao: int, pasta: Optional[Path]) -> None:
        try:
            self._corpo_da_busca(consulta, animada, geracao, pasta)
        except Exception:  # noqa: BLE001  (uma resposta de forma inesperada não pode deixar a tela carregando)
            logging.exception("SGDB picker search crashed")
            na_thread_principal(
                self._show_empty,
                _("Não foi possível concluir a busca"),
                _("Verifique a conexão e tente novamente."),
                geracao,
                True,
            )

    def _corpo_da_busca(self, consulta: str, animada: bool, geracao: int, pasta: Optional[Path]) -> None:
        def cancelar(*_args: Any) -> None:
            if self._closed or geracao != self._generation:
                raise DownloadCancelado

        try:
            itens = self._buscar(consulta, animada)
        except SgdbAuthError:
            na_thread_principal(
                self._show_empty,
                _("Chave da API inválida"),
                _("Verifique a chave da API do SteamGridDB nas Preferências."),
                geracao,
                True,
            )
            return
        except (SgdbError, requests.RequestException) as erro:
            logging.warning("SGDB picker search failed: %s", erro)
            na_thread_principal(
                self._show_empty,
                _("Não foi possível concluir a busca"),
                _("Verifique a conexão e tente novamente."),
                geracao,
                True,
            )
            return
        if not itens:
            na_thread_principal(self._show_empty, self._texto_de_nada, _("Tente buscar por outro nome."), geracao)
            return

        na_thread_principal(self._receber, geracao, [(original, animada) for original, _previa in itens])
        limite = MAX_ANIMATED_IMAGE_BYTES if animada else MAX_IMAGE_BYTES
        for numero, (_original, previa) in enumerate(itens):
            if self._closed or geracao != self._generation:
                return
            arquivo = None
            try:
                conteudo = download_bytes(previa, timeout=15, max_bytes=limite, ao_progredir=cancelar)
            except DownloadCancelado:
                return
            except requests.RequestException as erro:
                logging.warning("SGDB picker: preview download failed (%s: %s)", type(erro).__name__, erro)
            else:
                sufixo = self._sufixo(previa)
                # O SteamGridDB serve APNG como .png; é a extensão que faz a prévia tocar.
                if animada and sufixo == ".png":
                    sufixo = ".apng"
                # O nome nunca sai da resposta da API: um id "..\x" gravava fora da pasta.
                destino = pasta / f"{uuid4().hex}{sufixo}" if pasta is not None else None
                if destino is not None and not self._closed and geracao == self._generation:
                    try:
                        destino.write_bytes(conteudo)
                        arquivo = destino
                    except OSError:
                        arquivo = None
            na_thread_principal(self._previa_pronta, geracao, numero, arquivo)
        # Depois de todas as miniaturas (a fila roda na ordem): sem isto, toda miniatura falhando
        # deixava o seletor em "carregando" pela vida inteira.
        na_thread_principal(self._fim_das_previas, geracao)

    # -- resultados ------------------------------------------------------------------------------

    def _limpar(self) -> None:
        for linha in self._linhas:
            if linha["arquivo"] is not None:
                self._apagar(linha["arquivo"])
        if self._linhas:
            self.beginResetModel()
            self._linhas = []
            self.endResetModel()

    def _apagar(self, arquivo: Path) -> None:
        try:
            arquivo.unlink(missing_ok=True)
        except OSError:
            pass  # preso por uma prévia animada ainda aberta: a pasta inteira cai em `fechar`
        if arquivo.parent != self._pasta:
            # Um arquivo de uma pasta que já fechou: a pasta, agora vazia, não pode ficar.
            try:
                arquivo.parent.rmdir()
            except OSError:
                pass

    def _receber(self, geracao: int, itens: list[tuple[str, bool]]) -> None:
        if geracao != self._generation or self._closed:
            return
        self.beginResetModel()
        self._linhas = [
            {"id": numero, "original": original, "animada": animada, "miniatura": "", "carregando": True, "arquivo": None}
            for numero, (original, animada) in enumerate(itens)
        ]
        self.endResetModel()

    def _linha(self, numero: int) -> int:
        return next((i for i, linha in enumerate(self._linhas) if linha["id"] == numero), -1)

    def _previa_pronta(self, geracao: int, numero: int, arquivo: Optional[Path]) -> None:
        if geracao != self._generation or self._closed:
            if arquivo is not None:
                self._apagar(arquivo)
            return
        posicao = self._linha(numero)
        if posicao < 0:
            return
        if arquivo is None:
            # A miniatura não veio: a linha sai, em vez de ficar carregando para sempre.
            self.beginRemoveRows(QModelIndex(), posicao, posicao)
            del self._linhas[posicao]
            self.endRemoveRows()
            return
        linha = self._linhas[posicao]
        linha.update(miniatura=QUrl.fromLocalFile(str(arquivo)).toString(), carregando=False, arquivo=arquivo)
        indice = self.index(posicao, 0)
        self.dataChanged.emit(indice, indice, [self.Papel.Miniatura, self.Papel.Carregando])

    def _fim_das_previas(self, geracao: int) -> None:
        if geracao != self._generation or self._closed:
            return
        self._buscando = False
        if not self._linhas:
            self._show_empty(_("Não foi possível carregar as pré-visualizações"), _("Tente novamente."), erro=True)
        else:
            self.estadoChanged.emit()

    # -- escolher --------------------------------------------------------------------------------

    @Slot(int)
    def escolher(self, indice: int) -> None:
        if not self._aberto or self._baixando or not 0 <= indice < len(self._linhas):
            return
        linha = self._linhas[indice]
        if linha["carregando"]:
            return
        # Encerra a busca que ainda baixa miniaturas: cada uma que chegasse depois traria a grade de
        # volta por cima do carregamento.
        self._generation += 1
        self._cancelar_debounce()
        self._buscando = False
        self._baixando = True
        self._progresso, self._progresso_texto = 0.0, ""
        self.estadoChanged.emit()
        self.baixandoChanged.emit()
        self.progressoChanged.emit()
        args = (linha["original"], linha["animada"], self._generation)
        threading.Thread(target=self._thread_do_download, args=args, daemon=True).start()

    def _progredir(self, geracao: int, recebido: int, total: Optional[int]) -> None:
        """Na thread do download: interrompe se o seletor fechou ou a escolha ficou velha."""
        if geracao != self._generation:
            raise DownloadCancelado
        self._ao_progredir(recebido, total)
        na_thread_principal(self._progresso_recebido, geracao, recebido, total)

    def _progresso_recebido(self, geracao: int, recebido: int, total: Optional[int]) -> None:
        if geracao == self._generation and self._baixando:
            self._progresso = min(recebido / total, 1.0) if total else -1.0
            self._progresso_texto = tamanho_baixado(recebido, total)
            self.progressoChanged.emit()

    def _thread_do_download(self, url: str, animada: bool, geracao: int) -> None:
        try:
            self._corpo_do_download(url, animada, geracao)
        except Exception:  # noqa: BLE001  (idem: a tela "Baixando…" não pode ficar presa)
            logging.exception("SGDB picker download crashed")
            self._falhou(geracao)

    def _corpo_do_download(self, url: str, animada: bool, geracao: int) -> None:
        limite = MAX_ANIMATED_IMAGE_BYTES if animada else MAX_IMAGE_BYTES
        try:
            conteudo = download_bytes(
                url,
                timeout=15,
                max_bytes=limite,
                ao_progredir=lambda recebido, total: self._progredir(geracao, recebido, total),
            )
        except DownloadCancelado:
            return
        except requests.RequestException as erro:
            logging.warning("Could not download the chosen image: %s: %s", type(erro).__name__, erro)
            self._falhou(geracao)
            return
        # Fora da pasta do seletor, que cai em `fechar`: o arquivo é de quem o recebe.
        arquivo: Optional[Path] = None
        try:
            descritor, nome = tempfile.mkstemp(prefix=self._prefixo_da_pasta, suffix=self._sufixo(url))
            os.close(descritor)
            arquivo = Path(nome)
            arquivo.write_bytes(conteudo)
        except OSError as erro:
            logging.warning("Could not store the chosen image: %s", erro)
            if arquivo is not None:
                arquivo.unlink(missing_ok=True)
            self._falhou(geracao)
            return
        na_thread_principal(self._baixado, geracao, arquivo)

    def _falhou(self, geracao: int) -> None:
        na_thread_principal(self._show_empty, self._texto_de_falha, _("Tente novamente."), geracao, True)

    def _baixado(self, geracao: int, arquivo: Path) -> None:
        if geracao != self._generation or self._closed:
            # Ninguém mais vai recebê-lo, e então ninguém mais o apagaria.
            arquivo.unlink(missing_ok=True)
            return
        if self._destino is None:
            # A edição já morreu: ninguém receberá o arquivo.
            arquivo.unlink(missing_ok=True)
            self.fechar()
            return
        self._entregar(arquivo)
        self.fechar()

    # -- fechar ----------------------------------------------------------------------------------

    @Slot()
    def fechar(self) -> None:
        """Cancela a busca e o download e apaga todos os arquivos do seletor."""
        self._closed = True
        self._generation += 1
        self._cancelar_debounce()
        self._aberto = self._buscando = self._baixando = self._vazio = self._erro = False
        self._progresso, self._progresso_texto = 0.0, ""
        self._limpar()
        pasta, self._pasta = self._pasta, None
        self.abertoChanged.emit()
        self.estadoChanged.emit()
        self.baixandoChanged.emit()
        if pasta is not None:
            # As miniaturas animadas da tela soltam os arquivos abertos antes de a pasta sair.
            _largar_arquivos_abertos()
            shutil.rmtree(pasta, ignore_errors=True)
            if pasta.exists():
                # shortcut: um arquivo ainda preso pela tela cai um segundo depois, uma vez só; sem varredura.
                threading.Timer(1.0, shutil.rmtree, (pasta, True)).start()


class SeletorDoSgdb(_SeletorDoSteamGridDB):
    """A capa: "Animadas" alterna entre as capas paradas e as animadas."""

    animadasChanged = Signal()  # noqa: N815

    _texto_de_nada = _("Nenhuma capa encontrada")
    _texto_de_falha = _("Não foi possível baixar a capa")

    def __init__(self, destino: Any, parent: Any = None) -> None:
        super().__init__(destino, parent)
        self._animadas = False

    @Property(bool, notify=animadasChanged)
    def animadas(self) -> bool:
        return self._animadas

    @animadas.setter
    def animadas(self, valor: bool) -> None:
        if valor != self._animadas:
            self._animadas = valor
            self.animadasChanged.emit()
            if self._aberto:
                self.search()

    def _animada(self) -> bool:
        return self._animadas

    def _abrir_mais(self) -> None:
        self._animadas = shared.schema.get_boolean("sgdb-animated")
        self.animadasChanged.emit()

    def _buscar(self, consulta: str, animada: bool) -> list[tuple[str, str]]:
        primeiro = self._primeiro_id(consulta)
        grades = self.sgdb.get_grids(primeiro, animada, dimensions=PORTRAIT_DIMENSIONS) if primeiro is not None else []
        itens = []
        for grade in grades[: MAX_ANIMATED_RESULTS if animada else MAX_RESULTS]:
            if original := grade.get("url"):
                # O SteamGridDB serve a miniatura animada como .webm, que o Qt não toca: a prévia da
                # animada é a própria imagem; a parada usa a miniatura leve.
                itens.append((original, original if animada else (grade.get("thumb") or original)))
        return itens

    def _entregar(self, arquivo: Path) -> None:
        self._destino.entregar_capa_baixada(arquivo)


class SeletorDeLogo(_SeletorDoSteamGridDB):
    """O logo: "Usar o título" é a escolha de não usar logo neste jogo."""

    _prefixo_da_pasta = "cartridges_logo_"
    _texto_de_nada = _("Nenhum logo encontrado")
    _texto_de_falha = _("Não foi possível baixar o logo")

    def _sufixo(self, url: str) -> str:
        return _sufixo_da_url(url, IMAGE_SUFFIXES)

    @staticmethod
    def _ordenados(logos: list[dict]) -> list[dict]:
        """Todo logo usável, o melhor primeiro, julgado como a página os julga: o que o app escolheria
        sozinho vem primeiro, e os outros não são filtrados (é para ver as alternativas)."""
        ordenados, restantes = [], list(logos)
        while restantes and (melhor := game_logo.pick_logo(restantes)):
            ordenados.append(melhor)
            restantes.remove(melhor)
        return ordenados

    def _buscar(self, consulta: str, animada: bool) -> list[tuple[str, str]]:
        primeiro = self._primeiro_id(consulta)
        logos = self.sgdb.get_logos(primeiro) if primeiro is not None else []
        itens = []
        for logo in self._ordenados(logos)[:MAX_LOGOS]:
            if original := str(logo.get("url") or ""):
                itens.append((original, str(logo.get("thumb") or original)))
        return itens

    @Slot()
    def usarTitulo(self) -> None:  # noqa: N802
        if self._aberto:
            if (destino := self._destino) is not None:
                destino.usar_titulo_no_logo()
            self.fechar()

    def _entregar(self, arquivo: Path) -> None:
        self._destino.entregar_logo_baixado(arquivo)
