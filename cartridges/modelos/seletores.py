# seletores.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Os seletores do diálogo de edição (D41, camada 2): capa e logo do SteamGridDB (`SeletorDeImagens.qml`),
jogo da Steam (`SeletorDaSteam.qml`) e jogo do Ludusavi (`SeletorDoLudusavi.qml`).

Cada um é uma lista de miniaturas: a busca devolve os endereços, as linhas aparecem "carregando" e as
miniaturas chegam uma a uma. Escolher baixa a imagem original e a entrega ao diálogo de edição
(`entregar_capa_baixada`, `entregar_logo_baixado`, `usar_titulo_no_logo`). Só na thread principal; as
threads (busca, miniaturas, download) entregam por `na_thread_principal` e o que chega a um seletor que já
fechou, ou que já buscou outra coisa, é descartado (e o arquivo, apagado).

Todo arquivo do seletor mora numa pasta própria em %TEMP%, apagada em `fechar`. O original baixado vai para
fora dela: é de quem o recebe.
"""

import io
import logging
import os
import shutil
import tempfile
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from enum import IntEnum
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from uuid import uuid4

import requests
from PIL import Image, UnidentifiedImageError
from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QCoreApplication,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QUrl,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QGuiApplication

from cartridges import shared
from cartridges.saves import backup_de_saves, ludusavi
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.utils import game_logo
from cartridges.utils.busca_do_seletor import BuscaDoSeletor, tamanho_baixado
from cartridges.utils.download import (
    MAX_ANIMATED_IMAGE_BYTES,
    MAX_IMAGE_BYTES,
    MAX_WALLPAPER_BYTES,
    DownloadCancelado,
    download_bytes,
)
from cartridges.utils.logo_arquivos import IMAGE_SUFFIXES
from cartridges.utils.name_cleaner import clean_for_search, clean_game_name
from cartridges.utils.title_match import rank_candidates
from cartridges.utils.steam import SteamAPIHelper, SteamGameNotFoundError, SteamNotAGameError, SteamRateLimiter
from cartridges.utils.session_wallpaper import Formatos, Monitor, Posicoes, corta, eixo_do_corte, enquadrar, formatos
from cartridges.utils.steamgriddb import SgdbAuthError, SgdbError, SgdbHelper
from cartridges.utils.thread_principal import na_thread_principal
from cartridges.utils.wallhaven import IMAGE_SUFFIXES as WALLHAVEN_SUFFIXES, WallhavenError, buscar

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
    # O SteamGridDB não responde sem chave; o wallhaven (papel de parede) responde.
    _exige_chave = True

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
        consulta = clean_for_search(consulta)
        jogos = self.sgdb.search_games(consulta)
        # Só dicts com "id": um item de shape inesperado (200) não pode matar a thread.
        jogos = [j for j in jogos or [] if isinstance(j, dict) and j.get("id") is not None]
        # Como o caminho automático: o melhor do ranking; sem ninguém nele, o primeiro da lista (D105).
        ranking = rank_candidates(consulta, jogos)
        return (ranking[0][0] if ranking else jogos[0])["id"] if jogos else None

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
        if self._exige_chave and not shared.schema.get_string("sgdb-key"):
            self._show_empty(
                _("Chave da API não configurada"),
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
            # Chegou mais do que o servidor informou: o total real não é conhecido, e "30,0 MB de 20,0 MB"
            # pareceria erro do aplicativo.
            if total is not None and recebido > total:
                total = None
            self._progresso = recebido / total if total else -1.0
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


# -- papel de parede (wallhaven) ---------------------------------------------------------------------

# Uma página do site.
MAX_PAPEIS = 24
# O lado fixo da célula da grade, em pixels lógicos: a altura numa grade em pé, a largura numa deitada. O outro
# lado sai da proporção do monitor, e a célula é a tela em miniatura (146x260 num 9:16, 260x146 num 16:9).
LADO_DA_CELULA = 260
# A caixa em que a prévia do ajuste cabe: com uma orientação só ela tem o diálogo inteiro; no arranjo misto as
# duas dividem a largura, e a deitada fica com a maior parte.
CAIXA_UNICA = (640, 360)
CAIXA_DEITADA = (440, 250)
CAIXA_EM_PE = (150, 250)


def monitores_das_telas() -> list[Monitor]:
    """Os monitores ligados agora, em pixels de verdade, como o Windows os entrega à sessão do jogo."""
    monitores = []
    for tela in QGuiApplication.screens():
        retangulo, escala = tela.geometry(), tela.devicePixelRatio()
        monitores.append(
            Monitor(tela.name(), retangulo.x(), retangulo.y(), round(retangulo.width() * escala), round(retangulo.height() * escala))
        )
    return monitores


def _celula(largura: int, altura: int) -> tuple[int, int]:
    if altura > largura:
        return max(1, round(LADO_DA_CELULA * largura / altura)), LADO_DA_CELULA
    return LADO_DA_CELULA, max(1, round(LADO_DA_CELULA * altura / largura))


def _caber(largura: int, altura: int, caixa: tuple[int, int]) -> tuple[int, int]:
    escala = min(caixa[0] / largura, caixa[1] / altura)
    return max(1, round(largura * escala)), max(1, round(altura * escala))


class _CortesDoPapel(QAbstractListModel):
    """Os cortes da segunda etapa: um por orientação dos monitores. Quem os preenche é o seletor."""

    class Papel(IntEnum):
        Previa = Qt.ItemDataRole.UserRole + 1
        Posicao = Qt.ItemDataRole.UserRole + 2
        Desliza = Qt.ItemDataRole.UserRole + 3
        Dica = Qt.ItemDataRole.UserRole + 4
        LarguraDaPrevia = Qt.ItemDataRole.UserRole + 5
        AlturaDaPrevia = Qt.ItemDataRole.UserRole + 6
        Orientacao = Qt.ItemDataRole.UserRole + 7

    # papel -> (nome no QML, chave da linha)
    _NOMES = {
        Papel.Previa: (b"previa", "previa"), Papel.Posicao: (b"posicao", "posicao"),
        Papel.Desliza: (b"desliza", "desliza"), Papel.Dica: (b"dica", "dica"),
        Papel.LarguraDaPrevia: (b"larguraDaPrevia", "largura_da_previa"),
        Papel.AlturaDaPrevia: (b"alturaDaPrevia", "altura_da_previa"),
        Papel.Orientacao: (b"orientacao", "orientacao"),
    }  # fmt: skip

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.linhas: list[dict[str, Any]] = []

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802
        return {papel: QByteArray(nome) for papel, (nome, _chave) in self._NOMES.items()}

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self.linhas)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self.linhas) or role not in self._NOMES:
            return None
        return self.linhas[index.row()][self._NOMES[role][1]]

    def redefinir(self, linhas: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.linhas = linhas
        self.endResetModel()

    def mudou(self, linha: int) -> None:
        indice = self.index(linha, 0)
        self.dataChanged.emit(indice, indice)


class SeletorDePapelDeParede(_SeletorDoSteamGridDB):
    """O papel de parede da sessão, escolhido à mão no wallhaven em duas etapas.

    Primeira: a grade de candidatos já cortados no formato dos monitores. Segunda: a imagem escolhida, baixada
    inteira, com a barra que desliza a faixa de cada monitor. Toda a fidelidade vem de uma coisa só: a miniatura e
    o arquivo final passam pela mesma `enquadrar`, e como ela corta em proporção o quadro de 146 px da grade e o de
    1080 px do monitor são o mesmo quadro. "Usar esta imagem" entrega `(arquivo, Posicoes)` ao diálogo de edição;
    "Não trocar" entrega a decisão de não mexer no papel de parede deste jogo. O que a busca, as miniaturas e o
    download têm em comum com os seletores do SteamGridDB vem de `_SeletorDoSteamGridDB`.
    """

    ajustandoChanged = Signal()  # noqa: N815
    formatoChanged = Signal()  # noqa: N815 (também o "só arquivo", que muda junto com a abertura)

    _prefixo_da_pasta = "cartridges_wallpaper_"
    _exige_chave = False
    _texto_de_nada = _("Nenhum papel de parede encontrado")
    _texto_de_falha = _("Não foi possível baixar a imagem")

    def __init__(self, destino: Any, parent: Any = None) -> None:
        super().__init__(destino, parent)
        # Os testes põem monitores falsos aqui.
        self.monitores = monitores_das_telas
        self._formatos = Formatos(None, None)
        self._escala = 1
        self._ajustando = False
        self._so_arquivo = False
        self._cortes = _CortesDoPapel(self)
        # A imagem aberta na segunda etapa: o original inteiro (que é o que vai ser gravado) e uma cópia pequena,
        # de onde cada arrastada da barra recorta (recortar o 4K a cada pixel de arrasto travaria).
        self._original: Optional[Path] = None
        self._previa: Optional[Image.Image] = None

    # -- propriedades ----------------------------------------------------------------------------

    cortes = Property(QObject, lambda self: self._cortes, constant=True)

    @Property(bool, notify=ajustandoChanged)
    def ajustando(self) -> bool:
        return self._ajustando

    @Property(int, notify=formatoChanged)
    def larguraDaCelula(self) -> int:  # noqa: N802
        return _celula(*self._formatos.grade)[0]

    @Property(int, notify=formatoChanged)
    def alturaDaCelula(self) -> int:  # noqa: N802
        return _celula(*self._formatos.grade)[1]

    @Property(bool, notify=formatoChanged)
    def soArquivo(self) -> bool:  # noqa: N802
        """Aberto com um arquivo do disco: sem busca, sem "Não trocar", e "Voltar" desiste da escolha."""
        return self._so_arquivo

    # -- buscar ----------------------------------------------------------------------------------

    def _abrir_mais(self) -> None:
        self._so_arquivo = False
        self._formatos = formatos(self.monitores())
        tela = QGuiApplication.primaryScreen()
        self._escala = max(1, int(tela.devicePixelRatio())) if tela is not None else 1
        self._ajustando = False
        self.formatoChanged.emit()
        self.ajustandoChanged.emit()

    def _sufixo(self, url: str) -> str:
        sufixo = Path(urlparse(url).path).suffix.lower()
        return sufixo if sufixo in WALLHAVEN_SUFFIXES else ".jpg"

    @Slot(QUrl)
    def abrirArquivo(self, url: QUrl) -> None:  # noqa: N802
        """Leva um arquivo do disco direto à etapa de ajuste, como uma imagem da busca (como na `main`)."""
        caminho = Path(url.toLocalFile())
        if self._aberto:
            self.fechar()
        self._closed = False
        self._aberto = True
        self._pasta = Path(tempfile.mkdtemp(prefix=self._prefixo_da_pasta))
        self._busca = ""
        self._abrir_mais()
        self._so_arquivo = True
        self._generation += 1
        self._last_query = ""
        self._buscando, self._vazio, self._erro = True, False, False
        for sinal in (self.abertoChanged, self.buscaChanged, self.formatoChanged, self.estadoChanged):
            sinal.emit()
        args = (caminho, self._generation, self._pasta)
        threading.Thread(target=self._thread_do_arquivo, args=args, daemon=True).start()

    def _thread_do_arquivo(self, caminho: Path, geracao: int, pasta: Optional[Path]) -> None:
        try:
            # Sem limite de tamanho, como na `main`.
            conteudo = caminho.read_bytes()
            sufixo = caminho.suffix.lower()
            self._preparar(conteudo, sufixo if sufixo in WALLHAVEN_SUFFIXES else ".jpg", geracao, pasta)
        except Exception:  # noqa: BLE001  (a tela "carregando" não pode ficar presa)
            logging.exception("Wallpaper picker file open crashed")
            na_thread_principal(self._show_empty, _("Não foi possível abrir a imagem"), _("Tente outra imagem."), geracao, True)

    def _corpo_da_busca(self, consulta: str, animada: bool, geracao: int, pasta: Optional[Path]) -> None:
        def cancelar(*_args: Any) -> None:
            if self._closed or geracao != self._generation:
                raise DownloadCancelado

        alvo = self._formatos
        try:
            # O formato da grade primeiro e qualquer formato depois, na mesma grade: o que menos precisa de corte
            # aparece na frente. O mínimo é o de todos os alvos, para nenhum corte esticar.
            achados = buscar(consulta, *alvo.minimo, formato=alvo.ratio)
            vistos = {item["id"] for item in achados}
            achados += [item for item in buscar(consulta, *alvo.minimo) if item["id"] not in vistos]
        except WallhavenError as erro:
            logging.warning("Wallpaper picker search failed: %s", erro)
            na_thread_principal(
                self._show_empty, _("Não foi possível concluir a busca"), _("Verifique a conexão e tente novamente."), geracao, True
            )
            return
        if not achados:
            na_thread_principal(self._show_empty, self._texto_de_nada, _("Tente buscar por outro nome."), geracao)
            return
        itens = achados[:MAX_PAPEIS]
        na_thread_principal(self._receber, geracao, [(str(item["path"]), False) for item in itens])
        pixels = tuple(lado * self._escala for lado in _celula(*alvo.grade))
        # Seis de cada vez, na ordem da busca: uma por vez, com 15 s de limite cada, uma rede ruim seguraria a grade.
        with ThreadPoolExecutor(max_workers=6) as executor:
            arquivos = executor.map(lambda item: self._miniatura(str(item["thumb"]), pasta, pixels, cancelar), itens)
            for numero, arquivo in enumerate(arquivos):
                if self._closed or geracao != self._generation:
                    executor.shutdown(wait=False, cancel_futures=True)  # o que está na fila nem começa
                    return
                na_thread_principal(self._previa_pronta, geracao, numero, arquivo)
        na_thread_principal(self._fim_das_previas, geracao)

    @staticmethod
    def _miniatura(url: str, pasta: Optional[Path], pixels: tuple[int, ...], cancelar: Any) -> Optional[Path]:
        """Na thread de miniaturas: o arquivo da miniatura já cortada, ou None quando não deu."""
        try:
            return SeletorDePapelDeParede._baixar_miniatura(url, pasta, pixels, cancelar)
        except DownloadCancelado:
            return None
        except Exception:  # noqa: BLE001  (uma miniatura estranha não derruba a grade inteira)
            logging.exception("Wallpaper picker: preview crashed")
            return None

    @staticmethod
    def _baixar_miniatura(url: str, pasta: Optional[Path], pixels: tuple[int, ...], cancelar: Any) -> Optional[Path]:
        if pasta is None:
            return None
        cancelar()  # fechado ou busca trocada: nem baixa
        try:
            conteudo = download_bytes(url, timeout=15, max_bytes=MAX_IMAGE_BYTES, ao_progredir=cancelar)
        except DownloadCancelado:
            return None
        except requests.RequestException as erro:
            logging.info("Wallpaper picker: preview download failed (%s)", erro)
            return None
        # O nome nunca sai da resposta da API: um id "..\x" gravava fora da pasta.
        destino = pasta / f"{uuid4().hex}.png"
        cancelar()  # depois do `rmtree` do `fechar`, nada é gravado numa pasta que sobrou
        try:
            with Image.open(io.BytesIO(conteudo)) as imagem:
                enquadrar(imagem.convert("RGB"), *pixels).save(destino, "png", compress_level=1)
        except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError):
            destino.unlink(missing_ok=True)
            return None
        return destino

    # -- escolher: a segunda etapa ---------------------------------------------------------------

    def _corpo_do_download(self, url: str, animada: bool, geracao: int) -> None:
        pasta = self._pasta
        try:
            conteudo = download_bytes(
                url,
                timeout=45,
                max_bytes=MAX_WALLPAPER_BYTES,
                ao_progredir=lambda recebido, total: self._progredir(geracao, recebido, total),
            )
        except DownloadCancelado:
            return
        except requests.RequestException as erro:
            logging.warning("Could not download the wallpaper: %s: %s", type(erro).__name__, erro)
            self._falhou(geracao)
            return
        self._preparar(conteudo, self._sufixo(url), geracao, pasta)

    def _preparar(self, conteudo: bytes, sufixo: str, geracao: int, pasta: Optional[Path]) -> None:
        """Na thread: guarda a imagem na pasta do seletor e entrega a cópia reduzida à etapa de ajuste."""
        try:
            if pasta is None:
                raise OSError("seletor fechado")
            arquivo = pasta / f"escolhida{sufixo}"
            arquivo.write_bytes(conteudo)
            with Image.open(arquivo) as imagem:
                imagem = imagem.convert("RGB")
                escala = min(1.0, 2 * CAIXA_UNICA[1] * self._escala / max(1, imagem.height))
                previa = imagem.resize(
                    (max(1, round(imagem.width * escala)), max(1, round(imagem.height * escala))), Image.LANCZOS
                )
        # `DecompressionBombError` não herda de `OSError`: sem ela aqui a tela ficaria "Baixando…" para sempre.
        except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError) as erro:
            logging.warning("The chosen wallpaper could not be read: %s", erro)
            na_thread_principal(self._show_empty, _("Não foi possível abrir a imagem"), _("Tente outra imagem."), geracao, True)
            return
        na_thread_principal(self._ajuste_pronto, geracao, arquivo, previa)

    def _ajuste_pronto(self, geracao: int, arquivo: Path, previa: Image.Image) -> None:
        if geracao != self._generation or self._closed:
            return  # a pasta inteira cai em `fechar`
        self._original, self._previa = arquivo, previa
        formato = self._formatos
        alvos = [(tamanho, nome) for tamanho, nome in ((formato.paisagem, "paisagem"), (formato.retrato, "retrato")) if tamanho]
        # Sem alvo nenhum (monitor desligado com a tela aberta), o formato da grade ainda precisa de um corte.
        alvos = alvos or [(formato.grade, "paisagem")]
        linhas = []
        for (largura, altura), nome in alvos:
            caixa = CAIXA_UNICA if len(alvos) == 1 else CAIXA_EM_PE if altura > largura else CAIXA_DEITADA
            ver_largura, ver_altura = _caber(largura, altura, caixa)
            # Qual eixo a barra move depende das duas proporções: arte larga é cortada nas laterais, arte alta demais
            # em cima e embaixo. A barra só existe onde há o que deslizar: arte na proporção do monitor entra inteira.
            dica = (
                _("Arraste para escolher a faixa da imagem")
                if eixo_do_corte(previa.width, previa.height, largura, altura)
                else _("Arraste para escolher a altura da imagem")
            )
            linhas.append(
                {"orientacao": nome, "posicao": 50.0, "desliza": corta(previa.width, previa.height, largura, altura),
                 "dica": dica, "previa": "", "arquivo": None, "largura_da_previa": ver_largura, "altura_da_previa": ver_altura}
            )  # fmt: skip
        self._cortes.redefinir(linhas)
        for numero in range(len(linhas)):
            self._desenhar(numero)
        self._baixando = self._buscando = False
        self._ajustando = True
        self.estadoChanged.emit()
        self.baixandoChanged.emit()
        self.ajustandoChanged.emit()

    def _desenhar(self, numero: int) -> None:
        """Recorta a prévia do corte `numero` na faixa dele; o arquivo anterior daquele corte sai."""
        linha = self._cortes.linhas[numero]
        if self._previa is None or self._pasta is None:
            return
        quadro = enquadrar(
            self._previa, linha["largura_da_previa"] * self._escala, linha["altura_da_previa"] * self._escala, linha["posicao"] / 100
        )
        arquivo = self._pasta / f"{uuid4().hex}.png"
        quadro.save(arquivo, "png", compress_level=1)
        antigo, linha["arquivo"] = linha["arquivo"], arquivo
        linha["previa"] = QUrl.fromLocalFile(str(arquivo)).toString()
        if antigo is not None:
            self._apagar(antigo)

    @Slot(int, float)
    def definirPosicao(self, numero: int, valor: float) -> None:  # noqa: N802
        if self._ajustando and 0 <= numero < len(self._cortes.linhas):
            self._cortes.linhas[numero]["posicao"] = min(100.0, max(0.0, valor))
            self._desenhar(numero)
            self._cortes.mudou(numero)

    def _sair_do_ajuste(self) -> None:
        """Larga a imagem aberta (são dezenas de MB de bitmap) e as prévias dos cortes."""
        arquivos = [linha["arquivo"] for linha in self._cortes.linhas] + [self._original]
        self._cortes.redefinir([])
        self._original = self._previa = None
        if self._ajustando:
            self._ajustando = False
            self.ajustandoChanged.emit()
        # As prévias do ajuste soltam os arquivos abertos antes de saírem.
        _largar_arquivos_abertos()
        for arquivo in arquivos:
            if arquivo is not None:
                self._apagar(arquivo)

    @Slot()
    def voltar(self) -> None:
        """Da segunda etapa para a grade. As miniaturas que a escolha interrompeu saem: não voltariam sozinhas."""
        if self._so_arquivo:
            self.fechar()  # um arquivo do disco não tem grade para onde voltar
            return
        if not self._ajustando:
            return
        self._sair_do_ajuste()
        for numero in reversed(range(len(self._linhas))):
            if self._linhas[numero]["carregando"]:
                self.beginRemoveRows(QModelIndex(), numero, numero)
                del self._linhas[numero]
                self.endRemoveRows()
        if self._linhas:
            self.estadoChanged.emit()
        else:
            self._show_empty(_("Não foi possível carregar as pré-visualizações"), _("Tente novamente."), erro=True)

    @Slot()
    def usarEstaImagem(self) -> None:  # noqa: N802
        if not self._ajustando or self._original is None:
            return
        # Fora da pasta do seletor, que cai em `fechar`: o arquivo é de quem o recebe, até o Aplicar ou o Cancelar.
        copia: Optional[Path] = None
        try:
            descritor, nome = tempfile.mkstemp(prefix=self._prefixo_da_pasta, suffix=self._original.suffix)
            os.close(descritor)
            copia = Path(nome)
            shutil.copyfile(self._original, copia)
        except OSError as erro:
            logging.warning("Could not store the chosen wallpaper: %s", erro)
            if copia is not None:
                copia.unlink(missing_ok=True)
            self._sair_do_ajuste()
            self._show_empty(_("Não foi possível salvar a imagem"), _("Tente novamente."), erro=True)
            return
        # A orientação que não existe neste arranjo nunca sai do meio.
        faixas = {linha["orientacao"]: linha["posicao"] / 100 for linha in self._cortes.linhas}
        padrao = Posicoes()
        posicoes = Posicoes(retrato=faixas.get("retrato", padrao.retrato), paisagem=faixas.get("paisagem", padrao.paisagem))
        if (destino := self._destino) is None:
            copia.unlink(missing_ok=True)
        else:
            destino.entregar_papel_baixado(copia, posicoes)
        self.fechar()

    @Slot()
    def naoTrocar(self) -> None:  # noqa: N802
        if self._aberto:
            if (destino := self._destino) is not None:
                destino.nao_trocar_papel()
            self.fechar()

    @Slot()
    def buscarAgora(self) -> None:  # noqa: N802
        if not self._ajustando:
            super().buscarAgora()

    @Slot()
    def fechar(self) -> None:
        self._sair_do_ajuste()
        super().fechar()


class SeletorDaSteam(BuscaDoSeletor, QAbstractListModel):
    """Qual jogo da Steam é este: a lista de candidatos da loja para o título digitado.

    Serve à linha "AppID da Steam" (escolher só preenche o campo) e ao "Buscar dados na Steam pelo título"
    quando nenhum candidato é confiável (escolher continua a busca de metadados). Escolher baixa os dados
    do jogo e os entrega ao diálogo de edição (`steam_escolhida`). Só na thread principal; o que as threads
    entregam a um seletor que já fechou, ou que já buscou outra coisa, é descartado.
    """

    class Papel(IntEnum):
        Nome = Qt.ItemDataRole.UserRole + 1
        Appid = Qt.ItemDataRole.UserRole + 2
        Ano = Qt.ItemDataRole.UserRole + 3

    abertoChanged = Signal()  # noqa: N815
    buscaChanged = Signal()  # noqa: N815
    estadoChanged = Signal()  # noqa: N815

    # Mais que nos outros seletores: cada pausa na digitação é um pedido à loja da Steam, que limita a frequência.
    atraso_da_busca_ms = 700

    def __init__(self, destino: Any, parent: Any = None) -> None:
        super().__init__(parent)
        # Referência fraca, como nos seletores do SteamGridDB (ver `_SeletorDoSteamGridDB`).
        self._destino_fraco = weakref.ref(destino)
        # O `SteamAPIHelper` do app (ou um próprio, na falta dele); os testes põem um falso aqui.
        self.helper: Optional[SteamAPIHelper] = None
        self._linhas: list[dict[str, str]] = []
        self._aberto = False
        self._generation = 0
        self._closed = True
        self._last_query: Optional[str] = None
        self._busca = ""
        self._buscando = False
        self._vazio = False
        self._erro = False
        self._titulo = ""
        self._descricao = ""
        self._para_metadados = False

    @property
    def _destino(self) -> Any:
        return self._destino_fraco()

    def helper_da_steam(self) -> SteamAPIHelper:
        # O mesmo limitador do app inteiro: um por busca vazaria a thread de reposição dele.
        if self.helper is None:
            gerente = shared.store.managers.get(SteamAPIManager) if shared.store is not None else None
            self.helper = gerente.steam_api_helper if gerente else SteamAPIHelper(SteamRateLimiter())
        return self.helper

    # -- o modelo --------------------------------------------------------------------------------

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802
        return {
            self.Papel.Nome: QByteArray(b"nome"),
            self.Papel.Appid: QByteArray(b"appid"),
            self.Papel.Ano: QByteArray(b"ano"),
        }

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._linhas)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._linhas):
            return None
        linha = self._linhas[index.row()]
        match role:
            case self.Papel.Nome:
                return linha["nome"]
            case self.Papel.Appid:
                return linha["appid"]
            case self.Papel.Ano:
                return linha["ano"]
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
        """A busca da lista, ou a dos dados do jogo escolhido, ainda corre."""
        return self._buscando

    @Property(bool, notify=estadoChanged)
    def vazio(self) -> bool:
        return self._vazio

    @Property(bool, notify=estadoChanged)
    def erro(self) -> bool:
        return self._erro

    @Property(str, notify=estadoChanged)
    def tituloDoEstado(self) -> str:  # noqa: N802
        return self._titulo

    @Property(str, notify=estadoChanged)
    def descricaoDoEstado(self) -> str:  # noqa: N802
        return self._descricao

    # -- buscar ----------------------------------------------------------------------------------

    @Slot(str)
    def abrir(self, nome: str) -> None:
        """Pela linha do AppID: escolher só preenche o campo."""
        self._abrir(nome, False)

    def abrir_para_metadados(self, nome: str) -> None:
        """Pela busca de metadados: escolher continua a busca com o jogo escolhido."""
        self._abrir(nome, True)

    def _abrir(self, nome: str, para_metadados: bool) -> None:
        if self._aberto:
            self.fechar()
        self._closed = False
        self._aberto = True
        self._para_metadados = para_metadados
        self._busca = clean_game_name(nome)
        self.abertoChanged.emit()
        self.buscaChanged.emit()
        self.search()

    @Slot()
    def buscarAgora(self) -> None:  # noqa: N802
        """Enter no campo: busca já, sem esperar o atraso."""
        if self._aberto:
            self.search()

    def search(self) -> None:
        self._generation += 1
        geracao = self._generation
        self._cancelar_debounce()
        self._limpar()
        consulta = self._busca.strip()
        self._last_query = consulta
        if not consulta:
            self._show_empty(_("Digite o nome de um jogo"))
            return
        self._vazio = self._erro = False
        self._buscando = True
        self.estadoChanged.emit()
        threading.Thread(
            target=self._thread_da_busca, args=(consulta, geracao, self.helper_da_steam()), daemon=True
        ).start()

    def _show_empty(self, titulo: str, descricao: str = "", generation: Optional[int] = None, erro: bool = False) -> None:
        if generation is not None and (generation != self._generation or self._closed):
            return
        self._titulo, self._descricao = titulo, descricao
        self._vazio, self._erro, self._buscando = True, erro, False
        self.estadoChanged.emit()

    def _thread_da_busca(self, consulta: str, geracao: int, helper: SteamAPIHelper) -> None:
        try:
            candidatos = helper.find_candidates(clean_for_search(consulta))
        except SteamGameNotFoundError:
            na_thread_principal(self._show_empty, _("Nenhum jogo encontrado"), _("Tente buscar por outro nome."), geracao)
            return
        except Exception:  # noqa: BLE001  (a tela "carregando" não pode ficar presa por uma resposta inesperada)
            logging.warning("Steam picker search failed", exc_info=True)
            na_thread_principal(
                self._show_empty,
                _("Não foi possível concluir a busca"),
                _("Verifique a conexão e tente novamente."),
                geracao,
                True,
            )
            return
        na_thread_principal(self._receber, geracao, candidatos)

    def _limpar(self) -> None:
        if self._linhas:
            self.beginResetModel()
            self._linhas = []
            self.endResetModel()

    def _receber(self, geracao: int, candidatos: list[tuple[dict, Any]]) -> None:
        if geracao != self._generation or self._closed:
            return
        linhas = [
            # shortcut: a busca da loja não traz o ano de lançamento; o papel `ano` fica vazio; só preenche se a busca passar a consultar o appdetails de cada candidato.
            {"nome": str(candidato.get("name", "")), "appid": str(candidato.get("id", "")), "ano": ""}
            for candidato, _combina in candidatos
            if candidato.get("id")
        ]
        if not linhas:
            self._show_empty(_("Nenhum jogo encontrado"), _("Tente buscar por outro nome."), geracao)
            return
        self.beginResetModel()
        self._linhas = linhas
        self.endResetModel()
        self._buscando = False
        self.estadoChanged.emit()

    # -- escolher --------------------------------------------------------------------------------

    @Slot(int)
    def escolher(self, indice: int) -> None:
        if not self._aberto or self._buscando or not 0 <= indice < len(self._linhas):
            return
        # Invalida a busca da lista e qualquer escolha anterior: só vale a resposta desta.
        self._generation += 1
        self._cancelar_debounce()
        self._buscando = True
        self.estadoChanged.emit()
        args = (self._linhas[indice]["appid"], self._generation, self.helper_da_steam())
        threading.Thread(target=self._thread_da_escolha, args=args, daemon=True).start()

    def _thread_da_escolha(self, appid: str, geracao: int, helper: SteamAPIHelper) -> None:
        try:
            dados = helper.get_api_data(appid)
        except SteamNotAGameError:
            na_thread_principal(self._show_empty, _("Este item não é um jogo"), _("Escolha outro resultado."), geracao, True)
            return
        except Exception:  # noqa: BLE001
            logging.warning("Steam picker fetch failed", exc_info=True)
            na_thread_principal(
                self._show_empty,
                _("Não foi possível obter os dados"),
                _("Verifique a conexão e tente novamente."),
                geracao,
                True,
            )
            return
        na_thread_principal(self._escolhido, geracao, appid, dados)

    def _escolhido(self, geracao: int, appid: str, dados: dict) -> None:
        if geracao != self._generation or self._closed:
            return
        destino, para_metadados = self._destino, self._para_metadados
        self.fechar()
        if destino is not None:
            destino.steam_escolhida(appid, dados, para_metadados)

    @Slot()
    def fechar(self) -> None:
        """Cancela a busca pendente; o que as threads ainda entregam é descartado."""
        self._closed = True
        self._generation += 1
        self._cancelar_debounce()
        self._aberto = self._buscando = self._vazio = self._erro = False
        self._limpar()
        self.abertoChanged.emit()
        self.estadoChanged.emit()


def pasta_do_ludusavi() -> Path:
    return backup_de_saves._pasta_config()  # noqa: SLF001


class SeletorDoLudusavi(QAbstractListModel):
    """Escolher, na lista de jogos do Ludusavi, o jogo cujos saves entram no backup.

    O nome certo só quem conhece o jogo sabe dizer; o app apenas oferece a lista do `manifest.yaml`
    (dezenas de milhares de nomes), lida fora da thread principal e filtrada enquanto se digita. A opção
    "Nenhum (desliga o backup)" não é uma linha da lista: a tela a desenha acima dela (`escolherNenhum`).
    """

    class Papel(IntEnum):
        Nome = Qt.ItemDataRole.UserRole + 1

    abertoChanged = Signal()  # noqa: N815
    buscaChanged = Signal()  # noqa: N815
    estadoChanged = Signal()  # noqa: N815

    def __init__(self, destino: Any, parent: Any = None) -> None:
        super().__init__(parent)
        self._destino_fraco = weakref.ref(destino)
        self._todos: list[str] = []
        self._chaves: list[str] = []
        self._filtrados: list[str] = []
        self._aberto = False
        self._geracao = 0
        self._busca = ""
        self._atual = ""
        self._carregando = False
        self._erro = False

    @property
    def _destino(self) -> Any:
        return self._destino_fraco()

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802
        return {self.Papel.Nome: QByteArray(b"nome")}

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._filtrados)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if index.isValid() and 0 <= index.row() < len(self._filtrados) and role == self.Papel.Nome:
            return self._filtrados[index.row()]
        return None

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
            self._filtrar()

    @Property(bool, notify=estadoChanged)
    def carregando(self) -> bool:
        return self._carregando

    @Property(bool, notify=estadoChanged)
    def erro(self) -> bool:
        return self._erro

    @Property(bool, notify=estadoChanged)
    def vazio(self) -> bool:
        """A lista foi lida e o filtro não deixou nada."""
        return self._aberto and not self._carregando and not self._erro and not self._filtrados

    @Property(str, notify=estadoChanged)
    def tituloDoEstado(self) -> str:  # noqa: N802
        return _("Não foi possível ler a lista de jogos do Ludusavi.") if self._erro else _("Nenhum jogo encontrado")

    @Property(int, notify=estadoChanged)
    def indiceAtual(self) -> int:  # noqa: N802
        """A posição, na lista filtrada, do jogo que já estava escolhido (-1 se não está)."""
        try:
            return self._filtrados.index(self._atual) if self._atual else -1
        except ValueError:
            return -1

    @Slot(str)
    def abrir(self, atual: str) -> None:
        if self._aberto:
            self.fechar()
        self._aberto = True
        self._geracao += 1
        self._atual, self._busca = atual, ""
        self._carregando, self._erro = True, False
        self.abertoChanged.emit()
        self.buscaChanged.emit()
        self.estadoChanged.emit()
        threading.Thread(target=self._ler, args=(self._geracao, pasta_do_ludusavi()), daemon=True).start()

    def _ler(self, geracao: int, pasta: Path) -> None:
        try:
            nomes = ludusavi.nomes_do_manifesto(pasta)
        except Exception as erro:  # noqa: BLE001  (OSError, ValueError e qualquer outra: a tela não fica carregando)
            logging.warning("Não foi possível ler a lista de jogos do Ludusavi: %s", erro)
            na_thread_principal(self._mostrar_erro, geracao)
            return
        na_thread_principal(self._mostrar, geracao, nomes, [nome.casefold() for nome in nomes])

    def _mostrar_erro(self, geracao: int) -> None:
        if geracao == self._geracao and self._aberto:
            self._carregando, self._erro = False, True
            self.estadoChanged.emit()

    def _mostrar(self, geracao: int, nomes: list[str], chaves: list[str]) -> None:
        if geracao != self._geracao or not self._aberto:
            return
        self._todos, self._chaves = nomes, chaves
        self._carregando = False
        self._filtrar()

    def _filtrar(self) -> None:
        termo = self._busca.strip().casefold()
        self.beginResetModel()
        self._filtrados = [n for n, c in zip(self._todos, self._chaves, strict=True) if termo in c]
        self.endResetModel()
        self.estadoChanged.emit()

    @Slot(int)
    def escolher(self, indice: int) -> None:
        if self._aberto and 0 <= indice < len(self._filtrados):
            self._entregar(self._filtrados[indice])

    @Slot()
    def escolherNenhum(self) -> None:  # noqa: N802
        if self._aberto:
            self._entregar("")

    def _entregar(self, nome: str) -> None:
        destino = self._destino
        self.fechar()
        if destino is not None:
            destino.ludusavi_escolhido(nome)

    @Slot()
    def fechar(self) -> None:
        self._geracao += 1
        self._aberto = self._carregando = self._erro = False
        self.beginResetModel()
        self._todos, self._chaves, self._filtrados = [], [], []
        self.endResetModel()
        self.abertoChanged.emit()
        self.estadoChanged.emit()
