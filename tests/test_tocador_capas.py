# test_tocador_capas.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O tocador único das capas animadas: prazos, pausa, posição e falhas."""

import os
import threading

import pytest
from PIL import Image
from PIL.WebPImagePlugin import WebPImageFile

from cartridges.utils import tocador_capas
from cartridges.utils.tocador_capas import Tocador

LARGURA, ALTURA = 8, 12


def _cor(indice):
    # Cores bem distintas por quadro: o libwebp funde quadros quase iguais, e
    # os testes precisam de um quadro por duração pedida.
    return (10 + 30 * indice, 200 - 20 * indice, 60)


def _indice(dados):
    """Qual quadro é, lendo a cor do primeiro pixel."""
    return (dados[0] - 10) // 30


def criar_webp(caminho, duracoes):
    quadros = [
        Image.new("RGB", (LARGURA, ALTURA), _cor(i)) for i in range(len(duracoes))
    ]
    quadros[0].save(
        caminho,
        save_all=True,
        append_images=quadros[1:],
        duration=duracoes,
        lossless=True,
        loop=0,
    )
    return caminho


class Relogio:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Banca:
    """Um tocador com relógio falso, entrega síncrona e as chamadas contadas."""

    def __init__(self):
        self.relogio = Relogio()
        self.entregas = []
        self.tocador = Tocador(
            agora=self.relogio, entregar=self._entregar, iniciar_thread=False
        )

    def _entregar(self, func, *args):
        self.entregas.append((func, args))
        func(*args)

    def captura(self):
        """(ao_quadro, quadros, ao_falhar, falhas): o que um dono receberia."""
        quadros, falhas = [], []
        return (
            lambda dados, largura, altura: quadros.append(_indice(dados)),
            quadros,
            lambda: falhas.append(1),
            falhas,
        )


@pytest.fixture
def banca():
    return Banca()


def test_respeita_a_duracao_de_cada_quadro(banca, tmp_path):
    copia = criar_webp(tmp_path / "a.webp", [100, 50])
    dono = object()
    quadro, quadros, falhar, _ = banca.captura()
    banca.tocador.tocar(dono, copia, quadro, falhar)

    banca.tocador.passo()
    assert quadros == [0]
    banca.relogio.t = 0.05
    banca.tocador.passo()
    assert quadros == [0]
    banca.relogio.t = 0.1
    banca.tocador.passo()
    assert quadros == [0, 1]
    banca.relogio.t = 0.2
    banca.tocador.passo()
    assert quadros == [0, 1, 0]


def test_entrega_o_tamanho_do_quadro(banca, tmp_path):
    copia = criar_webp(tmp_path / "a.webp", [100, 50])
    recebido = []
    banca.tocador.tocar(
        object(), copia, lambda *a: recebido.append(a), lambda: None
    )
    banca.tocador.passo()
    dados, largura, altura = recebido[0]
    assert (largura, altura) == (LARGURA, ALTURA)
    assert len(dados) == LARGURA * ALTURA * 4


def test_um_pacote_por_tick(banca, tmp_path):
    copia = criar_webp(tmp_path / "a.webp", [100, 100])
    recebidos = []
    for _ in range(3):
        banca.tocador.tocar(
            object(), copia, lambda *a: recebidos.append(a), lambda: None
        )

    banca.tocador.passo()

    assert len(recebidos) == 3
    assert len(banca.entregas) == 1
    assert len(banca.entregas[0][1][0]) == 3


def test_tick_sem_nada_a_mostrar_nao_entrega(banca, tmp_path):
    copia = criar_webp(tmp_path / "a.webp", [100, 100])
    quadro, quadros, falhar, _ = banca.captura()
    banca.tocador.tocar(object(), copia, quadro, falhar)
    banca.tocador.passo()
    banca.entregas.clear()

    banca.relogio.t = 0.05
    banca.tocador.passo()

    assert banca.entregas == []


def test_atraso_nao_acelera(banca, tmp_path):
    copia = criar_webp(tmp_path / "a.webp", [50, 50, 50])
    quadro, quadros, falhar, _ = banca.captura()
    banca.tocador.tocar(object(), copia, quadro, falhar)
    banca.tocador.passo()
    assert quadros == [0]

    banca.relogio.t = 1.0  # a tela travou por um segundo
    banca.tocador.passo()
    assert quadros == [0, 1]
    banca.tocador.passo()  # mesmo instante: o prazo recomeça de agora
    assert quadros == [0, 1]


