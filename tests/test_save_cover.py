# test_save_cover.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A troca de capa não pode destruir a atual antes da nova existir.

Auditoria 26/08, M8: a ordem antiga — apagar toda forma existente e então
copiar — deixava a capa ausente ou truncada num disco cheio ou numa queda, e
uma truncada passa no ``is_file()`` do SGDB, que então nunca mais re-busca.
"""

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, UnidentifiedImageError
from PySide6.QtCore import QEventLoop, QTimer

from cartridges import shared
from cartridges.utils.save_cover import save_cover


def make_image(path, color="blue"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (60, 90), color).save(path)
    return path


def test_a_failed_copy_keeps_the_current_cover(tmp_path):
    current = make_image(shared.covers_dir / "g1.tiff", "red")
    before = current.read_bytes()

    with pytest.raises(FileNotFoundError):
        save_cover("g1", tmp_path / "inexistente.tiff")

    assert current.read_bytes() == before, "a capa atual sobrevive à cópia falhada"
    assert list(shared.covers_dir.glob("*.tmp")) == []


def test_a_replaced_cover_drops_the_other_formats_afterwards(tmp_path):
    old_gif = make_image(shared.covers_dir / "g1.gif")
    new = make_image(tmp_path / "novo.tiff", "green")

    save_cover("g1", new)

    assert (shared.covers_dir / "g1.tiff").is_file()
    assert not old_gif.exists(), "a forma antiga sai depois que a nova está no lugar"
    assert list(shared.covers_dir.glob("*.tmp")) == []


def test_passing_none_still_clears_every_format():
    make_image(shared.covers_dir / "g1.tiff")

    save_cover("g1", None)

    assert not (shared.covers_dir / "g1.tiff").exists()


def _copias(*nomes):
    shared.capas_animadas_dir.mkdir(parents=True, exist_ok=True)
    for nome in nomes:
        (shared.capas_animadas_dir / nome).write_bytes(b"x")


def test_salvar_capa_apaga_as_copias(tmp_path):
    _copias("g1_200x300.webp", "g1_280x420.webp", "g2_200x300.webp")
    nova = make_image(tmp_path / "novo.tiff", "green")

    save_cover("g1", nova)
    _rodar()  # a troca das cópias corre na thread principal

    assert [p.name for p in shared.capas_animadas_dir.iterdir()] == ["g2_200x300.webp"]


def test_remover_capa_apaga_as_copias():
    _copias("g1_200x300.webp", "g1_280x420.webp", "g2_200x300.webp")

    save_cover("g1", None)
    _rodar()

    assert [p.name for p in shared.capas_animadas_dir.iterdir()] == ["g2_200x300.webp"]


@pytest.fixture
def entregas(monkeypatch):
    """Troca a entrega à thread principal por um registro."""
    from cartridges.utils import save_cover as modulo

    registro = []
    monkeypatch.setattr(
        modulo, "entregar_na_tela", lambda func, *args: registro.append((func, args))
    )
    return registro


def _gif(caminho):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    quadros = [Image.new("RGB", (60, 90), cor) for cor in ("red", "blue")]
    quadros[0].save(caminho, save_all=True, append_images=quadros[1:], duration=100)
    return caminho


def test_capa_animada_nova_prepara_as_copias(tmp_path, schema, entregas):
    """Com o autoplay desligado (o padrão) também: quem liga a opção depois
    encontra as cópias prontas."""
    from cartridges.utils import save_cover as modulo

    nova = _gif(tmp_path / "nova.gif")
    save_cover("g1", nova)

    # Apagar, adotar e preparar numa entrega só, na thread principal.
    assert entregas == [(modulo._refazer_copias, ("g1", shared.covers_dir / "g1.gif", nova))]


def test_capa_provisoria_entrega_as_copias_que_ja_tem(tmp_path, schema, entregas, monkeypatch):
    """As cópias que a prévia da edição já gerou (as de um vídeo saem junto com
    ele) passam a ser as do jogo, e o ``preparar`` não as gera de novo."""
    from cartridges.utils import copias_animadas

    provisoria = _gif(tmp_path / "provisoria.gif")
    grade, detalhes = copias_animadas.tamanhos()
    copias_animadas.caminho_para(provisoria, grade).write_bytes(b"grade")
    monkeypatch.setattr(copias_animadas, "preparar", lambda *_a: None)  # só a adoção é o assunto

    save_cover("g1", provisoria)
    for func, args in entregas:
        func(*args)

    capa = shared.covers_dir / "g1.gif"
    assert copias_animadas.caminho_para(capa, grade).read_bytes() == b"grade"
    assert not copias_animadas.caminho_para(capa, detalhes).exists()
    assert list(shared.capas_animadas_dir.glob("*.tmp")) == []


def _apng(caminho):
    """Um PNG animado (APNG) de dois quadros, como os do SteamGridDB."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    quadros = [Image.new("RGB", (60, 90), cor) for cor in ("red", "blue")]
    quadros[0].save(
        caminho, "PNG", save_all=True, append_images=quadros[1:], duration=100
    )
    return caminho


