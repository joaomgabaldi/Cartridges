"""O cartão do aviso de conquista."""

import array
import io
import logging
import time
import wave
import winsound

import pytest
from gi.repository import Gio, GLib

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
    monkeypatch.setattr(conquista_aviso, "_som_escalado", None)  # o volume de um teste não vaza
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
    monkeypatch.setattr(conquista_aviso.GLib, "idle_add", lambda funcao, *args: idle.append(lambda: funcao(*args)) or 1)

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
    monkeypatch.setattr(conquista_aviso.GLib, "idle_add", lambda funcao, *args: idle.append(lambda: funcao(*args)) or 1)
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


# O som


@pytest.fixture
def sons(monkeypatch, sem_som):
    """A thread do som roda na hora, para o teste ver o que tocou."""
    monkeypatch.setattr(conquista_aviso, "_em_segundo_plano", lambda funcao, *args: funcao(*args))
    return sem_som


def test_som_toca_quando_o_cartao_entra(sons):
    conquista_aviso.mostrar(_aviso("Um"))
    assert len(sons) == 1
    dados, flags = sons[0]
    assert dados[:4] == b"RIFF" and dados[8:12] == b"WAVE"
    assert flags == winsound.SND_MEMORY | winsound.SND_NODEFAULT  # falha não vira o "ding" do Windows


def test_som_desligado_nao_toca(sons, schema):
    schema.set_boolean("conquistas-aviso-som", False)
    conquista_aviso.mostrar(_aviso("Um"))
    assert sons == []
    assert conquista_aviso.na_tela() == "Um"


def test_so_o_primeiro_cartao_da_fila_toca(sons, sem_efeitos):
    for titulo in ("Um", "Dois", "Tres"):
        conquista_aviso.mostrar(_aviso(titulo))
    sem_efeitos[-1][1]()
    assert conquista_aviso.na_tela() == "Dois"
    sem_efeitos[-1][1]()
    assert conquista_aviso.na_tela() == "Tres"
    assert len(sons) == 1


def test_conquista_depois_da_fila_vazia_toca_de_novo(sons, sem_efeitos):
    conquista_aviso.mostrar(_aviso("Um"))
    sem_efeitos[-1][1]()
    assert conquista_aviso.na_tela() is None
    conquista_aviso.mostrar(_aviso("Dois"))
    assert len(sons) == 2


def test_cartao_que_falha_no_meio_da_fila_nao_faz_o_seguinte_tocar(sons, sem_efeitos, monkeypatch):
    idle = []
    monkeypatch.setattr(
        conquista_aviso.GLib, "idle_add", lambda funcao, *args: idle.append((funcao, args)) or 1
    )
    monkeypatch.setattr(janela_por_cima, "preparar", lambda janela: janela.titulo != "Um")
    for titulo in ("Zero", "Um", "Dois"):
        conquista_aviso.mostrar(_aviso(titulo))
    sem_efeitos[-1][1]()  # "Zero" sai; "Um" falha e a recuperação fica para o idle
    funcao, args = idle.pop()
    funcao(*args)
    assert conquista_aviso.na_tela() == "Dois"
    assert len(sons) == 1


def test_primeiro_que_falha_nao_cala_a_conquista_seguinte(sons, monkeypatch):
    monkeypatch.setattr(janela_por_cima, "preparar", lambda janela: janela.titulo != "Um")
    conquista_aviso.mostrar(_aviso("Um"))
    conquista_aviso.mostrar(_aviso("Dois"))
    assert conquista_aviso.na_tela() == "Dois"
    assert len(sons) == 1


def test_exemplo_toca_mesmo_com_fila(sons, sem_efeitos):
    conquista_aviso.mostrar(_aviso("Um"))
    conquista_aviso.mostrar(_aviso("Dois"))
    conquista_aviso.fechar()
    conquista_aviso.mostrar(conquista_aviso.Aviso.exemplo())
    assert len(sons) == 2


def test_cartao_que_nao_entra_nao_toca(sons, monkeypatch):
    monkeypatch.setattr(janela_por_cima, "preparar", lambda _j: False)
    conquista_aviso.mostrar(_aviso("Um"))
    assert conquista_aviso.na_tela() is None
    assert sons == []


