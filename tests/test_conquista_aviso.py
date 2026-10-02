"""O cartão do aviso de conquista."""

import pytest

from cartridges import conquista_aviso
from cartridges.conquistas import icones, progresso
from cartridges.conquistas.catalogo import ConquistaInfo
from cartridges.conquistas.vigia import Desbloqueada
from cartridges.utils import janela_por_cima


@pytest.fixture(autouse=True)
def sem_efeitos(monkeypatch):
    """Sem ícone de rede, sem Win32 e com o relógio na mão do teste."""
    monkeypatch.setattr(icones, "carregar", lambda _o, _e: None)
    monkeypatch.setattr(janela_por_cima, "preparar", lambda _j: True)
    monkeypatch.setattr(janela_por_cima, "por_no_canto", lambda _j, _c, margem=24: True)
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


def test_falha_ao_mostrar_passa_para_o_proximo(monkeypatch, sem_efeitos):
    idle = []
    monkeypatch.setattr(conquista_aviso.GLib, "idle_add", lambda funcao: idle.append(funcao) or 1)
    chamadas = []

    def quebra_na_primeira(janela, canto, margem=24):
        chamadas.append(canto)
        if len(chamadas) == 1:
            raise RuntimeError("falha de teste")
        return True

    monkeypatch.setattr(janela_por_cima, "por_no_canto", quebra_na_primeira)
    conquista_aviso.mostrar(conquista_aviso.Aviso("r", "Um", "", ""))
    conquista_aviso.mostrar(conquista_aviso.Aviso("r", "Dois", "", ""))
    assert conquista_aviso.na_tela() == "Dois"
    for funcao in idle:  # o idle que sobrou não duplica a janela na tela
        funcao()
    assert conquista_aviso.na_tela() == "Dois"
