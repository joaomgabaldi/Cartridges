# calibracao_janela.py
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

"""O assistente de calibração da iluminação, no estilo da calibração HDR do
Windows: uma cor de referência por etapa, grande na tela, com o dispositivo
aceso nela, e controles até a parede bater com a tela.

Montado em código, como a janela do brilho por dispositivo das Preferências.
Tudo fica em memória até o Concluir; Cancelar ou fechar a janela não grava
nada, e as fitas voltam à cor do app de qualquer jeito.
"""

import colorsys
import math
from typing import Any, Optional

from gi.repository import Adw, GLib, Gtk

from cartridges.utils import calibracao, session_fita
from cartridges.utils.calibracao import NEUTRA, REFERENCIAS, Calibracao
from cartridges.utils.session_fita import Cor, Fita

NOMES_DAS_ETAPAS = (
    _("Vermelho"),
    _("Amarelo"),
    _("Verde"),
    _("Ciano"),
    _("Azul"),
    _("Magenta"),
    _("Branco"),
)
ETAPA_DO_BRANCO = len(REFERENCIAS)

# De quanto em quanto tempo o teste final troca de cor.
INTERVALO_DO_TESTE = 3


def _cor_da_etapa(etapa: int) -> Cor:
    """A cor de referência de uma etapa, no brilho padrão do app."""
    if etapa == ETAPA_DO_BRANCO:
        return Cor(0, 0, session_fita.brilho_padrao())
    return Cor(REFERENCIAS[etapa], session_fita.BRILHO_CHEIO, session_fita.brilho_padrao())


