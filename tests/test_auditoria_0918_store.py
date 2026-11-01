"""Regressões da auditoria de 18/09/2026 — grupo store (capas, papel de parede,
adoção, tela de edição)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from cartridges import shared
from cartridges.utils import session_wallpaper

# O conftest troca a `_AreaDeTrabalho` por uma guarda a cada teste; a classe de verdade é lida aqui, na importação.
_AREA_DE_TRABALHO = session_wallpaper._AreaDeTrabalho

OLD_ID = "shortcuts_1111111111111111"
NEW_ID = "shortcuts_2222222222222222"
LNK = "D:\\Atalhos\\Halo.lnk"


@pytest.fixture
def fitas_dir(tmp_path, monkeypatch):
    pasta = tmp_path / "fitas"
    pasta.mkdir()
    monkeypatch.setattr(shared, "fitas_dir", pasta, raising=False)
    return pasta


# region Store


def test_m13_adocao_leva_a_cor_da_fita(store, make_game, fitas_dir):
    store.add_game(make_game(game_id=OLD_ID, shortcut_path=LNK), {})
    (fitas_dir / f"{OLD_ID}.json").write_text('{"matiz": 10}', encoding="utf-8")

    store.adopt_legacy_game(make_game(game_id=NEW_ID, shortcut_path=LNK))

    assert (fitas_dir / f"{NEW_ID}.json").read_text(encoding="utf-8") == '{"matiz": 10}'
    assert not (fitas_dir / f"{OLD_ID}.json").exists()


def test_m9_cleanup_game_apaga_parede_e_fita(store, make_game, fitas_dir):
    game = make_game(game_id=OLD_ID)
    parede = shared.wallpapers_dir / f"{OLD_ID}.jpg"
    sidecar = shared.wallpapers_dir / f"{OLD_ID}.json"
    fita = fitas_dir / f"{OLD_ID}.json"
    for arquivo in (parede, sidecar, fita):
        arquivo.write_text("x", encoding="utf-8")

    store.cleanup_game(game)

    assert not parede.exists()
    assert not sidecar.exists()
    assert not fita.exists()


def test_cleanup_game_apaga_as_copias(store, make_game):
    game = make_game(game_id=OLD_ID)
    shared.capas_animadas_dir.mkdir(parents=True)
    for nome in (f"{OLD_ID}_200x300.webp", f"{OLD_ID}_280x420.webp", "outro_200x300.webp"):
        (shared.capas_animadas_dir / nome).write_bytes(b"c")

    store.cleanup_game(game)

    assert [p.name for p in shared.capas_animadas_dir.iterdir()] == ["outro_200x300.webp"]


def test_cleanup_game_apaga_a_capa_apng(store, make_game):
    game = make_game(game_id=OLD_ID)
    capa = shared.covers_dir / f"{OLD_ID}.apng"
    capa.parent.mkdir(parents=True, exist_ok=True)
    capa.write_bytes(b"c")

    store.cleanup_game(game)

    assert not capa.exists()


# endregion
# region Papel de parede


class _Winreg:
    HKEY_CURRENT_USER = object()

    def __init__(self, valores):
        self.valores = valores

    def OpenKey(self, _raiz, caminho):  # noqa: N802 - espelha a winreg
        if caminho not in self.valores:
            raise FileNotFoundError(caminho)
        return _Chave(caminho)

    def QueryValueEx(self, chave, nome):  # noqa: N802
        try:
            return self.valores[chave.caminho][nome], 4
        except KeyError as erro:
            raise FileNotFoundError(nome) from erro


class _Chave:
    def __init__(self, caminho):
        self.caminho = caminho

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


@pytest.mark.parametrize(
    "valores",
    [
        {session_wallpaper._SPOTLIGHT[0][0]: {"EnabledState": 1}},
        {session_wallpaper._SPOTLIGHT[1][0]: {"BackgroundType": 3}},
    ],
)
def test_b5_spotlight_conta_como_apresentacao(monkeypatch, valores):
    monkeypatch.setattr(session_wallpaper, "winreg", _Winreg(valores))
    area = SimpleNamespace(
        _estado=lambda *_: pytest.fail("com o Spotlight nem pergunta à COM"),
        _ponteiro=None,
    )

    assert _AREA_DE_TRABALHO.em_apresentacao(area) is True


def test_b5_sem_spotlight_nao_bloqueia(monkeypatch):
    monkeypatch.setattr(
        session_wallpaper,
        "winreg",
        _Winreg(
            {
                session_wallpaper._SPOTLIGHT[0][0]: {"EnabledState": 0},
                session_wallpaper._SPOTLIGHT[1][0]: {"BackgroundType": 0},
            }
        ),
    )
    assert session_wallpaper._spotlight_ligado() is False


def test_b7_sidecar_da_parede_nao_trunca_numa_queda(monkeypatch):
    sidecar = shared.wallpapers_dir / "jogo.json"
    sidecar.write_text('{"locked": true, "file": "jogo.png"}', encoding="utf-8")

    def cai_no_meio(self, texto, **_kwargs):
        with open(self, "w", encoding="utf-8") as arquivo:
            arquivo.write(texto[:5])
        raise OSError("disco cheio")

    monkeypatch.setattr(Path, "write_text", cai_no_meio)
    session_wallpaper._gravar_sidecar(
        "jogo", "Jogo", "jogo.png", session_wallpaper.Posicoes(), True
    )

    assert json.loads(sidecar.read_text(encoding="utf-8"))["locked"] is True
    assert [item.name for item in shared.wallpapers_dir.iterdir()] == ["jogo.json"]


def test_b7_pasta_que_nao_se_cria_so_loga(tmp_path, monkeypatch):
    bloqueio = tmp_path / "bloqueio"
    bloqueio.write_text("sou um arquivo", encoding="utf-8")
    monkeypatch.setattr(shared, "wallpapers_dir", bloqueio / "wallpapers")

    session_wallpaper._gravar_sidecar(
        "jogo", "Jogo", None, session_wallpaper.Posicoes(), True
    )


# endregion
# region Capas


def test_b9_bomba_nao_recursa_no_convert_cover(monkeypatch, tmp_path):
    from cartridges.utils.save_cover import convert_cover  # noqa: PLC0415

    arquivo = tmp_path / "enorme.png"
    Image.new("RGB", (100, 100)).save(arquivo)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    assert convert_cover(arquivo) is None


# endregion
