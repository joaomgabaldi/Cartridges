"""As decisões puras antes de restaurar: a versão está inteira, quais caminhos
trocar e onde o Ludusavi pode gravar."""

import _winapi
import ctypes
import os
import random
import zipfile
import zlib
from pathlib import Path

import pytest

from cartridges.conquistas.arquivos import Pastas
from cartridges.saves import conferencia
from cartridges.saves.conferencia import (
    CHAVES_PROIBIDAS,
    EXTENSOES_PROIBIDAS,
    MARCADORES,
)
from cartridges.saves.ludusavi import Previa

CASA = Path("C:/Users/João")
# Pastas de jogo que não existem e não estão no perfil de nenhum usuário.
VELHO = Path("C:/NaoExiste123/JogoA")
NOVO = Path("C:/NaoExiste123/JogoB")


def _zip(caminho: Path, entradas: dict[str, bytes], compressao=zipfile.ZIP_DEFLATED) -> Path:
    with zipfile.ZipFile(caminho, "w", compressao) as arquivo:
        for nome, dados in entradas.items():
            arquivo.writestr(nome, dados)
    return caminho


# --- integridade -------------------------------------------------------------


def test_integra_zip_bom(tmp_path):
    assert conferencia.integra(_zip(tmp_path / "v.zip", {"drive-C/x/a.sav": b"abc" * 100}))


def test_integra_crc_errado(tmp_path):
    # Dado sem repetição não comprime: sai guardado como está dentro do zip e dá
    # para trocar um byte do meio dele sem estragar o cabeçalho.
    conteudo = random.Random(0).randbytes(2000)
    arquivo = _zip(tmp_path / "v.zip", {"drive-C/x/a.sav": conteudo})
    bruto = bytearray(arquivo.read_bytes())
    meio = bruto.index(conteudo[1000:1016]) + 8
    bruto[meio] ^= 0xFF
    arquivo.write_bytes(bruto)

    assert conferencia.integra(arquivo) is False


def test_integra_dado_comprimido_estragado(tmp_path):
    # Aqui o byte trocado quebra o fluxo comprimido (`zlib.error`) antes de o CRC conferir.
    palavras = random.Random(1).choices(["ouro", "prata", "fase", "vida"], k=800)
    nome = "drive-C/x/a.sav"
    arquivo = _zip(tmp_path / "v.zip", {nome: " ".join(palavras).encode()})
    bruto = bytearray(arquivo.read_bytes())
    bruto[30 + len(nome) + 10] ^= 0xFF  # cabeçalho local + 10 bytes de dado
    arquivo.write_bytes(bruto)

    with pytest.raises(zlib.error), zipfile.ZipFile(arquivo) as zip_:
        zip_.testzip()  # o defeito é esse mesmo, e não um zip ilegível
    assert conferencia.integra(arquivo) is False


def test_integra_nome_ilegivel_no_cabecalho_local(tmp_path):
    arquivo = _zip(tmp_path / "v.zip", {"drive-C/Users/João/a.sav": b"abc"})
    bruto = bytearray(arquivo.read_bytes())
    bruto[bruto.index("ã".encode())] = 0xFF  # o primeiro é o do cabeçalho local
    arquivo.write_bytes(bruto)

    with pytest.raises(UnicodeDecodeError), zipfile.ZipFile(arquivo) as zip_:
        zip_.testzip()  # o defeito é esse mesmo
    assert conferencia.integra(arquivo) is False


def test_integra_ausente_e_none(tmp_path):
    assert conferencia.integra(tmp_path / "x.zip") is False
    assert conferencia.integra(None) is False


def test_integra_nao_e_zip(tmp_path):
    arquivo = tmp_path / "v.zip"
    arquivo.write_text("isto não é um zip")

    assert conferencia.integra(arquivo) is False


# --- nomes dentro do zip -----------------------------------------------------


