# test_auditoria_0923_resto.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regressões da auditoria de 23/09."""

from cartridges import shared


def test_m6_credencial_recusada_nao_e_salva(monkeypatch):
    from cartridges import fita_wizard  # noqa: PLC0415
    from cartridges.utils import tuya_conta  # noqa: PLC0415

    salvas = []
    monkeypatch.setattr(tuya_conta, "salvar", salvas.append)
    nuvem = type("Nuvem", (), {"token": None, "error": {"Error": "token"}})()
    assert fita_wizard.credencial_valida(nuvem, []) is False
    nuvem_boa = type("Nuvem", (), {"token": "abc", "error": None})()
    assert fita_wizard.credencial_valida(nuvem_boa, []) is True


def test_m9_webp_nao_e_candidato_utilizavel():
    from cartridges.utils import game_logo  # noqa: PLC0415

    webp = {"url": "https://x/logo.webp", "width": 800, "height": 300, "mime": "image/webp"}
    png = {"url": "https://x/logo.png", "width": 800, "height": 300, "mime": "image/png"}
    assert game_logo.pick_logo([webp, png]) is png


def test_b17_refresh_nao_tem_mais_dialogo_de_erro():
    from cartridges.metadata_refresh import MetadataRefresh  # noqa: PLC0415

    assert not hasattr(MetadataRefresh, "_show_error")


def test_b29_instalador_sem_gnome():
    from pathlib import Path  # noqa: PLC0415

    texto = (Path(__file__).parent.parent / "build-aux/windows/Cartridges.iss.in").read_text(
        encoding="utf-8"
    )
    assert "apps.gnome.org" not in texto
    assert '#define MyAppPublisher "joaomgabaldi"' in texto



def test_b24_confirmacao_de_patch_diz_o_que_aconteceu():
    from pathlib import Path  # noqa: PLC0415

    texto = (Path(__file__).parent.parent / "cartridges/qml/PaginaDoJogo.qml").read_text(encoding="utf-8")
    assert 'titulo: "Você instalou a atualização?"' in texto
    assert "A página da atualização foi aberta no navegador. Confirme após instalá-la para ocultar o aviso." in texto
    assert 'rotuloCancelar: "Ainda não"' in texto
    assert 'rotuloConfirmar: "Já instalei"' in texto