def test_parar_e_tocar_retoma_o_quadro(banca, tmp_path):
    copia = criar_webp(tmp_path / "a.webp", [100] * 4)
    dono = object()
    quadro, quadros, falhar, _ = banca.captura()
    banca.tocador.tocar(dono, copia, quadro, falhar)
    banca.tocador.passo()
    banca.relogio.t = 0.1
    banca.tocador.passo()
    assert quadros == [0, 1]
    assert banca.tocador.posicao_ms(dono) == 100

    banca.tocador.parar(dono)
    banca.relogio.t = 5.0
    banca.tocador.passo()
    assert quadros == [0, 1]  # parada, nada sai

    banca.tocador.tocar(dono, copia, quadro, falhar, posicao_inicial_ms=300)
    assert banca.tocador.posicao_ms(dono) == 100
    banca.tocador.passo()
    assert quadros == [0, 1, 2]


def test_fecha_depois_de_30_s_parada(banca, tmp_path):
    copia = criar_webp(tmp_path / "a.webp", [100] * 3)
    dono = object()
    quadro, quadros, falhar, _ = banca.captura()
    banca.tocador.tocar(dono, copia, quadro, falhar)
    banca.tocador.passo()
    banca.relogio.t = 0.1
    banca.tocador.passo()
    banca.tocador.parar(dono)

    banca.relogio.t = 0.1 + 31
    banca.tocador.passo()
    assert banca.tocador.posicao_ms(dono) == 0

    banca.tocador.tocar(dono, copia, quadro, falhar)
    banca.tocador.passo()
    assert quadros == [0, 1, 0]  # recomeçou do início

    banca.tocador.parar(dono)
    banca.relogio.t += 31
    banca.tocador.passo()
    banca.tocador.tocar(dono, copia, quadro, falhar, posicao_inicial_ms=200)
    banca.tocador.passo()
    assert quadros == [0, 1, 0, 2]


def test_nao_fecha_antes_dos_30_s(banca, tmp_path):
    copia = criar_webp(tmp_path / "a.webp", [100] * 3)
    dono = object()
    quadro, quadros, falhar, _ = banca.captura()
    banca.tocador.tocar(dono, copia, quadro, falhar)
    banca.tocador.passo()
    banca.relogio.t = 0.1
    banca.tocador.passo()
    banca.tocador.parar(dono)

    banca.relogio.t = 0.1 + 29
    banca.tocador.passo()
    assert banca.tocador.posicao_ms(dono) == 100


def test_troca_de_copia_no_mesmo_instante(banca, tmp_path):
    tres = criar_webp(tmp_path / "tres.webp", [100, 100, 100])
    dois = criar_webp(tmp_path / "dois.webp", [200, 100])
    dono = object()
    quadro, quadros, falhar, _ = banca.captura()
    banca.tocador.tocar(dono, tres, quadro, falhar)
    banca.tocador.passo()

    banca.tocador.tocar(dono, dois, quadro, falhar, posicao_inicial_ms=250)
    banca.tocador.passo()
    assert quadros == [0, 1]  # o 2º de "dois" cobre 200-300 ms
    assert banca.tocador.posicao_ms(dono) == 200

    # E de volta: o instante 200 cai no 3º quadro de "tres".
    banca.tocador.tocar(
        dono, tres, quadro, falhar, posicao_inicial_ms=banca.tocador.posicao_ms(dono)
    )
    banca.tocador.passo()
    assert quadros == [0, 1, 2]


def test_posicao_inicial_da_a_volta_na_duracao_total(banca, tmp_path):
    copia = criar_webp(tmp_path / "a.webp", [200, 100])
    quadro, quadros, falhar, _ = banca.captura()
    banca.tocador.tocar(object(), copia, quadro, falhar, posicao_inicial_ms=550)
    banca.tocador.passo()
    assert quadros == [1]  # 550 % 300 = 250


def test_falha_passageira_reabre(banca, tmp_path, monkeypatch):
    copia = criar_webp(tmp_path / "a.webp", [100, 100, 100])
    dono = object()
    quadro, quadros, falhar, falhas = banca.captura()
    banca.tocador.tocar(dono, copia, quadro, falhar)
    banca.tocador.passo()
    assert quadros == [0]

    original = Image.Image.convert
    restantes = [True]

    def convert(self, *args, **kwargs):
        if restantes and restantes.pop():
            raise OSError("falha forçada")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "convert", convert)
    banca.relogio.t = 0.1
    banca.tocador.passo()  # o quadro 1 falha
    assert quadros == [0]
    assert falhas == []

    banca.tocador.passo()  # reabre e recomeça do quadro 0
    assert quadros == [0, 0]
    assert falhas == []


