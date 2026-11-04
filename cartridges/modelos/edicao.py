# edicao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O formulário que o `DialogoDeEdicao.qml` edita.

Só guarda o `Formulario` de `cartridges.edicao` e chama a regra: validar e gravar são dela. O que mora aqui é o que a
tela precisa para desenhar (os índices dos seletores, as linhas que somem, a operação em voo) e para falar com a
pessoa (o erro, a pasta que não abriu). Só na thread principal.
"""

import dataclasses
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from PIL import Image
from PySide6.QtCore import Property, QCoreApplication, QEvent, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication

from cartridges import edicao, shared
from cartridges.edicao import Escolha, Formulario
from cartridges.jogo import STATUS_LABELS, Jogo
from cartridges.modelos.ordem import _url_da_capa  # noqa: PLC2701
from cartridges.modelos.seletores import (
    SeletorDaSteam,
    SeletorDeLogo,
    SeletorDePapelDeParede,
    SeletorDoLudusavi,
    SeletorDoSgdb,
    pasta_do_ludusavi,
)
from cartridges.saves import ludusavi
from cartridges.store.managers.hltb_manager import shared_helper as shared_hltb_helper
from cartridges.utils import capa_video, game_logo, session_fita, session_wallpaper
from cartridges.utils.game_folder import game_folder, open_folder
from cartridges.utils.hltb import fetch_times, has_times
from cartridges.utils.name_cleaner import clean_for_search, clean_game_name
from cartridges.utils.steam import SteamGameNotFoundError
from cartridges.utils.thread_principal import na_thread_principal


def _filtro(nome: str, sufixos: list[str] | tuple[str, ...]) -> str:
    return f"{nome} ({' '.join('*' + s for s in sorted(sufixos))})"


def filtro_de_capa() -> str:
    """As imagens que o Pillow lê e os vídeos que o ffmpeg converte. Sem SVG: o Pillow não o rasteriza."""
    # `.palm` e `.pdf` só o Pillow escreve.
    imagens = set(Image.registered_extensions()) - {".palm", ".pdf", ".svg"}
    return _filtro(_("Imagens e vídeos"), [*imagens, *capa_video.SUFIXOS])


def _segundo_monitor() -> bool:
    return len(QGuiApplication.screens()) >= 2


def _largar_arquivos_abertos() -> None:
    # O ``AnimatedImage`` só larga o arquivo quando destrói o filme, num ``deleteLater``.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _ler(atributo: str) -> Callable[[Any], Any]:
    return lambda self: getattr(self._form, atributo)  # noqa: SLF001


def _gravar(atributo: str, sinal: str) -> Callable[[Any, Any], None]:
    def gravar(self: Any, valor: Any) -> None:
        if getattr(self._form, atributo) != valor:  # noqa: SLF001
            setattr(self._form, atributo, valor)  # noqa: SLF001
            getattr(self, sinal).emit()
            self._ao_mudar(atributo)  # noqa: SLF001

    return gravar


class ModeloDaEdicao(QObject):
    """Um diálogo de edição por vez: `abrir` (um jogo) ou `adicionar` (um jogo novo)."""

    abertoChanged = Signal()  # noqa: N815
    ocupadoChanged = Signal()  # noqa: N815
    derivadosChanged = Signal()  # noqa: N815
    ludusaviChanged = Signal()  # noqa: N815
    notaChanged = Signal()  # noqa: N815
    controleIndiceChanged = Signal()  # noqa: N815
    statusIndiceChanged = Signal()  # noqa: N815
    nomeChanged = Signal()  # noqa: N815
    desenvolvedoraChanged = Signal()  # noqa: N815
    publicadoraChanged = Signal()  # noqa: N815
    lancamentoChanged = Signal()  # noqa: N815
    generoChanged = Signal()  # noqa: N815
    executavelChanged = Signal()  # noqa: N815
    adminChanged = Signal()  # noqa: N815
    rastrearProcessoChanged = Signal()  # noqa: N815
    executavelDoProcessoChanged = Signal()  # noqa: N815
    notificarAtualizacoesChanged = Signal()  # noqa: N815
    conquistasChanged = Signal()  # noqa: N815
    appidChanged = Signal()  # noqa: N815
    # O erro de validação veio do AppID: a seção "Opções avançadas" precisa estar à vista.
    avancadasPedidas = Signal()  # noqa: N815
    # O diálogo de erro fechou: o foco volta ao diálogo de edição.
    focoDevolvido = Signal()  # noqa: N815
    capaChanged = Signal()  # noqa: N815
    imagensChanged = Signal()  # noqa: N815
    buscandoMetadadosChanged = Signal()  # noqa: N815
    fitaChanged = Signal()  # noqa: N815

    def __init__(self, aplicativo: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._aplicativo = aplicativo  # `pedir_dialogo`
        self._jogo: Optional[Jogo] = None
        self._form = Formulario()
        self._aberto = False
        self._ocupacoes = 0
        self._appid_inicial = ""
        self._acompanha = False
        self._pasta = ""
        self._empacotado = False
        # Cada abertura é uma geração: o que uma thread entrega a uma anterior é descartado.
        self._geracao = 0
        self._pedido_da_capa = 0
        self._capas_em_voo = 0
        self._segundo_monitor = False
        # Os seletores do SteamGridDB entregam aqui (`entregar_*`, `usar_titulo_no_logo`).
        self._seletor_de_capa = SeletorDoSgdb(self, self)
        self._seletor_de_logo = SeletorDeLogo(self, self)
        self._seletor_de_papel = SeletorDePapelDeParede(self, self)
        self._seletor_da_steam = SeletorDaSteam(self, self)
        self._seletor_do_ludusavi = SeletorDoLudusavi(self, self)
        self._buscando_metadados = False
        # A lista de jogos do Ludusavi (o `manifest.yaml`) já foi baixada? Lido ao abrir.
        self._ludusavi_disponivel = True
        # A fita de LED: a prévia acesa nas fitas (que o fechar desfaz) e se há dispositivo configurado.
        self._fita_previa_usada = False
        self._fita_disponivel = False

    nome = Property(str, _ler("nome"), _gravar("nome", "nomeChanged"), notify=nomeChanged)
    desenvolvedora = Property(
        str, _ler("desenvolvedora"), _gravar("desenvolvedora", "desenvolvedoraChanged"), notify=desenvolvedoraChanged
    )
    publicadora = Property(
        str, _ler("publicadora"), _gravar("publicadora", "publicadoraChanged"), notify=publicadoraChanged
    )
    lancamento = Property(
        str, _ler("lancamento"), _gravar("lancamento", "lancamentoChanged"), notify=lancamentoChanged
    )
    genero = Property(str, _ler("genero"), _gravar("genero", "generoChanged"), notify=generoChanged)
    executavel = Property(
        str, _ler("executavel"), _gravar("executavel", "executavelChanged"), notify=executavelChanged
    )
    admin = Property(bool, _ler("admin"), _gravar("admin", "adminChanged"), notify=adminChanged)
    rastrearProcesso = Property(  # noqa: N815
        bool,
        _ler("rastrear_processo"),
        _gravar("rastrear_processo", "rastrearProcessoChanged"),
        notify=rastrearProcessoChanged,
    )
    executavelDoProcesso = Property(  # noqa: N815
        str,
        _ler("executavel_do_processo"),
        _gravar("executavel_do_processo", "executavelDoProcessoChanged"),
        notify=executavelDoProcessoChanged,
    )
    notificarAtualizacoes = Property(  # noqa: N815
        bool,
        _ler("notificar_atualizacoes"),
        _gravar("notificar_atualizacoes", "notificarAtualizacoesChanged"),
        notify=notificarAtualizacoesChanged,
    )
    conquistas = Property(
        bool, _ler("conquistas"), _gravar("conquistas", "conquistasChanged"), notify=conquistasChanged
    )
    appid = Property(str, _ler("appid"), _gravar("appid", "appidChanged"), notify=appidChanged)
    nota = Property(int, _ler("nota"), notify=notaChanged)

    # Os seletores guardam a posição; o valor gravado sai das listas da regra.
    @Property(int, notify=controleIndiceChanged)
    def controleIndice(self) -> int:  # noqa: N802
        return edicao.CONTROLLER_VALUES.index(self._form.controle)

    @controleIndice.setter
    def controleIndice(self, indice: int) -> None:  # noqa: N802
        if 0 <= indice < len(edicao.CONTROLLER_VALUES) and edicao.CONTROLLER_VALUES[indice] != self._form.controle:
            self._form.controle = edicao.CONTROLLER_VALUES[indice]
            self.controleIndiceChanged.emit()

    @Property(int, notify=statusIndiceChanged)
    def statusIndice(self) -> int:  # noqa: N802
        return edicao.STATUS_VALUES.index(self._form.status)

    @statusIndice.setter
    def statusIndice(self, indice: int) -> None:  # noqa: N802
        if 0 <= indice < len(edicao.STATUS_VALUES) and edicao.STATUS_VALUES[indice] != self._form.status:
            self._form.status = edicao.STATUS_VALUES[indice]
            self.statusIndiceChanged.emit()

    opcoesDeControle = Property(  # noqa: N815
        "QVariantList", lambda self: [edicao.CONTROLLER_LABELS[v] for v in edicao.CONTROLLER_VALUES], constant=True
    )
    opcoesDeStatus = Property(  # noqa: N815
        "QVariantList", lambda self: ["Sem status", *STATUS_LABELS.values()], constant=True
    )

    @Property(bool, notify=abertoChanged)
    def aberto(self) -> bool:
        return self._aberto

    @Property(str, notify=abertoChanged)
    def titulo(self) -> str:
        return _("Adicionar novo jogo") if self._jogo is None else _("Detalhes do jogo")

    @Property(str, notify=abertoChanged)
    def rotuloDoAplicar(self) -> str:  # noqa: N802
        return _("Adicionar") if self._jogo is None else _("Aplicar")

    @Property(bool, notify=abertoChanged)
    def zerado(self) -> bool:
        """Um zerado não é mais lançado: sem a linha do executável nem a das atualizações."""
        return bool(self._jogo and self._jogo.zerado)

    @Property(bool, notify=ocupadoChanged)
    def ocupado(self) -> bool:
        return self._ocupacoes > 0

    @Property(bool, notify=appidChanged)
    def appidValido(self) -> bool:  # noqa: N802
        """O AppID digitado é só números (ou vazio): a linha fica vermelha e o Aplicar, bloqueado, se não."""
        return edicao.appid_aceito(self._form.appid.strip())

    @Property(bool, notify=derivadosChanged)
    def empacotado(self) -> bool:
        return self._empacotado

    @Property(bool, notify=derivadosChanged)
    def rastreioVisivel(self) -> bool:  # noqa: N802
        """O jogo só cai na sessão manual (e precisa do nome do executável) quando nada o acompanha."""
        return not self._acompanha

    @Property(bool, notify=derivadosChanged)
    def podeAbrirPasta(self) -> bool:  # noqa: N802
        return bool(self._pasta)

    @Property(bool, notify=ludusaviChanged)
    def ludusaviDisponivel(self) -> bool:  # noqa: N802
        return self._ludusavi_disponivel

    @Property(str, notify=ludusaviChanged)
    def ludusaviSubtitulo(self) -> str:  # noqa: N802
        if not self._ludusavi_disponivel:
            return _("A lista de jogos do Ludusavi ainda não foi baixada.")
        jogo, form = self._jogo, self._form
        nome = jogo.ludusavi_nome if jogo else ""
        desligado = bool(jogo and jogo.backup_dos_saves_desligado)
        if form.ludusavi_escolhido is not None:
            nome, desligado = form.ludusavi_escolhido, not form.ludusavi_escolhido
        if nome:
            return nome
        if desligado:
            return _("Backup desligado")
        return _("Automático pelo AppID") if form.appid.strip() else _("Nenhum")

    seletorDaSteam = Property(QObject, lambda self: self._seletor_da_steam, constant=True)  # noqa: N815
    seletorDoLudusavi = Property(QObject, lambda self: self._seletor_do_ludusavi, constant=True)  # noqa: N815

    @Property(bool, notify=buscandoMetadadosChanged)
    def buscandoMetadados(self) -> bool:  # noqa: N802
        """O botão ao lado do título gira enquanto a Steam e o HowLongToBeat respondem."""
        return self._buscando_metadados

    @Slot()
    def buscarAppid(self) -> None:  # noqa: N802
        if self._aberto and (nome := self._form.nome.strip()):
            self._seletor_da_steam.abrir(nome)

    @Slot()
    def escolherJogoNoLudusavi(self) -> None:  # noqa: N802
        if not self._aberto or not self._ludusavi_disponivel:
            return
        atual = self._form.ludusavi_escolhido
        if atual is None:
            atual = self._jogo.ludusavi_nome if self._jogo else ""
        self._seletor_do_ludusavi.abrir(atual)

    def ludusavi_escolhido(self, nome: str) -> None:
        """O jogo que o seletor do Ludusavi entregou ("" desliga o backup dos saves)."""
        if self._aberto:
            self._form.ludusavi_escolhido = nome
            self.ludusaviChanged.emit()

    def _appid_para_buscar(self) -> str:
        """O AppID digitado nas opções avançadas, se é número e difere do gravado."""
        texto = self._form.appid.strip()
        return texto if texto and texto != self._appid_inicial and edicao.appid_aceito(texto) else ""

    def _definir_buscando_metadados(self, valor: bool) -> None:
        if valor != self._buscando_metadados:
            self._buscando_metadados = valor
            self.buscandoMetadadosChanged.emit()

    @Slot()
    def buscarMetadados(self) -> None:  # noqa: N802
        """Procura o título na Steam e, com o nome que ela confirmou, no HowLongToBeat.

        Nada é gravado aqui: o que chega só preenche o formulário, para a pessoa conferir antes do Aplicar.
        Até terminar, o Aplicar fica bloqueado (gravar no meio perderia o que ainda está a caminho).
        """
        nome = self._form.nome.strip()
        if not self._aberto or not nome or self._buscando_metadados:
            return
        self._definir_buscando_metadados(True)
        self.iniciar_operacao()
        # Um AppID já ligado a este jogo vale mais que buscar o nome de novo: é o que a busca anterior
        # resolveu ou o que a pessoa escolheu à mão. O gravado só vale com o título intacto.
        gravado = self._jogo.steam_appid if self._jogo and nome == (self._jogo.name or "").strip() else None
        appid = self._appid_para_buscar() or self._form.buscado.get("steam_appid") or gravado
        args = (self._geracao, nome, appid, self._seletor_da_steam.helper_da_steam())
        threading.Thread(target=self._thread_dos_metadados, args=args, daemon=True).start()

    def _thread_dos_metadados(self, geracao: int, nome: str, appid: Any, helper: Any) -> None:
        try:
            if appid:
                dados = helper.get_api_data(str(appid))
            else:
                appid, dados = helper.resolve(clean_for_search(nome))
        except SteamGameNotFoundError:
            # Nada em que o comparador confie: em vez de adotar o mais parecido (para "The Outer Worlds",
            # a continuação), a pessoa diz qual é o jogo.
            na_thread_principal(self._metadados_escolher, geracao, nome)
            return
        except Exception:  # noqa: BLE001  # a tela diz só "não encontrado"; sem isto a thread morreria com o Aplicar bloqueado
            logging.warning("Steam lookup failed for %s", nome, exc_info=True)
            na_thread_principal(self._metadados_chegaram, geracao, None, str(appid or ""))
            return
        na_thread_principal(self._metadados_chegaram, geracao, dados, str(appid))

    def _metadados_escolher(self, geracao: int, nome: str) -> None:
        if geracao != self._geracao or not self._aberto:
            return
        # Para a busca, a busca acabou: o seletor é modal sobre o diálogo, e o Esc nele nunca chamaria de volta.
        self.terminar_operacao()
        self._definir_buscando_metadados(False)
        self._seletor_da_steam.abrir_para_metadados(nome)

    def steam_escolhida(self, appid: str, dados: dict, para_metadados: bool) -> None:
        """O jogo que o seletor da Steam entregou: só o AppID, ou a continuação da busca de metadados."""
        if not self._aberto:
            return
        if not para_metadados:
            self.appid = appid
            return
        # Retoma a busca que `_metadados_escolher` largou: a perna do HowLongToBeat vem a seguir.
        self._definir_buscando_metadados(True)
        self.iniciar_operacao()
        self._metadados_chegaram(self._geracao, dados, appid)

    def _metadados_chegaram(self, geracao: int, dados: Optional[dict], appid: str) -> None:
        if geracao != self._geracao or not self._aberto:
            return  # o diálogo fechou (ou é de outro jogo)
        if not dados:
            self.terminar_operacao()
            self._definir_buscando_metadados(False)
            self._aplicativo.pedir_dialogo(
                _("Jogo não encontrado na Steam"),
                _("Confira o título e tente novamente."),
                [],
                self.focoDevolvido.emit,
            )
            return
        form = self._form
        # Outro jogo: o que a busca anterior trouxe não é dele. O AppID não volta: é sobrescrito logo abaixo.
        if dados.get("name") and clean_game_name(dados["name"]) != form.nome.strip():
            form.buscado = {}
        buscado = form.buscado
        # Direto no formulário, sem o setter: mudar o título pelo setter descartaria o que acabou de chegar.
        if dados.get("name"):
            form.nome = clean_game_name(dados["name"])
        if appid:
            buscado["steam_appid"] = appid
            form.appid = appid
        for campo, chave in (
            ("desenvolvedora", "developer"), ("publicadora", "publisher"), ("lancamento", "release_date"), ("genero", "genre"),
        ):  # fmt: skip
            if dados.get(chave):
                setattr(form, campo, dados[chave])
        if dados.get("controller_support") in ("full", "partial"):
            form.controle = dados["controller_support"]
        for chave in ("metacritic", "gamepad_recommended"):
            if dados.get(chave) is not None:
                buscado[chave] = dados[chave]
        for chave in ("steam_review", "description"):
            if dados.get(chave):
                buscado[chave] = dados[chave]
        for sinal in (
            self.nomeChanged, self.appidChanged, self.desenvolvedoraChanged, self.publicadoraChanged,
            self.lancamentoChanged, self.generoChanged, self.controleIndiceChanged, self.ludusaviChanged,
        ):  # fmt: skip
            sinal.emit()
        # Com o título que a Steam acabou de confirmar: é ele que faz o HowLongToBeat achar o jogo.
        nome = form.nome.strip()
        # O gravado só vale com o título intacto; lido aqui, na principal, e não na thread.
        gravado = self._jogo.hltb_id if self._jogo and nome == (self._jogo.name or "").strip() else None
        threading.Thread(target=self._thread_do_hltb, args=(geracao, nome, gravado), daemon=True).start()

    def _thread_do_hltb(self, geracao: int, nome: str, gravado: Any) -> None:
        """Fora da thread principal. Um erro aqui é silêncio: os dados da Steam, que a pessoa pediu, já chegaram."""
        tempos = None
        try:
            tempos = fetch_times(shared_hltb_helper(), nome, gravado)
        except Exception:  # noqa: BLE001  # `int(hltb_id)` de uma ficha editada à mão levanta ValueError: sem isto o Aplicar não desbloqueia
            logging.exception("Could not fetch HowLongToBeat times")
        na_thread_principal(self._hltb_chegou, geracao, tempos, nome)

    def _hltb_chegou(self, geracao: int, tempos: Optional[dict], nome: str) -> None:
        if geracao != self._geracao or not self._aberto:
            return
        self.terminar_operacao()
        self._definir_buscando_metadados(False)
        # O título mudou no meio do caminho: a pessoa disse que é outro jogo, e a resposta é do antigo.
        if nome != self._form.nome.strip():
            return
        if tempos and has_times(tempos):
            self._form.buscado["hltb"] = tempos
        else:
            logging.info("No HowLongToBeat times found for %s", nome)

    def _invalidar_buscado(self) -> None:
        """O título mudou: o que a última busca trouxe era de outro jogo, e o AppID dela também.

        A pessoa disse que é outro jogo; manter o AppID prenderia a próxima busca ao que ela acabou de
        corrigir. Se ela mexeu no AppID depois da busca, o que digitou fica.
        """
        buscado, self._form.buscado = self._form.buscado, {}
        if buscado.get("steam_appid") is not None and self._form.appid.strip() == buscado["steam_appid"]:
            self.appid = self._appid_inicial

    @Property(bool, notify=fitaChanged)
    def fitaDisponivel(self) -> bool:  # noqa: N802
        """Sem nenhum dispositivo configurado não há cor para escolher: as duas linhas ficam apagadas."""
        return self._fita_disponivel

    @Property(str, notify=fitaChanged)
    def fitaSubtitulo(self) -> str:  # noqa: N802
        if not self._fita_disponivel:
            return _("Nenhum dispositivo configurado")
        if self._fita_manual():
            return _("Escolhida manualmente")
        # Com a cor acompanhando a tela, o automático não é mais a cor da capa: ela é só o ponto de
        # partida de cada sessão.
        return _("Automático") if session_fita.acompanha_tela() else _("Extraída da capa")

    @Property(QColor, notify=fitaChanged)
    def fitaCor(self) -> QColor:  # noqa: N802
        """A cor cheia (sem o brilho da fita), como o seletor a mostra."""
        cor = self._form.fita_na_tela
        if cor is None:
            # Sem dispositivo o círculo usa a cor de partida do seletor, branca.
            return QColor("white")
        return QColor.fromRgbF(*session_fita.cor_para_rgb(cor))

    @Property(int, notify=fitaChanged)
    def fitaBrilho(self) -> int:  # noqa: N802
        cor = self._form.fita_na_tela
        # Sem dispositivo o campo fica em 0 (nada o preenche).
        return session_fita.por_cento(cor.brilho) if cor is not None else 0

    @Property(bool, notify=fitaChanged)
    def fitaManual(self) -> bool:  # noqa: N802
        return self._fita_disponivel and self._fita_manual()

    @Property(bool, notify=fitaChanged)
    def fitaAutomatica(self) -> bool:  # noqa: N802
        """A amostra mostra a roda de cores: a cor acompanha a tela, não há escolha à mão, e ninguém
        mexeu na cor desde que a tela a mostrou."""
        form = self._form
        return (
            session_fita.acompanha_tela()
            and form.fita_mostrada is not None
            and form.fita_na_tela is not None
            and not self._fita_manual()
            and edicao.mesmo_tom(form.fita_na_tela, form.fita_mostrada)
        )

    @Property(str, notify=fitaChanged)
    def dicaDeVoltar(self) -> str:  # noqa: N802
        return (
            _("Voltar ao automático") if session_fita.acompanha_tela() else _("Voltar a escolher a cor a partir da capa")
        )

    def _fita_manual(self) -> bool:
        """Vale a cor escolhida à mão (e não um "voltar ao automático" pedido)."""
        jogo = self._jogo
        return jogo is not None and not self._form.fita_redefinir and session_fita.escolhida(jogo.game_id)

    def _cor_automatica(self) -> session_fita.Cor:
        """A cor que a linha deve mostrar agora.

        Com a redefinição pedida é o automático, mesmo havendo escolha em disco: a escolha só será
        apagada no Aplicar, mas a tela já mostra o que o Aplicar vai deixar valendo. O automático sai da
        capa que a tela mostra, e não da gravada: a capa trocada e ainda não aplicada é a que o jogo vai
        ter. Jogo novo sem capa fica com o roxo do app.
        """
        jogo = self._jogo
        if self._fita_manual():
            return session_fita.cor_do_jogo(jogo)
        # O brilho do jogo fica, inclusive o de uma escolha que vai ser desfeita: "voltar ao
        # automático" é sobre a cor.
        brilho = session_fita.brilho_gravado(jogo.game_id) if jogo else None
        return session_fita.cor_da_capa(self._form.capa, brilho)

    def _atualizar_fita(self) -> None:
        """Mostra a cor que vale hoje: a escolhida ou a que sai da capa."""
        # Sem dispositivo não se calcula a cor: tirar a dominante da capa custa milissegundos na thread
        # principal, e seriam gastos por uma fita que não existe.
        self._fita_disponivel = bool(session_fita.fitas())
        if not self._fita_disponivel:
            self._form.fita_mostrada = self._form.fita_na_tela = None
        else:
            self._form.fita_mostrada = self._form.fita_na_tela = self._cor_automatica()
        self.fitaChanged.emit()

    def _fita_segue_capa(self) -> None:
        """A capa mudou: a linha da cor acompanha, se ninguém mexeu na cor.

        Uma cor mexida e ainda não aplicada é escolha de gente, e trocar a capa depois não a desfaz. O
        brilho é separado da cor: mexido, ele fica como está, e a cor segue a capa nova. Não acende a
        prévia: ela é para quem mexe na cor, não na capa.
        """
        form = self._form
        if form.fita_mostrada is None or form.fita_na_tela is None:
            return
        if not edicao.mesmo_tom(form.fita_na_tela, form.fita_mostrada):
            return
        brilho = form.fita_na_tela.brilho
        self._atualizar_fita()
        form.fita_na_tela = form.fita_na_tela._replace(brilho=brilho)
        self.fitaChanged.emit()

    def _previa_da_fita(self) -> None:
        """Mostra nas fitas a cor e o brilho que estão na tela agora (a conversa corre em threads)."""
        cor = self._form.fita_na_tela
        if self._form.fita_mostrada is None or cor is None:
            return
        self._fita_previa_usada = True
        session_fita.previa(cor)

    def _encerrar_previa_da_fita(self) -> None:
        """Devolve as fitas à cor do app depois de a tela sumir. Só quando houve prévia: sem isso,
        abrir e fechar a tela de um jogo qualquer repintaria as fitas à toa."""
        if self._fita_previa_usada:
            self._fita_previa_usada = False
            session_fita.previa(session_fita.cor_do_app())

    @Slot(QColor)
    def escolherCorDaFita(self, cor: QColor) -> None:  # noqa: N802
        atual = self._form.fita_na_tela
        if not self._aberto or atual is None or not cor.isValid():
            return
        self._form.fita_na_tela = session_fita.rgb_para_cor(cor.redF(), cor.greenF(), cor.blueF(), atual.brilho)
        self.fitaChanged.emit()
        self._previa_da_fita()

    @Slot(int)
    def definirBrilhoDaFita(self, brilho: int) -> None:  # noqa: N802
        atual = self._form.fita_na_tela
        if not self._aberto or atual is None:
            return
        novo = session_fita.de_por_cento(max(1, min(100, brilho)))
        if novo == atual.brilho:
            return
        self._form.fita_na_tela = atual._replace(brilho=novo)
        self.fitaChanged.emit()
        self._previa_da_fita()

    @Slot()
    def redefinirFita(self) -> None:  # noqa: N802
        """Marca a intenção de voltar ao automático. Quem apaga é o Aplicar."""
        if not self._aberto or self._jogo is None or self._form.fita_mostrada is None:
            return
        antes = self._form.fita_na_tela
        self._form.fita_redefinir = True
        self._atualizar_fita()
        if self._form.fita_na_tela != antes:  # sem mudança de cor, nada se repinta
            self._previa_da_fita()

    seletorDeCapa = Property(QObject, lambda self: self._seletor_de_capa, constant=True)  # noqa: N815
    seletorDeLogo = Property(QObject, lambda self: self._seletor_de_logo, constant=True)  # noqa: N815
    seletorDePapelDeParede = Property(QObject, lambda self: self._seletor_de_papel, constant=True)  # noqa: N815
    filtroDaCapa = Property(str, lambda self: filtro_de_capa(), constant=True)  # noqa: N815
    filtroDoLogo = Property(  # noqa: N815
        str, lambda self: _filtro(_("Imagens de logo"), game_logo.IMAGE_SUFFIXES), constant=True
    )
    # O papel de parede de um arquivo usa o filtro das capas, "Imagens e vídeos".
    filtroDoPapel = Property(str, lambda self: filtro_de_capa(), constant=True)  # noqa: N815

    @Property(str, notify=capaChanged)
    def capa(self) -> str:
        """A URL da capa que a tela mostra ("" sem capa)."""
        return _url_da_capa(self._form.capa)

    @Property(bool, notify=capaChanged)
    def temCapa(self) -> bool:  # noqa: N802
        return self._form.capa is not None

    @Property(bool, notify=capaChanged)
    def convertendoCapa(self) -> bool:  # noqa: N802
        return self._capas_em_voo > 0

    @Property(str, notify=imagensChanged)
    def logoSubtitulo(self) -> str:  # noqa: N802
        return {
            "manual": _("Escolhido manualmente"),
            "title": _("Sem logo; o título é exibido"),
        }.get(edicao.estado_do_logo(self._form, self._jogo), _("Automático (SteamGridDB)"))

    @Property(bool, notify=imagensChanged)
    def logoRestauravel(self) -> bool:  # noqa: N802
        return edicao.estado_do_logo(self._form, self._jogo) != "auto"

    @Property(bool, notify=imagensChanged)
    def papelDisponivel(self) -> bool:  # noqa: N802
        return self._segundo_monitor

    @Property(str, notify=imagensChanged)
    def papelSubtitulo(self) -> str:  # noqa: N802
        if not self._segundo_monitor:
            return _("Requer um segundo monitor")
        return {
            "manual": _("Escolhido manualmente"),
            "none": _("Não trocar o papel de parede"),
        }.get(edicao.estado_do_papel(self._form, self._jogo), _("Automático (wallhaven)"))

    @Property(bool, notify=imagensChanged)
    def papelRestauravel(self) -> bool:  # noqa: N802
        return self._segundo_monitor and edicao.estado_do_papel(self._form, self._jogo) != "auto"

    def _provisoria(self) -> Optional[Path]:
        """A capa que a tela criou e ainda é dela (a do disco não é)."""
        return self._form.capa if self._form.capa_mudou else None

    def _trocar_capa(self, nova: Optional[Path]) -> None:
        antiga = self._provisoria()
        self._form.capa, self._form.capa_mudou = nova, True
        self.capaChanged.emit()
        self._fita_segue_capa()
        if antiga is not None:
            # A prévia animada segura o arquivo aberto: ela larga antes, senão o Windows recusa apagar.
            _largar_arquivos_abertos()
            edicao.descartar_provisoria(antiga)

    def _trocar_escolha(self, atributo: str, nova: Optional[Escolha]) -> None:
        antiga = getattr(self._form, atributo)
        setattr(self._form, atributo, nova)
        if antiga is not None and antiga.temporario and antiga.arquivo:
            edicao.descartar_provisoria(antiga.arquivo)
        self.imagensChanged.emit()

    @Slot(QUrl)
    def escolherCapa(self, url: QUrl) -> None:  # noqa: N802
        """Converte a imagem (ou o vídeo) fora da thread principal; o Aplicar espera."""
        if self._aberto and (caminho := url.toLocalFile()):
            self._converter_capa(Path(caminho), apagar_origem=False)

    def entregar_capa_baixada(
        self,
        arquivo: Path,
        ao_terminar: Optional[Callable[[bool], None]] = None,
        vigente: Optional[Callable[[], bool]] = None,
    ) -> None:
        """A capa que o seletor do SteamGridDB baixou: vira provisória como a de um arquivo, e o original sai.

        ``ao_terminar(convertida)`` avisa o seletor, que só fecha com a capa pronta e volta à grade se ela falhar.
        ``vigente()`` diz se o seletor ainda a espera: fechado no meio da conversão, a capa pronta é descartada."""
        if self._aberto:
            self._converter_capa(arquivo, apagar_origem=True, ao_terminar=ao_terminar, vigente=vigente)
        else:
            arquivo.unlink(missing_ok=True)

    def _converter_capa(
        self,
        arquivo: Path,
        apagar_origem: bool,
        ao_terminar: Optional[Callable[[bool], None]] = None,
        vigente: Optional[Callable[[], bool]] = None,
    ) -> None:
        geracao = self._geracao
        self._pedido_da_capa += 1
        pedido = self._pedido_da_capa
        self._capas_em_voo += 1
        self.iniciar_operacao()
        self.capaChanged.emit()

        def trabalhar() -> None:
            nova, erro = None, ""
            try:
                if capa_video.eh_video(arquivo):
                    nova, erro = edicao.preparar_capa_de_video(arquivo)
                else:
                    nova = edicao.preparar_capa(arquivo)
            except Exception:  # noqa: BLE001  # só esta thread devolve o contador de ocupado
                logging.exception("Could not prepare the chosen cover")
            if apagar_origem:
                arquivo.unlink(missing_ok=True)
            na_thread_principal(self._capa_pronta, geracao, pedido, nova, erro, ao_terminar, vigente)

        threading.Thread(target=trabalhar, daemon=True).start()

    def _capa_pronta(
        self,
        geracao: int,
        pedido: int,
        nova: Optional[Path],
        erro: str,
        ao_terminar: Optional[Callable[[bool], None]] = None,
        vigente: Optional[Callable[[], bool]] = None,
    ) -> None:
        if geracao != self._geracao or not self._aberto:
            # O diálogo fechou (ou é de outro jogo): a capa pronta não tem onde entrar.
            if nova is not None:
                edicao.descartar_provisoria(nova)
            return
        self._capas_em_voo -= 1
        self.terminar_operacao()
        if vigente is not None and not vigente():
            # O seletor fechou no meio da conversão: a pessoa desistiu, e a capa do editor não muda.
            if nova is not None:
                edicao.descartar_provisoria(nova)
            self.capaChanged.emit()
            return
        if pedido != self._pedido_da_capa:
            # Uma escolha mais nova foi pedida depois desta: vale a última.
            if nova is not None:
                edicao.descartar_provisoria(nova)
            self.capaChanged.emit()
            if ao_terminar is not None:
                ao_terminar(True)  # a escolha mais nova é que vale; este seletor já cumpriu o que lhe cabia
            return
        if nova is not None:
            self._trocar_capa(nova)
        else:
            self.capaChanged.emit()
        if ao_terminar is not None:
            ao_terminar(nova is not None)
        if erro:
            self._aplicativo.pedir_dialogo(_("Não foi possível usar o vídeo"), erro, [], self.focoDevolvido.emit)

    @Slot()
    def excluirCapa(self) -> None:  # noqa: N802
        if self._aberto and self._form.capa is not None:
            # Uma conversão a caminho perde para a exclusão pedida depois dela.
            self._pedido_da_capa += 1
            self._trocar_capa(None)

    @Slot(QUrl)
    def escolherLogo(self, url: QUrl) -> None:  # noqa: N802
        if self._aberto and (caminho := url.toLocalFile()):
            self._trocar_escolha("logo", Escolha("manual", Path(caminho)))

    def entregar_logo_baixado(self, arquivo: Path) -> None:
        """O logo que o seletor do SteamGridDB baixou: é da tela até o Aplicar, que o apaga depois de gravado."""
        if self._aberto:
            self._trocar_escolha("logo", Escolha("manual", arquivo, temporario=True))
        else:
            arquivo.unlink(missing_ok=True)

    def usar_titulo_no_logo(self) -> None:
        if self._aberto:
            self._trocar_escolha("logo", Escolha("title"))

    @Slot()
    def restaurarLogo(self) -> None:  # noqa: N802
        if self._aberto:
            self._trocar_escolha("logo", Escolha("auto"))

    @Slot(QUrl)
    def escolherPapel(self, url: QUrl) -> None:  # noqa: N802
        """O arquivo do disco vai à etapa de ajuste da faixa, igual a uma imagem do wallhaven."""
        if self._aberto and url.toLocalFile():
            self._seletor_de_papel.abrirArquivo(url)

    def entregar_papel_baixado(self, arquivo: Path, posicoes: session_wallpaper.Posicoes) -> None:
        """O papel de parede que o seletor do wallhaven baixou, com a faixa escolhida: é da tela até o Aplicar."""
        if self._aberto:
            self._trocar_escolha("papel_de_parede", Escolha("manual", arquivo, posicoes, temporario=True))
        else:
            arquivo.unlink(missing_ok=True)

    def nao_trocar_papel(self) -> None:
        if self._aberto:
            self._trocar_escolha("papel_de_parede", Escolha("none"))

    @Slot()
    def restaurarPapel(self) -> None:  # noqa: N802
        if self._aberto:
            self._trocar_escolha("papel_de_parede", Escolha("auto"))

    def _ao_mudar(self, atributo: str) -> None:
        if atributo == "executavel":
            self._recalcular()
        elif atributo == "rastrear_processo" and self._form.rastrear_processo:
            # Ligar o rastreio já sugere o nome do .exe do comando.
            if not self._form.executavel_do_processo.strip():
                self.executavelDoProcesso = edicao.exe_name_from_command(self._form.executavel)
        elif atributo == "appid":
            self.ludusaviChanged.emit()
        elif atributo == "nome":
            self._invalidar_buscado()

    def _recalcular(self) -> None:
        # Lê o disco a cada mudança do comando: no disco local custa microssegundos.
        comando = self._form.executavel
        self._empacotado = edicao.empacotado(comando)
        self._acompanha = edicao.acompanha_sem_nome(comando)
        self._pasta = game_folder(comando) or ""
        self.derivadosChanged.emit()

    def iniciar_operacao(self) -> None:
        """Uma busca ou conversão a caminho: o Aplicar fica bloqueado até ela terminar."""
        self._ocupacoes += 1
        if self._ocupacoes == 1:
            self.ocupadoChanged.emit()

    def terminar_operacao(self) -> None:
        if self._ocupacoes > 0:
            self._ocupacoes -= 1
            if self._ocupacoes == 0:
                self.ocupadoChanged.emit()

    @Slot(str)
    @Slot(str, bool)
    def abrir(self, game_id: str, avancadas: bool = False) -> None:
        if self._aberto or (jogo := shared.store.get(game_id)) is None:
            return
        self._abrir(jogo)
        if avancadas:
            self.avancadasPedidas.emit()

    @Slot()
    def adicionar(self) -> None:
        # Com um diálogo aberto, nada.
        if not self._aberto:
            self._abrir(None)

    def _abrir(self, jogo: Optional[Jogo]) -> None:
        self._jogo = jogo
        self._form = Formulario.do_jogo(jogo)
        # O AppID que o campo mostrava ao abrir: é com ele que `aplicar` vê se a pessoa o mexeu.
        self._appid_inicial = self._form.appid
        self._ocupacoes = 0
        self._capas_em_voo = 0
        self._geracao += 1
        self._buscando_metadados = False
        self._ludusavi_disponivel = ludusavi.manifesto_baixado(pasta_do_ludusavi())
        self._segundo_monitor = _segundo_monitor()
        self._aberto = True
        self._fita_previa_usada = False
        self._atualizar_fita()
        self._recalcular()
        for sinal in (
            self.nomeChanged, self.desenvolvedoraChanged, self.publicadoraChanged, self.lancamentoChanged,
            self.generoChanged, self.executavelChanged, self.adminChanged, self.rastrearProcessoChanged,
            self.executavelDoProcessoChanged, self.notificarAtualizacoesChanged, self.conquistasChanged,
            self.appidChanged, self.notaChanged, self.controleIndiceChanged, self.statusIndiceChanged,
            self.ludusaviChanged, self.ocupadoChanged, self.abertoChanged, self.capaChanged, self.imagensChanged,
            self.buscandoMetadadosChanged,
        ):  # fmt: skip
            sinal.emit()

    def _fechar(self, descartar: bool = True) -> None:
        """Fecha o diálogo. ``descartar``: as provisórias da tela saem (no Aplicar, são do `aplicar`)."""
        for seletor in (
            self._seletor_de_capa, self._seletor_de_logo, self._seletor_de_papel, self._seletor_da_steam,
            self._seletor_do_ludusavi,
        ):
            seletor.fechar()
        provisoria = self._provisoria()
        escolhas = [e for e in (self._form.logo, self._form.papel_de_parede) if e is not None]
        # Aplicar ou cancelar: as fitas voltam à cor do app (a do jogo só vale na sessão).
        self._encerrar_previa_da_fita()
        self._aberto = False
        self._jogo = None
        self._ocupacoes = 0
        self._capas_em_voo = 0
        self._buscando_metadados = False
        self._form = Formulario()
        self.abertoChanged.emit()
        self.ocupadoChanged.emit()
        self.buscandoMetadadosChanged.emit()
        self._fita_disponivel = False
        self.fitaChanged.emit()
        # A prévia larga o arquivo (o da capa animada) antes de ele sair, ou de o `aplicar` o apagar.
        self.capaChanged.emit()
        self.imagensChanged.emit()
        _largar_arquivos_abertos()
        if not descartar:
            return
        if provisoria is not None:
            edicao.descartar_provisoria(provisoria)
        for escolha in escolhas:
            if escolha.temporario and escolha.arquivo:
                edicao.descartar_provisoria(escolha.arquivo)

    @Slot()
    def cancelar(self) -> None:
        if self._aberto:
            self._fechar()

    @Slot(int)
    def definirNota(self, nota: int) -> None:  # noqa: N802
        """Clicar na nota atual a remove: sem isso, 1 estrela seria o piso."""
        self._form.nota = 0 if self._form.nota == nota else nota
        self.notaChanged.emit()

    @Slot(QUrl)
    def escolherExecutavel(self, url: QUrl) -> None:  # noqa: N802
        if not (caminho := url.toLocalFile()):
            return
        # Aspas duplas: o cmd.exe só entende estas, e um caminho do Windows não tem `"`.
        self.executavel = f'"{os.path.normpath(caminho)}"'

    @Slot()
    def abrirPasta(self) -> None:  # noqa: N802
        if not open_folder(self._pasta):
            self._aplicativo.pedir_dialogo(
                _("Não foi possível abrir a pasta"),
                _("A pasta pode ter sido movida ou apagada."),
                [],
                self.focoDevolvido.emit,
            )

    @Slot()
    def aplicar(self) -> None:
        # O mesmo portão do botão, na porta do Enter: com uma operação em voo, nada é gravado.
        if not self._aberto or self._ocupacoes:
            return
        form, jogo = self._form, self._jogo
        if edicao.saiu_da_store(jogo):
            self._fechar()
            return
        if (erro := edicao.validar(form, jogo)) is not None:
            # Se sem o AppID o erro muda, foi ele: a seção que o guarda precisa estar à vista.
            if edicao.validar(dataclasses.replace(form, appid=""), jogo) != erro:
                self.avancadasPedidas.emit()
            self._aplicativo.pedir_dialogo(edicao.titulo_do_erro(jogo is None), erro, [], self.focoDevolvido.emit)
            return
        # A página de detalhes, se aberta, segue o jogo pelo `atualizado`: mostra o novo ou sai sozinha.
        edicao.aplicar(form, jogo, self._appid_inicial)
        # A capa nova é do `aplicar` (ele a apaga depois da recarga, ou a guarda como a da sessão).
        self._fechar(descartar=False)
