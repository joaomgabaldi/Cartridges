# test_acoes_dos_detalhes.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As ações da página de detalhes: jogar, remover, excluir, status, anotação, buscas e atualização."""

from urllib.parse import quote

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal

from kyron.jogo import Jogo
from kyron.modelos import detalhes as modulo
from kyron.modelos.avisos import FilaDeAvisos
from kyron.modelos.detalhes import DetalhesDoJogo
from kyron.utils import open_uri


class _Loja(QObject):
    jogo_excluido = Signal(str)

    def __init__(self, *jogos):
        super().__init__()
        self.jogos = {j.game_id: j for j in jogos}
        self.excluidos = []

    def get(self, game_id):
        return self.jogos.get(game_id)

    def excluir(self, jogo):
        self.excluidos.append(jogo)
        self.jogo_excluido.emit(jogo.game_id)


def _zerado(**extra):
    return _jogo(**{"removed": True, "status": "beaten", "executable": "", **extra})


def _jogo(**extra):
    return Jogo({"game_id": "a", "source": "imported", "name": "Alfa & Ômega", **extra})


def _mostrar(jogo, fila=None):
    loja = _Loja(jogo)
    modelo = DetalhesDoJogo(loja, avisos=fila)
    assert modelo.mostrar(jogo.game_id)
    modelo.sairam = []
    modelo.sair.connect(lambda: modelo.sairam.append(1))
    return modelo, loja


def test_jogar_chama_launch(app_qt, monkeypatch):
    jogo = _jogo()
    chamadas = []
    monkeypatch.setattr(jogo, "launch", lambda *a: chamadas.append(1))
    _mostrar(jogo)[0].jogar()
    assert chamadas == [1]


def test_jogar_zerado_nao_faz_nada(app_qt, monkeypatch):
    jogo = _zerado()
    chamadas = []
    monkeypatch.setattr(jogo, "launch", lambda *a: chamadas.append(1))
    _mostrar(jogo)[0].jogar()
    assert chamadas == []


def test_remover_sai_e_avisa_com_desfazer(app_qt):
    jogo = _jogo()
    modelo, _loja = _mostrar(jogo)
    avisos = []
    jogo.aviso.connect(lambda texto, acao: avisos.append((texto, acao)))
    modelo.remover()
    assert jogo.removed
    assert avisos == [("Alfa & Ômega removido", "remove")]
    assert modelo.sairam == [1]


def test_remover_zerado_nao_faz_nada(app_qt):
    jogo = _zerado()
    modelo, _loja = _mostrar(jogo)
    modelo.remover()
    assert modelo.sairam == [] and jogo.status == "beaten"


def test_excluir_so_zerado_e_reconfere(app_qt):
    fila = FilaDeAvisos()
    vivo = _jogo()
    modelo, loja = _mostrar(vivo, fila)
    modelo.excluir()
    assert loja.excluidos == []
    # Reconfere na hora: o jogo deixou de ser zerado enquanto a pergunta estava na tela.
    zerado = _zerado()
    modelo, loja = _mostrar(zerado, fila)
    zerado.status = "playing"
    modelo.excluir()
    assert loja.excluidos == []
    zerado.status = "beaten"
    modelo.excluir()
    assert loja.excluidos == [zerado]
    assert fila.texto == "Alfa & Ômega excluído"
    QCoreApplication.processEvents()  # o `jogo_excluido` chega enfileirado
    assert modelo.sairam == [1]


def test_status_de_zerado_para_desinstalado_sai(app_qt):
    jogo = _zerado()
    modelo, _loja = _mostrar(jogo)
    modelo.definirStatus("playing")
    assert jogo.status == "playing" and jogo.removed
    assert modelo.sairam == [1]


def test_status_de_zerado_para_instalado_troca_o_modo(app_qt, tmp_path):
    atalho = tmp_path / "a.lnk"
    atalho.write_text("x")
    jogo = _zerado(executable="a.exe", shortcut_path=str(atalho))
    modelo, _loja = _mostrar(jogo)
    assert modelo.zerado
    modelo.definirStatus("playing")
    assert not jogo.removed and not modelo.zerado
    assert modelo.sairam == []
    assert modelo.rotuloDoStatus == "Jogando"


def test_status_vazio_limpa(app_qt):
    jogo = _jogo(status="playing")
    modelo, _loja = _mostrar(jogo)
    modelo.definirStatus("")
    assert jogo.status == "" and modelo.rotuloDoStatus == "Definir status"


def test_anotacao_strip_e_nao_grava_igual(app_qt):
    jogo = _jogo(status="playing", notes="fase 2")
    modelo, _loja = _mostrar(jogo)
    salvos = []
    jogo.salvar.connect(lambda: salvos.append(1))
    modelo.gravarAnotacao("  fase 2\n")
    assert salvos == []
    modelo.gravarAnotacao("\n fase 3 \n")
    assert jogo.notes == "fase 3" and salvos == [1]
    assert modelo.anotacao == "fase 3"


