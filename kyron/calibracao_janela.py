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

"""A calibração da iluminação, no estilo da calibração HDR do Windows; tudo fica em memória até o Concluir."""

from typing import Any, Optional

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QColor

from kyron.utils import calibracao, session_fita
from kyron.utils.calibracao import NEUTRA, REFERENCIAS, Calibracao
from kyron.utils.session_fita import Cor, Fita

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

PAGINAS_DA_CALIBRACAO = ("inicio", "etapa", "etapa_todos", "teste")

# A escolha "Todos os dispositivos" na lista do início: todos acesos ao mesmo tempo, para comparar entre si e com a tela.
TODOS = "__todos__"

INTERVALO_DO_TESTE = 3

# A saturação das referências: a 100% a Intensidade não mudaria nada na parede; a 70% a faixa inteira (50% a 150%) aparece.
SATURACAO_DA_REFERENCIA = 700


def _cor_da_etapa(etapa: int) -> Cor:
    """A cor de referência de uma etapa, no brilho padrão do app."""
    if etapa == ETAPA_DO_BRANCO:
        return Cor(0, 0, session_fita.brilho_padrao())
    return Cor(REFERENCIAS[etapa], SATURACAO_DA_REFERENCIA, session_fita.brilho_padrao())


class AssistenteDeCalibracao(QObject):
    """O assistente. ``calibracoes`` é o estado em edição, por id da fita."""

    alterado = Signal()
    fechado = Signal()

    def __init__(self, configuradas: list[Fita], parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.fitas = configuradas
        self.calibracoes: dict[str, Calibracao] = {
            fita.id: calibracao.de_json(fita.calibracao) if fita.calibracao else NEUTRA
            for fita in configuradas
        }
        self.id_atual: Optional[str] = None
        self.etapa = 0
        self._pagina = "inicio"
        self._titulo = ""
        self._indice_do_teste = 0
        # O teste correndo; ``None`` é parado ou pausado.
        self._temporizador: Optional[QTimer] = None
        self._pausado = False
        self._encerrado = False
        # Enquanto a etapa carrega os controles, mexer neles não é ajuste.
        self._carregando = False
        self._cor_na_tela = _cor_da_etapa(0)
        self._controles: list[dict[str, Any]] = []

    def pagina(self) -> str:
        return self._pagina

    @Property(str, notify=alterado)
    def paginaAtual(self) -> str:  # noqa: N802
        return self._pagina

    @Property(str, notify=alterado)
    def titulo(self) -> str:
        return self._titulo

    @Property(QColor, notify=alterado)
    def corNaTela(self) -> QColor:  # noqa: N802
        cor = self._cor_na_tela
        # Valor 1: o brilho é da fita, a tela mostra a cor cheia.
        return QColor.fromHsvF(min(cor.matiz, 359) / 360, cor.saturacao / 1000, 1.0)

    # As faixas dos controles, das constantes da calibração (a tela não repete os números).
    @Property(int, constant=True)
    def tomMaximo(self) -> int:  # noqa: N802
        return calibracao.TOM_MAXIMO

    @Property(int, constant=True)
    def intensidadeMinima(self) -> int:  # noqa: N802
        return round(calibracao.FATOR_MINIMO * 100)

    @Property(int, constant=True)
    def intensidadeMaxima(self) -> int:  # noqa: N802
        return round(calibracao.FATOR_MAXIMO * 100)

    @Property(bool, notify=alterado)
    def pausado(self) -> bool:
        return self._pausado

    @Property("QVariantList", notify=alterado)
    def linhas(self) -> list[dict[str, str]]:
        todas = []
        if len(self.fitas) > 1:
            todas.append(
                {
                    "id": TODOS,
                    "nome": _("Todos os dispositivos"),
                    "subtitulo": _("Ajusta todos ao mesmo tempo, cada um com os seus controles"),
                }
            )
        todas.extend({"id": fita.id, "nome": fita.nome, "subtitulo": self.subtitulo_de(fita.id)} for fita in self.fitas)
        return todas

    @Property("QVariantList", notify=alterado)
    def controles(self) -> list[dict[str, Any]]:
        return self._controles

    def subtitulo_de(self, id_da_fita: str) -> str:
        return _("Calibrado") if self.calibracoes[id_da_fita] != NEUTRA else ""

    def _em_edicao(self) -> list[str]:
        """Os dispositivos que o ajuste de agora alcança."""
        assert self.id_atual is not None
        return [fita.id for fita in self.fitas] if self.id_atual == TODOS else [self.id_atual]

    def _alvo(self, id_da_fita: Optional[str]) -> str:
        """O dispositivo de um ajuste: o do controle, ou o que está em edição."""
        return id_da_fita if id_da_fita is not None else self._em_edicao()[0]

    def _atualizar_controles(self) -> None:
        """Os valores desta etapa, por dispositivo em edição (sem emitir)."""
        if self.id_atual is None:
            self._controles = []
            return
        nomes = {fita.id: fita.nome for fita in self.fitas}
        branco = self.etapa == ETAPA_DO_BRANCO
        self._controles = []
        for id_ in self._em_edicao():
            atual = self.calibracoes[id_]
            tom, fator = (0, 1.0) if branco else atual.cores[self.etapa]
            self._controles.append(
                {
                    "id": id_,
                    "nome": nomes[id_],
                    "tom": tom,
                    "intensidade": round(fator * 100),
                    "temperatura": round(calibracao.temperatura_do_branco(atual.branco) * 100),
                    "branco": branco,
                }
            )

    def _trocar_cor(self, tom: int, fator: float, id_da_fita: str) -> None:
        atual = self.calibracoes[id_da_fita]
        cores = list(atual.cores)
        cores[self.etapa] = (tom, fator)
        self.calibracoes[id_da_fita] = atual._replace(cores=tuple(cores))

    def _ao_ajustar(self, acao: Any) -> None:
        if not self._carregando and not self._encerrado:
            acao()

    @Slot(str)
    def escolherDispositivo(self, id_da_fita: str) -> None:  # noqa: N802
        self.escolher(id_da_fita)

    def escolher(self, id_da_fita: str) -> None:
        if self._encerrado:
            return
        self.id_atual = id_da_fita
        self.etapa = 0
        self._pagina = "etapa_todos" if id_da_fita == TODOS else "etapa"
        self._mostrar_etapa()

    def _mostrar_etapa(self) -> None:
        self._titulo = _("{} ({} de {})").format(
            NOMES_DAS_ETAPAS[self.etapa], self.etapa + 1, len(NOMES_DAS_ETAPAS)
        )
        self._cor_na_tela = _cor_da_etapa(self.etapa)
        self._carregando = True
        try:
            self._atualizar_controles()
            self.alterado.emit()
        finally:
            self._carregando = False
        self._mostrar_previa()

    def _mostrar_previa(self) -> None:
        if self.id_atual == TODOS:
            session_fita.previa(_cor_da_etapa(self.etapa), None, self.calibracoes)
        else:
            session_fita.previa_calibracao(
                self.id_atual, _cor_da_etapa(self.etapa), self.calibracoes
            )

    def _depois_de_ajustar(self) -> None:
        self._atualizar_controles()
        self.alterado.emit()
        self._mostrar_previa()

    @Slot(int, str)
    def mudarTom(self, graus: int, id_da_fita: str = "") -> None:  # noqa: N802
        self._ao_ajustar(lambda: self.mudar_tom(int(graus), id_da_fita or None))

    @Slot(int, str)
    def mudarIntensidade(self, porcento: int, id_da_fita: str = "") -> None:  # noqa: N802
        self._ao_ajustar(lambda: self.mudar_intensidade(porcento / 100, id_da_fita or None))

    @Slot(int, str)
    def mudarTemperatura(self, porcento: int, id_da_fita: str = "") -> None:  # noqa: N802
        self._ao_ajustar(lambda: self.mudar_temperatura(porcento / 100, id_da_fita or None))

    def mudar_tom(self, graus: int, id_da_fita: Optional[str] = None) -> None:
        alvo = self._alvo(id_da_fita)
        self._trocar_cor(graus, self.calibracoes[alvo].cores[self.etapa][1], alvo)
        self._depois_de_ajustar()

    def mudar_intensidade(self, fator: float, id_da_fita: Optional[str] = None) -> None:
        alvo = self._alvo(id_da_fita)
        self._trocar_cor(self.calibracoes[alvo].cores[self.etapa][0], round(fator, 2), alvo)
        self._depois_de_ajustar()

    def mudar_temperatura(self, temperatura: float, id_da_fita: Optional[str] = None) -> None:
        alvo = self._alvo(id_da_fita)
        self.calibracoes[alvo] = self.calibracoes[alvo]._replace(
            branco=calibracao.branco_da_temperatura(temperatura)
        )
        self._depois_de_ajustar()

    @Slot()
    def restaurar(self) -> None:
        """Devolve esta etapa ao neutro — de todos, no modo de todos."""
        if self._encerrado:
            return
        for id_ in self._em_edicao():
            if self.etapa == ETAPA_DO_BRANCO:
                self.calibracoes[id_] = self.calibracoes[id_]._replace(branco=NEUTRA.branco)
            else:
                self._trocar_cor(*NEUTRA.cores[self.etapa], id_)
        self._mostrar_etapa()

    @Slot()
    def proxima(self) -> None:
        if self._encerrado:
            return
        if self.etapa < ETAPA_DO_BRANCO:
            self.etapa += 1
            self._mostrar_etapa()
        else:
            # Depois do Branco, o teste, direto: para fitas iguais há "Todos os dispositivos".
            self.testar()

    @Slot()
    def anterior(self) -> None:
        if self._encerrado:
            return
        if self.etapa > 0:
            self.etapa -= 1
            self._mostrar_etapa()
        else:
            self._ir_para_a_lista()

    def _ir_para_a_lista(self) -> None:
        """De volta à lista: as fitas voltam à cor do app (com as calibrações em edição), não ficam na última cor."""
        if self._encerrado:
            return
        self._parar_temporizador()
        self._pagina = "inicio"
        self.alterado.emit()
        session_fita.previa(session_fita.cor_do_app(), None, self.calibracoes)

    @Slot()
    def testar(self) -> None:
        if self._encerrado:
            return
        self._pagina = "teste"
        self._indice_do_teste = 0
        self._passo_do_teste()
        self._ligar_temporizador()

    def _ligar_temporizador(self) -> None:
        self._parar_temporizador()
        temporizador = QTimer(self)
        temporizador.setInterval(INTERVALO_DO_TESTE * 1000)
        temporizador.timeout.connect(self._proxima_do_teste)
        temporizador.start()
        self._temporizador = temporizador
        self.alterado.emit()

    def _parar_temporizador(self) -> None:
        self._pausado = False
        if self._temporizador is not None:
            self._temporizador.stop()
            self._temporizador.deleteLater()
            self._temporizador = None

    def _passo_do_teste(self) -> None:
        cor = _cor_da_etapa(self._indice_do_teste)
        self._titulo = NOMES_DAS_ETAPAS[self._indice_do_teste]
        self._cor_na_tela = cor
        self.alterado.emit()
        session_fita.previa(cor, None, self.calibracoes)

    @Slot()
    def voltarAosAjustes(self) -> None:  # noqa: N802
        self.voltar_aos_ajustes()

    def voltar_aos_ajustes(self) -> None:
        """Sai do teste sem perder nada: os ajustes seguem em memória até o Concluir."""
        self._ir_para_a_lista()

    @Slot()
    def avancarTeste(self) -> None:  # noqa: N802
        self.avancar_teste()

    def avancar_teste(self) -> None:
        """O botão Avançar: a próxima cor, com os 3 s contados de novo (senão a cor pedida sumiria logo)."""
        if self._encerrado:
            return
        self._proxima_do_teste()
        if self._temporizador is not None:
            self._ligar_temporizador()

    def _proxima_do_teste(self) -> None:
        if self._encerrado:
            return
        self._indice_do_teste = (self._indice_do_teste + 1) % len(NOMES_DAS_ETAPAS)
        self._passo_do_teste()

    @Slot()
    def pausar(self) -> None:
        if self._encerrado:
            return
        if self._temporizador is not None:
            self._parar_temporizador()
            self._pausado = True
            self.alterado.emit()
        else:
            self._ligar_temporizador()

    @Slot()
    def concluir(self) -> None:
        """Grava a calibração de cada dispositivo (a neutra não é gravada)."""
        if self._encerrado:
            return
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

    @Slot()
    def cancelar(self) -> None:
        self._encerrar()

    def _encerrar(self) -> None:
        """Fechou de qualquer jeito: o teste para e as fitas voltam à cor do app. Cancelar, Concluir, Esc e o fechamento das Preferências chegam aqui."""
        if self._encerrado:
            return
        self._encerrado = True
        self._parar_temporizador()
        session_fita.previa(session_fita.cor_do_app())
        self.fechado.emit()

