# test_cortina_da_abertura.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A janela principal só aparece desenhada: escondida (cloak do DWM) até as capas à vista carregarem, ou até o prazo."""

from PySide6.QtCore import QObject, Signal

from kyron.janela import cortina_da_abertura as modulo
from kyron.janela.cortina_da_abertura import CortinaDaAbertura


class _Item:
    def __init__(self, nome="", status=0, filhos=()):
        self._nome, self.status, self._filhos = nome, status, list(filhos)
        self.visitas = 0

    def objectName(self):  # noqa: N802
        return self._nome

    def property(self, nome):
        return self.status == 2 if nome == "carregandoArquivo" else None  # 2: Image.Loading

    def childItems(self):  # noqa: N802
        self.visitas += 1
        return self._filhos


class _Janela(QObject):
    frameSwapped = Signal()  # noqa: N815

    def __init__(self, capas):
        super().__init__()
        self.raiz = _Item(filhos=[_Item(filhos=capas)])
        self.atualizacoes = 0
        self.grades = []  # o que `findChildren(QQuickItem, "grade")` devolve

    def winId(self):  # noqa: N802
        return 42

    def contentItem(self):  # noqa: N802
        return self.raiz

    def findChildren(self, _tipo, nome):  # noqa: N802
        assert nome == "grade"
        return self.grades

    def update(self):
        self.atualizacoes += 1


def _cortina(monkeypatch):
    chamadas = []
    monkeypatch.setattr(modulo, "_cloak", lambda hwnd, ligado: chamadas.append((hwnd, ligado)) or True)
    return CortinaDaAbertura(), chamadas


def test_revela_no_quadro_seguinte_ao_das_capas_prontas(app_qt, monkeypatch):  # noqa: ARG001
    cortina, chamadas = _cortina(monkeypatch)
    capa = _Item("capaParada", status=2)  # Image.Loading
    janela = _Janela([capa, _Item("capaParada", status=1)])
    cortina.cobrir(janela)
    assert chamadas == [(42, True)]
    cortina._quadro()  # noqa: SLF001  uma capa ainda carregando
    assert chamadas == [(42, True)]
    capa.status = 1  # Image.Ready
    cortina._quadro()  # noqa: SLF001  o quadro que acabou pode ser de antes da capa: pede mais um
    assert chamadas == [(42, True)]
    assert janela.atualizacoes == 1
    cortina._quadro()  # noqa: SLF001
    assert chamadas == [(42, True), (42, False)]
    cortina._quadro()  # noqa: SLF001  revelada uma vez só
    cortina.revelar()
    assert chamadas == [(42, True), (42, False)]


def test_o_prazo_revela_mesmo_com_capa_carregando(app_qt, monkeypatch):  # noqa: ARG001
    cortina, chamadas = _cortina(monkeypatch)
    cortina.cobrir(_Janela([_Item("capaParada", status=2)]))
    cortina._quadro()  # noqa: SLF001
    cortina._quadro()  # noqa: SLF001
    assert chamadas == [(42, True)]
    cortina._prazo.timeout.emit()  # noqa: SLF001
    assert chamadas == [(42, True), (42, False)]


def test_sem_cloak_nao_espera_nada(app_qt, monkeypatch):  # noqa: ARG001
    """O DWM recusou (outra versão do Windows, a janela sem HWND): a janela segue o caminho de sempre."""
    monkeypatch.setattr(modulo, "_cloak", lambda _hwnd, _ligado: False)
    cortina = CortinaDaAbertura()
    janela = _Janela([])
    cortina.cobrir(janela)
    assert not cortina._prazo.isActive()  # noqa: SLF001
    cortina._quadro()  # noqa: SLF001
    assert janela.atualizacoes == 0


def test_depois_de_revelar_espera_a_janela_aparecer(app_qt, monkeypatch):  # noqa: ARG001
    """A janela da restauração ou do assistente só fecha quando a principal aparece: sem isso, até o prazo, o app
    ficaria sem nenhuma janela à vista e pareceria fechado."""
    cortina, _chamadas = _cortina(monkeypatch)
    feitos = []
    cortina.depois_de_revelar(lambda: feitos.append("antes de cobrir"))
    assert feitos == ["antes de cobrir"]
    cortina.cobrir(_Janela([]))
    cortina.depois_de_revelar(lambda: feitos.append("fechar a restauração"))
    assert feitos == ["antes de cobrir"]
    cortina.revelar()
    assert feitos == ["antes de cobrir", "fechar a restauração"]
    cortina.depois_de_revelar(lambda: feitos.append("já revelada"))
    assert feitos[-1] == "já revelada"


def test_so_olha_a_grade_e_nao_o_resto_da_arvore(app_qt, monkeypatch):  # noqa: ARG001
    cortina, chamadas = _cortina(monkeypatch)
    capa = _Item("capaParada", status=2)
    grade = _Item("grade", filhos=[_Item(filhos=[capa])])
    fora = [_Item() for _ in range(300)]
    janela = _Janela([])
    janela.raiz = _Item(filhos=[grade, *fora])
    janela.grades = [grade]
    cortina.cobrir(janela)
    cortina._quadro()  # noqa: SLF001  a capa da grade ainda carrega: não revela
    cortina._quadro()  # noqa: SLF001
    assert chamadas == [(42, True)]
    assert janela.raiz.visitas == 0
    assert all(item.visitas == 0 for item in fora)
    capa.status = 1
    cortina._quadro()  # noqa: SLF001
    cortina._quadro()  # noqa: SLF001
    assert chamadas == [(42, True), (42, False)]


def test_sem_grade_na_arvore_percorre_tudo_como_antes(app_qt, monkeypatch):  # noqa: ARG001
    cortina, chamadas = _cortina(monkeypatch)
    janela = _Janela([_Item("capaParada", status=2)])  # `grades` vazio
    cortina.cobrir(janela)
    cortina._quadro()  # noqa: SLF001
    assert janela.raiz.visitas == 1
    assert chamadas == [(42, True)]


def test_raiz_destruida_no_meio_revela(app_qt, monkeypatch):  # noqa: ARG001
    cortina, chamadas = _cortina(monkeypatch)
    janela = _Janela([])
    janela.grades = [_Item("grade")]

    def destruida():
        raise RuntimeError("Internal C++ object already deleted.")

    janela.grades[0].objectName = destruida
    cortina.cobrir(janela)
    cortina._quadro()  # noqa: SLF001
    assert chamadas == [(42, True), (42, False)]


def test_com_o_qml_de_verdade_acha_a_grade_da_biblioteca(app_qt):  # noqa: ARG001
    from PySide6.QtQuick import QQuickItem  # noqa: PLC0415

    from tests.apoio_qml_biblioteca import _App, _jogos  # noqa: PLC0415

    app = _App(_jogos((0, "Jogo 00", {})))
    nomes = [item.objectName() for item in app.janela.findChildren(QQuickItem, "grade")]
    assert nomes == ["grade"]