def test_tres_falhas_seguidas_avisam(banca, tmp_path):
    copia = criar_webp(tmp_path / "a.webp", [100, 100, 100])
    copia.write_bytes(copia.read_bytes()[:-40])  # truncado no meio
    dono = object()
    quadro, quadros, falhar, falhas = banca.captura()
    banca.tocador.tocar(dono, copia, quadro, falhar)

    banca.tocador.passo()
    banca.tocador.passo()
    assert falhas == []
    banca.tocador.passo()
    assert falhas == [1]
    assert quadros == []

    banca.tocador.passo()  # a capa saiu da lista: nada mais acontece
    assert falhas == [1]
    assert banca.tocador.posicao_ms(dono) == 0


def test_sucesso_zera_o_contador(banca, tmp_path, monkeypatch):
    copia = criar_webp(tmp_path / "a.webp", [100, 100, 100])
    dono = object()
    quadro, quadros, falhar, falhas = banca.captura()
    banca.tocador.tocar(dono, copia, quadro, falhar)

    original = Image.Image.convert
    roteiro = [True, False, True, False, True]  # falha, sucesso, falha, ...
    leituras = []

    def convert(self, *args, **kwargs):
        falha = roteiro[len(leituras)]
        leituras.append(falha)
        if falha:
            raise OSError("falha forçada")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "convert", convert)
    for _ in roteiro:
        banca.relogio.t += 1.0
        banca.tocador.passo()

    assert len(leituras) == len(roteiro)
    assert quadros == [0, 0]
    assert falhas == []


def test_apagar_a_copia_enquanto_toca(banca, tmp_path):
    copia = criar_webp(tmp_path / "a.webp", [100, 100, 100])
    quadro, quadros, falhar, falhas = banca.captura()
    banca.tocador.tocar(object(), copia, quadro, falhar)
    banca.tocador.passo()

    os.remove(copia)  # no Windows falha se o tocador segurar o arquivo

    banca.relogio.t = 0.1
    banca.tocador.passo()
    assert quadros == [0, 1]
    assert falhas == []


def test_copia_apagada_enquanto_fechada_conta_como_falha(banca, tmp_path):
    copia = criar_webp(tmp_path / "a.webp", [100, 100, 100])
    dono = object()
    quadro, quadros, falhar, falhas = banca.captura()
    banca.tocador.tocar(dono, copia, quadro, falhar)
    banca.tocador.passo()
    banca.tocador.parar(dono)
    banca.relogio.t = 31.0
    banca.tocador.passo()  # fecha a pausada

    os.remove(copia)
    banca.tocador.tocar(dono, copia, quadro, falhar)  # não pode estourar
    banca.tocador.passo()
    banca.tocador.passo()
    assert falhas == []
    banca.tocador.passo()
    assert falhas == [1]
    assert quadros == [0]


def test_callbacks_rodam_sem_a_trava(banca, tmp_path):
    """Um ``ao_quadro`` que volta ao tocador não pode travar nele mesmo."""
    copia = criar_webp(tmp_path / "a.webp", [100, 100])
    dono = object()
    posicoes = []

    def quadro(dados, largura, altura):
        posicoes.append(banca.tocador.posicao_ms(dono))
        banca.tocador.parar(dono)

    banca.tocador.tocar(dono, copia, quadro, lambda: None)
    banca.tocador.passo()
    assert posicoes == [0]


def test_ao_falhar_pode_tocar_de_novo(banca, tmp_path):
    copia = criar_webp(tmp_path / "a.webp", [100, 100])
    copia.write_bytes(copia.read_bytes()[:-40])
    dono = object()
    chamado = []

    def falhar():
        chamado.append(1)
        banca.tocador.tocar(dono, copia, lambda *a: None, lambda: None)

    banca.tocador.tocar(dono, copia, lambda *a: None, falhar)
    for _ in range(3):
        banca.tocador.passo()
    assert chamado == [1]


def test_a_thread_nasce_no_primeiro_tocar_e_toca(tmp_path):
    copia = criar_webp(tmp_path / "a.webp", [30, 30])
    recebido = threading.Event()
    tocador = Tocador(entregar=lambda f, *a: f(*a))
    assert not any(t.name == "tocador-capas" for t in threading.enumerate())

    dono = object()
    tocador.tocar(dono, copia, lambda *a: recebido.set(), lambda: None)
    try:
        assert recebido.wait(2.0)
        thread = next(t for t in threading.enumerate() if t.name == "tocador-capas")
        assert thread.daemon
    finally:
        tocador.parar(dono)


def test_o_modulo_expoe_a_instancia_e_as_constantes():
    assert isinstance(tocador_capas.tocador, Tocador)
    assert tocador_capas.TICK == pytest.approx(1 / 30)
    assert tocador_capas.FECHAR_APOS == 30.0
    assert tocador_capas.FALHAS_ATE_CORROMPIDA == 3


