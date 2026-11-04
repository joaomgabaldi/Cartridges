# apoio_registro.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Apoio dos testes que mexem no registro de testes (HKCU, Software, CartridgesTestes).

Módulo à parte, e não o `conftest`: importar `tests.conftest` roda o arquivo
uma segunda vez (ver `apoio_edicao`).
"""

import winreg

# Referências guardadas na importação: um teste que troca `winreg.OpenKey` ainda
# está com o monkeypatch ativo quando a limpeza roda.
_abrir_chave, _enum_chave, _apagar = winreg.OpenKey, winreg.EnumKey, winreg.DeleteKey


def _apagar_chave(raiz: int, caminho: str) -> None:
    try:
        with _abrir_chave(raiz, caminho, 0, winreg.KEY_ALL_ACCESS) as chave:
            while True:
                try:
                    filha = _enum_chave(chave, 0)
                except OSError:
                    break
                _apagar_chave(raiz, f"{caminho}\\{filha}")
    except FileNotFoundError:
        return
    _apagar(raiz, caminho)
