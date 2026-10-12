# test_saves_ludusavi_real.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Os saves com o `ludusavi.exe` de verdade, o que fica ao lado do Python.

Só o Ludusavi de verdade mostra que a versão danificada não chega ao save, que o arquivo
travado deixa uma versão incompleta (e "Restaurar todos" a pula), que a pasta do jogo
movida é redirecionada, que o destino proibido é recusado e que a cópia antes da
restauração não apaga a versão escolhida.

Tudo fica em `tmp_path`: manifesto vazio e sem rede (`--no-manifest-update`), nenhuma
pasta de emulador no config, e cada chamada confere o config antes de rodar o Ludusavi.
As funções de trabalho rodam direto, sem thread.
"""

# pylint: disable=protected-access  # as funções de trabalho, chamadas sem a thread

import ctypes
import json
import os
import struct
import subprocess
import sys
import time
import zipfile
from collections import Counter
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path

import pytest

from cartridges.saves import backup_de_saves, conferencia, config
from cartridges.saves.pasta import dentro

# Lido no import, antes de qualquer monkeypatch do `sys.executable`.
EXE = Path(sys.executable).parent / "ludusavi.exe"
pytestmark = [
    pytest.mark.skipif(not EXE.is_file(), reason=f"{EXE} não existe"),
    pytest.mark.usefixtures("settings"),
]

NOME = "Jogo Real"
APPID = "2999999"


def _no_teste(caminho: str, raiz: Path) -> bool:
    # Absoluto antes: `dentro` completaria um relativo com a pasta atual do processo.
    return Path(caminho).is_absolute() and dentro(Path(caminho), raiz)


def _problemas(dados: dict, raiz: Path) -> list[str]:
    """O que, no config, poderia levar o Ludusavi para fora de ``raiz`` ou para a rede. Só
    as chaves que `config.montar` grava hoje passam: uma nova (`registry`, `installDir`,
    `toggledPaths`, `manifest`) faz a guarda falhar até ser conferida aqui."""
    secoes = [
        ("config", dados, {"release", "backup", "restore", "roots", "customGames", "redirects"}),
        ("release", dados["release"], {"check"}),
        ("backup", dados["backup"], {"path", "format", "retention"}),
        ("backup.format", dados["backup"]["format"], {"chosen"}),
        ("backup.retention", dados["backup"]["retention"], {"full", "differential"}),
        ("restore", dados["restore"], {"path"}),
        *(("roots[]", item, {"store", "path"}) for item in dados["roots"]),
        *(("customGames[]", j, {"name", "integration", "files"}) for j in dados["customGames"]),
        *(("redirects[]", r, {"kind", "source", "target"}) for r in dados.get("redirects", [])),
    ]
    problemas = [
        f"{onde}.{chave}" for onde, secao, aceitas in secoes for chave in set(secao) - aceitas
    ]
    if dados["release"]["check"] is not False:
        problemas.append("release.check")
    caminhos = [
        dados["backup"]["path"],
        dados["restore"]["path"],
        *(item["path"] for item in dados["roots"]),
        *(caminho for jogo in dados["customGames"] for caminho in jogo["files"]),
        *(c for r in dados.get("redirects", []) for c in (r["source"], r["target"])),
    ]
    return problemas + [caminho for caminho in caminhos if not _no_teste(caminho, raiz)]


def _executor(raiz: Path):
    """`subprocess.run` sem rede, que só deixa o Ludusavi rodar se o config inteiro está em
    ``raiz``, e espaça os backups: o nome da versão tem resolução de segundos."""
    ultimo_backup = 0.0

    def rodar(args, **kwargs):
        nonlocal ultimo_backup
        # `pytest.fail` não é `Exception`: o `except` do app não o engole. Qualquer outro
        # erro aqui (config ilegível, chave que falta) também falha o teste, sem rodar o exe.
        try:
            pasta_config = Path(args[args.index("--config") + 1])
            arquivo = pasta_config / "config.yaml"
            if not (_no_teste(str(pasta_config), raiz) and arquivo.is_file()):
                problemas = [f"sem o config do teste: {args}"]
            else:
                problemas = _problemas(json.loads(arquivo.read_text("utf-8")), raiz)
        except Exception as erro:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            problemas = [f"config ilegível: {erro!r}"]
        if problemas:
            pytest.fail(f"o Ludusavi não roda com este config: {problemas}")
        comando = ["--no-manifest-update" if a == "--try-manifest-update" else a for a in args]
        eh_backup = args[args.index("--try-manifest-update") + 1] == "backup"
        if eh_backup:
            time.sleep(max(0.0, ultimo_backup + 1.1 - time.monotonic()))
        try:
            # Quem confere o código de saída é o `ludusavi.rodar` do app.
            return subprocess.run(comando, check=False, **kwargs)
        finally:
            if eh_backup:
                ultimo_backup = time.monotonic()

    return rodar


@pytest.fixture(name="jogo")
def fixture_jogo(request, tmp_path, monkeypatch, store, make_game):
    """O jogo na biblioteca, com a pasta de saves dele (`steam_settings/<appid>`) vazia.

    O exe de verdade só é liberado no fim, com o executor e a guarda já no lugar."""
    (tmp_path / "ludusavi").mkdir()
    (tmp_path / "ludusavi" / "manifest.yaml").write_text("{}", encoding="utf-8")
    # As pastas de emulador ficam no %APPDATA% e no Público de verdade.
    monkeypatch.setattr(config, "pastas_de_emulador", lambda _appid: [])
    monkeypatch.setattr(backup_de_saves, "executor", _executor(tmp_path))
    monkeypatch.setattr(backup_de_saves, "_cache", {})
    monkeypatch.setattr(backup_de_saves, "_restaurando", Counter())
    monkeypatch.setattr(backup_de_saves, "_jogos_restaurando", Counter())
    monkeypatch.setattr(backup_de_saves, "_restaurando_todos", 0)
    monkeypatch.setattr(backup_de_saves, "_tarefas_abertas", 0)
    exe = tmp_path / "JogoA" / "jogo.exe"
    (exe.parent / "steam_settings" / APPID).mkdir(parents=True)
    exe.touch()
    jogo = make_game(
        game_id="real", name=NOME, steam_appid=APPID, executable=str(exe), ludusavi_nome=NOME
    )
    store.add_game(jogo, {})
    # O opt-in que tira a guarda de sessão do conftest, só nestes testes e só agora.
    request.getfixturevalue("ludusavi_real_da_maquina")
    return jogo


def saves_de(jogo) -> Path:
    return Path(jogo.executable).parent / "steam_settings" / APPID


def backup(jogo, flush_idle) -> None:
    backup_de_saves._backup(jogo, backup_de_saves._biblioteca())
    flush_idle()


def restaurar(jogo, versao: str, flush_idle) -> None:
    backup_de_saves._restaurar(jogo, NOME, versao, backup_de_saves._biblioteca())
    flush_idle()


def titulos(win) -> list[str]:
    return [toast.get_title() for toast in win.toast_queue.added]


def no_zip(arquivo: Path | None, nome: str) -> bytes | None:
    """O conteúdo de ``nome`` (o fim do caminho) dentro do zip de uma versão."""
    assert arquivo is not None
    with zipfile.ZipFile(arquivo) as zip_:
        achado = next((n for n in zip_.namelist() if n.endswith(f"/{nome}")), None)
        return None if achado is None else zip_.read(achado)


def danificar(arquivo: Path | None) -> None:
    """Inverte 64 bytes no meio dos dados do maior arquivo dentro do zip."""
    assert arquivo is not None
    with zipfile.ZipFile(arquivo) as zip_:
        maior = max(zip_.infolist(), key=lambda info: info.compress_size)
    assert maior.compress_size >= 128
    dados = bytearray(arquivo.read_bytes())
    # Cabeçalho local: 30 bytes, o nome e o campo extra (os tamanhos nos bytes 26 e 28).
    nome, extra = struct.unpack_from("<HH", dados, maior.header_offset + 26)
    meio = maior.header_offset + 30 + nome + extra + maior.compress_size // 2 - 32
    dados[meio : meio + 64] = bytes(byte ^ 0xFF for byte in dados[meio : meio + 64])
    arquivo.write_bytes(dados)


@contextmanager
def travado(arquivo: Path):
    """``arquivo`` aberto sem compartilhamento: ninguém mais o lê enquanto durar."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    # GENERIC_READ | GENERIC_WRITE, compartilhamento 0, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL
    handle = kernel32.CreateFileW(str(arquivo), 0xC0000000, 0, None, 3, 0x80, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel32.CloseHandle(handle)


def test_real_versao_danificada_nao_toca_o_save(jogo, flush_idle, win):
    saves = saves_de(jogo)
    # Grande e aleatório: o meio dele no zip é dado, e não cabeçalho.
    (saves / "dados.bin").write_bytes(os.urandom(4096))
    (saves / "save.sav").write_bytes(b"v1")
    backup(jogo, flush_idle)
    (saves / "save.sav").write_bytes(b"v2")
    backup(jogo, flush_idle)
    versoes = backup_de_saves.versoes_do_jogo(jogo)
    assert len(versoes) == 2
    danificar(versoes[-1].arquivo)
    (saves / "save.sav").write_bytes(b"atual")

    restaurar(jogo, versoes[-1].id, flush_idle)

    assert (saves / "save.sav").read_bytes() == b"atual"
    # Parou antes até da cópia dos saves atuais.
    assert len(backup_de_saves.versoes_do_jogo(jogo)) == 2
    assert titulos(win) == [
        "A versão escolhida dos saves de Jogo Real está danificada e não foi restaurada."
    ]


def test_real_backup_com_arquivo_travado_fica_marcado(jogo, flush_idle, win):
    saves = saves_de(jogo)
    (saves / "a.sav").write_bytes(b"a1")
    (saves / "b.sav").write_bytes(b"b1")
    backup(jogo, flush_idle)
    (saves / "a.sav").write_bytes(b"a2")
    (saves / "b.sav").write_bytes(b"b2")

    with travado(saves / "b.sav"):
        backup(jogo, flush_idle)

    nova, anterior = backup_de_saves.versoes_do_jogo(jogo)
    assert nova.comentario == backup_de_saves.INCOMPLETA
    assert anterior.comentario == ""
    assert no_zip(nova.arquivo, "a.sav") == b"a2"
    # O travado não entra (o Ludusavi 0.31 o deixa vazio): restaurá-la estragaria o `b.sav`.
    assert no_zip(nova.arquivo, "b.sav") in (b"", None)
    aviso = "Não foi possível fazer o backup dos saves de Jogo Real."
    assert titulos(win) == [aviso]

    backup_de_saves._restaurar_todos(backup_de_saves._biblioteca(), [id(jogo)])
    flush_idle()

    # A anterior, completa: a incompleta deixaria `a.sav` de uma e `b.sav` de outra.
    assert (saves / "a.sav").read_bytes() == b"a1"
    assert (saves / "b.sav").read_bytes() == b"b1"
    assert titulos(win) == [aviso]


def test_real_pasta_do_jogo_movida(jogo, flush_idle, win, tmp_path):
    if conferencia._USUARIO.match(tmp_path.as_posix()):
        pytest.skip(
            "tmp_path está num perfil (X:/Users/<nome>): ali a pasta do jogo não ganha "
            "redirecionamento (o do usuário cobre); rode com --basetemp fora do perfil"
        )
    (saves_de(jogo) / "save.sav").write_bytes(b"v1")
    backup(jogo, flush_idle)
    (versao,) = backup_de_saves.versoes_do_jogo(jogo)
    (tmp_path / "JogoA").rename(tmp_path / "JogoB")
    jogo.executable = str(tmp_path / "JogoB" / "jogo.exe")
    (saves_de(jogo) / "save.sav").write_bytes(b"atual")

    restaurar(jogo, versao.id, flush_idle)

    assert (tmp_path / "JogoB" / "steam_settings" / APPID / "save.sav").read_bytes() == b"v1"
    assert not (tmp_path / "JogoA").exists()
    assert titulos(win) == []


def test_real_destino_proibido_e_recusado(jogo, flush_idle, win):
    saves = saves_de(jogo)
    (saves / "save.sav").write_bytes(b"v1")
    (saves / "x.dll").write_bytes(b"MZ")
    backup(jogo, flush_idle)
    (versao,) = backup_de_saves.versoes_do_jogo(jogo)
    (saves / "x.dll").unlink()
    (saves / "save.sav").write_bytes(b"atual")

    restaurar(jogo, versao.id, flush_idle)

    assert (saves / "save.sav").read_bytes() == b"atual"
    assert not (saves / "x.dll").exists()
    assert titulos(win) == [
        (
            "O backup dos saves de Jogo Real contém arquivos fora das pastas de save "
            "e não foi restaurado."
        )
    ]


def test_real_copia_nao_apaga_a_escolhida(jogo, flush_idle, win):
    save = saves_de(jogo) / "save.sav"
    for numero in range(1, 6):
        save.write_bytes(f"v{numero}".encode())
        backup(jogo, flush_idle)
    antes = backup_de_saves.versoes_do_jogo(jogo)
    assert len(antes) == 5
    save.write_bytes(b"atual")

    restaurar(jogo, antes[-1].id, flush_idle)

    assert save.read_bytes() == b"v1"
    copia, *resto = backup_de_saves.versoes_do_jogo(jogo)
    # Nenhuma das cinco saiu, a escolhida (a mais antiga) inclusive.
    assert [v.id for v in resto] == [v.id for v in antes]
    assert copia.comentario == backup_de_saves.ANTES_DE_RESTAURAR
    assert no_zip(copia.arquivo, "save.sav") == b"atual"
    assert titulos(win) == []
