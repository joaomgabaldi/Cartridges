"""Regressões da auditoria de 18/09/2026 — grupo store (capas, papel de parede,
adoção, tela de edição)."""

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from cartridges import shared
from cartridges.utils import session_wallpaper

OLD_ID = "shortcuts_1111111111111111"
NEW_ID = "shortcuts_2222222222222222"


@pytest.fixture
def fitas_dir(tmp_path, monkeypatch):
    pasta = tmp_path / "fitas"
    pasta.mkdir()
    monkeypatch.setattr(shared, "fitas_dir", pasta, raising=False)
    return pasta


def _join_daemons() -> None:
    for thread in list(threading.enumerate()):
        if thread is not threading.current_thread() and thread.daemon:
            thread.join(timeout=5)


# region Store


def test_m13_adocao_leva_a_cor_da_fita(store, make_game, fitas_dir):
    store.add_game(make_game(game_id=OLD_ID), {})
    (fitas_dir / f"{OLD_ID}.json").write_text('{"matiz": 10}', encoding="utf-8")

    store.adopt_legacy_game(make_game(game_id=NEW_ID), [OLD_ID])

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


def test_b14_rekey_leva_a_capa_ao_arquivo_novo(store, make_game, win, flush_idle):
    store.add_game(make_game(game_id=OLD_ID), {})
    trocas = []
    capa = SimpleNamespace(
        path=shared.covers_dir / f"{OLD_ID}.gif", new_cover=trocas.append
    )
    win.game_covers[OLD_ID] = capa

    store.adopt_legacy_game(make_game(game_id=NEW_ID), [OLD_ID])
    flush_idle()

    assert win.game_covers[NEW_ID] is capa
    assert trocas == [shared.covers_dir / f"{NEW_ID}.gif"]


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

    assert session_wallpaper._AreaDeTrabalho.em_apresentacao(area) is True


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


def _tela_com_arquivo(monkeypatch, arquivo):
    from cartridges import wallpaper_picker  # noqa: PLC0415

    monkeypatch.setattr(
        wallpaper_picker,
        "formatos_ligados",
        lambda: session_wallpaper.Formatos(None, (1920, 1080)),
    )
    return wallpaper_picker.WallpaperPicker(
        "Halo", lambda *_: None, lambda: None, arquivo=arquivo
    )


def test_b9_bomba_na_tela_de_parede_sai_do_spinner(
    win, monkeypatch, tmp_path, flush_idle
):
    arquivo = tmp_path / "enorme.png"
    Image.new("RGB", (100, 100)).save(arquivo)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    picker = _tela_com_arquivo(monkeypatch, arquivo)
    _join_daemons()
    flush_idle()

    assert picker.stack.get_visible_child_name() == "empty"
    picker.close()


def test_h7_falha_de_leitura_nao_diz_nenhum_encontrado(
    win, monkeypatch, tmp_path, flush_idle
):
    picker = _tela_com_arquivo(monkeypatch, tmp_path / "sumiu.png")
    _join_daemons()
    flush_idle()

    assert picker.stack.get_visible_child_name() == "empty"
    assert "Nenhum papel de parede" not in picker.status_page.get_title()
    picker.close()


# endregion
# region Capas


def test_b9_bomba_nao_recursa_no_convert_cover(monkeypatch, tmp_path):
    from cartridges.utils.save_cover import convert_cover  # noqa: PLC0415

    arquivo = tmp_path / "enorme.png"
    Image.new("RGB", (100, 100)).save(arquivo)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    assert convert_cover(arquivo) is None


def test_b13_quadros_da_capa_antiga_nao_entram(monkeypatch, tmp_path):
    from cartridges import game_cover  # noqa: PLC0415

    gif = tmp_path / "capa.gif"
    quadros = [Image.new("RGB", (8, 12), cor) for cor in ("red", "blue")]
    quadros[0].save(gif, save_all=True, append_images=quadros[1:], duration=50)

    fila = []
    monkeypatch.setattr(
        game_cover.threading,
        "Thread",
        lambda target, daemon: SimpleNamespace(start=target),
    )
    monkeypatch.setattr(
        game_cover.GLib,
        "idle_add",
        lambda funcao, *args: fila.append((funcao, args)),
    )

    capa = game_cover.GameCover(set(), gif)
    capa._begin_loading_animation()
    # A capa troca por outra do mesmo jogo: mesmo arquivo, imagem nova.
    capa.new_cover(gif)
    for funcao, args in fila:
        funcao(*args)

    assert capa._frames is None


