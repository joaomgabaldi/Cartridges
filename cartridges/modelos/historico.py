# historico.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O que a tela do histórico de sessões mostra (`historico`): as linhas, o resumo e o gráfico, já calculados.

As regras são as de `session_history.py` (puras); aqui só se junta o que o QML lê e se faz a exclusão de uma sessão,
que desconta o tempo do total do jogo. Segue um jogo por vez e relê o arquivo de sessões a cada mudança: a tela mostra o
que está gravado, e não o que ela acha que gravou. Só na thread principal.
"""

import weakref
from datetime import date, datetime
from functools import partial
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from cartridges.modelos.ordem import _url_da_capa  # noqa: PLC2701
from cartridges.session_history import (
    PAGINA,
    PERIODS,
    dia_mais_perto,
    format_session_date,
    geometria_do_grafico,
    period_range,
    resumo_dos_ultimos_dias,
    sem_lacunas_longas,
    tempo_ou_nenhuma,
)
from cartridges.utils import game_logo, session_log
from cartridges.utils.format_playtime import format_playtime

# O logo é a manchete da caixa inteira, não o título de uma coluna: bem maior que o da página de detalhes (72 de altura),
# e a largura útil é a da caixa (1040) menos as margens de 24.
ALTURA_DO_LOGO = 120
LARGURA_DO_LOGO = 1040 - 2 * 24

_PADRAO: dict[str, Any] = {
    "aberto": False, "nome": "", "logo": "", "larguraDoLogo": 0, "resumo": "", "vazio": True, "sessoes": [],
    "haMais": False, "periodo": "month", "totalDoPeriodo": "", "grafico": {},
}  # fmt: skip


def _prop(tipo: Any, nome: str, notify: Any) -> Property:
    return Property(tipo, lambda self: self._v[nome], notify=notify)


class HistoricoDeSessoes(QObject):
    alterado = Signal()
    # Sinais próprios: trocar o período não refaz as linhas da tabela, e "Mostrar mais" não redesenha o gráfico.
    tabelaMudou = Signal()  # noqa: N815
    graficoMudou = Signal()  # noqa: N815

    _p = partial(_prop, notify=alterado)
    _t = partial(_prop, notify=tabelaMudou)
    _g = partial(_prop, notify=graficoMudou)
    aberto = _p(bool, "aberto")
    nome = _p(str, "nome")
    logo = _p(str, "logo")
    larguraDoLogo = _p(int, "larguraDoLogo")  # noqa: N815
    resumo = _p(str, "resumo")
    vazio = _p(bool, "vazio")
    sessoes = _t("QVariantList", "sessoes")
    haMais = _t(bool, "haMais")  # noqa: N815
    periodo = _g(str, "periodo")
    totalDoPeriodo = _g(str, "totalDoPeriodo")  # noqa: N815
    grafico = _g("QVariantMap", "grafico")
    del _p, _t, _g

    def __init__(self, store: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._v: dict[str, Any] = dict(_PADRAO)
        # Só referência fraca: a tela não prende um jogo que a loja já soltou.
        self._jogo: weakref.ref | None = None
        self._mostradas = PAGINA
        self._sessoes: list[dict[str, Any]] = []
        self._posicoes: list[int] = []
        self._dias: list[tuple[date, int]] = []

    # -- abrir e fechar --------------------------------------------------------------------------

    @Slot(str)
    def abrir(self, game_id: str) -> None:
        """Mostra o histórico do jogo, no mês; ignora (sem mudar nada) um jogo que a loja não tem."""
        jogo = self._store.get(game_id)
        if jogo is None:
            return
        self._jogo = weakref.ref(jogo)
        self._mostradas = PAGINA
        logo, largura = "", 0
        # Só o que já está em disco: a busca no SteamGridDB é da página de detalhes, de onde isto é aberto.
        if (caminho := game_logo.cached_logo_path(jogo)) and (carregado := game_logo.load_logo(caminho, LARGURA_DO_LOGO, ALTURA_DO_LOGO)):
            logo, largura = _url_da_capa(carregado[0]), carregado[1]
        self._v.update(aberto=True, nome=jogo.name, logo=logo, larguraDoLogo=largura, periodo="month")
        self._reler()

    @Slot()
    def fechar(self) -> None:
        self._jogo = None
        self._sessoes, self._dias, self._posicoes = [], [], []
        self._v = {**_PADRAO, "aberto": False}
        self._avisar_tudo()

    def _avisar_tudo(self) -> None:
        self.alterado.emit()
        self.tabelaMudou.emit()
        self.graficoMudou.emit()

    def _mostrado(self) -> Any:
        return self._jogo() if self._jogo else None

    # -- o que a tela mostra ----------------------------------------------------------------------

    def _reler(self) -> None:
        """Relê o arquivo e refaz tudo o que a tela mostra, em vez de tirar uma linha: a exclusão mexe no resumo e no
        gráfico também."""
        jogo = self._mostrado()
        self._sessoes = session_log.load(jogo.game_id) if jogo is not None else []
        if not self._sessoes:
            # Sem sessão não há o que listar nem desenhar: a frase do resumo explica o vazio.
            self._posicoes, self._dias = [], []
            self._v.update(
                resumo=_("Nenhuma sessão registrada."), vazio=True, sessoes=[], haMais=False, totalDoPeriodo="", grafico={}
            )
            self._avisar_tudo()
            return
        sete, trinta = resumo_dos_ultimos_dias(self._sessoes, date.today())
        # As variáveis são os tempos jogados nos últimos 7 e 30 dias
        resumo = _("Últimos 7 dias: {} · últimos 30 dias: {}").format(tempo_ou_nenhuma(sete), tempo_ou_nenhuma(trinta))
        self._v.update(resumo=resumo, vazio=False, **self._tabela(), **self._grafico())
        self._avisar_tudo()

    def _tabela(self) -> dict[str, Any]:
        return {
            "sessoes": [self._linha(s) for s in self._sessoes[: self._mostradas]],
            "haMais": len(self._sessoes) > self._mostradas,
        }

    @staticmethod
    def _linha(sessao: dict[str, Any]) -> dict[str, Any]:
        duracao = format_playtime(sessao["seconds"])
        return {
            "titulo": format_session_date(sessao["end"]),
            # As variáveis são a hora em que a sessão terminou e sua duração
            "subtitulo": _("Terminou às {} · {}").format(datetime.fromtimestamp(sessao["end"]).strftime("%H:%M"), duracao),
            "fim": sessao["end"],
            "segundos": sessao["seconds"],
            "duracao": duracao,
        }

    def _grafico(self) -> dict[str, Any]:
        """Os dias do período escolhido; as pausas longas só se cortam em "Todo o período"."""
        periodo = self._v["periodo"]
        primeiro, ultimo = period_range(self._sessoes, periodo, date.today())
        dias = session_log.daily_seconds(self._sessoes, primeiro, ultimo)
        quebras: frozenset[int] = frozenset()
        if periodo == "all":
            dias, quebras = sem_lacunas_longas(dias)
        geometria = geometria_do_grafico(dias, quebras)
        self._dias, self._posicoes = dias, geometria.get("posicoes", [])
        # A variável é o tempo jogado no período escolhido
        total = _("{} no período").format(tempo_ou_nenhuma(sum(segundos for _dia, segundos in dias)))
        return {"grafico": geometria, "totalDoPeriodo": total}

    # -- ações ------------------------------------------------------------------------------------

    @Slot()
    def mostrarMais(self) -> None:  # noqa: N802
        """Acrescenta a próxima página de sessões ao fim da tabela."""
        self._mostradas += PAGINA
        self._v.update(self._tabela())
        self.tabelaMudou.emit()

    @Slot(str)
    def definirPeriodo(self, periodo: str) -> None:  # noqa: N802
        if periodo not in PERIODS or periodo == self._v["periodo"] or self._mostrado() is None:
            return
        self._v["periodo"] = periodo
        if self._sessoes:
            self._v.update(self._grafico())
        self.graficoMudou.emit()

    @Slot("qint64", "qint64")
    def excluir(self, fim: int, segundos: int) -> None:
        """Apaga a sessão e desconta o tempo do total do jogo (a confirmação é da tela)."""
        jogo = self._mostrado()
        if jogo is None:
            return
        if not session_log.delete(jogo.game_id, fim, segundos):
            # A linha sumiu entre abrir a tela e confirmar (outra janela, o arquivo editado à mão). Nada a descontar:
            # o total continua correspondendo ao que sobrou no histórico.
            self._reler()
            return
        # Nunca abaixo de zero: um total menor que a sessão só acontece com um registro editado à mão, e o certo aí é
        # zerar, não guardar um tempo de jogo negativo que a ordenação levaria a sério.
        jogo.playtime = max(0, jogo.playtime - segundos)
        jogo.save()
        jogo.update()
        self._reler()

    @Slot(float, result=str)
    def dica(self, fracao: float) -> str:
        """"{data}: {tempo}" do dia mais perto de ``fracao`` (0 a 1 da largura do gráfico); "" sem gráfico."""
        if not self._dias:
            return ""
        dia, segundos = self._dias[dia_mais_perto(self._posicoes, fracao)]
        carimbo = int(datetime.combine(dia, datetime.min.time()).timestamp())
        return f"{format_session_date(carimbo)}: {tempo_ou_nenhuma(segundos)}"
