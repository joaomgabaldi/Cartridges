# test_copias_animadas.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cópias reduzidas das capas animadas (`utils/copias_animadas.py`)."""

import threading

import pytest
from PIL import Image

from cartridges import shared
from cartridges.utils import copias_animadas, tocador_capas


def _animada(caminho, duracoes, formato="WEBP", tons=None):
    """Grava uma capa animada pequena, com um quadro por duração.

    ``tons`` dá o vermelho de cada quadro; por padrão, todos diferentes.
    """
    tons = tons or [i * 30 % 256 for i in range(len(duracoes))]
    quadros = [Image.new("RGBA", (8, 12), (tom, 0, 0, 255)) for tom in tons]
    quadros[0].save(
        caminho, formato, save_all=True, append_images=quadros[1:],
        duration=duracoes, loop=0, lossless=True,
    )  # fmt: skip
    return caminho


def _duracoes(caminho):
    with Image.open(caminho) as image:
        resultado = []
        for i in range(image.n_frames):
            image.seek(i)
            image.load()  # no WebP a duração só aparece depois de decodificar
            resultado.append(image.info["duration"])
        return resultado


def test_quadros_curtos_sao_fundidos(tmp_path):
    origem = _animada(tmp_path / "a.webp", [16] * 6 + [100])
    destino = tmp_path / "copia.webp"

    assert copias_animadas.gerar(origem, destino, (200, 300)) is True

    assert _duracoes(destino) == [32, 32, 32, 100]
    with Image.open(destino) as image:
        assert image.n_frames == 4


def test_grade_e_detalhes_tem_a_mesma_duracao_total(tmp_path):
    # Quadros repetidos e quase iguais: o libwebp os funde em um só, e com
    # perda isso depende dos pixels, ou seja, do tamanho. A contagem de quadros
    # das duas cópias pode divergir; a duração total, não.
    tons = [0, 0, 0, 2, 2, 200, 200, 202]
    origem = _animada(tmp_path / "a.webp", [40] * 8, tons=tons)
    grade = tmp_path / "grade.webp"
    detalhes = tmp_path / "detalhes.webp"

    assert copias_animadas.gerar(origem, grade, (200, 300))
    assert copias_animadas.gerar(origem, detalhes, (280, 420))

    assert sum(_duracoes(grade)) == sum(_duracoes(detalhes)) == 40 * 8
    with Image.open(grade) as g, Image.open(detalhes) as d:
        assert g.size == (200, 300)
        assert d.size == (280, 420)


def test_origem_de_um_quadro_nao_grava(tmp_path):
    origem = tmp_path / "a.png"
    Image.new("RGBA", (8, 12)).save(origem)
    destino = tmp_path / "copia.webp"

    assert copias_animadas.gerar(origem, destino, (200, 300)) is False
    assert not destino.exists()


def test_origem_so_com_quadros_curtos_nao_grava(tmp_path):
    # Dois quadros de 16 ms fundem num só: não há o que animar.
    origem = _animada(tmp_path / "a.webp", [16, 16])
    destino = tmp_path / "copia.webp"

    assert copias_animadas.gerar(origem, destino, (200, 300)) is False
    assert not destino.exists()


def test_origem_ilegivel_levanta(tmp_path):
    origem = tmp_path / "a.webp"
    origem.write_bytes(b"isto nao e uma imagem")

    with pytest.raises(OSError):
        copias_animadas.gerar(origem, tmp_path / "copia.webp", (200, 300))


def test_nao_vigente_nao_grava(tmp_path):
    origem = _animada(tmp_path / "a.webp", [100, 100])
    destino = tmp_path / "copia.webp"

    resultado = copias_animadas.gerar(
        origem, destino, (200, 300), vigente=lambda: False
    )

    assert resultado is False
    assert not destino.exists()
    assert not (tmp_path / "copia.webp.tmp").exists()


def test_caminho_para(tmp_path):
    assert copias_animadas.caminho_para(
        shared.covers_dir / "g1.webp", (200, 300)
    ) == shared.capas_animadas_dir / "g1_200x300.webp"
    assert copias_animadas.caminho_para(
        tmp_path / "prev" / "9.webp", (200, 300)
    ) == tmp_path / "prev" / "9_200x300.webp"


