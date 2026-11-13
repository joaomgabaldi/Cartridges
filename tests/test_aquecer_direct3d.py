# test_aquecer_direct3d.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O driver de vídeo é acordado numa thread, no começo do processo; nunca nos testes nem sem janela."""

import ctypes
from pathlib import Path

import pytest

from kyron import aquecer_direct3d
from kyron.aquecer_direct3d import _criar_e_soltar, aquecer


class _D3D11Falso:
    def __init__(self, resultado=0, levanta=None):
        self.chamadas = []
        self._resultado, self._levanta = resultado, levanta

    @property
    def D3D11CreateDevice(self):  # noqa: N802
        d3d = self

        class _Criar:
            restype = argtypes = None

            def __call__(self, *args):
                if d3d._levanta:
                    raise d3d._levanta
                d3d.chamadas.append(args)
                if d3d._resultado >= 0:
                    args[7]._obj.value, args[9]._obj.value = 0x1000, 0x2000  # o dispositivo e o contexto
                return d3d._resultado

        return _Criar()


def test_cria_o_dispositivo_na_placa_e_solta_o_contexto_e_o_dispositivo():
    d3d, soltos = _D3D11Falso(), []
    _criar_e_soltar(lambda nome: {"d3d11": d3d}[nome], lambda ponteiro: soltos.append(ponteiro.value))
    (chamada,) = d3d.chamadas
    assert chamada[:7] == (None, 1, None, 0, None, 0, 7)  # adaptador padrão, HARDWARE, D3D11_SDK_VERSION
    assert soltos == [0x2000, 0x1000]


def test_criacao_recusada_nao_solta_nada():
    soltos = []
    _criar_e_soltar(lambda _nome: _D3D11Falso(resultado=-2005270524), soltos.append)  # DXGI_ERROR_UNSUPPORTED
    assert soltos == []


def test_falha_ao_carregar_ou_ao_criar_nao_levanta():
    def sem_dll(_nome):
        raise OSError("d3d11.dll não encontrada")

    _criar_e_soltar(sem_dll)
    _criar_e_soltar(lambda _nome: _D3D11Falso(levanta=OSError("violação de acesso")))


def test_soltar_ignora_o_ponteiro_nulo():
    aquecer_direct3d._soltar(ctypes.c_void_p())


def test_na_placa_de_verdade_os_dois_ponteiros_sao_soltos():
    """A chamada real: um tipo errado ou a posição errada do `Release` cairia no `except` e o aquecimento viraria nada, em silêncio."""
    soltos = []

    def espiao(ponteiro):
        soltos.append(ponteiro.value)
        aquecer_direct3d._soltar(ponteiro)

    _criar_e_soltar(ctypes.WinDLL, espiao)
    if not soltos:
        pytest.skip("sem placa Direct3D 11 nesta máquina")
    assert len(soltos) == 2 and all(soltos)


def test_aquecer_roda_numa_thread_e_volta_na_hora():
    d3d = _D3D11Falso(resultado=-1)
    thread = aquecer(["kyron"], ambiente={}, carregar=lambda _nome: d3d)
    assert thread is not None and thread.daemon and thread.name == "aquecer-direct3d"
    thread.join(5)
    assert len(d3d.chamadas) == 1


def test_nao_aquece_sem_janela_nem_fora_da_placa():
    def recusa(_nome):
        raise AssertionError("não era para carregar a d3d11")

    assert aquecer(["kyron", "--sair-apos-carregar"], ambiente={}, carregar=recusa) is None
    assert aquecer(["kyron"], ambiente={"QT_QPA_PLATFORM": "offscreen"}, carregar=recusa) is None
    assert aquecer(["kyron"], ambiente={"QT_QUICK_BACKEND": "software"}, carregar=recusa) is None


def test_o_main_aquece_antes_de_importar_o_app():
    linhas = (Path(aquecer_direct3d.__file__).parent / "__main__.py").read_text(encoding="utf-8").splitlines()
    codigo = [linha.split("#")[0].strip() for linha in linhas]
    assert codigo.index("aquecer(sys.argv)") < codigo.index("from kyron.app import main")
