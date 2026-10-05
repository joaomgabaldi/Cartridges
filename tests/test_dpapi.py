"""O DPAPI do Windows, usado pela conta da Tuya e pela conta Microsoft."""

from cartridges.utils import dpapi


def test_cifra_e_decifra():
    protegido = dpapi.proteger(b"segredo")
    assert protegido is not None and b"segredo" not in protegido
    assert dpapi.abrir(protegido) == b"segredo"


def test_adulterado_nao_abre():
    protegido = bytearray(dpapi.proteger(b"segredo"))
    protegido[-1] ^= 0xFF
    assert dpapi.abrir(bytes(protegido)) is None


def test_lixo_e_vazio_nao_abrem():
    assert dpapi.abrir(b"") is None
    assert dpapi.abrir(b"nao e dpapi") is None
