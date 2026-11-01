# detalhes.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O que a página de detalhes de um jogo mostra: textos prontos, logo e fundo desfocado.

As funções puras repetem as regras de `show_details_page` e vizinhas da janela GTK: recebem o
`Jogo` e devolvem o texto da linha, ou `""` quando a linha some. `DetalhesDoJogo` é o modelo que
o QML lê (`detalhes`): segue um jogo por vez, atualiza-se quando ele muda e busca o logo e o
desfoque fora da thread principal.
"""

import ctypes
import logging
import threading
import weakref
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from PySide6.QtCore import Property, QCoreApplication, QEvent, QObject, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtQuick import QQuickImageProvider

from cartridges.jogo import STATUS_LABELS, Jogo, status_label
from cartridges.modelos.ordem import Linha, _url_da_capa  # noqa: PLC2701
from cartridges.utils import copias_animadas, desfoque, game_logo, session_log
from cartridges.utils.format_playtime import format_playtime, format_size
from cartridges.utils.hltb import format_hltb_time
from cartridges.utils.open_uri import abrir_url
from cartridges.utils.relative_date import relative_date
from cartridges.utils.steam import format_release_date
from cartridges.utils.thread_principal import na_thread_principal

_COLUNAS_HLTB = (_("História"), _("Extras"), _("Completista"))
_CHAVES_HLTB = ("hltb_main", "hltb_main_extra", "hltb_completionist")
_RESERVA = desfoque.LUMINANCIA_RESERVA
_BUSCAS = {
    "igdb": "https://www.igdb.com/search?type=1&q=",
    "sgdb": "https://www.steamgriddb.com/search/grids?term=",
    "pcgw": "https://www.pcgamingwiki.com/w/index.php?search=",
    "hltb": "https://howlongtobeat.com/?q=",
}


# -- regras puras ------------------------------------------------------------------------------


def data_de_lancamento(jogo: Jogo) -> str:
    data = format_release_date(jogo.release_date)
    # A variável é a data de lançamento do jogo
    return _("Data de lançamento: {}").format(data) if data else ""


def nota(jogo: Jogo) -> str:
    """Cheias até a nota, vazias depois: cinco símbolos sempre, para comparar pelo desenho."""
    estrelas = jogo.stars
    # A variável são as cinco estrelas, cheias ou vazias
    return _("Minha nota: {}").format("★" * estrelas + "☆" * (5 - estrelas)) if estrelas else ""


def metacritic(jogo: Jogo) -> str:
    # A variável é a nota do jogo no Metacritic
    return _("Metacritic: {}").format(jogo.metacritic) if jogo.metacritic is not None else ""


def avaliacoes(jogo: Jogo) -> str:
    # A variável é o resumo das avaliações da Steam, por exemplo "Muito positivas"
    return _("Avaliações: {}").format(jogo.steam_review) if jogo.steam_review else ""


def controle(jogo: Jogo) -> str:
    """Só os dois estados que a Steam afirma: sem nenhum, a linha some em vez de dizer "sem suporte"."""
    return {
        "full": _("Compatibilidade total com controle"),
        "partial": _("Compatibilidade parcial com controle"),
    }.get(jogo.controller_support or "", "")


def adicionado(jogo: Jogo) -> str:
    # A variável é a data em que o jogo foi adicionado
    return _("Adicionado: {}").format(relative_date(jogo.added))


def jogado_por_ultimo(jogo: Jogo) -> str:
    data = relative_date(jogo.last_played) if jogo.last_played else _("nunca")
    # A variável é a data em que o jogo foi jogado pela última vez
    return _("Jogado por último: {}").format(data)


def tempo_de_jogo(jogo: Jogo) -> str:
    # A variável é o tempo total de jogo
    return _("Tempo de jogo: {}").format(format_playtime(jogo.playtime)) if jogo.playtime else ""


def tamanho(jogo: Jogo) -> str:
    """Some num zerado (a instalação não existe mais) e num jogo ainda não medido."""
    texto = "" if jogo.zerado else format_size(jogo.install_size)
    # A variável é o tamanho da instalação, por exemplo "87,4 GB"
    return _("Tamanho: {}").format(texto) if texto else ""


def rotulo_do_status(jogo: Jogo) -> str:
    return status_label(jogo.status) or _("Definir status")


def hltb(jogo: Jogo) -> dict:
    """O bloco do HowLongToBeat: um cartão de células, ou a tabela de capítulos (nunca os dois).

    Cada célula vem com `separador`: a linha vertical à esquerda dela, que só existe quando há
    uma célula visível antes. Ligá-lo à célula da direita é o que faz um buraco no meio colapsar
    certo ("História" e "Completista" juntos ficam com um separador só). Sem células nem
    capítulos, o bloco inteiro some.
    """
    colunas = list(_COLUNAS_HLTB)
    if capitulos := (jogo.hltb_chapters or []):
        return {
            "colunas": colunas,
            "celulas": [],
            "capitulos": [
                {
                    # A variável é o número do capítulo
                    "rotulo": _("Capítulo {}").format(capitulo.get("number") or numero),
                    "valores": [format_hltb_time(capitulo.get(chave)) for chave in _CHAVES_HLTB],
                }
                for numero, capitulo in enumerate(capitulos, start=1)
            ],
        }
    visiveis = [bool(segundos) for segundos in jogo.hltb_times]
    celulas = [
        {"rotulo": rotulo, "valor": format_hltb_time(segundos), "separador": any(visiveis[:i])}
        for i, (rotulo, segundos) in enumerate(zip(colunas, jogo.hltb_times))
        if visiveis[i]
    ]
    return {"colunas": colunas, "celulas": celulas, "capitulos": []}


def mostra_anotacao(jogo: Jogo) -> bool:
    """O botão da anotação: em "Jogando" ou com texto (senão o texto ficaria preso). Num zerado, só com texto."""
    texto = (jogo.notes or "").strip()
    if jogo.zerado:
        return bool(texto)
    return jogo.status == "playing" or bool(texto)


def dica_da_anotacao(jogo: Jogo) -> str:
    return _("Ver onde você parou neste jogo") if jogo.zerado else _("Anotar onde você parou neste jogo")


def opacidade_do_fundo(luminancia: tuple[float, float], escuro: bool, alto_contraste: bool) -> float:
    if alto_contraste:
        return 0.3
    return 1 - luminancia[0] if escuro else luminancia[1]


class _AltoContraste(ctypes.Structure):
    _fields_ = (("cbSize", ctypes.c_uint), ("dwFlags", ctypes.c_uint), ("padrao", ctypes.c_wchar_p))


def _alto_contraste() -> bool:
    """Se o Windows está em alto contraste (SPI_GETHIGHCONTRAST, bit HCF_HIGHCONTRASTON)."""
    estado = _AltoContraste(ctypes.sizeof(_AltoContraste), 0, None)
    try:
        if ctypes.windll.user32.SystemParametersInfoW(0x42, estado.cbSize, ctypes.byref(estado), 0):
            return bool(estado.dwFlags & 1)
    except (AttributeError, OSError):
        pass
    return False


# -- o fundo ------------------------------------------------------------------------------------


class ProvedorDeDesfoque(QQuickImageProvider):
    """Serve o PNG do desfoque do jogo mostrado em `image://desfoque/<id>?v=<n>`."""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._lock = threading.Lock()
        self._png: dict[str, bytes] = {}

    def guardar(self, game_id: str, png: bytes) -> None:
        """Só o jogo mostrado precisa do seu desfoque: o anterior sai."""
        with self._lock:
            self._png = {game_id: png}

    def requestImage(self, id: str, size: Any, requested_size: Any) -> QImage:  # noqa: A002, N802, ARG002
        with self._lock:
            png = self._png.get(unquote(id.split("?")[0]))
        return QImage.fromData(png, "PNG") if png else QImage()


# Todas as propriedades e o valor de quando nenhum jogo foi mostrado.
_PADRAO: dict[str, Any] = {
    **dict.fromkeys(
        (
            "jogoId", "nome", "capa", "capaAnimada", "logo", "desenvolvedora", "publicadora",
            "dataDeLancamento", "nota", "metacritic", "avaliacoes", "genero", "controle", "descricao",
            "adicionado", "jogadoPorUltimo", "tempoDeJogo", "tamanho", "rotuloDoStatus",
            "dicaDaAnotacao", "anotacao", "fundo",
        ),
        "",
    ),
    **dict.fromkeys(
        ("controleRecomendado", "zerado", "carregando", "temAtualizacao", "mostraAnotacao", "anotacaoEditavel", "temSessoes"),
        False,
    ),
    "larguraDoLogo": 0,
    "hltb": {},
    "opacidadeDoFundo": 0.3,
}  # fmt: skip


def _prop(tipo: Any, nome: str, notify: Any) -> Property:
    return Property(tipo, lambda self: self._v[nome], notify=notify)


def _entregar(fraco: Any, nome: str, *args: Any) -> None:
    """Entrega na principal, se o modelo ainda existe."""
    if (modelo := fraco()) is not None:
        getattr(modelo, nome)(*args)


# As threads seguram o modelo só por referência fraca: um QObject sem pai finalizado na thread de trabalho
# (a última referência caindo ali) dá access violation. Se o modelo morreu, o resultado é descartado.
def _buscar_logo(fraco: Any, jogo: Jogo) -> None:
    caminho = None
    try:
        caminho = game_logo.fetch_logo(jogo)
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        # Sem a entrega abaixo o id ficaria na lista de buscas para sempre, e o jogo nunca mais teria logo.
        logging.warning("Erro inesperado ao buscar o logo de %s", jogo.name, exc_info=True)
    finally:
        na_thread_principal(_entregar, fraco, "_logo_chegou", jogo.game_id, caminho)


def _calcular_fundo(fraco: Any, game_id: str, chave: str, caminho: Path) -> None:
    resultado = None
    try:
        resultado = desfoque.calcular(caminho)
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        # Sem a entrega abaixo a chave ficaria marcada e o fundo parado até a capa mudar.
        logging.warning("Erro inesperado ao desfocar a capa de %s", game_id, exc_info=True)
    finally:
        na_thread_principal(_entregar, fraco, "_fundo_chegou", game_id, chave, resultado)


class DetalhesDoJogo(QObject):
    """O jogo da página de detalhes, em propriedades que o QML lê. Só na thread principal."""

    # Um só aviso para todas as propriedades: a página é pequena e reavaliar tudo custa nada.
    alterado = Signal()
    # O jogo mostrado foi excluído, removido ou saiu dos Jogos Zerados: a página deve fechar.
    sair = Signal()

    _p = partial(_prop, notify=alterado)
    jogoId = _p(str, "jogoId")  # noqa: N815
    nome = _p(str, "nome")
    capa = _p(str, "capa")
    capaAnimada = _p(str, "capaAnimada")  # noqa: N815
    logo = _p(str, "logo")
    larguraDoLogo = _p(int, "larguraDoLogo")  # noqa: N815
    desenvolvedora = _p(str, "desenvolvedora")
    publicadora = _p(str, "publicadora")
    dataDeLancamento = _p(str, "dataDeLancamento")  # noqa: N815
    nota = _p(str, "nota")
    metacritic = _p(str, "metacritic")
    avaliacoes = _p(str, "avaliacoes")
    genero = _p(str, "genero")
    controle = _p(str, "controle")
    controleRecomendado = _p(bool, "controleRecomendado")  # noqa: N815
    descricao = _p(str, "descricao")
    hltb = _p("QVariantMap", "hltb")
    adicionado = _p(str, "adicionado")
    jogadoPorUltimo = _p(str, "jogadoPorUltimo")  # noqa: N815
    tempoDeJogo = _p(str, "tempoDeJogo")  # noqa: N815
    tamanho = _p(str, "tamanho")
    rotuloDoStatus = _p(str, "rotuloDoStatus")  # noqa: N815
    zerado = _p(bool, "zerado")
    carregando = _p(bool, "carregando")
    temAtualizacao = _p(bool, "temAtualizacao")  # noqa: N815
    mostraAnotacao = _p(bool, "mostraAnotacao")  # noqa: N815
    dicaDaAnotacao = _p(str, "dicaDaAnotacao")  # noqa: N815
    anotacao = _p(str, "anotacao")
    anotacaoEditavel = _p(bool, "anotacaoEditavel")  # noqa: N815
    temSessoes = _p(bool, "temSessoes")  # noqa: N815
    fundo = _p(str, "fundo")
    opacidadeDoFundo = _p(float, "opacidadeDoFundo")  # noqa: N815
    del _p
    # Os status do menu, [valor, rótulo]: uma só fonte, a do `jogo`.
    statusOpcoes = Property("QVariantList", lambda self: [[k, v] for k, v in STATUS_LABELS.items()], constant=True)  # noqa: N815

    def __init__(self, store: Any, parent: QObject | None = None, avisos: Any = None) -> None:
        super().__init__(parent)
        self._avisos = avisos  # a FilaDeAvisos, para o "excluído"
        self.provedor = ProvedorDeDesfoque()
        self._store = store
        self._v: dict[str, Any] = dict(_PADRAO)
        # Só referência fraca ao jogo: a página não pode prender um jogo que a store já soltou.
        self._jogo: weakref.ref | None = None
        self._removido = False
        # O jogo que a página segue agora; "" depois de `sair`/`esquecer`: resultado atrasado é descartado.
        self._atual = ""
        self._luminancia = _RESERVA
        self._versao_do_fundo = 0
        self._chave_do_fundo = ""
        self._buscas_de_logo: set[str] = set()
        # O `jogo_excluido` sai de threads do importador: a conexão enfileirada leva à principal.
        store.jogo_excluido.connect(self._excluido, Qt.ConnectionType.QueuedConnection)
        # Referência fraca: o gancho é global e o modelo pode morrer antes (como o da grade).
        fraca = weakref.ref(self)
        copias_animadas.soltar_da_pagina = lambda game_id: (m := fraca()) and m.soltar_copia(game_id)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._tema_mudou)
        # O alto contraste não tem sinal próprio no Qt 6.12; ligá-lo troca a paleta, e é por ela que reavaliamos.
        QGuiApplication.instance().paletteChanged.connect(self._tema_mudou)

    @property
    def loja(self) -> Any:
        """A loja de onde saem os jogos (outros modelos buscam o jogo por ela)."""
        return self._store

    # -- seguir o jogo ---------------------------------------------------------------------------

    @Slot(str, result=bool)
    def mostrar(self, game_id: str) -> bool:
        """Passa a seguir o jogo; `False` (sem mudar nada) se ele não está na loja."""
        jogo = self._store.get(game_id)
        if jogo is None:
            return False
        self._desligar()
        trocou = self._v["jogoId"] != game_id
        self._jogo = weakref.ref(jogo)
        self._atual = game_id
        self._removido = jogo.removed
        # Conexão para o próprio QObject: o `atualizado` também sai de outras threads, e chega aqui na principal.
        jogo.atualizado.connect(self._ao_atualizar)
        self._atualizar(jogo, trocou)
        return True

    def _desligar(self) -> None:
        if self._jogo is not None and (antigo := self._jogo()) is not None:
            try:
                antigo.atualizado.disconnect(self._ao_atualizar)
            except (RuntimeError, TypeError):
                pass
        self._jogo = None
        self._atual = ""
        # Um desfoque a caminho não pode travar o fundo se o mesmo jogo voltar a ser mostrado.
        self._chave_do_fundo = ""

    def soltar_copia(self, game_id: str) -> None:
        """Esvazia a cópia animada da página, e o ``AnimatedImage`` larga o arquivo. Só na principal."""
        if game_id == self._atual and self._v["capaAnimada"]:
            self._mesclar({"capaAnimada": ""})
            # O ``AnimatedImage`` só larga o arquivo quando destrói o filme, num ``deleteLater``.
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    @Slot()
    def esquecer(self) -> None:
        """A página fechou: para de seguir o jogo e descarta o que ainda estiver a caminho."""
        self._desligar()

    @Slot()
    def _ao_atualizar(self) -> None:
        jogo = self._jogo() if self._jogo else None
        if jogo is None:
            return
        removido, self._removido = self._removido, jogo.removed
        if jogo.removed and (not removido or not jogo.zerado):
            self._desligar()  # a página fecha: sem repetir o `sair` nem buscar logo para quem ninguém vê
            self.sair.emit()
            return
        self._atualizar(jogo, False)

    @Slot(str)
    def _excluido(self, game_id: str) -> None:
        if game_id == self._atual:
            self._desligar()
            self.sair.emit()

    def _atualizar(self, jogo: Jogo, trocou: bool) -> None:
        linha = Linha.de(jogo)
        campos = {
            "jogoId": jogo.game_id, "nome": jogo.name, "capa": linha.capa, "capaAnimada": linha.capa_animada,
            "desenvolvedora": jogo.developer or "", "publicadora": jogo.publisher or "",
            "dataDeLancamento": data_de_lancamento(jogo), "nota": nota(jogo), "metacritic": metacritic(jogo),
            "avaliacoes": avaliacoes(jogo), "genero": jogo.genre or "", "controle": controle(jogo),
            "controleRecomendado": bool(jogo.gamepad_recommended), "descricao": jogo.description or "",
            "hltb": hltb(jogo), "adicionado": adicionado(jogo), "jogadoPorUltimo": jogado_por_ultimo(jogo),
            "tempoDeJogo": tempo_de_jogo(jogo), "tamanho": tamanho(jogo),
            "rotuloDoStatus": rotulo_do_status(jogo), "zerado": jogo.zerado, "carregando": jogo.loading > 0,
            "temAtualizacao": bool(jogo.has_update and not jogo.zerado),
            "mostraAnotacao": mostra_anotacao(jogo), "dicaDaAnotacao": dica_da_anotacao(jogo),
            "anotacao": jogo.notes or "", "anotacaoEditavel": not jogo.zerado,
        }  # fmt: skip
        if trocou:
            # O logo e o fundo do jogo anterior não ficam atrás dos metadados deste.
            campos.update(logo="", larguraDoLogo=0, fundo="")
            self._luminancia = _RESERVA
            self._chave_do_fundo = ""
        campos.update(self._logo(jogo))
        campos.update(self._fundo(jogo, linha.capa))
        self._mesclar(campos)

    def _mesclar(self, campos: dict[str, Any]) -> None:
        novo = {**self._v, **campos}
        tema = QGuiApplication.styleHints().colorScheme()
        # Sem esquema de cores no sistema (Unknown) vale o 0.3 do alto contraste, como na janela GTK.
        fixo = _alto_contraste() or tema == Qt.ColorScheme.Unknown
        # O total só abre a lista das sessões que o formaram se elas existem (o tempo restaurado de um backup é um
        # total sem sessões); relido a cada mudança, e só de um jogo com tempo.
        novo["temSessoes"] = bool(novo["tempoDeJogo"]) and bool(session_log.load(novo["jogoId"]))
        novo["opacidadeDoFundo"] = opacidade_do_fundo(self._luminancia, tema == Qt.ColorScheme.Dark, fixo)
        if novo != self._v:
            self._v = novo
            self.alterado.emit()

    def _tema_mudou(self, *_args: Any) -> None:
        self._mesclar({})

    # -- ações -----------------------------------------------------------------------------------

    def _mostrado(self) -> Jogo | None:
        return self._jogo() if self._jogo else None

    @Slot()
    def jogar(self) -> None:
        # O botão some na tela de um zerado; isto cobre o que chega por outro caminho.
        if (jogo := self._mostrado()) is not None and not jogo.zerado:
            jogo.launch()

    @Slot()
    def remover(self) -> None:
        # Um zerado já saiu da biblioteca: o "Desfazer" o traria de volta desinstalado.
        if (jogo := self._mostrado()) is not None and not jogo.zerado:
            jogo.remove_game()  # o `atualizado` dele fecha a página (`sair`)

    @Slot()
    def excluir(self) -> None:
        # De novo o `zerado`: a pergunta ficou na tela e o jogo pode ter mudado.
        if (jogo := self._mostrado()) is None or not jogo.zerado:
            return
        nome = jogo.name
        self._store.excluir(jogo)  # o `jogo_excluido` dela fecha a página (`sair`)
        if self._avisos is not None:
            # A variável é o nome do jogo
            self._avisos.adicionar(_("{} excluído").format(nome))

    @Slot(str)
    def definirStatus(self, valor: str) -> None:  # noqa: N802
        if (jogo := self._mostrado()) is None:
            return
        # O `atualizado` do `update` decide: zerado desinstalado e fora dos zerados fecha a página
        # (`sair`); zerado reinstalado volta à biblioteca e a página só troca de modo.
        jogo.definir_status(valor)
        jogo.save()
        jogo.update()

    @Slot(str)
    def buscarEm(self, site: str) -> None:  # noqa: N802
        if (jogo := self._mostrado()) is None:
            return
        if site == "hltb" and jogo.hltb_id:
            # Quem já tem o id do HowLongToBeat vai direto à página do jogo.
            abrir_url(f"https://howlongtobeat.com/game/{jogo.hltb_id}")
        elif prefixo := _BUSCAS.get(site):
            abrir_url(prefixo + quote(jogo.name))

    @Slot(str)
    def gravarAnotacao(self, texto: str) -> None:  # noqa: N802
        jogo = self._mostrado()
        # A caixa de um zerado é só leitura: fechar não grava nada.
        if jogo is None or jogo.zerado:
            return
        texto = texto.strip()
        if texto == (jogo.notes or ""):
            return
        jogo.notes = texto
        jogo.save()
        jogo.update()

    @Slot()
    def abrirAtualizacao(self) -> None:
        if (jogo := self._mostrado()) is not None and jogo.has_update and not jogo.zerado:
            # A URL vem de um feed de terceiros: o esquema é conferido em `abrir_url`.
            abrir_url(jogo.update_url)

    @Slot()
    def confirmarAtualizacao(self) -> None:
        if (jogo := self._mostrado()) is not None:
            jogo.dismiss_update()

    # -- logo ------------------------------------------------------------------------------------

    def _logo(self, jogo: Jogo) -> dict[str, Any]:
        """Os campos do logo em disco, se vale para o jogo; senão o título, e a busca em segundo plano."""
        caminho = game_logo.cached_logo_path(jogo)
        if caminho and (carregado := game_logo.load_logo(caminho)):
            return {"logo": _url_da_capa(carregado[0]), "larguraDoLogo": carregado[1]}
        if game_logo.logo_lookup_needed(jogo) and jogo.game_id not in self._buscas_de_logo:
            self._buscas_de_logo.add(jogo.game_id)
            threading.Thread(target=_buscar_logo, args=(weakref.ref(self), jogo), daemon=True).start()
        return {"logo": "", "larguraDoLogo": 0}

    def _logo_chegou(self, game_id: str, caminho: Path | None) -> None:
        self._buscas_de_logo.discard(game_id)
        # Julgado contra o jogo na tela, não contra um contador: voltar ao mesmo jogo com a busca ainda
        # de pé não pode descartar o resultado dela.
        if not caminho or game_id != self._atual:
            return
        if carregado := game_logo.load_logo(caminho):
            self._mesclar({"logo": _url_da_capa(carregado[0]), "larguraDoLogo": carregado[1]})

    # -- fundo -----------------------------------------------------------------------------------

    def _fundo(self, jogo: Jogo, chave: str) -> dict[str, Any]:
        """Calcula o desfoque da capa fora da principal; a capa trocada com a página aberta o recalcula."""
        if chave and chave == self._chave_do_fundo:
            return {}
        self._chave_do_fundo = chave
        caminho = jogo.get_cover_path()
        if caminho is None:
            self._luminancia = _RESERVA
            return {"fundo": ""}
        threading.Thread(
            target=_calcular_fundo, args=(weakref.ref(self), jogo.game_id, chave, caminho), daemon=True
        ).start()
        return {}

    def _fundo_chegou(self, game_id: str, chave: str, resultado: desfoque.Desfoque | None) -> None:
        if game_id != self._atual or chave != self._chave_do_fundo:
            return
        if resultado is None:
            # Sem capa legível: o QML usa o fundo de reserva.
            self._luminancia = _RESERVA
            self._mesclar({"fundo": ""})
            return
        self.provedor.guardar(game_id, resultado.png)
        self._versao_do_fundo += 1
        self._luminancia = resultado.luminancia
        self._mesclar({"fundo": f"image://desfoque/{quote(game_id)}?v={self._versao_do_fundo}"})
