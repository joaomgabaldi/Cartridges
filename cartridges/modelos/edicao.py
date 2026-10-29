# edicao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O formulário que o `DialogoDeEdicao.qml` edita (D41, camada 2).

Só guarda o `Formulario` de `cartridges.edicao` e chama a regra: validar e gravar são dela. O que
mora aqui é o que a tela precisa para desenhar (os índices dos seletores, as linhas que somem, a
operação em voo) e para falar com a pessoa (o erro, a pasta que não abriu). Só na thread principal.
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
from PySide6.QtGui import QGuiApplication

from cartridges import edicao, shared
from cartridges.edicao import Escolha, Formulario
from cartridges.jogo import STATUS_LABELS, Jogo
from cartridges.modelos.ordem import _url_da_capa  # noqa: PLC2701
from cartridges.modelos.seletores import SeletorDeLogo, SeletorDoSgdb
from cartridges.utils import capa_video, game_logo, session_wallpaper
from cartridges.utils.game_folder import game_folder, open_folder
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

    # -- campos do formulário --------------------------------------------------------------------

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

    # -- o que a tela mostra e decide ------------------------------------------------------------

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

    @Property(str, notify=ludusaviChanged)
    def ludusaviSubtitulo(self) -> str:  # noqa: N802
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

    # -- capa, logo e papel de parede ------------------------------------------------------------

    seletorDeCapa = Property(QObject, lambda self: self._seletor_de_capa, constant=True)  # noqa: N815
    seletorDeLogo = Property(QObject, lambda self: self._seletor_de_logo, constant=True)  # noqa: N815
    filtroDaCapa = Property(str, lambda self: filtro_de_capa(), constant=True)  # noqa: N815
    filtroDoLogo = Property(  # noqa: N815
        str, lambda self: _filtro(_("Imagens de logo"), game_logo.IMAGE_SUFFIXES), constant=True
    )
    filtroDoPapel = Property(  # noqa: N815
        str, lambda self: _filtro(_("Imagens"), session_wallpaper.IMAGE_SUFFIXES), constant=True
    )

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

    def entregar_capa_baixada(self, arquivo: Path) -> None:
        """A capa que o seletor do SteamGridDB baixou: vira provisória como a de um arquivo, e o original sai."""
        if self._aberto:
            self._converter_capa(arquivo, apagar_origem=True)
        else:
            arquivo.unlink(missing_ok=True)

    def _converter_capa(self, arquivo: Path, apagar_origem: bool) -> None:
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
            na_thread_principal(self._capa_pronta, geracao, pedido, nova, erro)

        threading.Thread(target=trabalhar, daemon=True).start()

    def _capa_pronta(self, geracao: int, pedido: int, nova: Optional[Path], erro: str) -> None:
        if geracao != self._geracao or not self._aberto:
            # O diálogo fechou (ou é de outro jogo): a capa pronta não tem onde entrar.
            if nova is not None:
                edicao.descartar_provisoria(nova)
            return
        self._capas_em_voo -= 1
        self.terminar_operacao()
        if pedido != self._pedido_da_capa:
            # Uma escolha mais nova foi pedida depois desta: vale a última.
            if nova is not None:
                edicao.descartar_provisoria(nova)
            self.capaChanged.emit()
            return
        if nova is not None:
            self._trocar_capa(nova)
        else:
            self.capaChanged.emit()
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
        # shortcut: o arquivo entra com o corte centralizado; a tela de ajuste da faixa vem com a tarefa 10.
        if self._aberto and (caminho := url.toLocalFile()):
            self._trocar_escolha("papel_de_parede", Escolha("manual", Path(caminho)))

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

    def _recalcular(self) -> None:
        # Lê o disco a cada mudança do comando, como a `main`: no disco local custa microssegundos.
        comando = self._form.executavel
        self._empacotado = edicao.empacotado(comando)
        self._acompanha = edicao.acompanha_sem_nome(comando)
        self._pasta = game_folder(comando) or ""
        self.derivadosChanged.emit()

    # -- operação em voo -------------------------------------------------------------------------

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

    # -- abrir e fechar --------------------------------------------------------------------------

    @Slot(str)
    def abrir(self, game_id: str) -> None:
        if self._aberto or (jogo := shared.store.get(game_id)) is None:
            return
        self._abrir(jogo)

    @Slot()
    def adicionar(self) -> None:
        # Como o `DetailsDialog.is_open`: com um diálogo aberto, nada.
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
        self._segundo_monitor = _segundo_monitor()
        self._aberto = True
        self._recalcular()
        for sinal in (
            self.nomeChanged, self.desenvolvedoraChanged, self.publicadoraChanged, self.lancamentoChanged,
            self.generoChanged, self.executavelChanged, self.adminChanged, self.rastrearProcessoChanged,
            self.executavelDoProcessoChanged, self.notificarAtualizacoesChanged, self.conquistasChanged,
            self.appidChanged, self.notaChanged, self.controleIndiceChanged, self.statusIndiceChanged,
            self.ludusaviChanged, self.ocupadoChanged, self.abertoChanged, self.capaChanged, self.imagensChanged,
        ):  # fmt: skip
            sinal.emit()

    def _fechar(self, descartar: bool = True) -> None:
        """Fecha o diálogo. ``descartar``: as provisórias da tela saem (no Aplicar, são do `aplicar`)."""
        for seletor in (self._seletor_de_capa, self._seletor_de_logo):
            seletor.fechar()
        provisoria = self._provisoria()
        escolhas = [e for e in (self._form.logo, self._form.papel_de_parede) if e is not None]
        self._aberto = False
        self._jogo = None
        self._ocupacoes = 0
        self._capas_em_voo = 0
        self._form = Formulario()
        self.abertoChanged.emit()
        self.ocupadoChanged.emit()
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

    # -- ações -----------------------------------------------------------------------------------

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