def test_caminhos_no_zip(tmp_path):
    arquivo = _zip(
        tmp_path / "v.zip",
        {
            "drive-C/Users/x/a.sav": b"1",
            "drive-D/Jogos/X/steam_settings/1/b.ini": b"2",
            "registry.reg": b"3",
        },
    )

    assert conferencia.caminhos_no_zip(arquivo) == [
        "C:/Users/x/a.sav",
        "D:/Jogos/X/steam_settings/1/b.ini",
    ]


# --- redirecionamentos -------------------------------------------------------


def test_redireciona_usuario_antigo_inexistente():
    caminhos = ["C:/Users/NaoExiste123/AppData/a.sav"]

    assert conferencia.redirecionamentos(caminhos, CASA, []) == [
        ("C:/Users/NaoExiste123", "C:/Users/João")
    ]


def test_nao_redireciona_o_mesmo_usuario():
    assert conferencia.redirecionamentos(["c:/users/joão/AppData/a.sav"], CASA, []) == []


def test_nao_redireciona_usuario_que_existe():
    assert conferencia.redirecionamentos(["C:/Users/Public/Documents/x"], CASA, []) == []


def test_redireciona_cada_usuario_uma_vez():
    caminhos = [
        "C:/Users/NaoExiste123/AppData/a.sav",
        "C:/Users/NaoExiste123/Documents/b.sav",
        "D:/Users/NaoExiste456/c.sav",
    ]

    assert conferencia.redirecionamentos(caminhos, CASA, []) == [
        ("C:/Users/NaoExiste123", "C:/Users/João"),
        ("D:/Users/NaoExiste456", "C:/Users/João"),
    ]


def test_redireciona_a_pasta_do_jogo_movida():
    caminhos = [
        f"{VELHO.as_posix()}/steam_settings/480/a.ini",
        f"{VELHO.as_posix()}/bin/steam_settings/480/b.ini",
    ]
    atuais = [NOVO / "bin", NOVO]

    assert conferencia.redirecionamentos(caminhos, CASA, atuais) == [
        (VELHO.as_posix(), NOVO.as_posix())
    ]


@pytest.mark.parametrize("marcador", MARCADORES)
def test_cada_marcador_acha_a_pasta_do_jogo(marcador):
    caminho = VELHO.as_posix() + marcador + ("a.ini" if marcador.endswith("/") else "")

    assert conferencia.redirecionamentos([caminho], CASA, [NOVO]) == [
        (VELHO.as_posix(), NOVO.as_posix())
    ]


def test_marcador_sem_diferenca_de_maiusculas():
    caminho = f"{VELHO.as_posix()}/STEAM_SETTINGS/480/a.ini"

    assert conferencia.redirecionamentos([caminho], CASA, [NOVO]) == [
        (VELHO.as_posix(), NOVO.as_posix())
    ]


def test_a_origem_mantem_a_caixa_do_zip():
    # O Ludusavi compara a origem do redirecionamento sem trocar maiúsculas por minúsculas.
    caminho = "C:/NaoExiste123/JoGoA/steam_settings/480/a.ini"

    assert conferencia.redirecionamentos([caminho], CASA, [NOVO]) == [
        ("C:/NaoExiste123/JoGoA", NOVO.as_posix())
    ]


@pytest.mark.parametrize(
    ("subpasta", "atuais"),
    [
        ("Binaries/Win64", [NOVO / "Binaries" / "Win64", NOVO / "Binaries", NOVO]),
        ("bin", [NOVO / "bin", NOVO]),
        ("bin", [NOVO]),  # a instalação nova é plana: a raiz continua sendo a raiz
    ],
)
def test_redireciona_de_raiz_para_raiz(subpasta, atuais):
    # O save ao lado do executável: o que se leva é a raiz, e a estrutura de dentro fica.
    caminho = f"{VELHO.as_posix()}/{subpasta}/steam_settings/480/a.ini"

    assert conferencia.redirecionamentos([caminho], CASA, atuais) == [
        (VELHO.as_posix(), NOVO.as_posix())
    ]


