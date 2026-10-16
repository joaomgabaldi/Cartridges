import os
from pathlib import Path

import pytest

from cartridges.conquistas.ea import jogo
from cartridges.conquistas.ea.jogo import Candidato, candidato, normalizar

# O conftest troca `jogo.chaves_do_registro` por um stub; este teste usa a função de verdade.
_CHAVES_REAL = jogo.chaves_do_registro


def _xml(pasta: Path, corpo: str) -> None:
    (pasta / "__Installer").mkdir(parents=True, exist_ok=True)
    (pasta / "__Installer" / "installerdata.xml").write_text(corpo, encoding="utf-8")


def _titulos(pt: str = "", en: str = "") -> str:
    itens = ""
    if pt:
        itens += f'<gameTitle locale="pt_BR">{pt}</gameTitle>'
    if en:
        itens += f'<gameTitle locale="en_US">{en}</gameTitle>'
    return f"<DiPManifest><gameTitles>{itens}</gameTitles></DiPManifest>"


def _chaves(*itens):
    return lambda: list(itens)


@pytest.mark.parametrize(
    "titulo, esperado",
    [
        ("STAR WARS™ Battlefront™ II", "starwarsbattlefrontii"),
        ("Star Wars: Battlefront II", "starwarsbattlefrontii"),
        ("Battlefield™ 6", "battlefield6"),
        ("Edição Deluxe", "edicaodeluxe"),
        ("FIFA™ 23", "fifa23"),
    ],
)
def test_normalizar(titulo, esperado):
    assert normalizar(titulo) == esperado


def test_candidato_pela_chave(tmp_path):
    _xml(tmp_path, _titulos(pt="Battlefield™ 6", en="Battlefield 6 EN"))
    achado = candidato([tmp_path], _chaves(("DisplayName", str(tmp_path))))
    assert achado == Candidato(
        pasta=os.path.normcase(str(tmp_path.resolve())),
        titulo="Battlefield™ 6",
        titulos=("Battlefield™ 6", "Battlefield 6 EN", "DisplayName"),
    )


def test_sem_chave_nao_e_candidato_mesmo_com_installerdata(tmp_path):
    _xml(tmp_path, _titulos(pt="Jogo"))
    assert candidato([tmp_path], _chaves()) is None


def test_install_dir_sem_caixa_e_barra(tmp_path):
    pasta = tmp_path / "STAR WARS Battlefront II"
    pasta.mkdir()
    texto = str(tmp_path / "STAR WARS BATTLEFRONT II") + "\\"
    assert candidato([pasta], _chaves(("SW", texto))) is not None


def test_install_dir_raiz_ignorada(tmp_path):
    raiz = Path(tmp_path.anchor)
    assert candidato([raiz, tmp_path], _chaves(("X", str(raiz)))) is None


def test_casa_com_pasta_acima(tmp_path):
    exe = tmp_path / "Bin"
    exe.mkdir()
    _xml(tmp_path, _titulos(pt="Jogo"))
    achado = candidato([exe, tmp_path], _chaves(("DN", str(tmp_path))))
    assert achado is not None and achado.titulo == "Jogo"


def test_titulo_en_us_e_displayname_de_reserva(tmp_path):
    _xml(tmp_path, _titulos(en="So em ingles"))
    assert candidato([tmp_path], _chaves(("DN", str(tmp_path)))).titulo == "So em ingles"
    sem = tmp_path / "sem"
    sem.mkdir()
    assert candidato([sem], _chaves(("Nome do Registro", str(sem)))).titulo == "Nome do Registro"


def test_installerdata_grande_ou_quebrado(tmp_path):
    grande = tmp_path / "grande"
    _xml(grande, _titulos(pt="Grande") + " " * (2 * 1024 * 1024 + 1))
    assert candidato([grande], _chaves(("DN-grande", str(grande)))).titulo == "DN-grande"
    quebrado = tmp_path / "quebrado"
    _xml(quebrado, "<DiPManifest><gameTitles>")
    assert candidato([quebrado], _chaves(("DN-q", str(quebrado)))).titulo == "DN-q"
    medio = tmp_path / "medio"
    _xml(medio, _titulos(pt="Medio") + "<!--" + "x" * 400_000 + "-->")
    assert candidato([medio], _chaves(("DN", str(medio)))).titulo == "Medio"


def test_installerdata_com_codificacao_desconhecida(tmp_path):
    _xml(tmp_path, '<?xml version="1.0" encoding="foo-bar"?><a/>')
    assert candidato([tmp_path], _chaves(("DN", str(tmp_path)))).titulo == "DN"


def test_titulos_sem_repetir_os_normalizados(tmp_path):
    _xml(tmp_path, _titulos(pt="Battlefield™ 6", en="Battlefield 6"))
    achado = candidato([tmp_path], _chaves(("BATTLEFIELD 6", str(tmp_path))))
    assert achado.titulos == ("Battlefield™ 6",) and achado.titulo == "Battlefield™ 6"


def test_installerdata_ausente_nao_loga(tmp_path, caplog):
    caplog.set_level("DEBUG")
    achado = candidato([tmp_path], _chaves(("DN", str(tmp_path))))
    assert achado.titulo == "DN" and achado.titulos == ("DN",)
    assert caplog.text == ""


def test_chave_ruim_nao_derruba_as_outras(tmp_path):
    achado = candidato([tmp_path], _chaves(("Ruim", None), ("Bom", str(tmp_path))))
    assert achado is not None and achado.titulo == "Bom"


def test_vista_do_registro_sem_permissao_nao_derruba_a_outra(monkeypatch):
    abertas = []

    def abrir(_raiz, caminho, *_a):
        abertas.append(caminho)
        raise PermissionError("negado")

    monkeypatch.setattr(jogo.winreg, "OpenKey", abrir)
    assert _CHAVES_REAL() == []
    assert len(abertas) == 2


def test_registro_com_erro(tmp_path):
    def falha():
        raise OSError("sem registro")

    assert candidato([tmp_path], falha) is None


def test_chaves_do_registro_sem_winreg_nao_levanta(monkeypatch):
    def falha(*_):
        raise OSError

    monkeypatch.setattr(jogo.winreg, "OpenKey", falha)
    assert _CHAVES_REAL() == []
