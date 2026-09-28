# restauracao_dialogs.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As telas da restauração de um backup: a pasta de atalhos que falta, os
jogos sem atalho, a escolha do atalho e o conflito de histórico.

Só abrem enquanto `restauracao_pendente.json` existir (ver
`utils/restauracao.py`); a lógica mora lá, e aqui só os widgets.
"""

from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from gi.repository import Adw, GdkPixbuf, Gio, GLib, Gtk

from cartridges import shared
from cartridges.game import Game
from cartridges.game_cover import texture_from_pixbuf
from cartridges.utils import restauracao
from cartridges.utils.create_dialog import create_dialog
from cartridges.utils.format_playtime import format_playtime


def avisar_falha() -> None:
    create_dialog(
        shared.win,
        _("Não foi possível restaurar"),
        _("Não foi possível restaurar o backup. Tente novamente."),
    )


def _avisar_concluida() -> None:
    """O fim da restauração: nenhum jogo restaurado ficou sem atalho."""
    shared.win.toast_queue.add(Adw.Toast.new(_("Restauração concluída")))


def _sessoes(numero: int) -> str:
    return ngettext("{} sessão", "{} sessões", numero).format(numero)


def _dialogo(titulo: str, conteudo: Gtk.Widget, largura: int = 480) -> Adw.Dialog:
    dialogo = Adw.Dialog(title=titulo, content_width=largura)
    vista = Adw.ToolbarView()
    vista.add_top_bar(Adw.HeaderBar())
    vista.set_content(conteudo)
    dialogo.set_child(vista)
    return dialogo


def _caixa() -> Gtk.Box:
    return Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=18,
        margin_top=12,
        margin_bottom=24,
        margin_start=24,
        margin_end=24,
    )


def _rolagem(filho: Gtk.Widget, altura: int) -> Gtk.ScrolledWindow:
    rolagem = Gtk.ScrolledWindow(
        hscrollbar_policy=Gtk.PolicyType.NEVER,
        propagate_natural_height=True,
        max_content_height=altura,
    )
    rolagem.set_child(filho)
    return rolagem


def _capa(jogo: Game, largura: int, altura: int) -> Gtk.Widget:
    """A capa num tamanho fixo. ``size_request`` num Gtk.Picture é piso, não
    teto, e a largura natural dele é a da imagem: a imagem vem já reduzida
    (como nas prévias do `logo_picker`) e um Adw.Clamp segura a largura."""
    imagem = Gtk.Picture(
        content_fit=Gtk.ContentFit.COVER,
        can_shrink=True,
        width_request=largura,
        height_request=altura,
    )
    imagem.set_overflow(Gtk.Overflow.HIDDEN)
    imagem.add_css_class("card")
    if (caminho := jogo.get_cover_path()) is not None:
        escala = max(1, int(shared.scale_factor))
        try:
            imagem.set_paintable(
                texture_from_pixbuf(
                    GdkPixbuf.Pixbuf.new_from_file_at_scale(
                        str(caminho), largura * escala, altura * escala, False
                    )
                )
            )
        except GLib.Error:
            pass  # capa ilegível: fica o cartão vazio
    return Adw.Clamp(
        child=imagem,
        maximum_size=largura,
        tightening_threshold=largura,
        valign=Gtk.Align.CENTER,
    )


class PedirPasta:
    """Obrigatória: sem a pasta de atalhos, nenhum jogo restaurado abre."""

    def __init__(self, ao_escolher: Callable[[], None]) -> None:
        self.ao_escolher = ao_escolher
        caminho = shared.schema.get_string("shortcuts-location")
        caixa = _caixa()
        self.texto = Gtk.Label(
            label=(
                _("A pasta de atalhos {} não foi encontrada.").format(caminho)
                if caminho
                else _("A pasta de atalhos não foi encontrada.")
            ),
            wrap=True,
            justify=Gtk.Justification.CENTER,
        )
        self.botao = Gtk.Button(label=_("Escolher pasta…"), halign=Gtk.Align.CENTER)
        self.botao.add_css_class("pill")
        self.botao.add_css_class("suggested-action")
        self.botao.connect("clicked", self._escolher)
        caixa.append(self.texto)
        caixa.append(self.botao)

        self.dialogo = _dialogo(_("Pasta de atalhos"), caixa)
        # Nem Esc nem o X fecham: a janela só sai com a pasta escolhida.
        self.dialogo.set_can_close(False)

    def present(self) -> None:
        self.dialogo.present(shared.win)

    def _escolher(self, *_args: object) -> None:
        def fim(seletor: Gtk.FileDialog, resultado: Gio.AsyncResult) -> None:
            try:
                pasta = seletor.select_folder_finish(resultado)
            except GLib.Error:
                return  # cancelado: a janela continua
            shared.schema.set_string("shortcuts-location", pasta.get_path())
            self.dialogo.force_close()
            self.ao_escolher()

        Gtk.FileDialog().select_folder(shared.win, None, fim)


class JanelaPendentes:
    def __init__(self) -> None:
        caixa = _caixa()
        self.texto = Gtk.Label(
            label=_("Os atalhos dos jogos abaixo não foram encontrados."), wrap=True
        )
        self.lista = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.lista.add_css_class("boxed-list")
        # "Lembrar mais tarde" só fecha: a restauração continua pendente e o
        # aviso de concluída não aparece.
        self.depois = Gtk.Button(label=_("Lembrar mais tarde"), halign=Gtk.Align.CENTER)
        self.depois.add_css_class("pill")
        self.depois.connect("clicked", lambda *_a: self.dialogo.close())
        caixa.append(self.texto)
        caixa.append(_rolagem(self.lista, 420))
        caixa.append(self.depois)

        self.dialogo = _dialogo(_("Jogos sem atalho"), caixa, largura=560)
        self.atualizar()

    def present(self) -> None:
        self.dialogo.present(shared.win)

    def atualizar(self) -> None:
        self.lista.remove_all()
        # Travada enquanto a importação de uma escolha de atalho roda.
        self.lista.set_sensitive(True)
        jogos = restauracao.pendentes()
        if not jogos:
            self.dialogo.force_close()
            _avisar_concluida()
            return
        for jogo in jogos:
            linha = Adw.ActionRow(
                title=jogo.name,
                subtitle=format_playtime(jogo.playtime or 0),
                use_markup=False,
            )
            linha.add_prefix(_capa(jogo, 32, 48))
            escolher = Gtk.Button(label=_("Escolher atalho…"), valign=Gtk.Align.CENTER)
            escolher.connect("clicked", lambda *_a, j=jogo: self._escolher(j))
            excluir = Gtk.Button(label=_("Excluir"), valign=Gtk.Align.CENTER)
            excluir.add_css_class("destructive-action")
            excluir.connect("clicked", lambda *_a, j=jogo: self._excluir(j))
            linha.add_suffix(escolher)
            linha.add_suffix(excluir)
            self.lista.append(linha)

    def _escolher(self, jogo: Game) -> None:
        EscolherAtalho(
            jogo, self.atualizar, lambda: self.lista.set_sensitive(False)
        ).dialogo.present(self.dialogo)

    def _excluir(self, jogo: Game) -> None:
        def resposta(_dialogo: Adw.AlertDialog, escolha: str) -> None:
            if escolha == "delete":
                restauracao.excluir(jogo)
                self.atualizar()

        create_dialog(
            self.dialogo,
            # A variável é o nome do jogo
            _("Excluir {}?").format(jogo.name),
            _("Tem certeza que deseja excluir este jogo? Esta ação é irreversível."),
            "delete",
            _("Excluir"),
            destructive=True,
        ).connect("response", resposta)


class EscolherAtalho:
    def __init__(
        self,
        jogo: Game,
        ao_concluir: Callable[[], None],
        ao_importar: Callable[[], None] = lambda: None,
    ) -> None:
        self.jogo = jogo
        self.ao_concluir = ao_concluir
        # Chamado antes da importação: quem abriu esta tela impede uma
        # segunda escolha até ela terminar. Duas importações ao mesmo tempo
        # zerariam as listas de jogos achados uma da outra.
        self.ao_importar = ao_importar
        caixa = _caixa()
        self.lista = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.lista.add_css_class("boxed-list")
        for caminho in restauracao.candidatos(jogo):
            linha = Adw.ActionRow(
                title=caminho.stem, subtitle=caminho.name, activatable=True, use_markup=False
            )
            linha.connect("activated", lambda *_a, c=caminho: self._usar(c))
            self.lista.append(linha)
        procurar = Gtk.Button(label=_("Procurar outro atalho…"), halign=Gtk.Align.CENTER)
        procurar.add_css_class("pill")
        procurar.connect("clicked", self._procurar)
        if self.lista.get_row_at_index(0) is not None:
            caixa.append(_rolagem(self.lista, 360))
        caixa.append(procurar)

        self.dialogo = _dialogo(jogo.name, caixa)

    def _procurar(self, *_args: object) -> None:
        filtro = Gtk.FileFilter(name=_("Atalhos"))
        filtro.add_suffix("lnk")
        filtro.add_suffix("url")
        filtros = Gio.ListStore.new(Gtk.FileFilter)
        filtros.append(filtro)
        seletor = Gtk.FileDialog()
        seletor.set_filters(filtros)

        def fim(dialogo: Gtk.FileDialog, resultado: Gio.AsyncResult) -> None:
            try:
                origem = Path(dialogo.open_finish(resultado).get_path())
            except GLib.Error:
                return
            try:
                caminho = restauracao.copiar_para_a_pasta(origem)
            except restauracao.AtalhoJaExiste:
                create_dialog(
                    self.dialogo,
                    _("Já existe um atalho com este nome. Selecione-o na lista."),
                    "",
                )
                return
            self._usar(caminho)

        seletor.open(shared.win, None, fim)

    def _usar(self, caminho: Path) -> None:
        novo = restauracao.jogo_do_atalho(caminho)
        self.dialogo.close()
        if novo is not None and restauracao.tem_historico(novo):
            TelaConflito(
                self.jogo, novo, lambda decisao: self._concluir(caminho, novo, decisao)
            ).dialogo.present(shared.win)
        else:
            self._concluir(caminho, novo, "backup")

    def _concluir(self, caminho: Path, novo: Optional[Game], decisao: str) -> None:
        restauracao.decidir(self.jogo, caminho, novo, decisao)
        if decisao == "este_pc":
            self.ao_concluir()
            return
        # A varredura adota o jogo pelo atalho novo e o tira das pendências.
        self.ao_importar()
        shared.win.get_application().on_import_action(
            mostrar_progresso=False, ao_terminar=self.ao_concluir, varrer_atalhos=True
        )


class TelaConflito:
    """Arranjo da tela de conflito de saves do PlayStation: capa e nome no
    topo, os dois cartões lado a lado com o aviso no meio, o texto e os
    botões embaixo."""

    def __init__(
        self, restaurado: Game, novo: Game, ao_decidir: Callable[[str], None]
    ) -> None:
        caixa = _caixa()

        topo = Gtk.Box(spacing=14, halign=Gtk.Align.CENTER)
        topo.append(_capa(restaurado, 44, 66))
        nome = Gtk.Label(label=restaurado.name)
        nome.add_css_class("title-2")
        topo.append(nome)
        caixa.append(topo)

        cartoes = Gtk.Box(spacing=12)
        cartoes.append(self._cartao(_("Backup"), "drive-harddisk-symbolic", restaurado))
        aviso = Gtk.Image(icon_name="dialog-warning-symbolic", valign=Gtk.Align.CENTER)
        aviso.add_css_class("warning")
        cartoes.append(aviso)
        cartoes.append(self._cartao(_("Este PC"), "computer-symbolic", novo))
        caixa.append(cartoes)

        self.texto = Gtk.Label(
            label=_(
                "Este jogo já possui dados locais. Escolha qual versão deseja "
                "manter ou mescle as duas fontes."
            ),
            wrap=True,
            justify=Gtk.Justification.CENTER,
        )
        caixa.append(self.texto)

        linha = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        self.botoes: dict[str, Gtk.Button] = {}
        for decisao, rotulo in (
            ("backup", _("Manter backup")),
            ("mesclar", _("Mesclar dados")),
            ("este_pc", _("Manter este PC")),
        ):
            botao = Gtk.Button(label=rotulo)
            botao.add_css_class("pill")
            botao.connect("clicked", lambda *_a, d=decisao: self._decidir(d, ao_decidir))
            self.botoes[decisao] = botao
            linha.append(botao)
        caixa.append(linha)

        segundos_a, sessoes_a, _ultima_a = restauracao.resumo(restaurado)
        segundos_b, sessoes_b, _ultima_b = restauracao.resumo(novo)
        self.dica = Gtk.Label(
            label=_("Mesclar dados: {} em {}").format(
                format_playtime(segundos_a + segundos_b), _sessoes(sessoes_a + sessoes_b)
            )
        )
        self.dica.add_css_class("dim-label")
        self.dica.add_css_class("caption")
        caixa.append(self.dica)

        self.dialogo = _dialogo(_("Dados do jogo"), caixa, largura=620)

    @staticmethod
    def _cartao(titulo: str, icone: str, jogo: Game) -> Gtk.Widget:
        segundos, sessoes, ultima = restauracao.resumo(jogo)
        cartao = Gtk.Box(spacing=12, hexpand=True)
        cartao.add_css_class("card")
        cartao.append(
            Gtk.Image(
                icon_name=icone,
                pixel_size=24,
                valign=Gtk.Align.START,
                margin_start=14,
                margin_top=14,
            )
        )
        interno = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            margin_top=14,
            margin_bottom=14,
            margin_end=14,
        )
        rotulo = Gtk.Label(label=titulo, xalign=0)
        rotulo.add_css_class("heading")
        interno.append(rotulo)
        linhas = [format_playtime(segundos), _sessoes(sessoes)]
        if ultima:
            data = datetime.fromtimestamp(ultima).strftime("%d/%m/%Y")
            linhas.append(_("Última: {}").format(data))
        for texto in linhas:
            linha = Gtk.Label(label=texto, xalign=0)
            linha.add_css_class("dim-label")
            interno.append(linha)
        cartao.append(interno)
        return cartao

    def _decidir(self, decisao: str, ao_decidir: Callable[[str], None]) -> None:
        self.dialogo.close()
        ao_decidir(decisao)


def mostrar_pendentes() -> None:
    """Fim da importação da abertura durante uma restauração: a janela, se
    ainda houver pendências; senão, a restauração acabou ali mesmo."""
    if restauracao.existe() and restauracao.pendentes():
        JanelaPendentes().present()
    else:
        _avisar_concluida()
