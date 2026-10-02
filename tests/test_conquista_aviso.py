"""O cartão do aviso de conquista."""

import time

import pytest
from gi.repository import GLib

from cartridges import conquista_aviso
from cartridges.conquistas import icones, progresso
from cartridges.conquistas.catalogo import ConquistaInfo
from cartridges.conquistas.vigia import Desbloqueada
from cartridges.utils import janela_por_cima

_PREPARAR_REAL = janela_por_cima.preparar
_POR_NO_CANTO_REAL = janela_por_cima.por_no_canto
_SAIR_REAL = conquista_aviso._JanelaDoAviso.sair


@pytest.fixture(autouse=True)
def sem_efeitos(monkeypatch):
    """Sem ícone de rede, sem Win32, saída sem animação e com o relógio na mão do teste."""
    monkeypatch.setattr(icones, "carregar", lambda _o, _e: None)
    monkeypatch.setattr(janela_por_cima, "preparar", lambda _j: True)
    monkeypatch.setattr(janela_por_cima, "por_no_canto", lambda _j, _c, margem=24: True)
    monkeypatch.setattr(
        conquista_aviso._JanelaDoAviso, "sair", lambda _self, ao_terminar: ao_terminar()
    )
    agendados = []
    monkeypatch.setattr(
        conquista_aviso, "_agendar", lambda segundos, funcao: agendados.append((segundos, funcao)) or 1
    )
    yield agendados
    conquista_aviso.fechar()


def _info(rara=False, porcentagem=50.0):
    return ConquistaInfo("A", "Mestre da Grama", "Corte toda a grama.", "", "", False, 4.1 if rara else porcentagem)


def test_porcentagem_em_texto():
    assert progresso.porcentagem_em_texto(4.1) == "4,1%"
    assert progresso.porcentagem_em_texto(55.0) == "55,0%"


def test_aviso_comum():
    aviso = conquista_aviso.Aviso.de(Desbloqueada("A", _info(), False))
    assert aviso.rotulo == "Conquista desbloqueada"
    assert (aviso.titulo, aviso.descricao) == ("Mestre da Grama", "Corte toda a grama.")


def test_aviso_raro():
    aviso = conquista_aviso.Aviso.de(Desbloqueada("A", _info(rara=True), False))
    assert aviso.rotulo == "Conquista desbloqueada · ★ Rara, 4,1%"


def test_aviso_que_completa_o_jogo():
    aviso = conquista_aviso.Aviso.de(Desbloqueada("A", _info(rara=True), True))
    assert aviso.rotulo == "Todas as conquistas desbloqueadas · ★ Rara, 4,1%"


def test_sem_catalogo_nao_ha_aviso():
    assert conquista_aviso.Aviso.de(Desbloqueada("A", None, False)) is None


def test_avisos_entram_em_fila(sem_efeitos):
    um = conquista_aviso.Aviso("Conquista desbloqueada", "Um", "", "")
    dois = conquista_aviso.Aviso("Conquista desbloqueada", "Dois", "", "")
    conquista_aviso.mostrar(um)
    conquista_aviso.mostrar(dois)
    assert conquista_aviso.na_tela() == "Um"
    segundos, esconder = sem_efeitos[-1]
    assert segundos == conquista_aviso.DURACAO
    esconder()
    assert conquista_aviso.na_tela() == "Dois"
    sem_efeitos[-1][1]()
    assert conquista_aviso.na_tela() is None


def test_texto_nao_vira_markup(sem_efeitos):
    conquista_aviso.mostrar(conquista_aviso.Aviso("Conquista desbloqueada", "A & <b>B</b>", "x < y", ""))
    assert conquista_aviso.na_tela() == "A & <b>B</b>"


def test_fechar_esvazia_a_fila(sem_efeitos):
    conquista_aviso.mostrar(conquista_aviso.Aviso("r", "Um", "", ""))
    conquista_aviso.mostrar(conquista_aviso.Aviso("r", "Dois", "", ""))
    conquista_aviso.fechar()
    assert conquista_aviso.na_tela() is None
    sem_efeitos[-1][1]()  # o temporizador antigo dispara depois: não levanta nem mostra nada
    assert conquista_aviso.na_tela() is None