def test_tamanhos_sao_inteiros():
    assert copias_animadas.tamanhos() == (
        (int(shared.display_size[0]), int(shared.display_size[1])),
        (int(shared.details_size[0]), int(shared.details_size[1])),
    )


# --- Fila de geração e invalidação -------------------------------------------


class _ExecutorManual:
    """Guarda os trabalhos; o teste decide quando rodá-los."""

    def __init__(self):
        self.fila = []

    def submit(self, funcao):
        self.fila.append(funcao)

    def rodar_tudo(self):
        while self.fila:
            self.fila.pop(0)()


@pytest.fixture
def fila(monkeypatch):
    executor = _ExecutorManual()
    monkeypatch.setattr(copias_animadas, "_executor", executor)
    # A entrega "na thread principal" vira uma chamada direta.
    monkeypatch.setattr(
        copias_animadas, "entregar_na_tela", lambda funcao, *args: funcao(*args)
    )
    yield executor
    # Nenhum estado da fila vaza para o teste seguinte.
    copias_animadas.cancelar_pendentes()


def _pedido(tmp_path, nome="g1", animada=True):
    origem = tmp_path / f"{nome}.webp"
    if animada:
        _animada(origem, [100, 100])
    else:
        Image.new("RGBA", (8, 12)).save(origem)
    return origem, tmp_path / f"{nome}_200x300.webp"


def test_pedido_repetido_nao_duplica(fila, tmp_path):
    origem, destino = _pedido(tmp_path)
    recebidos = []

    copias_animadas.pedir(origem, destino, (200, 300), recebidos.append)
    copias_animadas.pedir(origem, destino, (200, 300), recebidos.append)

    assert len(fila.fila) == 1
    fila.rodar_tudo()
    assert recebidos == ["pronta", "pronta"]
    assert destino.exists()


def test_pedido_depois_do_fim_gera_de_novo(fila, tmp_path):
    origem, destino = _pedido(tmp_path)

    copias_animadas.pedir(origem, destino, (200, 300), lambda _r: None)
    fila.rodar_tudo()
    copias_animadas.pedir(origem, destino, (200, 300), lambda _r: None)

    assert len(fila.fila) == 1


def test_capa_trocada_durante_a_geracao_nao_grava_a_antiga(fila, tmp_path):
    origem, destino = _pedido(tmp_path)
    recebidos = []
    copias_animadas.pedir(origem, destino, (200, 300), recebidos.append)

    copias_animadas.apagar("g1")
    fila.rodar_tudo()

    assert not destino.exists()
    assert list(tmp_path.glob("*.tmp")) == []
    assert recebidos == []


def test_capa_trocada_no_meio_do_trabalho_descarta_sem_avisar(
    fila, tmp_path, monkeypatch
):
    origem, destino = _pedido(tmp_path)
    recebidos = []
    original = copias_animadas.gerar

    def gerar_e_trocar(*args, **kwargs):
        # A capa muda quando o trabalho já está rodando.
        copias_animadas.apagar("g1")
        return original(*args, **kwargs)

    monkeypatch.setattr(copias_animadas, "gerar", gerar_e_trocar)
    copias_animadas.pedir(origem, destino, (200, 300), recebidos.append)
    fila.rodar_tudo()

    assert not destino.exists()
    assert list(tmp_path.glob("*.tmp")) == []
    assert recebidos == []


def test_pedido_novo_depois_de_apagar_nao_herda_o_trabalho_velho(fila, tmp_path):
    origem, destino = _pedido(tmp_path)
    antigos, novos = [], []
    copias_animadas.pedir(origem, destino, (200, 300), antigos.append)

    copias_animadas.apagar("g1")
    copias_animadas.pedir(origem, destino, (200, 300), novos.append)
    fila.rodar_tudo()

    assert antigos == []
    assert novos == ["pronta"]
    assert destino.exists()


def test_apagar_de_outro_jogo_nao_atrapalha(fila, tmp_path):
    origem, destino = _pedido(tmp_path)
    recebidos = []
    copias_animadas.pedir(origem, destino, (200, 300), recebidos.append)

    copias_animadas.apagar("g10")
    fila.rodar_tudo()

    assert recebidos == ["pronta"]


def test_cancelar_pendentes(fila, tmp_path):
    recebidos = []
    for nome in ("g1", "g2"):
        origem, destino = _pedido(tmp_path, nome)
        copias_animadas.pedir(origem, destino, (200, 300), recebidos.append)

    copias_animadas.cancelar_pendentes()
    fila.rodar_tudo()

    assert recebidos == []
    assert list(tmp_path.glob("*_200x300.webp")) == []