def test_pasta_do_jogo_sem_marcador_nao_redireciona():
    caminhos = [f"{VELHO.as_posix()}/save/a.sav"]

    assert conferencia.redirecionamentos(caminhos, CASA, [NOVO]) == []


def test_pasta_do_jogo_que_existe_nao_redireciona():
    windows = Path(os.environ.get("SystemRoot", "C:/Windows"))
    caminhos = [f"{windows.as_posix()}/steam_settings/480/a.ini"]

    assert conferencia.redirecionamentos(caminhos, CASA, [NOVO]) == []


def test_raiz_antiga_que_existe_nao_redireciona():
    windows = Path(os.environ.get("SystemRoot", "C:/Windows"))
    caminhos = [f"{windows.as_posix()}/Win64/steam_settings/480/a.ini"]

    assert conferencia.redirecionamentos(caminhos, CASA, [NOVO]) == []


def test_pasta_do_jogo_igual_a_atual_nao_redireciona():
    # Nem existe: o que vale é ser a mesma pasta.
    caminhos = [f"{NOVO.as_posix()}/steam_settings/480/a.ini"]

    assert conferencia.redirecionamentos(caminhos, CASA, [NOVO]) == []


def test_raiz_antiga_igual_a_atual_nao_redireciona():
    caminhos = [f"{NOVO.as_posix()}/bin/steam_settings/480/a.ini"]

    assert conferencia.redirecionamentos(caminhos, CASA, [NOVO / "bin", NOVO]) == []


def test_sem_pasta_atual_do_jogo_nao_redireciona():
    caminhos = [f"{VELHO.as_posix()}/steam_settings/480/a.ini"]

    assert conferencia.redirecionamentos(caminhos, CASA, []) == []


def test_pasta_do_jogo_dentro_do_perfil_de_um_usuario_nao_redireciona():
    # O redirecionamento do usuário já leva essa pasta; dois sobre o mesmo caminho se encadeiam.
    caminho = "C:/Users/Public/Documents/My Games/NaoExisteJogo123/Profile/save.dat"

    assert conferencia.redirecionamentos([caminho], CASA, [NOVO]) == []


def test_jogo_no_perfil_de_usuario_antigo_so_leva_o_redirecionamento_do_usuario():
    caminho = "C:/Users/NaoExiste123/Documents/My Games/NaoExisteJogo123/Profile/save.dat"

    assert conferencia.redirecionamentos([caminho], CASA, [NOVO]) == [
        ("C:/Users/NaoExiste123", "C:/Users/João")
    ]


@pytest.mark.parametrize(
    "caminho", ["C:/ProgramData/NaoExiste123/Jogo/Profile/x.sav", "D:/Docs/NaoExiste123/Profile/x.sav"]
)
def test_pasta_do_sistema_nunca_vira_a_pasta_do_jogo(caminho):
    # Um save do ProgramData (ou dos Documentos em outro disco) com `/Profile/` no caminho
    # não é save de emulador: levá-lo à pasta do jogo o gravaria no lugar errado.
    sistema = (Path("C:/ProgramData"), Path("D:/Docs"))

    assert conferencia.redirecionamentos([caminho], CASA, [NOVO], sistema) == []


def test_usuarios_vem_antes_da_pasta_do_jogo():
    caminhos = [
        f"{VELHO.as_posix()}/Profile/a.sav",
        "C:/Users/NaoExiste123/AppData/b.sav",
    ]

    assert conferencia.redirecionamentos(caminhos, CASA, [NOVO]) == [
        ("C:/Users/NaoExiste123", "C:/Users/João"),
        (VELHO.as_posix(), NOVO.as_posix()),
    ]


# --- destinos permitidos -----------------------------------------------------


def _pastas(documentos=Path("C:/Users/João/Documents")) -> Pastas:
    return Pastas(
        appdata=Path("C:/Users/João/AppData/Roaming"),
        localappdata=Path("C:/Users/João/AppData/Local"),
        documentos=documentos,
        documentos_publicos=Path("C:/Users/Public/Documents"),
        programdata=Path("C:/ProgramData"),
    )