class AssistenteDeCalibracao(Adw.Dialog):
    """O assistente. ``calibracoes`` é o estado em edição, por id da fita."""

    def __init__(self, configuradas: list[Fita]) -> None:
        super().__init__(title=_("Calibrar as cores"), content_width=520, content_height=620)
        self.fitas = configuradas
        self.calibracoes: dict[str, Calibracao] = {
            fita.id: calibracao.de_json(fita.calibracao) if fita.calibracao else NEUTRA
            for fita in configuradas
        }
        self.id_atual: Optional[str] = None
        self.etapa = 0
        self._indice_do_teste = 0
        self._temporizador = 0
        self._encerrado = False
        # Enquanto a etapa carrega os controles, mexer neles não é ajuste.
        self._carregando = False
        self._cor_na_tela = _cor_da_etapa(0)

        self._pilha = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self._pilha.add_named(self._montar_inicio(), "inicio")
        self._pilha.add_named(self._montar_etapa(), "etapa")
        self._pilha.add_named(self._montar_fim(), "fim")
        self._pilha.add_named(self._montar_teste(), "teste")

        cabecalho = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        cancelar = Gtk.Button(label=_("Cancelar"))
        cancelar.connect("clicked", lambda *_: self.cancelar())
        cabecalho.pack_start(cancelar)
        vista = Adw.ToolbarView(content=self._pilha)
        vista.add_top_bar(cabecalho)
        self.set_child(vista)
        self.connect("closed", self._ao_fechar)

    # region Montagem

    def _amostra(self) -> Gtk.DrawingArea:
        """O quadro grande com a cor de referência."""
        area = Gtk.DrawingArea(vexpand=True, hexpand=True, content_height=240)
        area.set_draw_func(self._desenhar)
        return area

    def _desenhar(self, _area: Any, contexto: Any, largura: int, altura: int) -> None:
        cor = self._cor_na_tela
        vermelho, verde, azul = colorsys.hsv_to_rgb(cor.matiz / 360, cor.saturacao / 1000, 1)
        contexto.set_source_rgb(vermelho, verde, azul)
        raio = 12
        contexto.new_sub_path()
        contexto.arc(largura - raio, raio, raio, -math.pi / 2, 0)
        contexto.arc(largura - raio, altura - raio, raio, 0, math.pi / 2)
        contexto.arc(raio, altura - raio, raio, math.pi / 2, math.pi)
        contexto.arc(raio, raio, raio, math.pi, 3 * math.pi / 2)
        contexto.close_path()
        contexto.fill()

    def _botao(self, rotulo: str, acao: Any, sugerido: bool = False) -> Gtk.Button:
        botao = Gtk.Button(label=rotulo)
        if sugerido:
            botao.add_css_class("suggested-action")
        botao.connect("clicked", lambda *_: acao())
        return botao

    def _pagina(self, *filhos: Gtk.Widget) -> Gtk.Widget:
        caixa = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=12,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )
        for filho in filhos:
            caixa.append(filho)
        return caixa

    def _linha_de_botoes(self, *botoes: Gtk.Widget) -> Gtk.Box:
        caixa = Gtk.Box(spacing=12, halign=Gtk.Align.END)
        for botao in botoes:
            caixa.append(botao)
        return caixa

    def _montar_inicio(self) -> Gtk.Widget:
        texto = Gtk.Label(
            label=_(
                "Escolha o dispositivo a calibrar. Em cada etapa, ajuste os controles "
                "até a cor do dispositivo ficar igual à da tela. Para um resultado "
                "melhor, deixe o ambiente com pouca luz."
            ),
            wrap=True,
            xalign=0,
        )
        self._lista = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE)
        self._linhas_do_inicio: dict[str, Adw.ActionRow] = {}
        for fita in self.fitas:
            linha = Adw.ActionRow(title=fita.nome, activatable=True)
            linha.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            linha.connect("activated", lambda _linha, id_=fita.id: self.escolher(id_))
            self._lista.append(linha)
            self._linhas_do_inicio[fita.id] = linha
        self._atualizar_inicio()
        return self._pagina(texto, self._lista)

    def _escala(self, minimo: float, maximo: float, passo: float, ao_mudar: Any) -> Gtk.Scale:
        escala = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, minimo, maximo, passo)
        escala.set_hexpand(True)
        escala.connect("value-changed", lambda escala: ao_mudar(escala.get_value()))
        return escala

    def _montar_etapa(self) -> Gtk.Widget:
        self._titulo_da_etapa = Gtk.Label(css_classes=["title-2"], xalign=0)
        self._amostra_da_etapa = self._amostra()

        self._tom = self._escala(
            -calibracao.TOM_MAXIMO, calibracao.TOM_MAXIMO, 1,
            lambda valor: self._ao_ajustar(lambda: self.mudar_tom(round(valor))),
        )
        self._intensidade = self._escala(
            calibracao.FATOR_MINIMO * 100, calibracao.FATOR_MAXIMO * 100, 1,
            lambda valor: self._ao_ajustar(lambda: self.mudar_intensidade(valor / 100)),
        )
        self._temperatura = self._escala(
            -100, 100, 1,
            lambda valor: self._ao_ajustar(lambda: self.mudar_temperatura(valor / 100)),
        )
        # O ponto sem ajuste de cada controle, marcado: é para onde o
        # Restaurar leva.
        self._tom.add_mark(0, Gtk.PositionType.BOTTOM, None)
        self._intensidade.add_mark(100, Gtk.PositionType.BOTTOM, None)
        self._temperatura.add_mark(0, Gtk.PositionType.BOTTOM, None)
        # As pontas da Temperatura em rótulos próprios, e não nas marcas: a
        # marca centraliza o texto na ponta, e "Mais frio" passava da margem.
        pontas = Gtk.Box()
        pontas.append(Gtk.Label(label=_("Mais quente"), hexpand=True, xalign=0, css_classes=["dim-label"]))
        pontas.append(Gtk.Label(label=_("Mais frio"), hexpand=True, xalign=1, css_classes=["dim-label"]))

        self._linhas_de_cor = []
        controles = Gtk.Grid(column_spacing=12, row_spacing=6)
        for linha, (rotulo, escala) in enumerate(
            ((_("Tom"), self._tom), (_("Intensidade"), self._intensidade),
             (_("Temperatura"), self._temperatura))
        ):
            nome = Gtk.Label(label=rotulo, xalign=0)
            controles.attach(nome, 0, linha, 1, 1)
            controles.attach(escala, 1, linha, 1, 1)
            self._linhas_de_cor.append((nome, escala))
        controles.attach(pontas, 1, 3, 1, 1)
        self._pontas_da_temperatura = pontas

        botoes = self._linha_de_botoes(
            self._botao(_("Restaurar"), self.restaurar),
            self._botao(_("Voltar"), self.anterior),
            self._botao(_("Próximo"), self.proxima, sugerido=True),
        )
        return self._pagina(self._titulo_da_etapa, self._amostra_da_etapa, controles, botoes)

    def _montar_fim(self) -> Gtk.Widget:
        self._grupo_do_fim = Adw.PreferencesGroup(title=_("Aplicar esta calibração também a"))
        self._marcadas: dict[str, Adw.SwitchRow] = {}
        botoes = self._linha_de_botoes(
            self._botao(_("Calibrar outro dispositivo"), self.calibrar_outro),
            self._botao(_("Testar calibração"), self.testar, sugerido=True),
        )
        return self._pagina(self._grupo_do_fim, botoes)

    def _montar_teste(self) -> Gtk.Widget:
        self._titulo_do_teste = Gtk.Label(css_classes=["title-2"], xalign=0)
        self._amostra_do_teste = self._amostra()
        self._pausar = self._botao(_("Pausar"), self.pausar)
        botoes = self._linha_de_botoes(
            self._pausar,
            self._botao(_("Avançar"), self.avancar_teste),
            self._botao(_("Concluir"), self.concluir, sugerido=True),
        )
        return self._pagina(self._titulo_do_teste, self._amostra_do_teste, botoes)

    # endregion
    # region Estado

    def pagina(self) -> str:
        return self._pilha.get_visible_child_name()

    def subtitulo_de(self, id_da_fita: str) -> str:
        return _("Calibrado") if self.calibracoes[id_da_fita] != NEUTRA else ""

    def _atualizar_inicio(self) -> None:
        for id_, linha in self._linhas_do_inicio.items():
            linha.set_subtitle(self.subtitulo_de(id_))

    def _calibracao_atual(self) -> Calibracao:
        assert self.id_atual is not None
        return self.calibracoes[self.id_atual]

    def _trocar_cor(self, tom: int, fator: float) -> None:
        cores = list(self._calibracao_atual().cores)
        cores[self.etapa] = (tom, fator)
        self.calibracoes[self.id_atual] = self._calibracao_atual()._replace(cores=tuple(cores))

    def _ao_ajustar(self, acao: Any) -> None:
        if not self._carregando:
            acao()

    # endregion
    # region Etapas

    def escolher(self, id_da_fita: str) -> None:
        self.id_atual = id_da_fita
        self.etapa = 0
        self._pilha.set_visible_child_name("etapa")
        self._mostrar_etapa()

    def _mostrar_etapa(self) -> None:
        branco = self.etapa == ETAPA_DO_BRANCO
        self._titulo_da_etapa.set_label(
            _("{} ({} de {})").format(NOMES_DAS_ETAPAS[self.etapa], self.etapa + 1, len(NOMES_DAS_ETAPAS))
        )
        for indice, (nome, escala) in enumerate(self._linhas_de_cor):
            visivel = branco if indice == 2 else not branco
            nome.set_visible(visivel)
            escala.set_visible(visivel)
        self._pontas_da_temperatura.set_visible(branco)
        atual = self._calibracao_atual()
        self._carregando = True
        try:
            if branco:
                self._temperatura.set_value(calibracao.temperatura_do_branco(atual.branco) * 100)
            else:
                tom, fator = atual.cores[self.etapa]
                self._tom.set_value(tom)
                self._intensidade.set_value(fator * 100)
        finally:
            self._carregando = False
        self._cor_na_tela = _cor_da_etapa(self.etapa)
        self._amostra_da_etapa.queue_draw()
        self._mostrar_previa()

    def _mostrar_previa(self) -> None:
        session_fita.previa_calibracao(self.id_atual, _cor_da_etapa(self.etapa), self.calibracoes)

    def mudar_tom(self, graus: int) -> None:
        self._trocar_cor(graus, self._calibracao_atual().cores[self.etapa][1])
        self._mostrar_previa()

    def mudar_intensidade(self, fator: float) -> None:
        self._trocar_cor(self._calibracao_atual().cores[self.etapa][0], round(fator, 2))
        self._mostrar_previa()

    def mudar_temperatura(self, temperatura: float) -> None:
        self.calibracoes[self.id_atual] = self._calibracao_atual()._replace(
            branco=calibracao.branco_da_temperatura(temperatura)
        )
        self._mostrar_previa()

    def restaurar(self) -> None:
        if self.etapa == ETAPA_DO_BRANCO:
            self.calibracoes[self.id_atual] = self._calibracao_atual()._replace(
                branco=NEUTRA.branco
            )
        else:
            self._trocar_cor(*NEUTRA.cores[self.etapa])
        self._mostrar_etapa()

    def proxima(self) -> None:
        if self.etapa < ETAPA_DO_BRANCO:
            self.etapa += 1
            self._mostrar_etapa()
        else:
            self._ir_para_o_fim()

    def anterior(self) -> None:
        if self.etapa > 0:
            self.etapa -= 1
            self._mostrar_etapa()
        else:
            self._atualizar_inicio()
            self._pilha.set_visible_child_name("inicio")

    # endregion
    # region Fim e teste

    def _ir_para_o_fim(self) -> None:
        for linha in self._marcadas.values():
            self._grupo_do_fim.remove(linha)
        self._marcadas = {}
        for fita in self.fitas:
            if fita.id == self.id_atual:
                continue
            linha = Adw.SwitchRow(title=fita.nome)
            self._grupo_do_fim.add(linha)
            self._marcadas[fita.id] = linha
        self._grupo_do_fim.set_visible(bool(self._marcadas))
        self._pilha.set_visible_child_name("fim")

    def aplicar_tambem(self, ids: set[str]) -> None:
        for id_ in ids:
            self.calibracoes[id_] = self._calibracao_atual()

    def _aplicar_marcadas(self) -> None:
        if self.id_atual is not None:
            self.aplicar_tambem({id_ for id_, linha in self._marcadas.items() if linha.get_active()})

    def calibrar_outro(self) -> None:
        self._aplicar_marcadas()
        self._atualizar_inicio()
        self._pilha.set_visible_child_name("inicio")

    def testar(self) -> None:
        self._aplicar_marcadas()
        self._pilha.set_visible_child_name("teste")
        self._indice_do_teste = 0
        self._passo_do_teste()
        self._ligar_temporizador()

    def _ligar_temporizador(self) -> None:
        self._parar_temporizador()
        self._temporizador = GLib.timeout_add_seconds(INTERVALO_DO_TESTE, self._ao_temporizador)
        self._pausar.set_label(_("Pausar"))

    def _parar_temporizador(self) -> None:
        if self._temporizador:
            GLib.source_remove(self._temporizador)
            self._temporizador = 0

    def _ao_temporizador(self) -> bool:
        self.avancar_teste()
        return GLib.SOURCE_CONTINUE

    def _passo_do_teste(self) -> None:
        cor = _cor_da_etapa(self._indice_do_teste)
        self._titulo_do_teste.set_label(NOMES_DAS_ETAPAS[self._indice_do_teste])
        self._cor_na_tela = cor
        self._amostra_do_teste.queue_draw()
        session_fita.previa(cor, None, self.calibracoes)

    def avancar_teste(self) -> None:
        self._indice_do_teste = (self._indice_do_teste + 1) % len(NOMES_DAS_ETAPAS)
        self._passo_do_teste()

    def pausar(self) -> None:
        if self._temporizador:
            self._parar_temporizador()
            self._pausar.set_label(_("Continuar"))
        else:
            self._ligar_temporizador()

    # endregion
    # region Concluir e cancelar

    def concluir(self) -> None:
        """Grava a calibração de cada dispositivo (a neutra não é gravada)."""
        session_fita.gravar_fitas(
            [
                fita._replace(
                    calibracao=calibracao.para_json(self.calibracoes[fita.id])
                    if self.calibracoes.get(fita.id, NEUTRA) != NEUTRA
                    else None
                )
                if fita.id in self.calibracoes
                else fita
                for fita in session_fita.fitas()
            ]
        )
        self._encerrar()
        self.close()

    def cancelar(self) -> None:
        self._encerrar()
        self.close()

    def _ao_fechar(self, *_args: Any) -> None:
        self._encerrar()

    def _encerrar(self) -> None:
        """Fechou de qualquer jeito: o teste para, e as fitas voltam à cor do
        app — com a calibração gravada, se houve Concluir. Uma vez só: o
        Cancelar e o Concluir chamam direto, e o ``closed`` chega depois (e
        não chega, se a janela nunca foi apresentada)."""
        if self._encerrado:
            return
        self._encerrado = True
        self._parar_temporizador()
        session_fita.previa(session_fita.cor_do_app())

    # endregion
