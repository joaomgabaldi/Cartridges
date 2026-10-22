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

"""O assistente da primeira abertura: pasta dos jogos, capas e o resto do essencial.

Aparece uma vez, quando não há nada configurado. Cada controle grava na hora, com
handlers explícitos: fechar o assistente a qualquer momento deixa o que já foi
escolhido valendo.
"""

import dataclasses
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from gi.repository import Adw, Gio, GLib, Graphene, Gsk, Gtk

from cartridges import big_picture, conquista_aviso, shared
from cartridges.grupo_das_contas import GrupoDasContas  # registra o GType antes do template
from cartridges.utils import backup, session_fita, window_geometry
from cartridges.utils.create_dialog import create_dialog
from cartridges.utils.na_tela import entregar_na_tela

# A animação da capa (ms): placeholder parado, desliza e some, capa sozinha, capa
# some e o placeholder volta. Um ciclo só, repetido.
_PARADO = 1000
_DESLIZE = 700
_SOZINHA = 2000
_TROCA = 300
_CICLO = _PARADO + _DESLIZE + _SOZINHA + 2 * _TROCA
_DESLOCAMENTO = 60  # px que o placeholder anda para a esquerda


class PalcoDasCapas(Gtk.Widget):
    """O palco da animação: do tamanho de uma capa (2:3), com a capa de exemplo e,
    por cima, o placeholder.

    O palco mede e aloca à mão: as imagens informariam o tamanho do SVG
    (600×900) ao layout da página. O deslocamento do placeholder é só uma
    transformação na alocação, sem mexer no tamanho de ninguém.
    """

    __gtype_name__ = "PalcoDasCapas"
    LARGURA = 120
    ALTURA = 180

    def __init__(self) -> None:
        super().__init__()
        self.capa = self._imagem("/capa_de_exemplo.svg")
        self.vazia = self._imagem("/library_placeholder.svg")
        self.deslocamento = 0.0

    def _imagem(self, recurso: str) -> Gtk.Picture:
        imagem = Gtk.Picture.new_for_resource(shared.PREFIX + recurso)
        imagem.set_content_fit(Gtk.ContentFit.FILL)
        imagem.set_can_shrink(True)
        imagem.set_overflow(Gtk.Overflow.HIDDEN)
        imagem.add_css_class("capa-de-exemplo")
        imagem.set_parent(self)
        return imagem

    def deslocar(self, x: float) -> None:
        self.deslocamento = x
        self.queue_allocate()

    def do_measure(self, orientation: Gtk.Orientation, _para: int) -> tuple[int, int, int, int]:
        tamanho = self.LARGURA if orientation == Gtk.Orientation.HORIZONTAL else self.ALTURA
        return tamanho, tamanho, -1, -1

    def do_size_allocate(self, largura: int, altura: int, _linha_de_base: int) -> None:
        self.capa.allocate(largura, altura, -1, None)
        self.vazia.allocate(
            largura,
            altura,
            -1,
            Gsk.Transform.new().translate(Graphene.Point().init(self.deslocamento, 0)),
        )

    def do_dispose(self) -> None:
        self.capa.unparent()
        self.vazia.unparent()
        super().do_dispose()


def _animacoes_ligadas() -> bool:
    """O sistema permite animações? Sem elas a capa fica parada."""
    return Gtk.Settings.get_default().get_property("gtk-enable-animations")


def _em_thread(tarefa: Callable[[], None]) -> None:
    """Roda ``tarefa`` fora da interface; os testes trocam por uma chamada direta."""
    threading.Thread(target=tarefa, daemon=True).start()