def _recusado(*arquivos: str, chaves: tuple[str, ...] = (), pastas: Pastas | None = None):
    permitidas = conferencia.raizes(pastas or _pastas(), CASA, [])
    return conferencia.recusado(Previa(arquivos, chaves), permitidas)


def test_raizes():
    r = conferencia.raizes(_pastas(), CASA, [Path("D:/Jogos/X")])

    assert r.permitidas == (
        CASA,
        Path("C:/Users/João/AppData/Roaming"),
        Path("C:/Users/João/AppData/Local"),
        Path("C:/Users/João/Documents"),
        Path("C:/Users/Public"),
        Path("C:/ProgramData"),
        Path("D:/Jogos/X"),
    )
    assert r.proibidas == (
        Path("C:/Users/João/AppData/Roaming/Microsoft"),
        Path("C:/Users/João/AppData/Local/Microsoft"),
        Path("C:/ProgramData/Microsoft"),
        Path("C:/Users/João/Documents/WindowsPowerShell"),
        Path("C:/Users/João/Documents/PowerShell"),
        Path("C:/Users/João/.ssh"),
        Path("C:/Users/João/.local"),
        Path("C:/Users/João/.config/git"),
    )
    assert r.casa == CASA


@pytest.mark.parametrize(
    "arquivo",
    [
        "C:/Windows/System32/x.dat",
        "D:/Outro/x.sav",
        "C:/Users/Outro/AppData/Roaming/Jogo/x.sav",
        "C:/Users/João/../Outro/x.sav",
        "//servidor/pasta/x.sav",
    ],
)
def test_recusa_fora_das_raizes(arquivo):
    assert _recusado("C:/Users/João/AppData/Roaming/Jogo/ok.sav", arquivo) == arquivo


