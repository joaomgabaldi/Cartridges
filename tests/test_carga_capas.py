# test_carga_capas.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""`capas_do_disco`: na carga, as capas saem de uma listagem só da pasta, sem um `is_file` por sufixo."""

import threading
from pathlib import Path

from kyron.jogo import Jogo, capas_do_disco


def _jogo() -> Jogo:
    return Jogo({"game_id": "shortcuts_1", "source": "shortcuts", "name": "Probe", "executable": "x.exe", "added": 0})


def test_dentro_do_indice_a_capa_sai_sem_is_file(app_dirs, monkeypatch):
    tiff = app_dirs.covers / "shortcuts_1.tiff"
    tiff.write_bytes(b"x")
    chamadas = []
    monkeypatch.setattr(Path, "is_file", lambda self: chamadas.append(self) or False)

    with capas_do_disco():
        assert _jogo().get_cover_path() == tiff

    assert chamadas == []


def test_indice_respeita_a_precedencia(app_dirs):
    (app_dirs.covers / "shortcuts_1.tiff").write_bytes(b"x")
    gif = app_dirs.covers / "shortcuts_1.gif"
    gif.write_bytes(b"x")

    with capas_do_disco():
        assert _jogo().get_cover_path() == gif


def test_indice_sem_capa_devolve_none_e_pasta_ausente_vale_listagem_vazia(app_dirs):
    with capas_do_disco():
        assert _jogo().get_cover_path() is None
    app_dirs.covers.rmdir()
    with capas_do_disco():
        assert _jogo().get_cover_path() is None


def test_indice_nao_vale_em_outra_thread(app_dirs):
    tiff = app_dirs.covers / "shortcuts_1.tiff"
    resultado = []

    def outra():
        tiff.write_bytes(b"x")  # criada depois de o índice ser tirado
        resultado.append(_jogo().get_cover_path())

    with capas_do_disco():
        thread = threading.Thread(target=outra)
        thread.start()
        thread.join()
        assert _jogo().get_cover_path() is None  # esta thread ainda vê a listagem antiga

    assert resultado == [tiff]


def test_fora_do_indice_nada_muda(app_dirs):
    with capas_do_disco():
        pass
    tiff = app_dirs.covers / "shortcuts_1.tiff"
    tiff.write_bytes(b"x")
    assert _jogo().get_cover_path() == tiff


def test_capa_da_sessao_continua_valendo_no_indice(app_dirs, tmp_path):
    (app_dirs.covers / "shortcuts_1.tiff").write_bytes(b"x")
    provisoria = tmp_path / "provisoria.tiff"
    provisoria.write_bytes(b"y")
    jogo = _jogo()
    jogo.capa_da_sessao = provisoria

    with capas_do_disco():
        assert jogo.get_cover_path() == provisoria


def test_indice_ignora_maiusculas_como_o_is_file_do_windows(app_dirs):
    (app_dirs.covers / "Shortcuts_1.TIFF").write_bytes(b"x")

    with capas_do_disco():
        # O caminho devolvido é o montado a partir do id, não o nome do disco.
        assert _jogo().get_cover_path() == app_dirs.covers / "shortcuts_1.tiff"