def test_exemplo():
    exemplo = conquista_aviso.Aviso.exemplo()
    assert exemplo.titulo and "★ Rara" in exemplo.rotulo


def test_icone_que_chega_depois_do_fechamento_nao_levanta(monkeypatch, sem_efeitos):
    entregas = []
    monkeypatch.setattr(icones, "carregar", lambda _o, entregar: entregas.append(entregar))
    conquista_aviso.mostrar(conquista_aviso.Aviso("r", "Um", "", "https://exemplo.test/i.jpg"))
    assert len(entregas) == 1
    conquista_aviso.fechar()
    entregas[0](object())  # a textura chega com a janela já destruída: nada acontece


def _aviso(titulo):
    return conquista_aviso.Aviso("r", titulo, "", "")


def test_falha_ao_mostrar_passa_para_o_proximo(monkeypatch, sem_efeitos):
    """Um cartão que falha no meio da fila não trava a fila: o idle de recuperação
    segue com o próximo, e um idle que sobra não duplica o que já está na tela."""
    idle = []
    monkeypatch.setattr(conquista_aviso.GLib, "idle_add", lambda funcao: idle.append(funcao) or 1)

    def quebra_no_dois(janela, canto, margem=24):
        if janela.titulo == "Dois":
            raise RuntimeError("falha de teste")
        return True

    monkeypatch.setattr(janela_por_cima, "por_no_canto", quebra_no_dois)
    conquista_aviso.mostrar(_aviso("Um"))
    conquista_aviso.mostrar(_aviso("Dois"))
    conquista_aviso.mostrar(_aviso("Tres"))
    assert conquista_aviso.na_tela() == "Um"
    sem_efeitos[-1][1]()  # o tempo de "Um" acaba: "Dois" falha com "Tres" ainda na fila
    assert conquista_aviso.na_tela() is None
    assert len(idle) == 1  # a recuperação ficou para fora desta chamada
    conquista_aviso.mostrar(_aviso("Quatro"))  # chega antes do idle: mostra "Tres"
    assert conquista_aviso.na_tela() == "Tres"
    idle[0]()  # o idle roda tarde: não troca nem duplica o que está na tela
    assert conquista_aviso.na_tela() == "Tres"
    assert [a.titulo for a in conquista_aviso._fila] == ["Quatro"]


def test_idle_de_recuperacao_mostra_o_proximo_quando_ninguem_chegou(monkeypatch, sem_efeitos):
    idle = []
    monkeypatch.setattr(conquista_aviso.GLib, "idle_add", lambda funcao: idle.append(funcao) or 1)
    monkeypatch.setattr(
        janela_por_cima, "preparar", lambda janela: janela.titulo != "Dois"
    )
    conquista_aviso.mostrar(_aviso("Um"))
    conquista_aviso.mostrar(_aviso("Dois"))
    conquista_aviso.mostrar(_aviso("Tres"))
    sem_efeitos[-1][1]()
    assert conquista_aviso.na_tela() is None and len(idle) == 1
    idle[0]()
    assert conquista_aviso.na_tela() == "Tres"


def test_preparar_que_falha_nao_mostra_a_janela(monkeypatch, sem_efeitos):
    """Sem os estilos o cartão ativaria e tiraria o jogo da tela cheia: ele é
    descartado sem nunca ter sido mostrado, e a fila segue."""
    mostradas = []
    original = conquista_aviso._JanelaDoAviso.set_visible

    def espia(self, visivel):
        mostradas.append(self.titulo)
        original(self, visivel)

    monkeypatch.setattr(conquista_aviso._JanelaDoAviso, "set_visible", espia)
    monkeypatch.setattr(janela_por_cima, "preparar", lambda janela: janela.titulo != "Um")
    conquista_aviso.mostrar(_aviso("Um"))
    assert conquista_aviso.na_tela() is None
    assert mostradas == []
    conquista_aviso.mostrar(_aviso("Dois"))
    assert conquista_aviso.na_tela() == "Dois"
    assert mostradas == ["Dois"]