def precisa_mostrar() -> bool:
    """O assistente deve abrir? Só na primeira abertura de quem ainda não tem nada.

    Quem já tem jogos na biblioteca (uma atualização de versão, ou um backup
    restaurado) é marcado como concluído aqui mesmo, para o assistente nunca
    aparecer por cima de uma biblioteca que já existe, nem se ela esvaziar depois.
    """
    if shared.schema.get_boolean("assistente-concluido"):
        return False
    if shared.games_dir.is_dir() and any(shared.games_dir.iterdir()):
        shared.schema.set_boolean("assistente-concluido", True)
        return False
    return True


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/assistente.ui")
class JanelaDoAssistente(Adw.ApplicationWindow):
    __gtype_name__ = "JanelaDoAssistente"

    toasts: Adw.ToastOverlay = Gtk.Template.Child()
    carrossel: Adw.Carousel = Gtk.Template.Child()
    rodape: Gtk.Box = Gtk.Template.Child()
    botoes: Gtk.CenterBox = Gtk.Template.Child()
    voltar_botao: Gtk.Button = Gtk.Template.Child()
    pular_botao: Gtk.Button = Gtk.Template.Child()
    continuar_botao: Gtk.Button = Gtk.Template.Child()

    pagina_boas_vindas: Adw.StatusPage = Gtk.Template.Child()
    pagina_jogos: Adw.StatusPage = Gtk.Template.Child()
    pagina_capas: Adw.StatusPage = Gtk.Template.Child()
    pagina_conquistas: Adw.StatusPage = Gtk.Template.Child()
    pagina_iluminacao: Adw.StatusPage = Gtk.Template.Child()
    pagina_controle: Adw.StatusPage = Gtk.Template.Child()
    pagina_monitores: Adw.StatusPage = Gtk.Template.Child()
    pagina_pronto: Adw.StatusPage = Gtk.Template.Child()

    comecar_botao: Gtk.Button = Gtk.Template.Child()
    restaurar_botao: Gtk.Button = Gtk.Template.Child()
    pular_configuracao_botao: Gtk.Button = Gtk.Template.Child()
    abrir_biblioteca_botao: Gtk.Button = Gtk.Template.Child()

    pasta_row: Adw.ActionRow = Gtk.Template.Child()
    escolher_pasta_botao: Gtk.Button = Gtk.Template.Child()

    palco_das_capas: PalcoDasCapas = Gtk.Template.Child()
    chave_sgdb_grupo: Adw.PreferencesGroup = Gtk.Template.Child()
    chave_sgdb_row: Adw.EntryRow = Gtk.Template.Child()
    capas_animadas_switch: Adw.SwitchRow = Gtk.Template.Child()

    lugar_do_cartao: Gtk.Box = Gtk.Template.Child()
    grupo_das_contas: GrupoDasContas = Gtk.Template.Child()
    chave_steam_grupo: Adw.PreferencesGroup = Gtk.Template.Child()
    chave_steam_row: Adw.EntryRow = Gtk.Template.Child()

    configurar_iluminacao_botao: Gtk.Button = Gtk.Template.Child()

    big_picture_switch: Adw.SwitchRow = Gtk.Template.Child()

    mover_switch: Adw.SwitchRow = Gtk.Template.Child()
    monitor_row: Adw.ComboRow = Gtk.Template.Child()
    identificar_row: Adw.ButtonRow = Gtk.Template.Child()
    papel_de_parede_switch: Adw.SwitchRow = Gtk.Template.Child()

    def __init__(
        self,
        ao_terminar: Callable[[], None],
        ao_restaurar: Callable[[], None],
        **kwargs: Any,
    ) -> None:
        super().__init__()
        # Propriedades passadas ao `super().__init__` de um widget de template são
        # ignoradas; por isso entram aqui.
        for nome, valor in kwargs.items():
            self.set_property(nome, valor)
        self._ao_terminar = ao_terminar
        self._ao_restaurar = ao_restaurar
        self._indice = 0
        self._preparando_restauracao = False

        # A página já explica as contas: o título e a descrição do grupo, que
        # as Preferências mostram, só repetiriam o texto aqui.
        self.grupo_das_contas.set_title("")
        self.grupo_das_contas.set_description("")

        self._montar_animacao_das_capas()
        self._montar_cartao_de_conquista()

        self.comecar_botao.connect("clicked", lambda *_: self.avancar())
        self.continuar_botao.connect("clicked", lambda *_: self.avancar())
        self.pular_botao.connect("clicked", lambda *_: self.avancar())
        self.voltar_botao.connect("clicked", lambda *_: self.voltar())
        self.pular_configuracao_botao.connect("clicked", lambda *_: self.concluir())
        self.abrir_biblioteca_botao.connect("clicked", lambda *_: self.concluir())

        self.restaurar_botao.connect("clicked", self._escolher_backup)
        self.connect("close-request", self._fechar_no_x)
        self.connect("destroy", lambda *_: self._animacao_das_capas.reset())

        self.escolher_pasta_botao.connect("clicked", self._escolher_pasta)
        self._atualizar_subtitulo_da_pasta()

        # Os controles nascem com o que já está gravado, antes de ligar os
        # handlers (que gravariam de volta o que acabaram de ler).
        chave = shared.schema.get_string("sgdb-key")
        self.chave_sgdb_row.set_text(chave)
        self.capas_animadas_switch.set_visible(bool(chave))
        self.capas_animadas_switch.set_active(
            shared.schema.get_boolean("sgdb-animated")
        )
        self.chave_steam_row.set_text(
            shared.schema.get_string("conquistas-chave-steam")
        )
        self.big_picture_switch.set_active(
            shared.schema.get_boolean("big-picture-ao-conectar")
        )
        self.mover_switch.set_active(shared.schema.get_boolean("session-move-window"))
        self.papel_de_parede_switch.set_active(
            shared.schema.get_boolean("session-wallpaper")
        )

        self.chave_sgdb_row.connect("changed", self._chave_sgdb_mudou)
        # A mesma frase das Preferências.
        self.chave_sgdb_grupo.set_description(
            _(
                "É necessária uma chave da API para usar o SteamGridDB. {}Obtenha aqui{}."
            ).format('<a href="https://www.steamgriddb.com/profile/preferences/api">', "</a>")
        )
        self.capas_animadas_switch.connect("notify::active", self._capas_animadas_mudou)

        self.chave_steam_row.connect(
            "changed",
            lambda linha: shared.schema.set_string(
                "conquistas-chave-steam", linha.get_text().strip()
            ),
        )
        self.chave_steam_grupo.set_description(
            _("Informe a chave da Steam Web API. {}Obtenha aqui{}.").format(
                '<a href="https://steamcommunity.com/dev/apikey">', "</a>"
            )
        )

        self.configurar_iluminacao_botao.connect("clicked", self._configurar_iluminacao)

        self.big_picture_switch.connect(
            "notify::active",
            lambda *_: shared.schema.set_boolean(
                "big-picture-ao-conectar", self.big_picture_switch.get_active()
            ),
        )
        # Só dá para saber se há renderizador 3D com a janela realizada.
        self.connect("realize", self._ao_realizar)

        monitores = window_geometry.monitores_da_sessao()
        if monitores:
            window_geometry.preencher_escolha_de_monitor(self.monitor_row, monitores)
            self.identificar_row.connect(
                "activated", lambda *_: window_geometry.identify_monitors()
            )
            self.mover_switch.connect(
                "notify::active",
                lambda *_: shared.schema.set_boolean(
                    "session-move-window", self.mover_switch.get_active()
                ),
            )
            self.papel_de_parede_switch.connect(
                "notify::active",
                lambda *_: shared.schema.set_boolean(
                    "session-wallpaper", self.papel_de_parede_switch.get_active()
                ),
            )
        else:
            self.carrossel.remove(self.pagina_monitores)

        self._atualizar_rodape()

    def _ao_realizar(self, *_args: Any) -> None:
        if not big_picture.tem_3d(self):
            self.carrossel.remove(self.pagina_controle)
            self._atualizar_rodape()

    def paginas(self) -> list[Gtk.Widget]:
        """As telas que estão no carrossel, na ordem."""
        return [
            self.carrossel.get_nth_page(i) for i in range(self.carrossel.get_n_pages())
        ]

    def _atualizar_rodape(self) -> None:
        # A primeira e a última telas têm botões próprios; o rodapé some.
        paginas = self.paginas()
        self.botoes.set_visible(0 < self._indice < len(paginas) - 1)
        # O Tab não pode alcançar controles de telas fora da vista.
        for i, pagina in enumerate(paginas):
            pagina.set_can_focus(i == self._indice)
        atual = paginas[self._indice]
        # Sem pasta escolhida, não há o que continuar: só "Pular" segue em frente.
        self.continuar_botao.set_sensitive(
            atual is not self.pagina_jogos or bool(shared.schema.get_string("shortcuts-location"))
        )
        self._atualizar_animacao_das_capas(atual is self.pagina_capas)

    def _ir_para(self, indice: int) -> None:
        paginas = self.paginas()
        if 0 <= indice < len(paginas):
            self._indice = indice
            self._atualizar_rodape()
            self.carrossel.scroll_to(paginas[indice], True)

    def avancar(self) -> None:
        self._ir_para(self._indice + 1)

    def voltar(self) -> None:
        self._ir_para(self._indice - 1)

    def concluir(self) -> None:
        """Fecha o assistente de vez: "Pular configuração" e "Abrir a biblioteca"."""
        shared.schema.set_boolean("assistente-concluido", True)
        # Um login pendente não pode ficar preso a uma janela destruída.
        self.grupo_das_contas.fechar()
        # Mesmo com a abertura quebrada: uma janela órfã, sem dono no app, não
        # teria como ser fechada.
        try:
            self._ao_terminar()
        finally:
            self.destroy()

    def _fechar_no_x(self, *_args: Any) -> bool:
        """Fechar pelo X cancela logins em andamento; a marca não é gravada."""
        # Com o backup sendo preparado, fechar deixaria a cópia pela metade ou a
        # restauração agendada sem a janela: o toast já pede para aguardar.
        if self._preparando_restauracao:
            return True
        self.grupo_das_contas.fechar()
        return False  # fecha; sem janelas, o app encerra

    # Tela 0: restaurar um backup
    def _escolher_backup(self, *_args: Any) -> None:
        filtro = Gtk.FileFilter()
        filtro.set_name(_("Backup do Cartridges"))
        filtro.add_pattern("*.zip")
        filtros = Gio.ListStore.new(Gtk.FileFilter)
        filtros.append(filtro)
        dialogo = Gtk.FileDialog()
        dialogo.set_filters(filtros)

        def terminou(_dialogo: Any, resultado: Any) -> None:
            try:
                arquivo = dialogo.open_finish(resultado)
            except GLib.Error:
                return  # cancelar não muda nada
            self.restaurar_backup(Path(arquivo.get_path()))

        dialogo.open(self, None, terminou)

    def restaurar_backup(self, caminho: Path) -> None:
        """Valida e agenda o backup; sem confirmação, pois não há nada a perder."""
        # A validação lê o arquivo inteiro e leva segundos: os botões da tela 0
        # ficam inativos, senão um segundo clique restauraria duas vezes (ou
        # abriria a biblioteca no meio).
        self._bloquear_boas_vindas(True)
        self._preparando_restauracao = True
        # "Aguarde" porque o X também fica sem efeito até terminar (`_fechar_no_x`).
        self._toast_restauracao = Adw.Toast.new(_("Preparando a restauração. Aguarde…"))
        self._toast_restauracao.set_timeout(0)
        self.toasts.add_toast(self._toast_restauracao)

        def trabalho() -> None:
            try:
                backup.validar(caminho)
                backup.agendar(caminho)
            except backup.BackupInvalido:
                entregar_na_tela(self._backup_invalido)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Não foi possível agendar a restauração do backup")
                entregar_na_tela(self._backup_falhou)
            else:
                entregar_na_tela(self._backup_agendado)

        _em_thread(trabalho)

    def _bloquear_boas_vindas(self, bloquear: bool) -> None:
        for botao in (
            self.comecar_botao,
            self.restaurar_botao,
            self.pular_configuracao_botao,
        ):
            botao.set_sensitive(not bloquear)

    def _fim_da_preparacao(self) -> None:
        self._preparando_restauracao = False
        self._toast_restauracao.dismiss()
        self._bloquear_boas_vindas(False)

    def _backup_agendado(self) -> bool:
        shared.schema.set_boolean("assistente-concluido", True)
        self.grupo_das_contas.fechar()
        # Idem `concluir`: a janela não pode sobrar órfã se a restauração quebrar.
        try:
            self._ao_restaurar()
        finally:
            self.destroy()
        return False

    def _backup_invalido(self) -> bool:
        self._fim_da_preparacao()
        create_dialog(
            self,
            _("Backup inválido"),
            _("O arquivo não é um backup válido do Cartridges."),
        )
        return False

    def _backup_falhou(self) -> bool:
        self._fim_da_preparacao()
        create_dialog(
            self,
            _("Não foi possível restaurar"),
            _("Não foi possível restaurar o backup. Tente novamente."),
        )
        return False

    # Tela 4: a iluminação inteligente
    def _configurar_iluminacao(self, *_args: Any) -> None:
        from cartridges.fita_wizard import FitaWizard  # noqa: PLC0415

        assistente = FitaWizard()
        assistente.connect("closed", lambda *_: self.ao_fechar_iluminacao())
        assistente.present(self)

    def ao_fechar_iluminacao(self) -> None:
        # Sem isso nada acenderia: o recurso nasce desligado.
        if session_fita.fitas():
            shared.schema.set_boolean("session-fita", True)

    # Tela 1: a pasta dos atalhos
    def _escolher_pasta(self, *_args: Any) -> None:
        dialogo = Gtk.FileDialog()

        def terminou(_dialogo: Any, resultado: Any) -> None:
            try:
                pasta = dialogo.select_folder_finish(resultado)
            except GLib.Error:
                return  # cancelar não muda nada
            self.gravar_pasta(Path(pasta.get_path()))

        dialogo.select_folder(self, None, terminou)

    def gravar_pasta(self, caminho: Path) -> None:
        shared.schema.set_string("shortcuts-location", str(caminho))
        # Sem a importação ligada a pasta escolhida não traria nenhum jogo.
        shared.schema.set_boolean("auto-import", True)
        self._atualizar_subtitulo_da_pasta()
        self._atualizar_rodape()

    def _atualizar_subtitulo_da_pasta(self) -> None:
        local = shared.schema.get_string("shortcuts-location")
        # Mesmo formato das Preferências: barras invertidas, e o escape do markup
        # porque um "&" no caminho derrubaria o subtítulo inteiro.
        self.pasta_row.set_subtitle(
            GLib.markup_escape_text(local.replace("/", "\\"))
            if local
            else _("Nenhuma pasta selecionada")
        )

    # Tela 2: o SteamGridDB
    def _montar_animacao_das_capas(self) -> None:
        """A capa de exemplo com o placeholder por cima, que desliza e revela a capa."""
        self.capa_de_exemplo = self.palco_das_capas.capa
        self.capa_vazia = self.palco_das_capas.vazia
        self._animacao_das_capas = Adw.TimedAnimation(
            widget=self.palco_das_capas,
            value_from=0,
            value_to=_CICLO,
            duration=_CICLO,
            easing=Adw.Easing.LINEAR,
            repeat_count=0,  # sem fim, enquanto a tela estiver à vista
            target=Adw.CallbackAnimationTarget.new(self._quadro_das_capas),
        )

    def _quadro_das_capas(self, instante: float) -> None:
        """Um quadro do ciclo, ``instante`` em ms desde o começo dele."""
        deslize_fim = _PARADO + _DESLIZE
        sozinha_fim = deslize_fim + _SOZINHA
        x, vazia, capa = 0.0, 1.0, 1.0
        if instante >= sozinha_fim + _TROCA:  # o placeholder volta ao centro
            vazia, capa = (instante - sozinha_fim - _TROCA) / _TROCA, 0.0
        elif instante >= sozinha_fim:  # a capa some
            vazia, capa = 0.0, 1 - (instante - sozinha_fim) / _TROCA
            x = -_DESLOCAMENTO
        elif instante >= deslize_fim:  # a capa sozinha
            vazia, x = 0.0, -_DESLOCAMENTO
        elif instante >= _PARADO:  # o placeholder desliza e some
            progresso = (instante - _PARADO) / _DESLIZE
            vazia = 1 - progresso
            x = -_DESLOCAMENTO * (1 - (1 - progresso) ** 3)
        # Só o desenho se move; o tamanho do palco não muda.
        self.palco_das_capas.deslocar(x)
        self.capa_vazia.set_opacity(min(1.0, max(0.0, vazia)))
        self.capa_de_exemplo.set_opacity(min(1.0, max(0.0, capa)))

    def _atualizar_animacao_das_capas(self, visivel: bool) -> None:
        """Anima só com a tela à vista; sem animações no sistema, a capa fica parada."""
        animacao = self._animacao_das_capas
        if visivel and _animacoes_ligadas():
            if animacao.get_state() != Adw.AnimationState.PLAYING:
                animacao.play()
            return
        animacao.reset()
        self._quadro_das_capas(_PARADO + _DESLIZE + _TROCA)  # a capa, sozinha

    def _montar_cartao_de_conquista(self) -> None:
        """O cartão do aviso de conquista, o de verdade, com um exemplo."""
        aviso = dataclasses.replace(
            conquista_aviso.Aviso.exemplo(2.3),
            titulo=_("Lenda das ruas"),
            descricao=_("Vença todas as corridas em primeiro lugar."),
        )
        self.cartao_de_conquista, _imagem = conquista_aviso.montar_cartao(
            aviso, shared.PREFIX + "/conquista_de_exemplo.svg"
        )
        self.cartao_de_conquista.add_css_class("conquista-aviso-cartao-embutido")
        self.lugar_do_cartao.append(self.cartao_de_conquista)

    def _chave_sgdb_mudou(self, linha: Adw.EntryRow) -> None:
        chave = linha.get_text().strip()
        shared.schema.set_string("sgdb-key", chave)
        shared.schema.set_boolean("sgdb", bool(chave))
        self.capas_animadas_switch.set_visible(bool(chave))

    def _capas_animadas_mudou(self, *_args: Any) -> None:
        # Uma sem a outra não tem efeito visível.
        ativo = self.capas_animadas_switch.get_active()
        shared.schema.set_boolean("sgdb-animated", ativo)
        shared.schema.set_boolean("cover-autoplay", ativo)