def test_cadencia_de_quadros_curtos(banca, tmp_path):
    """Quadros de 40 ms (25 fps) em ticks de 1/30 s têm de tocar a 25 fps."""
    copia = criar_webp(tmp_path / "a.webp", [40, 40, 40, 40])
    quadro, quadros, falhar, _ = banca.captura()
    banca.tocador.tocar(object(), copia, quadro, falhar)
    for k in range(30):
        banca.relogio.t = k * tocador_capas.TICK
        banca.tocador.passo()
    assert 24 <= len(quadros) <= 26


def test_durações_do_container_batem_com_as_do_pillow(tmp_path):
    duracoes = [100, 50, 70, 33]
    copia = criar_webp(tmp_path / "a.webp", duracoes)
    dados = copia.read_bytes()
    assert tocador_capas._duracoes_do_container(dados) == duracoes
    with Image.open(copia) as imagem:
        reais = []
        for n in range(imagem.n_frames):
            imagem.seek(n)
            imagem.load()
            reais.append(imagem.info["duration"])
    assert reais == duracoes


def test_abrir_nao_decodifica_os_outros_quadros(banca, tmp_path, monkeypatch):
    copia = criar_webp(tmp_path / "a.webp", [100, 100, 100, 100])
    chamadas = []
    original = WebPImageFile.seek

    def seek(self, frame):
        chamadas.append(frame)
        return original(self, frame)

    monkeypatch.setattr(WebPImageFile, "seek", seek)
    quadro, quadros, falhar, _ = banca.captura()
    banca.tocador.tocar(object(), copia, quadro, falhar, posicao_inicial_ms=250)
    banca.tocador.passo()

    assert quadros == [2]
    assert set(chamadas) <= {2}


def test_container_malformado_cai_na_leitura_quadro_a_quadro(banca, tmp_path):
    # Um WebP estático não tem blocos ANMF: nada a ler no contêiner.
    estatico = tmp_path / "estatico.webp"
    Image.new("RGB", (LARGURA, ALTURA), _cor(0)).save(estatico, lossless=True)
    assert tocador_capas._duracoes_do_container(estatico.read_bytes()) is None
    assert tocador_capas._duracoes_do_container(b"") is None
    assert tocador_capas._duracoes_do_container(b"RIFF\0\0\0\0WEBPANMF") is None
    animado = criar_webp(tmp_path / "a.webp", [100, 100]).read_bytes()
    assert tocador_capas._duracoes_do_container(animado[:-10]) is None

    quadro, quadros, falhar, falhas = banca.captura()
    banca.tocador.tocar(object(), estatico, quadro, falhar)
    banca.tocador.passo()
    assert quadros == [0]
    assert falhas == []


def test_esquecer_a_copia_regravada_toca_o_conteudo_novo(banca, tmp_path):
    copia = criar_webp(tmp_path / "a.webp", [100, 100, 100])
    dono = object()
    quadro, quadros, falhar, falhas = banca.captura()
    banca.tocador.tocar(dono, copia, quadro, falhar)
    banca.tocador.passo()
    banca.relogio.t = 0.1
    banca.tocador.passo()
    assert quadros == [0, 1]

    # Mesmo caminho, outras cores (a capa foi trocada e a cópia regenerada).
    novos = [Image.new("RGB", (LARGURA, ALTURA), _cor(i + 5)) for i in range(2)]
    novos[0].save(
        copia, save_all=True, append_images=novos[1:], duration=[100, 100], lossless=True
    )
    banca.tocador.esquecer(copia)
    assert banca.tocador.posicao_ms(dono) == 0
    banca.relogio.t = 0.2
    banca.tocador.passo()
    assert quadros == [0, 1, 5]  # quadro 0 do conteúdo novo
    assert falhas == []


def test_esquecer_fecha_a_pausada_e_ignora_outras_copias(banca, tmp_path):
    a = criar_webp(tmp_path / "a.webp", [100, 100])
    b = criar_webp(tmp_path / "b.webp", [100, 100])
    pausada, outra = object(), object()
    quadro, quadros, falhar, _ = banca.captura()
    banca.tocador.tocar(pausada, a, quadro, falhar)
    banca.tocador.tocar(outra, b, quadro, falhar)
    banca.tocador.passo()
    banca.relogio.t = 0.1
    banca.tocador.passo()
    banca.tocador.parar(pausada)

    banca.tocador.esquecer(a)

    assert banca.tocador.posicao_ms(pausada) == 0
    assert banca.tocador.posicao_ms(outra) == 100
