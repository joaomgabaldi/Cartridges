# test_auditoria_0918_importadores.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regressões da auditoria de 18/09/2026, grupo dos importadores.

Um teste (ou um grupo parametrizado) por achado, com o ID no nome. Nenhum
toca a rede: as respostas HTTP são ``requests.Response`` de verdade montadas
sobre bytes, para o teto de ``download.get_capped`` ler o corpo como leria do
soquete.
"""

import io
import json
import os
import subprocess
import sys
import time
from hashlib import sha256

import pytest
import requests

from cartridges import shared
from cartridges.importer import shortcuts_source as ss
from cartridges.utils import download, game_logo, run_executable, steamgriddb, wallhaven
from cartridges.utils.steam import SteamAPIHelper, SteamGameNotFoundError


def _response(body, status=200, url="https://example.invalid/"):
    """Uma resposta real do requests, com o corpo num fluxo."""
    if not isinstance(body, bytes):
        body = json.dumps(body).encode("utf-8")
    response = requests.Response()
    response.status_code = status
    response.url = url
    response.raw = io.BytesIO(body)
    return response


@pytest.fixture
def http(monkeypatch):
    """Roteia todo ``requests.get`` para uma fila de respostas prontas."""
    calls: list = []
    queue: list = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return queue.pop(0)

    monkeypatch.setattr(download.requests, "get", fake_get)
    return queue, calls


@pytest.fixture
def scan(tmp_path, schema, monkeypatch):
    """O ``__iter__`` real sobre arquivos reais, sem PowerShell."""

    def runner(files=None, lnk_data=None, root=None, recursive=True):
        root = root or tmp_path
        for name, content in (files or {}).items():
            path = root / name
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
        schema["shortcuts-location"] = str(root)
        schema["shortcuts-recursive"] = recursive
        resolved = {
            str(root / name): {"File": str(root / name), **data}
            for name, data in (lnk_data or {}).items()
        }
        monkeypatch.setattr(ss, "resolve_lnk_targets", lambda paths: dict(resolved))
        monkeypatch.setattr(ss, "resolve_start_apps", lambda: [])
        return [r for r in iter(ss.ShortcutsSource()) if r is not None]

    return runner


# ---------------------------------------------------------------------------
# A1 — drive desligado não troca a identidade nem empobrece o comando
# ---------------------------------------------------------------------------


def test_a1_alvo_ausente_mantem_identidade_e_comando(scan, tmp_path):
    exe = tmp_path / "jogo" / "game.exe"
    exe.parent.mkdir()
    exe.write_text("x", encoding="utf-8")
    data = {
        "Target": str(exe).replace("/", "\\"),
        "Arguments": "-dx11",
        "WorkingDirectory": str(exe.parent).replace("/", "\\"),
    }

    (antes, _), = scan({"Jogo.lnk": "x"}, {"Jogo.lnk": data})
    exe.unlink()
    (depois, _), = scan({"Jogo.lnk": "x"}, {"Jogo.lnk": data})

    assert depois.game_id == antes.game_id
    assert depois.executable == antes.executable
    assert "/D" in depois.executable and depois.executable.endswith(" -dx11")
    identidade = f"{data['Target']}|-dx11"
    assert antes.game_id.endswith(sha256(identidade.encode()).hexdigest()[:16])


def test_a1_alvo_com_esquema_continua_uri(scan):
    (jogo, _), = scan(
        {"Epic.lnk": "x"},
        {"Epic.lnk": {"Target": "com.epicgames.launcher://apps/x", "Arguments": "-a"}},
    )
    assert jogo.executable == 'start "" "com.epicgames.launcher://apps/x"'


# ---------------------------------------------------------------------------
# M11 — args_safe acompanha as aspas
# ---------------------------------------------------------------------------

LEGITIMOS = [
    '/command=runGame /gameId=1207658924 /path="D:\\GOG Games\\X"',
    '--exec="launch Pro"',
    '-L "cores\\snes9x_libretro.dll" "D:\\ROMs\\Chrono Trigger (USA).sfc"',
    '"C:\\Program Files (x86)\\Game\\cfg.ini"',
    "-dx11 --skip-intro",
    '"a & b | c < d > e ^ f"',
    "",
]

INJECOES = [
    "& calc",
    '"a" & calc',
    '"a"&calc&"b"',
    '"a^"&calc',
    '"impar',
    'a "b" "c',
    "%COMSPEC%",
    '"%COMSPEC%"',
    '"!COMSPEC!"',
    "-a\r\ncalc",
    "-a\ncalc",
    '"a"\n"b"',
    "a (b)",
    "a ^& calc",
    "a | calc",
    "a > C:\\x.txt",
]


@pytest.mark.parametrize("args", LEGITIMOS)
def test_m11_argumentos_legitimos_sao_aceitos(args):
    assert ss.args_safe(args)


@pytest.mark.parametrize("args", INJECOES)
def test_m11_injecoes_sao_recusadas(args):
    assert not ss.args_safe(args)


def test_m11_atalho_do_gog_e_importado(scan, tmp_path):
    exe = tmp_path / "GalaxyClient.exe"
    exe.write_text("x", encoding="utf-8")
    (jogo, _), = scan(
        {"Witcher.lnk": "x"},
        {"Witcher.lnk": {"Target": str(exe), "Arguments": LEGITIMOS[0]}},
    )
    assert jogo.executable.endswith(LEGITIMOS[0])


@pytest.mark.skipif(sys.platform != "win32", reason="precisa do cmd.exe real")
def test_m11_cmd_real_nao_executa_o_que_foi_aceito(scan, tmp_path):
    """Prova no cmd.exe de verdade, com o comando que o importador monta.

    Cada carga tenta um ``echo`` para um arquivo-marca. As aceitas por
    ``args_safe`` não podem criar a marca; as recusadas criam — o que prova
    que o arnês detectaria uma injeção e que a recusa era necessária.
    """
    alvo = os.path.join(os.environ["SystemRoot"], "System32", "hostname.exe")
    marca = str(tmp_path / "marca.txt").replace("/", "\\")
    eco = f"echo x> {marca}"
    aceitas = [
        f'"a {eco}"'.replace("echo", "& echo"),
        f'x" & {eco} & "',
        f'"a" "& {eco}"',
        f'-L "cores\\x.dll" "Jogo (USA).sfc" "& {eco}"',
        f'"a^" "& {eco}"',
    ]
    recusadas = [
        f"& {eco}",
        f'"a" & {eco}',
        f'"a"&{eco}&"b"',
        f'"a^"&{eco}',
    ]

    def roda(args):
        if os.path.exists(marca):
            os.remove(marca)
        (jogo, _), = scan({"Jogo.lnk": "x"}, {"Jogo.lnk": {"Target": alvo}})
        # O comando do importador, com /B para o hostname não abrir console.
        comando = jogo.executable.replace('start ""', 'start "" /B', 1) + f" {args}"
        subprocess.run(
            comando,
            shell=True,
            capture_output=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        time.sleep(0.2)
        return os.path.exists(marca)

    for args in aceitas:
        assert ss.args_safe(args), args
        assert not roda(args), f"executou: {args}"
    for args in recusadas:
        assert not ss.args_safe(args), args
        assert roda(args), f"o arnês não viu a injeção: {args}"


# ---------------------------------------------------------------------------
# M12 — sem a lista de apps da Steam
# ---------------------------------------------------------------------------


def test_m12_busca_sem_confianca_faz_so_a_busca_da_loja(http):
    queue, calls = http
    queue.append(_response({"items": [{"id": 1, "name": "Halo Wars"}]}))

    with pytest.raises(SteamGameNotFoundError):
        SteamAPIHelper(_nullcontext()).resolve("Halo Infinite")

    # Antes, sem candidato confiável, `find_candidates` ia à lista de apps
    # (endpoint que hoje dá 404) e entrava no backoff.
    assert len(calls) == 1 and "storesearch" in calls[0][0]


def _nullcontext():
    import contextlib  # noqa: PLC0415

    return contextlib.nullcontext()


# ---------------------------------------------------------------------------
# A2 — capa .webp escolhida à mão conta como capa
# ---------------------------------------------------------------------------


def test_a2_webp_existente_nao_e_sobrescrita(make_game, schema, monkeypatch):
    schema["sgdb"] = True
    schema["sgdb-prefer"] = False
    game = make_game()
    webp = shared.covers_dir / f"{game.game_id}.webp"
    webp.write_bytes(b"RIFF")

    def nao_devia_buscar(*_a, **_k):
        raise AssertionError("buscou capa para um jogo que já tem uma")

    monkeypatch.setattr(steamgriddb.SgdbHelper, "get_game_id", nao_devia_buscar)
    steamgriddb.SgdbHelper().conditionaly_update_cover(game)
    assert webp.read_bytes() == b"RIFF"


# ---------------------------------------------------------------------------
# B7 — sidecar do logo por temporário + replace
# ---------------------------------------------------------------------------


def test_b7_escrita_que_falha_nao_estraga_o_sidecar(monkeypatch):
    game_logo._write_sidecar("shortcuts_1", "Halo", "shortcuts_1.png", locked=True)
    sidecar = shared.logos_dir / "shortcuts_1.json"
    antes = sidecar.read_text(encoding="utf-8")

    def falha(*_a, **_k):
        raise OSError("disco cheio")

    monkeypatch.setattr(json, "dump", falha)
    monkeypatch.setattr(json, "dumps", falha)
    game_logo._write_sidecar("shortcuts_1", "Halo", None)

    assert sidecar.read_text(encoding="utf-8") == antes
    assert sorted(p.name for p in shared.logos_dir.iterdir()) == ["shortcuts_1.json"]


# ---------------------------------------------------------------------------
# B18 — elevado com as aspas externas
# ---------------------------------------------------------------------------


def test_b18_elevado_passa_o_comando_entre_aspas(monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        run_executable, "_shell_execute_runas", lambda *args: chamadas.append(args)
    )
    comando = 'start "" "C:\\Dir (x86)\\x.exe" -cfg "C:\\a b\\c.ini"'
    run_executable._elevate_worker(comando)

    assert chamadas[0][0] == "cmd.exe"
    assert chamadas[0][1] == f'/c "{comando}"'


# ---------------------------------------------------------------------------
# B19 — junção NTFS não repete atalhos
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="junção é NTFS")
def test_b19_juncao_em_laco_nao_repete_atalhos(scan, tmp_path):
    root = tmp_path / "atalhos"
    (root / "sub").mkdir(parents=True)
    corpo = "[InternetShortcut]\nURL=steam://rungameid/440\n"
    (root / "sub" / "Outro.url").write_text(
        corpo.replace("440", "570"), encoding="utf-8"
    )
    alvo = str(root).replace("/", "\\")
    link = str(root / "sub" / "laco").replace("/", "\\")
    subprocess.run(
        f'mklink /J "{link}" "{alvo}"', shell=True, check=True, capture_output=True
    )
    try:
        results = scan({"Halo.url": corpo}, root=root)
    finally:
        os.rmdir(link)

    nomes = sorted(game.name for game, _ in results)
    assert nomes == ["Halo", "Outro"]


# ---------------------------------------------------------------------------
# B21 — appid nulo ou ausente não mata a thread
# ---------------------------------------------------------------------------


def test_b21_itens_sem_appid_viram_nao_encontrado(http):
    queue, _calls = http
    queue.append(_response({"items": [{"id": None, "name": "Halo"}, {"name": "Halo"}]}))

    with pytest.raises(SteamGameNotFoundError):
        SteamAPIHelper(_nullcontext()).resolve("Halo")


# ---------------------------------------------------------------------------
# B22 — SGDB escolhe pelo título, não pelo primeiro resultado
# ---------------------------------------------------------------------------


def test_b22_titulo_com_dois_pontos_acha_o_jogo_certo(http, make_game, schema):
    schema["sgdb-key"] = "chave"
    queue, _calls = http
    queue.append(
        _response(
            {
                "data": [
                    {"id": 1, "name": "Aliens: Colonial Marines"},
                    {"id": 2, "name": "Alien: Isolation"},
                ]
            }
        )
    )
    game = make_game(name="Alien: Isolation")
    assert steamgriddb.SgdbHelper().get_game_id(game) == 2


# ---------------------------------------------------------------------------
# B23 — .url em ANSI
# ---------------------------------------------------------------------------


def test_b23_url_em_cp1252_e_importado(scan):
    corpo = (
        "[InternetShortcut]\r\nURL=steam://rungameid/440\r\n"
        "IconFile=C:\\Jogos\\Ação\\icone.ico\r\n"
    ).encode("cp1252")
    (jogo, extra), = scan({"Ação.url": corpo})
    assert extra["steam_appid"] == "440"


# ---------------------------------------------------------------------------
# B24 — filtro de não-jogo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "nome,importa",
    [
        ("Manual Samuel", True),
        ("Tech Support Error Unknown", True),
        ("Halo Manual", False),
        ("Halo Benchmark", False),
        ("Uninstall Halo", False),
    ],
)
def test_b24_filtro_so_derruba_o_que_nao_e_jogo(scan, tmp_path, nome, importa):
    exe = tmp_path / "game.exe"
    exe.write_text("x", encoding="utf-8")
    results = scan({f"{nome}.lnk": "x"}, {f"{nome}.lnk": {"Target": str(exe)}})
    assert bool(results) is importa


# ---------------------------------------------------------------------------
# B25 — corpos HTTP com teto
# ---------------------------------------------------------------------------


def _grande():
    return _response(b"x" * (download.MAX_RESPONSE_BYTES + 1))


def test_b25_steam_respeita_o_teto(http):
    queue, calls = http
    queue.append(_grande())
    with pytest.raises(requests.RequestException):
        SteamAPIHelper(_nullcontext()).search_store("Halo")
    assert calls[0][1]["stream"] is True


def test_b25_sgdb_respeita_o_teto(http, schema):
    schema["sgdb-key"] = "chave"
    queue, _calls = http
    queue.append(_grande())
    with pytest.raises(requests.RequestException):
        steamgriddb.SgdbHelper().get_grids("1")


def test_b25_wallhaven_respeita_o_teto(http):
    queue, calls = http
    queue.append(_grande())
    with pytest.raises(wallhaven.WallhavenError):
        wallhaven.buscar("Halo", 1920, 1080)
    # Sem stream o requests já teria lido o corpo inteiro antes do teto.
    assert calls[0][1]["stream"] is True


# ---------------------------------------------------------------------------
# H5 — Location morto
# ---------------------------------------------------------------------------


def test_h5_location_saiu_e_a_excecao_ficou():
    from cartridges.importer import location  # noqa: PLC0415

    assert not hasattr(location, "Location")
    assert issubclass(location.UnresolvableLocationError, Exception)