def test_anotacao_de_zerado_nao_grava(app_qt):
    jogo = _zerado(notes="antes")
    modelo, _loja = _mostrar(jogo)
    modelo.gravarAnotacao("depois")
    assert jogo.notes == "antes"


def _abertos(monkeypatch):
    abertos = []
    monkeypatch.setattr(modulo, "abrir_url", lambda url: abertos.append(url) or True)
    return abertos


def test_buscar_hltb_com_id_abre_a_pagina(app_qt, monkeypatch):
    abertos = _abertos(monkeypatch)
    modelo, _loja = _mostrar(_jogo(hltb_id="123"))
    modelo.buscarEm("hltb")
    assert abertos == ["https://howlongtobeat.com/game/123"]


def test_buscar_codifica_o_nome(app_qt, monkeypatch):
    abertos = _abertos(monkeypatch)
    modelo, _loja = _mostrar(_jogo())
    nome = "Alfa%20%26%20%C3%94mega"
    assert quote("Alfa & Ômega") == nome
    for site in ("igdb", "sgdb", "pcgw", "hltb", "outro"):
        modelo.buscarEm(site)
    assert abertos == [
        f"https://www.igdb.com/search?type=1&q={nome}",
        f"https://www.steamgriddb.com/search/grids?term={nome}",
        f"https://www.pcgamingwiki.com/w/index.php?search={nome}",
        f"https://howlongtobeat.com/?q={nome}",
    ]


def test_abrir_url_recusa_esquemas(app_qt, monkeypatch):
    chamadas = []
    monkeypatch.setattr(open_uri.QDesktopServices, "openUrl", lambda url: chamadas.append(url) or True)
    for url in ("file:///c:/x", "javascript:alert(1)", "", "  ", "ftp://x"):
        assert open_uri.abrir_url(url) is False
    assert chamadas == []
    assert open_uri.abrir_url("https://exemplo.com/a") is True
    assert [u.toString() for u in chamadas] == ["https://exemplo.com/a"]


def test_confirmar_atualizacao_esconde_a_faixa(app_qt, monkeypatch):
    abertos = _abertos(monkeypatch)
    jogo = _jogo(track_updates=True, update_available_ts=10, update_url="https://r.example/x")
    monkeypatch.setattr(jogo, "save", lambda: None)
    modelo, _loja = _mostrar(jogo)
    assert modelo.temAtualizacao
    modelo.abrirAtualizacao()
    assert abertos == ["https://r.example/x"] and modelo.temAtualizacao
    modelo.confirmarAtualizacao()
    assert not modelo.temAtualizacao and jogo.update_available_ts == 0


def test_acoes_sem_jogo_nao_fazem_nada(app_qt, monkeypatch):
    abertos = _abertos(monkeypatch)
    loja = _Loja()
    modelo = DetalhesDoJogo(loja, avisos=FilaDeAvisos())
    saidas = []
    modelo.sair.connect(lambda: saidas.append(1))
    for acao in (modelo.jogar, modelo.remover, modelo.excluir, modelo.abrirAtualizacao, modelo.confirmarAtualizacao):
        acao()
    modelo.definirStatus("playing")
    modelo.buscarEm("igdb")
    modelo.gravarAnotacao("x")
    QCoreApplication.processEvents()
    assert abertos == [] and loja.excluidos == [] and saidas == []


def test_opcoes_de_status_vem_do_jogo(app_qt):
    assert DetalhesDoJogo(_Loja()).statusOpcoes == [
        ["backlog", "Quero jogar"], ["playing", "Jogando"], ["beaten", "Zerado"], ["dropped", "Abandonado"],
    ]


def test_status_fora_do_filtro_sai_da_pagina_e_excluir_solta_a_linha(app_qt):
    """A grade segue o jogo: o status que sai do filtro tira o cartão; o excluído sai do modelo."""
    from kyron.modelos.biblioteca import FiltroDaPagina, FiltrosDaBiblioteca, ModeloDaBiblioteca

    jogo = _jogo(status="playing")
    modelo_da_grade = ModeloDaBiblioteca()
    modelo_da_grade.atualizar(jogo)
    filtros = FiltrosDaBiblioteca(modelo_da_grade)
    pagina = FiltroDaPagina(modelo_da_grade, filtros, "biblioteca")
    filtros.status = "playing"
    assert pagina.rowCount() == 1
    detalhes, loja = _mostrar(jogo)
    # No app, o ExibicaoManager leva cada `atualizado` ao modelo; aqui, a mesma ligação.
    jogo.atualizado.connect(lambda: modelo_da_grade.atualizar(jogo))
    detalhes.definirStatus("backlog")
    assert pagina.rowCount() == 0
    filtros.status = ""
    assert pagina.rowCount() == 1
    loja.jogo_excluido.connect(modelo_da_grade.retirar, Qt.ConnectionType.QueuedConnection)
    jogo.status, jogo.removed = "beaten", True
    detalhes.excluir()
    QCoreApplication.processEvents()
    assert pagina.rowCount() == 0
