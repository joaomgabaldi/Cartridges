# test_regras_do_big_picture.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Big Picture, regras puras: lista, entrada automática, carrossel, fundo, fila da entrada e tique."""

import array
import hashlib
import io
import subprocess
import sys
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from kyron.modelos import regras_do_big_picture as regras
from kyron.modelos.ordem import Linha
from kyron.xinput import intervalo_de_repeticao_us

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data"


def _linha(jogo_id, jogado_em=0, removido=False, nome=None):
    return Linha(
        jogo_id=jogo_id, nome=nome or jogo_id, capa="", zerado=False, removido=removido, status="",
        genero="", desenvolvedora="", publicadora="", anotacoes="", lancamento="", adicionado=0,
        jogado_em=jogado_em, tempo_de_jogo=0, tamanho=0, estrelas=0, carregando=False,
    )  # fmt: skip


def test_regras_sem_gi_nem_qt():
    codigo = "import builtins, sys; builtins._ = lambda s: s; import kyron.modelos.regras_do_big_picture; assert not [m for m in sys.modules if m == 'gi' or m.startswith(('gi.', 'PySide6'))], sorted(sys.modules)"
    saida = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, check=False)
    assert saida.returncode == 0, saida.stderr


# --- lista ---------------------------------------------------------------------------------------


def test_lista_so_tem_jogos_da_biblioteca_do_mais_recente():
    linhas = [_linha("a", 10), _linha("b", 30), _linha("c", 50, removido=True), _linha("e", 70)]
    assert [j.jogo_id for j in regras.jogos_da_biblioteca(linhas)] == ["e", "b", "a"]


def test_empate_de_jogado_em_vai_por_nome():
    linhas = [_linha("1", 0, nome="beta"), _linha("2", 0, nome="Alfa")]
    assert [j.nome for j in regras.jogos_da_biblioteca(linhas)] == ["Alfa", "beta"]


# --- entrada automática e repetição --------------------------------------------------------------


@pytest.mark.parametrize("campo", ["preferencia", "controle_ligado", "tem_3d", "grade_a_vista", "ja_saiu"])
def test_cada_condicao_bloqueia_a_entrada_automatica(campo):
    args = {"preferencia": True, "controle_ligado": True, "tem_3d": True, "grade_a_vista": True, "ja_saiu": False}
    assert regras.pode_entrar_sozinho(**args)
    args[campo] = not args[campo]
    assert not regras.pode_entrar_sozinho(**args)


def test_repeticao_acelera_depois_de_um_segundo():
    assert intervalo_de_repeticao_us(0) == 120_000
    assert intervalo_de_repeticao_us(999_999) == 120_000
    assert intervalo_de_repeticao_us(1_000_000) == 40_000


# --- carrossel -----------------------------------------------------------------------------------


def test_mover_fica_preso_nas_pontas():
    c = regras.Carrossel(["a", "b", "c"])
    assert c.indice == 0 and c.atual == "a"
    assert not c.mover(-1) and c.indice == 0
    assert c.mover(+1) and c.atual == "b"
    assert c.mover(+10) and c.indice == 2
    assert not c.mover(+1)


def test_inicio_e_fim():
    c = regras.Carrossel(["a", "b", "c"])
    assert not c.inicio()
    assert c.fim() and c.indice == 2
    assert not c.fim()
    assert c.inicio() and c.indice == 0


def test_lista_vazia_nao_move():
    c = regras.Carrossel([])
    assert c.atual is None and not c.mover(1) and not c.fim()


def test_trocar_lista_mantem_o_jogo_central():
    c = regras.Carrossel(["a", "b", "c"])
    c.ir_para(1)
    c.trocar_lista(["x", "a", "b", "c"])
    assert c.atual == "b"


def test_trocar_lista_cai_no_vizinho_quando_o_central_some():
    c = regras.Carrossel(["a", "b", "c"])
    c.ir_para(2)
    c.trocar_lista(["a", "b"])
    assert c.indice == 1


def test_trocar_lista_com_centro_explicito():
    c = regras.Carrossel(["a", "b", "c"])
    c.trocar_lista(["a", "b", "c"], centro="c")
    assert c.atual == "c"


def test_trocar_para_lista_vazia_zera_o_indice():
    c = regras.Carrossel(["a", "b"])
    c.ir_para(1)
    c.trocar_lista([])
    assert c.indice == 0 and c.atual is None


# --- fundo ---------------------------------------------------------------------------------------


def test_fundo_tem_o_tamanho_certo():
    assert len(regras.bytes_do_fundo(64, 32)) == 64 * 32 * 3


def test_fundo_topo_e_base():
    b = regras.bytes_do_fundo(64, 100)
    assert all(abs(v - a) <= 1 for v, a in zip(b[: 64 * 3], (28, 28, 30) * 64, strict=True))
    assert max(b[-64 * 3 :]) <= 1