def test_saida_e_animada_e_o_proximo_so_entra_depois(monkeypatch, sem_efeitos):
    saidas = []
    monkeypatch.setattr(
        conquista_aviso._JanelaDoAviso, "sair", lambda self, ao_terminar: saidas.append(ao_terminar)
    )
    conquista_aviso.mostrar(_aviso("Um"))
    conquista_aviso.mostrar(_aviso("Dois"))
    sem_efeitos[-1][1]()  # o tempo de "Um" acaba
    assert conquista_aviso.na_tela() == "Um" and len(saidas) == 1  # saindo, ainda na tela
    conquista_aviso.mostrar(_aviso("Tres"))  # chega durante a saída: só entra na fila
    assert conquista_aviso.na_tela() == "Um"
    saidas[0]()  # a animação de saída terminou
    assert conquista_aviso.na_tela() == "Dois"
    assert [a.titulo for a in conquista_aviso._fila] == ["Tres"]


def test_temporizador_velho_nao_esconde_o_cartao_seguinte(sem_efeitos):
    conquista_aviso.mostrar(_aviso("Um"))
    conquista_aviso.mostrar(_aviso("Dois"))
    esconder_um = sem_efeitos[-1][1]
    esconder_um()
    assert conquista_aviso.na_tela() == "Dois"
    esconder_um()  # o mesmo temporizador, de novo, já velho
    assert conquista_aviso.na_tela() == "Dois"


def test_fechar_durante_a_saida_fecha_na_hora(monkeypatch, sem_efeitos):
    saidas = []
    monkeypatch.setattr(
        conquista_aviso._JanelaDoAviso, "sair", lambda self, ao_terminar: saidas.append(ao_terminar)
    )
    conquista_aviso.mostrar(_aviso("Um"))
    conquista_aviso.mostrar(_aviso("Dois"))
    sem_efeitos[-1][1]()
    conquista_aviso.fechar()
    assert conquista_aviso.na_tela() is None
    saidas[0]()  # a animação "termina" depois do fim da sessão: nada acontece
    assert conquista_aviso.na_tela() is None and not conquista_aviso._fila


def test_animacao_que_nunca_termina_nao_trava_a_fila(monkeypatch, sem_efeitos):
    saidas = []
    monkeypatch.setattr(
        conquista_aviso._JanelaDoAviso, "sair", lambda self, ao_terminar: saidas.append(ao_terminar)
    )
    conquista_aviso.mostrar(_aviso("Um"))
    conquista_aviso.mostrar(_aviso("Dois"))
    sem_efeitos[-1][1]()
    segundos, forcar = sem_efeitos[-1]
    assert segundos == conquista_aviso._LIMITE_DA_SAIDA
    assert conquista_aviso.na_tela() == "Um"
    forcar()
    assert conquista_aviso.na_tela() == "Dois"
    saidas[0]()  # e se a animação terminar depois, nada se repete
    assert conquista_aviso.na_tela() == "Dois"


def test_saida_que_falha_nao_trava_a_fila(monkeypatch, sem_efeitos):
    def quebra(self, ao_terminar):
        raise RuntimeError("falha de teste")

    monkeypatch.setattr(conquista_aviso._JanelaDoAviso, "sair", quebra)
    conquista_aviso.mostrar(_aviso("Um"))
    conquista_aviso.mostrar(_aviso("Dois"))
    sem_efeitos[-1][1]()
    assert conquista_aviso.na_tela() == "Dois"


def test_animacao_de_saida_de_verdade_termina_e_destroi(monkeypatch, sem_efeitos):
    monkeypatch.setattr(janela_por_cima, "preparar", _PREPARAR_REAL)  # sem pegar o foco
    monkeypatch.setattr(janela_por_cima, "por_no_canto", _POR_NO_CANTO_REAL)
    monkeypatch.setattr(conquista_aviso._JanelaDoAviso, "sair", _SAIR_REAL)
    conquista_aviso.mostrar(_aviso("Um"))
    conquista_aviso.mostrar(_aviso("Dois"))
    janela = conquista_aviso._atual
    sem_efeitos[-1][1]()
    contexto = GLib.MainContext.default()
    fim = time.monotonic() + 5
    while conquista_aviso.na_tela() != "Dois" and time.monotonic() < fim:
        while contexto.iteration(False):
            pass
        time.sleep(0.01)
    assert conquista_aviso.na_tela() == "Dois"
    assert janela._destruida
