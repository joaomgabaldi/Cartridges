# redefinir.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Redefinir Cartridges: o app volta ao estado de recém-instalado.

Preferências só agenda (`agendar`) e reinicia o app; a limpeza roda na abertura
seguinte (`aplicar_pendente`), antes do log em arquivo, que no Windows trava a
própria pasta, e antes de qualquer leitura de dados. Sai tudo da pasta do app e
todas as configurações voltam ao padrão. Uma pasta dos saves escolhida fora da
pasta do app é só esquecida: ela pode ser a raiz do OneDrive ou dos Documentos.
"""

import shutil
from contextlib import suppress
from typing import Optional

from gi.repository import Gio

from cartridges import shared
from cartridges.utils.backup import _apagar_pasta, _irma

_AGENDADO = "redefinir"

# Desfazem o que o app mudou fora dele (fitas e papel de parede do Windows) quando
# o fechamento não conseguiu; zerar deixaria a mudança para sempre. O balde do
# limitador da Steam é o que segura as requisições depois de uma rajada.
_FICAM = frozenset({"fita-estado-anterior", "session-wallpaper-saved", "steam-limiter-tokens-history"})

# O erro da última `aplicar_pendente`, para a abertura registrar no log (que ainda
# não existia) e avisar depois de a janela abrir. Fora o caso, ``None``.
falha: Optional[OSError] = None  # pylint: disable=invalid-name


def agendar() -> None:
    shared.app_dir.mkdir(parents=True, exist_ok=True)
    (shared.app_dir / _AGENDADO).touch()


def ha_pendente() -> bool:
    return (shared.app_dir / _AGENDADO).is_file()


def aplicar_pendente() -> Optional[bool]:
    """``None``: nada agendado. ``True``: redefinido. ``False``: falhou no meio
    (o erro fica em `falha`)."""
    global falha  # pylint: disable=global-statement
    falha = None
    marca = shared.app_dir / _AGENDADO
    if not marca.is_file():
        return None
    try:
        # Sobras de uma restauração de backup interrompida: a abertura as
        # devolveria à pasta recém-esvaziada.
        for sufixo in (".anterior", ".restaurando", ".lixo"):
            _apagar_pasta(_irma(sufixo))
        for item in list(shared.app_dir.iterdir()):
            if item.name == _AGENDADO:
                continue
            if item.name == "logs":
                # O processo que pediu a redefinição ainda pode estar saindo,
                # com o log aberto; o que sobrar dele não é de ninguém.
                shutil.rmtree(item, ignore_errors=True)
            elif item.is_dir() and not item.is_symlink() and not item.is_junction():
                _apagar_pasta(item)
            else:
                item.unlink(missing_ok=True)
        for settings in (shared.schema, shared.state_schema):
            for chave in settings.props.settings_schema.list_keys():
                if chave not in _FICAM:
                    settings.reset(chave)
        Gio.Settings.sync()
    except OSError as erro:
        falha = erro
        return False
    finally:
        # Mesmo na falha: repetir sozinho numa abertura futura apagaria o que o
        # usuário fizesse até lá. O aviso pede que ele tente de novo.
        with suppress(OSError):
            marca.unlink(missing_ok=True)
    return True