def test_pontilhado_nunca_passa_de_um_tom():
    w, h = 128, 256
    b = regras.bytes_do_fundo(w, h)
    for y in range(h):
        k = (1 - y / (h - 1)) ** 1.6
        exatos = (28 * k, 28 * k, 30 * k)
        for x in range(0, w, 7):
            for c in range(3):
                assert abs(b[(y * w + x) * 3 + c] - exatos[c]) < 1.0 + 1e-9


def test_linha_8_abaixo_nunca_e_mais_clara():
    w, h = 64, 300
    b = regras.bytes_do_fundo(w, h)
    for y in range(h - 8):
        for i in range(w * 3):
            assert b[(y + 8) * w * 3 + i] <= b[y * w * 3 + i]


def test_limiares_sem_padrao_de_hachura():
    m = regras._LIMIARES  # noqa: SLF001
    assert not any(m[1] == m[0][k:] + m[0][:k] for k in range(8))
    por_xor = {}
    for y in range(8):
        for x in range(8):
            por_xor.setdefault(x ^ y, set()).add(m[y][x])
    assert any(len(v) > 1 for v in por_xor.values())


def test_fundo_rapido():
    inicio = time.perf_counter()
    regras.bytes_do_fundo(2560, 1440)
    assert time.perf_counter() - inicio < 0.1


# --- fila da entrada e da saída ------------------------------------------------------------------


def test_quadro_entrada_comeco_e_fim():
    assert regras.quadro_da_fila(0.0, 30, 0) == pytest.approx((30, 0.0, 0.0, 0.0))
    assert regras.quadro_da_fila(1.0, 30, 0) == pytest.approx((0, 1.0, 1.0, 1.0))


def test_quadro_virada_ultrapassa():
    assert max(regras.quadro_da_fila(t / 100, 30, 0)[1] for t in range(100)) > 1.0


def test_quadro_saida_parte_da_capa_atual():
    assert regras.quadro_da_fila(1.0, 30, 10)[0] == pytest.approx(10)


def test_quadro_um_jogo():
    for t in (0.0, 0.3, 0.7, 1.0):
        assert regras.quadro_da_fila(t, 0, 0)[0] == 0


# --- tique ---------------------------------------------------------------------------------------


@pytest.fixture
def tiques(monkeypatch):
    """Registra os tiques sem tocar de verdade; a thread roda direto e o relógio é controlado."""
    tocados = []
    monkeypatch.setattr(regras.winsound, "PlaySound", lambda dados, flags: tocados.append((dados, flags)))
    monkeypatch.setattr(
        regras.threading, "Thread",
        lambda target, args=(), daemon=None: SimpleNamespace(start=lambda: target(*args)),
    )  # fmt: skip
    monkeypatch.setattr(regras, "_ultimo_tique", -1000.0)
    agora = [100.0]
    monkeypatch.setattr(regras.time, "monotonic", lambda: agora[0])
    return SimpleNamespace(tocados=tocados, relogio=agora)


def test_troca_de_capa_toca(tiques):
    regras.tocar_tique()
    assert len(tiques.tocados) == 1
    dados, flags = tiques.tocados[0]
    assert dados[:4] == b"RIFF"
    assert flags == regras.winsound.SND_MEMORY | regras.winsound.SND_NODEFAULT


def test_duas_trocas_em_menos_de_70ms_tocam_uma_vez(tiques):
    regras.tocar_tique()
    tiques.relogio[0] += 0.069
    regras.tocar_tique()
    assert len(tiques.tocados) == 1
    tiques.relogio[0] += 0.001
    regras.tocar_tique()
    assert len(tiques.tocados) == 2


def test_preferencia_desligada_nao_toca(tiques, schema):
    schema.set_boolean("big-picture-som", False)
    regras.tocar_tique()
    assert tiques.tocados == []


def test_falha_ao_tocar_nao_levanta(tiques, monkeypatch):
    chamadas = []

    def falha(*_args):
        chamadas.append(1)
        raise RuntimeError("sem placa de som")

    monkeypatch.setattr(regras.winsound, "PlaySound", falha)
    regras.tocar_tique()
    assert chamadas == [1]


def test_falha_ao_ler_o_som_avisa_uma_vez_so(tiques, monkeypatch, caplog):
    monkeypatch.setattr(regras, "_dados_tique", None)
    monkeypatch.setattr(regras, "_ARQUIVO_DO_TIQUE", DADOS / "sons" / "nao-existe.wav")
    for _ in range(3):
        tiques.relogio[0] += 1
        regras.tocar_tique()
    assert tiques.tocados == []
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1


# --- embaralhar da fila --------------------------------------------------------------------------


@pytest.mark.parametrize("entrar", [True, False])
@pytest.mark.parametrize("n", [1, 2, 19, 30])
def test_um_flip_por_capa_que_passa(n, entrar):
    instantes = regras.instantes_da_fila(n, entrar=entrar)
    assert len(instantes) == n
    assert all(a < b for a, b in zip(instantes, instantes[1:]))
    assert all(0 <= t <= 1 for t in instantes)