def test_pedido_depois_de_cancelar_roda(fila, tmp_path):
    origem, destino = _pedido(tmp_path)
    recebidos = []
    copias_animadas.pedir(origem, destino, (200, 300), lambda _r: None)

    copias_animadas.cancelar_pendentes()
    copias_animadas.pedir(origem, destino, (200, 300), recebidos.append)
    fila.rodar_tudo()

    assert recebidos == ["pronta"]


def test_origem_ilegivel_resulta_ilegivel(fila, tmp_path, caplog):
    origem = tmp_path / "g1.webp"
    origem.write_bytes(b"isto nao e uma imagem")
    recebidos = []

    copias_animadas.pedir(
        origem, tmp_path / "g1_200x300.webp", (200, 300), recebidos.append
    )
    fila.rodar_tudo()

    assert recebidos == ["ilegivel"]
    assert "g1.webp" in caplog.text


def test_origem_estatica_resulta_estatica(fila, tmp_path):
    origem, destino = _pedido(tmp_path, animada=False)
    recebidos = []

    copias_animadas.pedir(origem, destino, (200, 300), recebidos.append)
    fila.rodar_tudo()

    assert recebidos == ["estatica"]
    assert not destino.exists()


def test_gravacao_negada_resulta_falhou(fila, tmp_path, monkeypatch, caplog):
    origem, destino = _pedido(tmp_path)
    recebidos = []

    def negar(self, alvo):
        raise PermissionError("negado")

    monkeypatch.setattr(copias_animadas.Path, "replace", negar)
    copias_animadas.pedir(origem, destino, (200, 300), recebidos.append)
    fila.rodar_tudo()

    assert recebidos == ["falhou"]
    assert not destino.exists()
    assert list(tmp_path.glob("*.tmp")) == []
    assert "g1.webp" in caplog.text


def test_falha_ao_gravar_levanta_gravacao_falhou(tmp_path, monkeypatch):
    origem = _animada(tmp_path / "a.webp", [100, 100])
    destino = tmp_path / "copia.webp"

    def negar(self, alvo):
        raise PermissionError("negado")

    monkeypatch.setattr(copias_animadas.Path, "replace", negar)

    with pytest.raises(copias_animadas.GravacaoFalhou):
        copias_animadas.gerar(origem, destino, (200, 300))
    assert not destino.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_pasta_de_destino_impossivel_levanta_gravacao_falhou(tmp_path):
    origem = _animada(tmp_path / "a.webp", [100, 100])
    arquivo = tmp_path / "arquivo"
    arquivo.write_text("x")  # um arquivo no lugar da pasta

    with pytest.raises(copias_animadas.GravacaoFalhou):
        copias_animadas.gerar(origem, arquivo / "copia.webp", (200, 300))


def test_trabalho_que_falha_nao_trava_o_destino(fila, tmp_path):
    origem = tmp_path / "g1.webp"
    origem.write_bytes(b"isto nao e uma imagem")
    destino = tmp_path / "g1_200x300.webp"
    copias_animadas.pedir(origem, destino, (200, 300), lambda _r: None)
    fila.rodar_tudo()

    _animada(origem, [100, 100])
    recebidos = []
    copias_animadas.pedir(origem, destino, (200, 300), recebidos.append)
    fila.rodar_tudo()

    assert recebidos == ["pronta"]


def test_apagar_remove_todos_os_tamanhos():
    pasta = shared.capas_animadas_dir
    pasta.mkdir(parents=True, exist_ok=True)
    for nome in ("g1_200x300.webp", "g1_280x420.webp", "g10_200x300.webp"):
        (pasta / nome).write_bytes(b"x")

    copias_animadas.apagar("g1")

    assert [p.name for p in pasta.iterdir()] == ["g10_200x300.webp"]


def test_apagar_sem_pasta_nao_levanta():
    copias_animadas.apagar("g1")


# --- Troca atômica com a invalidação e encerramento --------------------------


