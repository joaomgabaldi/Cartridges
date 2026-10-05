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


def test_nenhuma_chamada_abre_dialogo(monkeypatch):
    """O DPAPI nunca pode abrir uma janela de confirmação: `CRYPTPROTECT_UI_FORBIDDEN`
    (0x1) vai nas duas chamadas."""
    from types import SimpleNamespace  # noqa: PLC0415

    flags = {}

    def falsa(nome):
        def chamar(_entrada, _descricao, _entropia, _reservado, _prompt, flag, _saida):
            flags[nome] = flag
            return False

        return chamar

    monkeypatch.setattr(
        dpapi,
        "_crypt32",
        SimpleNamespace(
            CryptProtectData=falsa("proteger"), CryptUnprotectData=falsa("abrir")
        ),
    )
    assert dpapi.proteger(b"segredo") is None
    assert dpapi.abrir(b"segredo") is None
    assert flags == {"proteger": 0x1, "abrir": 0x1}