@pytest.mark.parametrize("entrar", [True, False])
def test_cada_flip_cai_quando_a_capa_cruza_o_centro(entrar):
    n = 12
    for t in regras.instantes_da_fila(n, entrar=entrar):
        tempo_da_animacao = t if entrar else 1 - t  # a saída anima de 1 a 0
        posicao = regras.quadro_da_fila(tempo_da_animacao, n, 0)[0]
        assert posicao == pytest.approx(round(posicao), abs=1e-9)


def test_entrada_desacelera_e_saida_acelera():
    entrada = regras.instantes_da_fila(10, entrar=True)
    saida = regras.instantes_da_fila(10, entrar=False)
    assert entrada[1] - entrada[0] < entrada[-1] - entrada[-2]
    assert saida[1] - saida[0] > saida[-1] - saida[-2]


def test_sem_capas_sem_flips():
    assert regras.instantes_da_fila(0, entrar=True) == []


def test_saida_so_toca_as_capas_que_existem_depois_da_central():
    todas = regras.instantes_da_fila(30, entrar=False)
    assert regras.instantes_da_fila(30, entrar=False, passam=4) == todas[:4]
    assert regras.instantes_da_fila(30, entrar=False, passam=0) == []


def test_flips_antes_de_desde_ficam_de_fora():
    todas = regras.instantes_da_fila(30, entrar=True)
    depois = regras.instantes_da_fila(30, entrar=True, desde=0.15)
    assert depois == [t for t in todas if t >= 0.15]
    assert 0 < len(depois) < len(todas)


def test_wav_sem_os_flips_do_escuro_comeca_em_silencio_e_mantem_o_tempo():
    with wave.open(io.BytesIO(regras.wav_do_embaralhar(30, entrar=True, desde=0.15))) as w:
        amostras = array.array("h", w.readframes(w.getnframes()))
        assert w.getnframes() / 44100 == pytest.approx(regras.DURACAO_FILA_ENTRADA_MS / 1000, abs=0.01)
    assert max(abs(a) for a in amostras[: int(0.15 * len(amostras)) - 10]) == 0


def test_embaralhar_sem_capas_depois_da_central_nao_toca(tiques):
    regras.tocar_embaralhar(30, entrar=False, passam=0)
    assert tiques.tocados == []


def test_falha_ao_montar_o_embaralhar_nao_levanta(tiques, monkeypatch, caplog):
    def falha(*_a, **_k):
        raise RuntimeError("sem memória")

    monkeypatch.setattr(regras, "wav_do_embaralhar", falha)
    regras.tocar_embaralhar(5, entrar=True)
    assert tiques.tocados == []
    assert any("montar o embaralhar" in r.message for r in caplog.records)


@pytest.mark.parametrize(("entrar", "duracao_ms"), [(True, regras.DURACAO_FILA_ENTRADA_MS), (False, regras.DURACAO_FILA_SAIDA_MS)])
def test_wav_do_embaralhar_tem_a_duracao_da_fila(entrar, duracao_ms):
    with wave.open(io.BytesIO(regras.wav_do_embaralhar(20, entrar=entrar))) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 44100)
        assert w.getnframes() / 44100 == pytest.approx(duracao_ms / 1000, abs=0.01)


def test_wav_do_embaralhar_tem_som_onde_cai_cada_flip():
    with wave.open(io.BytesIO(regras.wav_do_embaralhar(3, entrar=True))) as w:
        amostras = array.array("h", w.readframes(w.getnframes()))
    for t in regras.instantes_da_fila(3, entrar=True):
        inicio = int(t * regras.DURACAO_FILA_ENTRADA_MS / 1000 * 44100)
        assert max(abs(a) for a in amostras[inicio : inicio + 200]) > 1000
    assert max(abs(a) for a in amostras[-2000:]) == 0  # depois do último flip, silêncio


def test_embaralhar_toca(tiques):
    regras.tocar_embaralhar(5, entrar=True)
    assert len(tiques.tocados) == 1
    dados, flags = tiques.tocados[0]
    assert dados[:4] == b"RIFF"
    assert flags == regras.winsound.SND_MEMORY | regras.winsound.SND_NODEFAULT


def test_embaralhar_com_preferencia_desligada_nao_toca(tiques, schema):
    schema.set_boolean("big-picture-som", False)
    regras.tocar_embaralhar(5, entrar=True)
    assert tiques.tocados == []


def test_embaralhar_sem_capas_nao_toca(tiques):
    regras.tocar_embaralhar(0, entrar=False)
    assert tiques.tocados == []


def test_som_e_o_aprovado():
    dados = (DADOS / "sons" / "tique.wav").read_bytes()
    assert hashlib.sha256(dados).hexdigest() == "5b894a70465ead3b6a74724c3fd1c5a4c17d5b5bc7b737cd2c8762d64c3ac9ef"