def test_apagar_entre_a_checagem_e_a_troca_nao_deixa_a_copia_velha(
    fila, tmp_path, monkeypatch
):
    origem = _animada(tmp_path / "g1.webp", [100, 100])
    destino = shared.capas_animadas_dir / "g1_200x300.webp"
    recebidos = []
    trocar = copias_animadas.Path.replace
    apagador = []

    def trocar_com_apagar_em_paralelo(self, alvo):
        # A capa muda exatamente aqui: depois de vigente() dar True e antes do
        # rename. O apagar tem de esperar o rename acabar para depois apagá-lo.
        apagador.append(threading.Thread(target=copias_animadas.apagar, args=("g1",)))
        apagador[0].start()
        apagador[0].join(0.3)
        assert apagador[0].is_alive()  # preso na trava, não passou na frente
        return trocar(self, alvo)

    monkeypatch.setattr(copias_animadas.Path, "replace", trocar_com_apagar_em_paralelo)
    copias_animadas.pedir(origem, destino, (200, 300), recebidos.append)
    fila.rodar_tudo()
    apagador[0].join(5)

    assert not apagador[0].is_alive()
    assert not destino.exists()
    assert list(destino.parent.glob("*.tmp")) == []
    assert recebidos == []


def test_gerar_para_de_ler_quando_deixa_de_ser_vigente(tmp_path):
    origem = _animada(tmp_path / "a.webp", [100] * 20)
    destino = tmp_path / "copia.webp"
    chamadas = []

    def vigente():
        chamadas.append(1)
        return len(chamadas) <= 3

    assert copias_animadas.gerar(origem, destino, (200, 300), vigente) is False
    assert len(chamadas) == 4  # parou no 4º quadro, dos 20
    assert not destino.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_encerrar_nao_deixa_trabalho_pendente_rodar(fila, tmp_path, monkeypatch):
    origem, destino = _pedido(tmp_path)
    recebidos, geradas = [], []
    monkeypatch.setattr(
        copias_animadas, "gerar", lambda *a, **k: geradas.append(1) or True
    )
    copias_animadas.pedir(origem, destino, (200, 300), recebidos.append)

    copias_animadas.encerrar()
    fila.rodar_tudo()

    assert geradas == []
    assert recebidos == []


def test_encerrar_aborta_o_trabalho_em_andamento(fila, tmp_path, monkeypatch):
    origem = _animada(tmp_path / "g1.webp", [100] * 20)
    destino = tmp_path / "g1_200x300.webp"
    recebidos, chamadas = [], []
    original = copias_animadas.gerar

    def gerar_e_encerrar(origem, destino, tamanho, vigente):
        def contando():
            chamadas.append(1)
            if len(chamadas) == 3:
                copias_animadas.encerrar()  # o app fecha no meio da leitura
            return vigente()

        return original(origem, destino, tamanho, contando)

    monkeypatch.setattr(copias_animadas, "gerar", gerar_e_encerrar)
    copias_animadas.pedir(origem, destino, (200, 300), recebidos.append)
    fila.rodar_tudo()

    assert len(chamadas) == 3
    assert not destino.exists()
    assert list(tmp_path.glob("*.tmp")) == []
    assert recebidos == []


# --- As cópias acompanham a capa, o jogo e o backup ---------------------------


class _TocadorFalso:
    """Só registra o que o ``esquecer`` recebeu; nenhuma thread."""

    def __init__(self):
        self.eventos = []

    def esquecer(self, copia):
        self.eventos.append(("esquecer", copia))


@pytest.fixture
def tocador_falso(monkeypatch):
    falso = _TocadorFalso()
    monkeypatch.setattr(tocador_capas, "tocador", falso)
    return falso


def test_copia_pronta_e_esquecida_antes_de_avisar(fila, tmp_path, tocador_falso):
    origem, destino = _pedido(tmp_path)

    copias_animadas.pedir(
        origem, destino, (200, 300), lambda r: tocador_falso.eventos.append((r,))
    )
    fila.rodar_tudo()

    assert tocador_falso.eventos == [("esquecer", destino), ("pronta",)]


def test_copia_estatica_nao_e_esquecida(fila, tmp_path, tocador_falso):
    origem, destino = _pedido(tmp_path, animada=False)

    copias_animadas.pedir(origem, destino, (200, 300), lambda _r: None)
    fila.rodar_tudo()

    assert tocador_falso.eventos == []


