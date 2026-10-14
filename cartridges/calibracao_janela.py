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

# A escolha "Todos os dispositivos" na lista do início: todos acesos ao mesmo
# tempo, cada um com os seus controles e a sua calibração, para comparar um com
# o outro e com a tela enquanto se ajusta.
TODOS = "__todos__"

# De quanto em quanto tempo o teste final troca de cor.
INTERVALO_DO_TESTE = 3

# A saturação das referências, na tela e na fita. No máximo (100%), aumentar a
# Intensidade não mudaria nada na parede — a saturação já não tem para onde
# subir —, e o valor seria gravado sem ser visto. A 70%, a faixa inteira do
# controle (50% a 150%) aparece.
SATURACAO_DA_REFERENCIA = 700


def _cor_da_etapa(etapa: int) -> Cor:
    """A cor de referência de uma etapa, no brilho padrão do app."""
    if etapa == ETAPA_DO_BRANCO:
        return Cor(0, 0, session_fita.brilho_padrao())
    return Cor(REFERENCIAS[etapa], SATURACAO_DA_REFERENCIA, session_fita.brilho_padrao())


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
        self._pilha.add_named(self._montar_etapa_de_todos(), "etapa_todos")
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

    def _amostra(self, altura: int = 240, expande: bool = True) -> Gtk.DrawingArea:
        """O quadro com a cor de referência."""
        area = Gtk.DrawingArea(vexpand=expande, hexpand=True, content_height=altura)
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
        if len(self.fitas) > 1:
            linha = Adw.ActionRow(
                title=_("Todos os dispositivos"),
                subtitle=_("Ajusta todos ao mesmo tempo, cada um com os seus controles"),
                activatable=True,
            )
            linha.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            linha.connect("activated", lambda *_: self.escolher(TODOS))
            self._lista.append(linha)
            self._linhas_do_inicio[TODOS] = linha
        for fita in self.fitas:
            linha = Adw.ActionRow(title=fita.nome, activatable=True)
            linha.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            linha.connect("activated", lambda _linha, id_=fita.id: self.escolher(id_))
            self._lista.append(linha)
            self._linhas_do_inicio[fita.id] = linha
        self._atualizar_inicio()
        # Da lista direto ao teste (e dele ao Concluir), sem passar pelas
        # etapas de um dispositivo: para quem voltou só para conferir.
        self._testar_da_lista = self._botao(_("Testar calibração"), self.testar)
        return self._pagina(texto, self._lista, self._linha_de_botoes(self._testar_da_lista))

    def _escala(self, minimo: float, maximo: float, passo: float, ao_mudar: Any) -> Gtk.Scale:
        escala = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, minimo, maximo, passo)
        escala.set_hexpand(True)
        escala.connect("value-changed", lambda escala: ao_mudar(escala.get_value()))
        return escala

    def _controles(self, id_da_fita: Optional[str]) -> tuple[Gtk.Grid, dict[str, Any]]:
        """Tom, Intensidade e Temperatura de um dispositivo (``None``: o que
        estiver em edição no modo de um dispositivo só)."""
        tom = self._escala(
            -calibracao.TOM_MAXIMO, calibracao.TOM_MAXIMO, 1,
            lambda valor: self._ao_ajustar(lambda: self.mudar_tom(round(valor), id_da_fita)),
        )
        intensidade = self._escala(
            calibracao.FATOR_MINIMO * 100, calibracao.FATOR_MAXIMO * 100, 1,
            lambda valor: self._ao_ajustar(
                lambda: self.mudar_intensidade(valor / 100, id_da_fita)
            ),
        )
        temperatura = self._escala(
            -100, 100, 1,
            lambda valor: self._ao_ajustar(
                lambda: self.mudar_temperatura(valor / 100, id_da_fita)
            ),
        )
        # O ponto sem ajuste de cada controle, marcado: é para onde o
        # Restaurar leva.
        tom.add_mark(0, Gtk.PositionType.BOTTOM, None)
        intensidade.add_mark(100, Gtk.PositionType.BOTTOM, None)
        temperatura.add_mark(0, Gtk.PositionType.BOTTOM, None)
        # As pontas da Temperatura em rótulos próprios, e não nas marcas: a
        # marca centraliza o texto na ponta, e "Mais frio" passava da margem.
        pontas = Gtk.Box()
        pontas.append(Gtk.Label(label=_("Mais quente"), hexpand=True, xalign=0, css_classes=["dim-label"]))
        pontas.append(Gtk.Label(label=_("Mais frio"), hexpand=True, xalign=1, css_classes=["dim-label"]))

        grade = Gtk.Grid(column_spacing=12, row_spacing=6)
        linhas = []
        for linha, (rotulo, escala) in enumerate(
            ((_("Tom"), tom), (_("Intensidade"), intensidade), (_("Temperatura"), temperatura))
        ):
            nome = Gtk.Label(label=rotulo, xalign=0)
            grade.attach(nome, 0, linha, 1, 1)
            grade.attach(escala, 1, linha, 1, 1)
            linhas.append((nome, escala))
        grade.attach(pontas, 1, 3, 1, 1)
        return grade, {
            "tom": tom,
            "intensidade": intensidade,
            "temperatura": temperatura,
            "pontas": pontas,
            "linhas": linhas,
        }

    def _montar_etapa(self) -> Gtk.Widget:
        self._titulo_da_etapa = Gtk.Label(css_classes=["title-2"], xalign=0)
        self._amostra_da_etapa = self._amostra()
        controles, self._controles_de_um = self._controles(None)
        botoes = self._linha_de_botoes(
            self._botao(_("Restaurar"), self.restaurar),
            self._botao(_("Voltar"), self.anterior),
            self._botao(_("Próximo"), self.proxima, sugerido=True),
        )
        return self._pagina(self._titulo_da_etapa, self._amostra_da_etapa, controles, botoes)

    def _montar_etapa_de_todos(self) -> Gtk.Widget:
        """A etapa com todos os dispositivos: a cor numa faixa menor e, embaixo,
        um grupo de controles por dispositivo, numa área que rola."""
        self._titulo_de_todos = Gtk.Label(css_classes=["title-2"], xalign=0)
        self._amostra_de_todos = self._amostra(altura=72, expande=False)
        grupos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self._controles_por_fita: dict[str, dict[str, Any]] = {}
        for fita in self.fitas:
            grade, controles = self._controles(fita.id)
            grupo = Adw.PreferencesGroup(title=fita.nome)
            grupo.add(grade)
            grupos.append(grupo)
            self._controles_por_fita[fita.id] = controles
        rolagem = Gtk.ScrolledWindow(
            child=grupos, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER
        )
        botoes = self._linha_de_botoes(
            self._botao(_("Restaurar"), self.restaurar),
            self._botao(_("Voltar"), self.anterior),
            self._botao(_("Próximo"), self.proxima, sugerido=True),
        )
        return self._pagina(self._titulo_de_todos, self._amostra_de_todos, rolagem, botoes)

    def _montar_teste(self) -> Gtk.Widget:
        self._titulo_do_teste = Gtk.Label(css_classes=["title-2"], xalign=0)
        self._amostra_do_teste = self._amostra()
        self._pausar = self._botao(_("Pausar"), self.pausar)
        botoes = self._linha_de_botoes(
            self._botao(_("Voltar aos ajustes"), self.voltar_aos_ajustes),
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
            if id_ != TODOS:
                linha.set_subtitle(self.subtitulo_de(id_))

    def _em_edicao(self) -> list[str]:
        """Os dispositivos que o ajuste de agora alcança."""
        assert self.id_atual is not None
        return [fita.id for fita in self.fitas] if self.id_atual == TODOS else [self.id_atual]

    def _alvo(self, id_da_fita: Optional[str]) -> str:
        """O dispositivo de um ajuste: o do controle, ou o que está em edição."""
        return id_da_fita if id_da_fita is not None else self._em_edicao()[0]

    def _trocar_cor(self, tom: int, fator: float, id_da_fita: str) -> None:
        atual = self.calibracoes[id_da_fita]
        cores = list(atual.cores)
        cores[self.etapa] = (tom, fator)
        self.calibracoes[id_da_fita] = atual._replace(cores=tuple(cores))

    def _ao_ajustar(self, acao: Any) -> None:
        if not self._carregando:
            acao()

    # endregion
    # region Etapas

    def escolher(self, id_da_fita: str) -> None:
        self.id_atual = id_da_fita
        self.etapa = 0
        self._pilha.set_visible_child_name("etapa_todos" if id_da_fita == TODOS else "etapa")
        self._mostrar_etapa()

    def _mostrar_etapa(self) -> None:
        todos = self.id_atual == TODOS
        titulo = self._titulo_de_todos if todos else self._titulo_da_etapa
        titulo.set_label(
            _("{} ({} de {})").format(NOMES_DAS_ETAPAS[self.etapa], self.etapa + 1, len(NOMES_DAS_ETAPAS))
        )
        if todos:
            pares = [(self._controles_por_fita[id_], id_) for id_ in self._em_edicao()]
        else:
            pares = [(self._controles_de_um, self.id_atual)]
        self._carregando = True
        try:
            for controles, id_ in pares:
                self._carregar(controles, self.calibracoes[id_])
        finally:
            self._carregando = False
        self._cor_na_tela = _cor_da_etapa(self.etapa)
        (self._amostra_de_todos if todos else self._amostra_da_etapa).queue_draw()
        self._mostrar_previa()

    def _carregar(self, controles: dict[str, Any], atual: Calibracao) -> None:
        """Põe nos controles de um dispositivo os valores desta etapa."""
        branco = self.etapa == ETAPA_DO_BRANCO
        for indice, (nome, escala) in enumerate(controles["linhas"]):
            visivel = branco if indice == 2 else not branco
            nome.set_visible(visivel)
            escala.set_visible(visivel)
        controles["pontas"].set_visible(branco)
        if branco:
            controles["temperatura"].set_value(
                calibracao.temperatura_do_branco(atual.branco) * 100
            )
        else:
            tom, fator = atual.cores[self.etapa]
            controles["tom"].set_value(tom)
            controles["intensidade"].set_value(fator * 100)

    def _mostrar_previa(self) -> None:
        if self.id_atual == TODOS:
            session_fita.previa(_cor_da_etapa(self.etapa), None, self.calibracoes)
        else:
            session_fita.previa_calibracao(
                self.id_atual, _cor_da_etapa(self.etapa), self.calibracoes
            )

    def mudar_tom(self, graus: int, id_da_fita: Optional[str] = None) -> None:
        alvo = self._alvo(id_da_fita)
        self._trocar_cor(graus, self.calibracoes[alvo].cores[self.etapa][1], alvo)
        self._mostrar_previa()

    def mudar_intensidade(self, fator: float, id_da_fita: Optional[str] = None) -> None:
        alvo = self._alvo(id_da_fita)
        self._trocar_cor(self.calibracoes[alvo].cores[self.etapa][0], round(fator, 2), alvo)
        self._mostrar_previa()

    def mudar_temperatura(self, temperatura: float, id_da_fita: Optional[str] = None) -> None:
        alvo = self._alvo(id_da_fita)
        self.calibracoes[alvo] = self.calibracoes[alvo]._replace(
            branco=calibracao.branco_da_temperatura(temperatura)
        )
        self._mostrar_previa()

    def restaurar(self) -> None:
        """Devolve esta etapa ao neutro — de todos, no modo de todos."""
        for id_ in self._em_edicao():
            if self.etapa == ETAPA_DO_BRANCO:
                self.calibracoes[id_] = self.calibracoes[id_]._replace(branco=NEUTRA.branco)
            else:
                self._trocar_cor(*NEUTRA.cores[self.etapa], id_)
        self._mostrar_etapa()

    def proxima(self) -> None:
        if self.etapa < ETAPA_DO_BRANCO:
            self.etapa += 1
            self._mostrar_etapa()
        else:
            # Depois do Branco, o teste, direto. Não há "aplicar também a
            # outros": para fitas iguais há "Todos os dispositivos", e outro
            # dispositivo se calibra pelo "Voltar aos ajustes" do teste.
            self.testar()

    def anterior(self) -> None:
        if self.etapa > 0:
            self.etapa -= 1
            self._mostrar_etapa()
        else:
            self._ir_para_a_lista()

    def _ir_para_a_lista(self) -> None:
        """De volta à lista: as fitas voltam à cor do app (com as calibrações
        em edição), e não ficam na última cor de referência ou do teste."""
        self._parar_temporizador()
        self._atualizar_inicio()
        self._pilha.set_visible_child_name("inicio")
        session_fita.previa(session_fita.cor_do_app(), None, self.calibracoes)

    # endregion
    # region Teste

    def testar(self) -> None:
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
        self._proxima_do_teste()
        return GLib.SOURCE_CONTINUE

    def _passo_do_teste(self) -> None:
        cor = _cor_da_etapa(self._indice_do_teste)
        self._titulo_do_teste.set_label(NOMES_DAS_ETAPAS[self._indice_do_teste])
        self._cor_na_tela = cor
        self._amostra_do_teste.queue_draw()
        session_fita.previa(cor, None, self.calibracoes)

    def voltar_aos_ajustes(self) -> None:
        """Sai do teste sem perder nada: os ajustes seguem em memória até o
        Concluir."""
        self._ir_para_a_lista()

    def avancar_teste(self) -> None:
        """O botão Avançar: a próxima cor, com os 3 s contados de novo — sem
        isso, a cor pedida podia sumir logo em seguida."""
        self._proxima_do_teste()
        if self._temporizador:
            self._ligar_temporizador()

    def _proxima_do_teste(self) -> None:
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
                    if self.calibracoes[fita.id] != NEUTRA
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
