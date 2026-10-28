# test_baixar_qt_sdk.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A extração do SDK só vale depois de terminar: o marcador decide, não os arquivos soltos."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import baixar_qt_sdk as sdk  # noqa: E402


def _falsa(chamadas, falhar_no=None):
    def extrair(pacote, destino):
        chamadas.append(pacote.name)
        destino.mkdir(parents=True, exist_ok=True)
        (destino / pacote.name).write_text("x")
        if pacote.name == falhar_no:
            raise OSError("interrompida")

    return extrair


def test_extracao_interrompida_recomeca_do_zero(tmp_path):
    qt = tmp_path / "qt"
    pacotes = [tmp_path / "a.7z", tmp_path / "b.7z"]
    chamadas = []
    with pytest.raises(OSError):
        sdk.extrair_qt(pacotes, qt, _falsa(chamadas, falhar_no="b.7z"))
    assert not (qt / sdk.MARCADOR).exists()
    chamadas.clear()
    sdk.extrair_qt(pacotes, qt, _falsa(chamadas))
    assert chamadas == ["a.7z", "b.7z"] and (qt / sdk.MARCADOR).exists()
    chamadas.clear()
    sdk.extrair_qt(pacotes, qt, _falsa(chamadas))
    assert chamadas == []