def test_apagar_esquece_cada_copia_apagada(tocador_falso):
    pasta = shared.capas_animadas_dir
    pasta.mkdir(parents=True, exist_ok=True)
    for nome in ("g1_200x300.webp", "g1_280x420.webp", "g2_200x300.webp"):
        (pasta / nome).write_bytes(b"x")

    copias_animadas.apagar("g1")

    assert sorted(copia.name for _, copia in tocador_falso.eventos) == [
        "g1_200x300.webp",
        "g1_280x420.webp",
    ]


def test_apagar_nao_leva_as_copias_de_um_id_que_comeca_igual():
    pasta = shared.capas_animadas_dir
    pasta.mkdir(parents=True, exist_ok=True)
    for nome in ("x_200x300.webp", "x_280x420.webp", "x_y_200x300.webp", "x_y_280x420.webp"):
        (pasta / nome).write_bytes(b"x")

    copias_animadas.apagar("x")

    assert sorted(p.name for p in pasta.iterdir()) == [
        "x_y_200x300.webp",
        "x_y_280x420.webp",
    ]


def test_pares_de_migracao_troca_so_o_prefixo():
    pasta = shared.capas_animadas_dir
    pasta.mkdir(parents=True, exist_ok=True)
    for nome in ("velho_200x300.webp", "velho_280x420.webp", "velho_y_200x300.webp"):
        (pasta / nome).write_bytes(b"x")

    pares = copias_animadas.pares_de_migracao("velho", "novo")

    assert sorted(pares) == [
        (pasta / "velho_200x300.webp", pasta / "novo_200x300.webp"),
        (pasta / "velho_280x420.webp", pasta / "novo_280x420.webp"),
    ]


def test_pares_de_migracao_sem_pasta_ou_sem_copias():
    assert copias_animadas.pares_de_migracao("velho", "novo") == []


def test_limpar():
    pasta = shared.capas_animadas_dir
    pasta.mkdir(parents=True, exist_ok=True)
    nomes = [
        "g1_200x300.webp",
        "g1_280x420.webp",
        "g1_400x600.webp",  # tamanho que nenhuma tela usa mais
        "morto_200x300.webp",  # jogo que não existe mais
        "g1_200x300.webp.tmp",
        "g1_200x300.webp.0123abcd.tmp",  # o temporário que ``gerar`` grava
        "estranho.webp",  # não é do formato {id}_{L}x{A}
        "g1_axb.webp",
    ]
    for nome in nomes:
        (pasta / nome).write_bytes(b"x")

    copias_animadas.limpar({"g1"})

    assert sorted(p.name for p in pasta.iterdir()) == [
        "g1_200x300.webp",
        "g1_280x420.webp",
    ]


def test_limpar_respeita_ids_com_sublinhado():
    pasta = shared.capas_animadas_dir
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "steam_123_200x300.webp").write_bytes(b"x")

    copias_animadas.limpar({"steam_123"})

    assert [p.name for p in pasta.iterdir()] == ["steam_123_200x300.webp"]


def test_limpar_nao_apaga_pastas_nem_o_que_nao_e_dele(tmp_path):
    pasta = shared.capas_animadas_dir
    (pasta / "sub.tmp").mkdir(parents=True)
    (pasta / "sub.tmp" / "dentro.tmp").write_bytes(b"x")
    (pasta / "notas.txt").write_bytes(b"x")
    fora = tmp_path / "fora_200x300.webp"
    fora.write_bytes(b"x")
    fora_tmp = tmp_path / "fora.tmp"
    fora_tmp.write_bytes(b"x")

    copias_animadas.limpar(set())

    assert (pasta / "sub.tmp" / "dentro.tmp").exists()
    assert (pasta / "notas.txt").exists()
    assert fora.exists() and fora_tmp.exists()


def test_limpar_sem_pasta_nao_levanta():
    copias_animadas.limpar({"g1"})


def test_limpar_segue_adiante_quando_um_arquivo_resiste(monkeypatch):
    pasta = shared.capas_animadas_dir
    pasta.mkdir(parents=True, exist_ok=True)
    for nome in ("a_200x300.webp", "b_200x300.webp"):
        (pasta / nome).write_bytes(b"x")
    original = copias_animadas.Path.unlink

    def negar_a(self, *args, **kwargs):
        if self.name.startswith("a_"):
            raise PermissionError("preso")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(copias_animadas.Path, "unlink", negar_a)

    copias_animadas.limpar(set())

    assert [p.name for p in pasta.iterdir()] == ["a_200x300.webp"]