def _stub_sgdb(store):
    from cartridges.store.managers.sgdb_manager import (  # noqa: PLC0415
        SgdbManager,
    )

    class StubSgdb:
        signals: set = set()

        def reset_cancellable(self):
            pass

        def collect_errors(self):
            return []

        def process_game(self, game, _data, callback):
            game.set_loading(-1)
            callback(self)

    store.managers[SgdbManager] = StubSgdb()


def _jogo():
    from cartridges.game import Game  # noqa: PLC0415

    return Game(
        {
            "game_id": "imported_1",
            "name": "Probe",
            "source": "imported",
            "executable": "x.exe",
            "hidden": False,
            "added": 0,
        }
    )


def test_b13_capa_que_nao_grava_nao_derruba_o_aplicar(
    real_window, store, monkeypatch, tmp_path
):
    from cartridges import details_dialog as modulo  # noqa: PLC0415

    _stub_sgdb(store)
    game = _jogo()
    dialog = modulo.DetailsDialog(game)
    capa = tmp_path / "nova.tiff"
    Image.new("RGB", (60, 90), "green").save(capa)
    dialog.set_cover_from_path(capa)
    dialog.name.set_text("Outro nome")

    def recusa(*_args):
        raise PermissionError(5, "Acesso negado")

    monkeypatch.setattr(modulo, "save_cover", recusa)
    dialog.apply_preferences()

    assert game.name == "Outro nome"
    assert store.get("imported_1") is game


def test_b10_temporarios_de_logo_e_capa_sao_apagados(
    real_window, store, tmp_path
):
    from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415

    _stub_sgdb(store)
    game = _jogo()
    dialog = DetailsDialog(game)
    logo = tmp_path / "logo_tmp.png"
    Image.new("RGBA", (40, 12)).save(logo)
    capa = tmp_path / "capa_tmp.tiff"
    Image.new("RGB", (60, 90), "green").save(capa)

    dialog.set_logo_from_picker(logo)
    dialog.set_cover_from_path(capa)
    dialog.apply_preferences()

    assert not logo.exists(), "o logo já foi copiado para a pasta dos logos"
    assert not capa.exists(), "a capa já foi copiada para a pasta das capas"


def test_b10_fechar_sem_aplicar_apaga_os_temporarios(real_window, tmp_path):
    from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415

    dialog = DetailsDialog(_jogo())
    logo = tmp_path / "logo_tmp.png"
    Image.new("RGBA", (40, 12)).save(logo)
    arquivo_do_usuario = tmp_path / "meu_logo.png"
    Image.new("RGBA", (40, 12)).save(arquivo_do_usuario)

    dialog.set_logo_from_picker(logo)
    dialog.set_logo_from_path(arquivo_do_usuario)
    assert not logo.exists(), "trocar de escolha apaga o temporário anterior"
    dialog.set_logo_from_picker(logo2 := tmp_path / "logo2_tmp.png")
    logo2.write_bytes(b"x")
    dialog.emit("closed")

    assert not logo2.exists(), "fechar sem aplicar apaga o temporário"

    assert arquivo_do_usuario.exists(), "arquivo do disco do usuário nunca se apaga"


# endregion
# region Busca de metadados


def test_b28_busca_que_volta_depois_de_fechar_nao_abre_nada(
    real_window, monkeypatch
):
    from cartridges import details_dialog as modulo  # noqa: PLC0415

    dialog = modulo.DetailsDialog(_jogo())
    dialog.emit("closed")
    abriu = []
    monkeypatch.setattr(modulo, "create_dialog", lambda *a, **k: abriu.append(a))
    monkeypatch.setattr(
        modulo, "SteamPicker", lambda *a, **k: abriu.append(a) or pytest.fail("abriu")
    )

    dialog._fetch_metadata_choose(None, "Probe")
    dialog._fetch_metadata_done(None, RuntimeError("rede"), "")

    assert abriu == []


def test_b29_escolha_da_steam_volta_o_spinner(real_window, monkeypatch):
    from cartridges import details_dialog as modulo  # noqa: PLC0415

    dialog = modulo.DetailsDialog(_jogo())
    monkeypatch.setattr(dialog, "_fetch_metadata_done", lambda *_: False)

    dialog._on_steam_picked("1", {"name": "Probe"})

    assert dialog.steam_fetch_stack.get_visible_child() is dialog.steam_fetch_spinner
    assert not dialog.apply_button.get_sensitive()


# endregion