def test_apng_vira_apng_com_todos_os_quadros(tmp_path):
    from cartridges.utils.save_cover import convert_cover

    origem = _apng(tmp_path / "capa.png")

    convertida = convert_cover(origem)

    assert convertida.suffix == ".apng"
    assert convertida.read_bytes() == origem.read_bytes()


def test_png_de_um_quadro_continua_tiff(tmp_path):
    from cartridges.utils.save_cover import convert_cover

    assert convert_cover(make_image(tmp_path / "capa.png")).suffix == ".tiff"


def test_capa_apng_prepara_as_copias(tmp_path, schema, entregas):
    from cartridges.utils import save_cover as modulo

    nova = _apng(tmp_path / "nova.apng")
    save_cover("g1", nova)

    assert entregas == [(modulo._refazer_copias, ("g1", shared.covers_dir / "g1.apng", nova))]


def test_trocar_apng_por_gif_nao_deixa_as_duas(tmp_path, schema, entregas):
    save_cover("g1", _apng(tmp_path / "a.apng"))
    save_cover("g1", _gif(tmp_path / "b.gif"))

    assert sorted(p.name for p in shared.covers_dir.glob("g1.*")) == ["g1.gif"]


def test_pedido_no_meio_da_troca_nao_deixa_copia_da_capa_velha(tmp_path, monkeypatch):
    """A capa na tela ainda é a velha até o ``new_cover`` (por idle) e pode pedir
    a cópia durante a troca: o que for gerado da velha não sobrevive a ela."""
    from cartridges.utils import copias_animadas
    from cartridges.utils import save_cover as modulo

    def animada(caminho, cor):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        quadros = [Image.new("RGB", (60, 90), c) for c in (cor, "black")]
        quadros[0].save(caminho, save_all=True, append_images=quadros[1:], duration=100)
        return caminho

    velha = animada(shared.covers_dir / "g1.gif", "red")
    nova = animada(tmp_path / "nova.gif", "lime")
    fila, avisos, recebidos = [], [], []
    monkeypatch.setattr(copias_animadas, "_executor", SimpleNamespace(submit=fila.append))
    monkeypatch.setattr(
        copias_animadas, "entregar_na_tela", lambda func, *a: avisos.append((func, a))
    )
    grade, detalhes = copias_animadas.tamanhos()
    copias = [copias_animadas.caminho_para(velha, t) for t in (grade, detalhes)]
    copiar = modulo.copyfile

    def copiar_com_pedidos(origem, destino):
        # Um pedido da capa velha gera inteiro antes da cópia; outro fica na fila.
        copias_animadas.pedir(velha, copias[0], grade, recebidos.append)
        fila.pop(0)()
        copias_animadas.pedir(velha, copias[1], detalhes, recebidos.append)
        return copiar(origem, destino)

    monkeypatch.setattr(modulo, "copyfile", copiar_com_pedidos)
    save_cover("g1", nova)
    _rodar()  # a troca das cópias (apagar) corre na thread principal
    while fila:
        fila.pop(0)()
    for func, args in avisos:
        func(*args)

    # As cópias que existem agora são as da capa nova (verde), geradas depois do ``apagar``.
    assert all(c.exists() for c in copias)
    for c in copias:
        with Image.open(c) as copia:
            r, g, _b = copia.convert("RGB").getpixel((copia.width // 2, copia.height // 2))
        assert g > r
    # Só o que terminou antes da troca avisou; o pendente foi invalidado.
    assert recebidos == ["pronta"]


def test_capa_estatica_ou_removida_nao_prepara(tmp_path, schema, entregas):
    save_cover("g1", make_image(tmp_path / "nova.tiff"))
    save_cover("g1", None)

    # Só apagar as cópias velhas: nenhuma capa animada para preparar.
    assert [args[1] for _func, args in entregas] == [shared.covers_dir / "g1.tiff", None]


# region Montagem da capa a partir de uma imagem qualquer


def test_imagem_mais_alta_que_a_capa_e_esticada(tmp_path):
    from cartridges.utils.save_cover import composite_cover  # noqa: PLC0415

    imagem = composite_cover(make_image_sized(tmp_path / "alta.png", (400, 900)))

    assert imagem.size == (400, 900)


def test_imagem_pouco_mais_larga_ainda_e_esticada(tmp_path):
    # 600x800: esticar para 600x900 distorce 11 %, dentro dos 12 % tolerados.
    from cartridges.utils.save_cover import composite_cover  # noqa: PLC0415

    imagem = composite_cover(make_image_sized(tmp_path / "quase.png", (600, 800)))

    assert imagem.size == (600, 800)


def test_imagem_larga_vai_ao_centro_sobre_o_proprio_desfoque(tmp_path):
    from cartridges.utils.save_cover import composite_cover  # noqa: PLC0415

    imagem = composite_cover(make_image_sized(tmp_path / "larga.png", (1200, 400)))

    assert imagem.size == shared.image_size
    assert imagem.convert("RGB").getpixel((imagem.width // 2, imagem.height // 2)) == (0, 0, 255)


def test_arquivo_ilegivel_levanta(tmp_path):
    from cartridges.utils.save_cover import UnreadableCoverError, composite_cover  # noqa: PLC0415

    ruim = tmp_path / "ruim.png"
    ruim.write_bytes(b"nada")

    with pytest.raises(UnreadableCoverError):
        composite_cover(ruim)


def make_image_sized(path, size):
    Image.new("RGB", size, "blue").save(path)
    return path


# region Sem temporário, sem GLib e a capa nova na grade


def test_convert_cover_nao_deixa_temporario_se_o_pillow_falha(tmp_path, monkeypatch):
    """O Pillow falha no meio da gravação: nem capa pela metade nem ``.tmp`` sobram."""
    from cartridges.utils.save_cover import convert_cover  # noqa: PLC0415

    capa = make_image(tmp_path / "capa.png")
    temporarios = tmp_path / "temporarios"
    temporarios.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(temporarios))

    def salvar_pela_metade(self, destino, *_args, **_kwargs):
        open(destino, "wb").write(b"metade")  # noqa: SIM115
        raise OSError("disco cheio")

    monkeypatch.setattr(Image.Image, "save", salvar_pela_metade)

    assert convert_cover(capa) is None
    assert list(temporarios.iterdir()) == []


def test_convert_cover_nao_deixa_temporario_numa_falha_inesperada(tmp_path, monkeypatch):
    from cartridges.utils.save_cover import convert_cover  # noqa: PLC0415

    capa = make_image(tmp_path / "capa.png")
    temporarios = tmp_path / "temporarios"
    temporarios.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(temporarios))

    def salvar_e_quebrar(self, destino, *_args, **_kwargs):  # noqa: ARG001
        open(destino, "wb").write(b"metade")  # noqa: SIM115
        raise KeyError("formato")

    monkeypatch.setattr(Image.Image, "save", salvar_e_quebrar)

    with pytest.raises(KeyError):
        convert_cover(capa)
    assert list(temporarios.iterdir()) == []


def test_save_cover_com_destino_que_falha_nao_deixa_tmp(tmp_path, monkeypatch):
    from cartridges.utils import save_cover as modulo  # noqa: PLC0415

    def copiar_pela_metade(origem, destino):  # noqa: ARG001
        destino.write_bytes(b"metade")
        raise OSError("disco cheio")

    monkeypatch.setattr(modulo, "copyfile", copiar_pela_metade)

    with pytest.raises(OSError):
        save_cover("g1", make_image(tmp_path / "nova.tiff"))

    assert list(shared.covers_dir.iterdir()) == []


def _rodar(limite=0.1):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(10, laco.quit)
        laco.exec()


def test_save_cover_atualiza_o_jogo_na_principal(tmp_path, store, make_game):
    """A grade troca a capa porque o jogo avisa que mudou, e isso só na thread principal."""
    import threading  # noqa: PLC0415

    _rodar()  # as entregas que os outros testes deixaram na fila
    jogo = make_game(game_id="g1")
    store.add_game(jogo, {})
    jogo.updates = 0
    nova = make_image(tmp_path / "nova.tiff", "green")

    linha = threading.Thread(target=save_cover, args=("g1", nova))
    linha.start()
    linha.join()
    assert jogo.updates == 0  # enfileirado, não chamado da thread do trabalho
    _rodar()

    assert jogo.updates == 1


def test_save_cover_de_jogo_fora_da_store_nao_quebra(tmp_path):
    save_cover("fantasma", make_image(tmp_path / "nova.tiff"))
    _rodar()
    assert (shared.covers_dir / "fantasma.tiff").is_file()


def test_convert_cover_sem_redimensionar_devolve_o_original(tmp_path):
    from cartridges.utils.save_cover import convert_cover  # noqa: PLC0415

    origem = make_image(tmp_path / "capa.png")

    assert convert_cover(origem, resize=False) == origem


def test_convert_cover_ilegivel_devolve_none(tmp_path):
    from cartridges.utils.save_cover import convert_cover  # noqa: PLC0415

    ruim = tmp_path / "ruim.png"
    ruim.write_bytes(b"nada")

    assert convert_cover(ruim) is None
    assert convert_cover(None) is None


def test_formato_que_o_pillow_nao_le_mas_o_qt_le_vira_capa(tmp_path, monkeypatch):
    """B02: o `Gdk.Texture` da `main` vira o `QImageReader`; sem resize, a TIFF do Qt é a própria saída."""
    from cartridges.utils import save_cover as modulo  # noqa: PLC0415

    origem = tmp_path / "so_o_qt.xyz"  # PNG por dentro; a extensão não é do Pillow, e ele "não o lê"
    Image.new("RGB", (300, 200), "blue").save(origem, format="PNG")
    abrir = Image.open

    def sem_png(fp, *args, **kwargs):
        if Path(fp).suffix == ".xyz":
            raise UnidentifiedImageError(fp)
        return abrir(fp, *args, **kwargs)

    monkeypatch.setattr(modulo.Image, "open", sem_png)

    reduzida = modulo.convert_cover(origem)
    assert reduzida is not None and reduzida.suffix == ".tiff"
    with Image.open(reduzida) as imagem:
        assert imagem.size == shared.image_size
    reduzida.unlink()

    inteira = modulo.convert_cover(origem, resize=False)
    assert inteira is not None and inteira != origem
    with Image.open(inteira) as imagem:
        assert imagem.size == (300, 200)
    inteira.unlink()


def test_modulos_desta_tarefa_nao_importam_gi():
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    modulos = [
        "cartridges.utils.save_cover",
        "cartridges.utils.steamgriddb",
        "cartridges.utils.passada_agendada",
        "cartridges.utils.hltb_backfill",
        "cartridges.modelos.tarefas",
        "cartridges.store.managers.sgdb_manager",
        "cartridges.store.managers.exibicao_manager",
    ]
    codigo = (
        "import builtins, sys\n"
        "builtins._ = lambda m: m\n"
        f"import {', '.join(modulos)}\n"
        "print([m for m in sys.modules if m == 'gi' or m.startswith('gi.')])\n"
    )
    saida = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, check=False)
    assert saida.stdout.strip() == "[]", saida.stderr