def test_recusa_caminho_relativo_mesmo_dentro_de_uma_raiz(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    permitidas = conferencia.raizes(_pastas(), tmp_path, [])

    assert conferencia.recusado(Previa(("Jogo/x.sav",), ()), permitidas) == "Jogo/x.sav"


def test_aceita_documentos_em_outro_disco():
    assert _recusado("d:/docs/Jogo/s.sav", pastas=_pastas(documentos=Path("D:/Docs"))) is None


def test_aceita_o_que_esta_nas_raizes_extras():
    permitidas = conferencia.raizes(_pastas(), CASA, [Path("D:/Jogos/X")])

    previa = Previa(("D:/Jogos/X/steam_settings/1/a.ini",), ())

    assert conferencia.recusado(previa, permitidas) is None


@pytest.mark.parametrize(
    "arquivo",
    [
        "C:/Users/João/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/x.txt",
        "C:/Users/João/AppData/Local/Microsoft/x",
        "C:/ProgramData/Microsoft/x",
        "C:/Users/João/Documents/WindowsPowerShell/profile.txt",
        "C:/Users/João/Documents/PowerShell/x",
    ],
)
def test_recusa_cada_pasta_proibida(arquivo):
    assert _recusado(arquivo) == arquivo


@pytest.mark.parametrize("extensao", sorted(EXTENSOES_PROIBIDAS))
def test_recusa_extensao_proibida(extensao):
    minuscula = f"C:/Users/João/AppData/Local/Jogo/x{extensao}"
    maiuscula = f"C:/Users/João/AppData/Local/Jogo/X{extensao.upper()}"

    assert _recusado(minuscula) == minuscula
    assert _recusado(maiuscula) == maiuscula


@pytest.mark.parametrize("nome", ["x.exe.", "x.exe ", "x.exe. .", "x.exe::$DATA", "x.sav:y.exe"])
def test_recusa_extensao_disfarcada_pelo_windows(nome):
    # O Windows tira pontos e espaços do fim do nome ao criar o arquivo, e `::$DATA`
    # (um fluxo alternativo do NTFS) cria o arquivo de nome antes dele.
    arquivo = f"C:/Users/João/AppData/Local/Jogo/{nome}"

    assert _recusado(arquivo) == arquivo


@pytest.mark.parametrize(
    "nome", ["slot1.sav", "config.ini", "perfil.json", "savegame", "a.exe.sav"]
)
def test_aceita_save_comum(nome):
    assert _recusado(f"C:/Users/João/AppData/Local/Jogo/{nome}") is None


def test_devolve_o_primeiro_recusado_e_arquivos_vem_antes_das_chaves():
    previa = Previa(
        ("C:/Users/João/AppData/Local/Jogo/ok.sav", "C:/Windows/a.dat", "C:/Windows/b.dat"),
        ("HKEY_LOCAL_MACHINE/Software/Jogo",),
    )

    permitidas = conferencia.raizes(_pastas(), CASA, [])

    assert conferencia.recusado(previa, permitidas) == "C:/Windows/a.dat"


def test_previa_vazia_nao_e_recusada():
    assert _recusado() is None


# Destinos que o texto não entrega: o disco decide onde o arquivo vai parar.


def _pastas_em(raiz: Path) -> Pastas:
    return Pastas(
        appdata=raiz / "AppData" / "Roaming",
        localappdata=raiz / "AppData" / "Local",
        documentos=raiz / "Documents",
        documentos_publicos=raiz / "Public" / "Documents",
        programdata=raiz / "ProgramData",
    )


def _recusado_em(raiz: Path, arquivo: Path):
    permitidas = conferencia.raizes(_pastas_em(raiz), raiz / "casa", [])
    return conferencia.recusado(Previa((arquivo.as_posix(),), ()), permitidas)


def _nome_curto(pasta: Path) -> str:
    """O nome 8.3 de uma pasta que existe (o próprio nome, se o volume não os guarda)."""
    buffer = ctypes.create_unicode_buffer(1024)
    ctypes.windll.kernel32.GetShortPathNameW(str(pasta), buffer, len(buffer))
    return Path(buffer.value).name


def test_recusa_o_nome_curto_de_uma_pasta_proibida(tmp_path):
    proibida = _pastas_em(tmp_path).appdata / "Microsoft"
    proibida.mkdir(parents=True)
    curto = _nome_curto(proibida)
    if curto.casefold() == proibida.name.casefold():
        pytest.skip("o volume dos testes não guarda nomes curtos (8.3)")

    assert _recusado_em(tmp_path, proibida.parent / curto / "Excel" / "XLSTART" / "x.sav")


def test_recusa_a_juncao_que_leva_a_uma_pasta_proibida(tmp_path):
    destino = _pastas_em(tmp_path).appdata / "Microsoft" / "Windows" / "SendTo"
    destino.mkdir(parents=True)
    (tmp_path / "casa").mkdir()
    _winapi.CreateJunction(str(destino), str(tmp_path / "casa" / "SendTo"))

    assert _recusado_em(tmp_path, tmp_path / "casa" / "SendTo" / "x.sav")


def test_aceita_a_juncao_que_leva_a_uma_pasta_permitida(tmp_path):
    destino = _pastas_em(tmp_path).appdata / "Jogo"
    destino.mkdir(parents=True)
    (tmp_path / "casa").mkdir()
    _winapi.CreateJunction(str(destino), str(tmp_path / "casa" / "Application Data"))

    assert _recusado_em(tmp_path, tmp_path / "casa" / "Application Data" / "x.sav") is None


def test_recusa_fluxo_do_ntfs_numa_pasta_do_caminho():
    arquivo = "C:/Users/João/AppData/Roaming/Microsoft::$INDEX_ALLOCATION/Excel/XLSTART/x.sav"

    assert _recusado(arquivo) == arquivo


@pytest.mark.parametrize(
    "arquivo",
    ["//servidor/pasta/x.sav", r"\servidor\pasta\x.sav", r"\?\UNC\servidor\pasta\x.sav"],
)
def test_caminho_de_rede_e_recusado_sem_tocar_no_disco(arquivo, monkeypatch):
    consultados = []
    real = os.path.realpath

    def espia(caminho, *args, **kwargs):
        consultados.append(os.fspath(caminho))
        return real(caminho, *args, **kwargs)

    monkeypatch.setattr(conferencia.os.path, "realpath", espia)

    assert _recusado(arquivo) == arquivo
    assert not any("servidor" in consultado for consultado in consultados)


@pytest.mark.parametrize("nome", [".gitconfig", ".bashrc", "notas.txt"])
def test_recusa_arquivo_solto_na_pasta_do_usuario(nome):
    arquivo = f"C:/Users/João/{nome}"

    assert _recusado(arquivo) == arquivo


def test_aceita_arquivo_numa_subpasta_da_pasta_do_usuario():
    assert _recusado("C:/Users/João/Saved Games/Jogo/slot1.sav") is None


def test_recusa_a_pasta_ssh():
    arquivo = "C:/Users/João/.ssh/authorized_keys"

    assert _recusado(arquivo) == arquivo


@pytest.mark.parametrize(
    "arquivo",
    [
        # o site-packages do usuário, que o Python do app lê ao abrir
        "C:/Users/João/.local/lib/python3.14-mingw_x86_64_ucrt_gnu/site-packages/x.txt",
        "C:/Users/João/.config/git/config",  # o `core.fsmonitor` roda um programa
    ],
)
def test_recusa_as_pastas_de_configuracao_que_rodam_codigo(arquivo):
    assert _recusado(arquivo) == arquivo


@pytest.mark.parametrize(
    "extensao",
    [
        # Python: o `.pth` roda a linha `import`; os compilados rodam sem o fonte
        ".pth", ".pyc", ".pyo", ".pyz", ".pyzw",
        # scripts e atalhos do Windows
        ".wsc", ".sct", ".settingcontent-ms", ".library-ms", ".searchconnector-ms",
        ".search-ms", ".ps1xml",
        # instaladores de aplicativo
        ".application", ".appinstaller", ".msix", ".msixbundle", ".appx", ".appxbundle",
    ],
)
def test_recusa_extensao_que_instala_ou_roda_codigo(extensao):
    arquivo = f"C:/Users/João/AppData/Local/Jogo/x{extensao}"

    assert _recusado(arquivo) == arquivo


@pytest.mark.parametrize(
    "extensao",
    [
        ".asi", ".node", ".pyd", ".xll", ".xla", ".xlam",
        ".chm", ".msc", ".appref-ms", ".asar", ".scf", ".inf",
    ],
)
def test_recusa_extensao_que_carrega_codigo(extensao):
    arquivo = f"C:/Users/João/AppData/Local/Jogo/x{extensao}"

    assert _recusado(arquivo) == arquivo


# --- chaves do registro ------------------------------------------------------


def _chave_recusada(chave: str):
    return _recusado(chaves=(chave,))


def test_chave_comum_e_aceita():
    assert _chave_recusada("HKEY_CURRENT_USER/Software/Jogo/x") is None
    assert _chave_recusada("hkey_current_user\\software\\Jogo\\x") is None


@pytest.mark.parametrize(
    "chave",
    [
        r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run",
        "HKEY_LOCAL_MACHINE/Software/Jogo",
        "HKEY_CURRENT_USER/Console/%%Startup",
        "HKEY_CURRENT_USER/Software",
        "HKEY_CURRENT_USER/Software/Microsoft",
    ],
)
def test_chaves_recusadas(chave):
    assert _chave_recusada(chave) == chave


@pytest.mark.parametrize("prefixo", CHAVES_PROIBIDAS)
def test_cada_chave_proibida(prefixo):
    for chave in (prefixo + "x", prefixo.upper() + "X", prefixo.replace("/", "\\") + "x"):
        assert _chave_recusada(chave) == chave
