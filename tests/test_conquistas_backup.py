"""O backup leva o histórico de conquistas."""

import zipfile

from kyron import shared
from kyron.conquistas import historico
from kyron.conquistas.formatos import Desbloqueio
from kyron.utils import backup


def test_backup_leva_o_historico(tmp_path):
    historico.registrar("shortcuts_1", [Desbloqueio("A", 1)])
    destino = tmp_path / "saida" / "backup.zip"
    destino.parent.mkdir()
    backup.exportar(destino, {"settings": {}, "state": {}})
    with zipfile.ZipFile(destino) as arquivo:
        assert "conquistas/shortcuts_1.json" in arquivo.namelist()
    assert shared.conquistas_dir.is_dir()
