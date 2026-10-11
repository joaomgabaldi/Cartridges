"""As decisões puras antes de restaurar: a versão está inteira, quais caminhos
trocar e onde o Ludusavi pode gravar."""

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


def test_redireciona_a_pasta_do_jogo_movida(tmp_path):
    velho = tmp_path / "JogoA"
    caminhos = [
        f"{velho.as_posix()}/steam_settings/480/a.ini",
        f"{velho.as_posix()}/bin/steam_settings/480/b.ini",
    ]
    atuais = [tmp_path / "JogoB" / "bin", tmp_path / "JogoB"]

    assert conferencia.redirecionamentos(caminhos, tmp_path / "casa", atuais) == [
        (velho.as_posix(), (tmp_path / "JogoB").as_posix())
    ]


@pytest.mark.parametrize("marcador", MARCADORES)
def test_cada_marcador_acha_a_pasta_do_jogo(tmp_path, marcador):
    velho = tmp_path / "JogoA"
    caminho = velho.as_posix() + marcador + ("a.ini" if marcador.endswith("/") else "")
    atuais = [tmp_path / "JogoB"]

    assert conferencia.redirecionamentos([caminho], tmp_path / "casa", atuais) == [
        (velho.as_posix(), (tmp_path / "JogoB").as_posix())
    ]


def test_marcador_sem_diferenca_de_maiusculas(tmp_path):
    velho = tmp_path / "JogoA"
    caminho = f"{velho.as_posix()}/STEAM_SETTINGS/480/a.ini"

    assert conferencia.redirecionamentos([caminho], tmp_path / "casa", [tmp_path / "JogoB"]) == [
        (velho.as_posix(), (tmp_path / "JogoB").as_posix())
    ]


def test_pasta_do_jogo_sem_marcador_nao_redireciona(tmp_path):
    velho = tmp_path / "JogoA"
    caminhos = [f"{velho.as_posix()}/save/a.sav"]

    assert conferencia.redirecionamentos(caminhos, tmp_path / "casa", [tmp_path / "JogoB"]) == []


def test_pasta_do_jogo_que_existe_nao_redireciona(tmp_path):
    velho = tmp_path / "JogoA"
    velho.mkdir()
    caminhos = [f"{velho.as_posix()}/steam_settings/480/a.ini"]

    assert conferencia.redirecionamentos(caminhos, tmp_path / "casa", [tmp_path / "JogoB"]) == []


def test_pasta_do_jogo_igual_a_atual_nao_redireciona(tmp_path):
    atual = tmp_path / "JogoA"  # nem existe: o que vale é ser a mesma pasta
    caminhos = [f"{atual.as_posix()}/steam_settings/480/a.ini"]

    assert conferencia.redirecionamentos(caminhos, tmp_path / "casa", [atual]) == []


def test_sem_pasta_atual_do_jogo_nao_redireciona(tmp_path):
    caminhos = [f"{(tmp_path / 'JogoA').as_posix()}/steam_settings/480/a.ini"]

    assert conferencia.redirecionamentos(caminhos, tmp_path / "casa", []) == []


def test_usuarios_vem_antes_da_pasta_do_jogo(tmp_path):
    velho = tmp_path / "JogoA"
    caminhos = [
        f"{velho.as_posix()}/Profile/a.sav",
        "C:/Users/NaoExiste123/AppData/b.sav",
    ]

    assert conferencia.redirecionamentos(caminhos, CASA, [tmp_path / "JogoB"]) == [
        ("C:/Users/NaoExiste123", "C:/Users/João"),
        (velho.as_posix(), (tmp_path / "JogoB").as_posix()),
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
    )


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