def test_falha_do_som_nao_impede_o_cartao(sons, monkeypatch, caplog):
    def sem_audio(_dados, _flags):
        raise RuntimeError("Failed to play sound")

    monkeypatch.setattr(winsound, "PlaySound", sem_audio)
    with caplog.at_level(logging.WARNING):
        conquista_aviso.mostrar(_aviso("Um"))
    assert conquista_aviso.na_tela() == "Um"
    assert any("som" in r.getMessage() for r in caplog.records)


def test_recurso_ausente_nao_impede_o_cartao(sons, monkeypatch, caplog):
    def ausente(_caminho, _flags):
        raise GLib.Error("recurso inexistente")

    monkeypatch.setattr(Gio, "resources_lookup_data", ausente)
    with caplog.at_level(logging.WARNING):
        conquista_aviso.mostrar(_aviso("Um"))
    assert conquista_aviso.na_tela() == "Um"
    assert sons == []
    assert any("som" in r.getMessage() for r in caplog.records)


# O volume


def _wav(amostras, canais=2, largura=2, taxa=48000):
    saida = io.BytesIO()
    with wave.open(saida, "wb") as arquivo:
        arquivo.setnchannels(canais)
        arquivo.setsampwidth(largura)
        arquivo.setframerate(taxa)
        arquivo.writeframes(array.array("h", amostras).tobytes() if largura == 2 else bytes(amostras))
    return saida.getvalue()


def _amostras(dados):
    with wave.open(io.BytesIO(dados)) as arquivo:
        return (
            arquivo.getnchannels(),
            arquivo.getframerate(),
            arquivo.getnframes(),
            list(array.array("h", arquivo.readframes(arquivo.getnframes()))),
        )


def test_volume_pela_metade():
    escalado = conquista_aviso._no_volume(_wav([1000, -1000, 3, 0]), 50)
    assert _amostras(escalado) == (2, 48000, 2, [500, -500, 2, 0])


def test_volume_cheio_devolve_o_original():
    dados = _wav([1000, -1000])
    assert conquista_aviso._no_volume(dados, 100) is dados


def test_amostra_no_extremo_cabe_em_16_bits():
    assert _amostras(conquista_aviso._no_volume(_wav([-32768, 32767]), 10))[3] == [-3277, 3277]


def test_wav_de_8_bits_toca_o_original(sons, caplog):
    dados = _wav([128, 200], canais=1, largura=1)
    with caplog.at_level(logging.WARNING):
        conquista_aviso._reproduzir(dados, 50)
    assert sons[-1][0] == dados
    assert any("volume" in r.getMessage() for r in caplog.records)


def test_volume_lido_a_cada_som(sons, schema, sem_efeitos):
    maiores = []
    for volume in (50, 100, 50):
        schema.set_int("conquistas-aviso-som-volume", volume)
        conquista_aviso.fechar()
        conquista_aviso.mostrar(_aviso("Um"))
        maiores.append(max(abs(a) for a in _amostras(sons[-1][0])[3]))
    assert maiores[0] == maiores[2] < maiores[1]


def _rotulos(widget):
    achados = []
    filho = widget.get_first_child()
    while filho:
        if isinstance(filho, conquista_aviso.Gtk.Label):
            achados.append(filho.get_label())
        achados += _rotulos(filho)
        filho = filho.get_next_sibling()
    return achados


def test_montar_cartao_e_o_mesmo_do_aviso_real(sem_efeitos):
    aviso = conquista_aviso.Aviso("Rótulo", "Título", "Descrição", "")
    cartao, imagem = conquista_aviso.montar_cartao(aviso)
    assert cartao.has_css_class("conquista-aviso-cartao")
    assert imagem.get_icon_name() == "starred-symbolic"
    janela = conquista_aviso._JanelaDoAviso(aviso)
    try:
        assert janela.cartao.has_css_class("conquista-aviso-cartao")
        assert janela._imagem.get_icon_name() == "starred-symbolic"
        assert _rotulos(janela.cartao) == _rotulos(cartao) == ["Rótulo", "Título", "Descrição"]
    finally:
        janela.fechar()


def test_exemplo_aceita_a_porcentagem():
    assert conquista_aviso.Aviso.exemplo(2.3).rotulo == "Conquista desbloqueada · ★ Rara, 2,3%"
