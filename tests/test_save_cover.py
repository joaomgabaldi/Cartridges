# test_save_cover.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A troca de capa não pode destruir a atual antes da nova existir.

Auditoria 26/08, M8: a ordem antiga — apagar toda forma existente e então
copiar — deixava a capa ausente ou truncada num disco cheio ou numa queda, e
uma truncada passa no ``is_file()`` do SGDB, que então nunca mais re-busca.
"""

from types import SimpleNamespace

import pytest
from PIL import Image

from cartridges import shared
from cartridges.utils.save_cover import save_cover


@pytest.fixture(autouse=True)
def stub_win(monkeypatch):
    """save_cover consulta shared.win.game_covers no fim; nos testes não há
    janela, e um stub vazio é exatamente o caso "jogo sem widget na grade"."""
    monkeypatch.setattr(shared, "win", SimpleNamespace(game_covers={}))


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

    assert [p.name for p in shared.capas_animadas_dir.iterdir()] == ["g2_200x300.webp"]


def test_remover_capa_apaga_as_copias():
    _copias("g1_200x300.webp", "g1_280x420.webp", "g2_200x300.webp")

    save_cover("g1", None)

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


def test_capa_animada_nova_com_a_opcao_ligada_prepara_as_copias(
    tmp_path, schema, entregas
):
    from cartridges.utils import copias_animadas

    schema.set_boolean("cover-autoplay", True)

    save_cover("g1", _gif(tmp_path / "nova.gif"))

    # Pela mesma entrega do ``apagar``: a ordem entre as duas é a das chamadas.
    assert entregas == [
        (copias_animadas.preparar, ([("g1", shared.covers_dir / "g1.gif")],))
    ]


def test_capa_animada_nova_com_a_opcao_desligada_nao_prepara(
    tmp_path, schema, entregas
):
    save_cover("g1", _gif(tmp_path / "nova.gif"))

    assert entregas == []


def test_capa_estatica_ou_removida_nao_prepara(tmp_path, schema, entregas):
    schema.set_boolean("cover-autoplay", True)

    save_cover("g1", make_image(tmp_path / "nova.tiff"))
    save_cover("g1", None)

    assert entregas == []


# region Montagem da capa a partir de uma imagem qualquer


def test_imagem_mais_alta_que_a_capa_e_esticada(tmp_path):
    from cartridges.utils.save_cover import composite_cover  # noqa: PLC0415

    pixbuf = composite_cover(make_image_sized(tmp_path / "alta.png", (400, 900)))

    assert (pixbuf.get_width(), pixbuf.get_height()) == (400, 900)


def test_imagem_pouco_mais_larga_ainda_e_esticada(tmp_path):
    # 600x800: esticar para 600x900 distorce 11 %, dentro dos 12 % tolerados.
    from cartridges.utils.save_cover import composite_cover  # noqa: PLC0415

    pixbuf = composite_cover(make_image_sized(tmp_path / "quase.png", (600, 800)))

    assert (pixbuf.get_width(), pixbuf.get_height()) == (600, 800)


def test_imagem_larga_vai_ao_centro_sobre_o_proprio_desfoque(tmp_path):
    from cartridges.utils.save_cover import composite_cover  # noqa: PLC0415

    pixbuf = composite_cover(make_image_sized(tmp_path / "larga.png", (1200, 400)))

    assert (pixbuf.get_width(), pixbuf.get_height()) == shared.image_size
    pixels = pixbuf.get_pixels()
    meio = (pixbuf.get_height() // 2) * pixbuf.get_rowstride() + (pixbuf.get_width() // 2) * pixbuf.get_n_channels()
    assert tuple(pixels[meio : meio + 3]) == (0, 0, 255)


def test_arquivo_ilegivel_levanta(tmp_path):
    from cartridges.utils.save_cover import UnreadableCoverError, composite_cover  # noqa: PLC0415

    ruim = tmp_path / "ruim.png"
    ruim.write_bytes(b"nada")

    with pytest.raises(UnreadableCoverError):
        composite_cover(ruim)


def make_image_sized(path, size):
    Image.new("RGB", size, "blue").save(path)
    return path
