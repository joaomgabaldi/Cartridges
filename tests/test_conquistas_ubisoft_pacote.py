"""O catálogo de um jogo da Ubisoft Connect a partir do ZIP do launcher."""

import os

from cartridges import shared
from cartridges.conquistas import catalogo
from cartridges.conquistas.ubisoft import pacote
from tests.apoio_conquistas import PNG_MINIMO, gravar_pacote, pastas  # noqa: F401

PT = {
    1: ("Último a Sair", "Sente-se em um navio em chamas"),
    12: ("Silêncio!", "Mate um guarda que estiver tocando um sino"),
}
EN = {1: ("Last One Out", "Sit on a burning ship"), 12: ("Silence!", "Kill a guard ringing a bell")}


def test_catalogo_em_portugues_com_icones(pastas):  # noqa: F811
    gravar_pacote(pastas, "65043", {"en-US": EN, "pt-BR": PT})
    cat, refeito = pacote.obter("65043")
    assert refeito
    assert [(i.nome, i.titulo, i.descricao) for i in cat.conquistas] == [
        ("UBI:1", "Último a Sair", "Sente-se em um navio em chamas"),
        ("UBI:12", "Silêncio!", "Mate um guarda que estiver tocando um sino"),
    ]
    icone = shared.conquistas_cache_dir / "ubisoft" / "65043" / "12.png"
    assert cat.conquistas[1].icone == str(icone)
    assert icone.read_bytes() == PNG_MINIMO
    assert all(i.icone_cinza == "" and not i.oculta and i.porcentagem is None for i in cat.conquistas)
    assert catalogo.em_cache("ubisoft-65043") == cat
    assert pacote.chave("65043") == "ubisoft-65043"


def test_sem_portugues_usa_ingles(pastas):  # noqa: F811
    gravar_pacote(pastas, "65043", {"fr-FR": {1: ("Fr", "")}, "en-US": EN})
    assert pacote.obter("65043")[0].conquistas[0].titulo == "Last One Out"


def test_sem_portugues_nem_ingles_usa_o_primeiro_em_ordem(pastas):  # noqa: F811
    gravar_pacote(pastas, "65043", {"ja-JP": {1: ("Ja", "")}, "de-DE": {1: ("De", "")}})
    assert pacote.obter("65043")[0].conquistas[0].titulo == "De"


def test_linhas_estranhas_e_zeros_a_esquerda(pastas):  # noqa: F811
    texto = "﻿\n007\tSete\tCom\ttab\nlixo\n\n8\tsó dois\nx\tA\tB\n9\tNove\tN\n"
    gravar_pacote(pastas, "65043", {}, pngs=[], extras={"pt-BR_loc.txt": texto.encode("utf-8")})
    cat, _refeito = pacote.obter("65043")
    assert [(i.nome, i.titulo, i.descricao, i.icone) for i in cat.conquistas] == [
        ("UBI:7", "Sete", "Com\ttab", ""),
        ("UBI:9", "Nove", "N", ""),
    ]


def test_nome_com_barra_ou_ponto_ponto_e_ignorado(pastas):  # noqa: F811
    gravar_pacote(
        pastas,
        "65043",
        {"pt-BR": PT},
        pngs=[],
        extras={"../1.png": PNG_MINIMO, "x/12.png": PNG_MINIMO, "pt/pt-BR_loc.txt": b"1\tX\tY"},
    )
    cat, _refeito = pacote.obter("65043")
    assert all(i.icone == "" for i in cat.conquistas)
    assert cat.conquistas[0].titulo == "Último a Sair"
    assert not (shared.conquistas_cache_dir / "ubisoft" / "1.png").exists()


def test_png_grande_demais_fica_sem_icone(pastas, monkeypatch):  # noqa: F811
    monkeypatch.setattr(pacote, "_PNG_MAXIMO", 4)  # o PNG de teste tem 8 bytes
    gravar_pacote(pastas, "65043", {"pt-BR": PT})
    cat, _refeito = pacote.obter("65043")
    assert [i.icone for i in cat.conquistas] == ["", ""]


def test_idioma_grande_demais_e_pulado(pastas, monkeypatch):  # noqa: F811
    monkeypatch.setattr(pacote, "_LOC_MAXIMO", 30)
    gravar_pacote(pastas, "65043", {"pt-BR": PT, "en-US": {1: ("A", "")}})
    assert [i.titulo for i in pacote.obter("65043")[0].conquistas] == ["A"]


def test_entradas_demais_mantem_o_cache(pastas, monkeypatch):  # noqa: F811
    gravar_pacote(pastas, "65043", {"pt-BR": PT})
    guardado, _refeito = pacote.obter("65043")
    monkeypatch.setattr(pacote, "_ENTRADAS_MAXIMAS", 2)
    caminho = gravar_pacote(pastas, "65043", {"pt-BR": EN})
    os.utime(caminho, (4_000_000_000, 4_000_000_000))  # mais novo que o cache
    assert pacote.obter("65043") == (guardado, False)


def test_zip_corrompido_sem_cache_e_none(pastas):  # noqa: F811
    caminho = gravar_pacote(pastas, "65043", {"pt-BR": PT})
    caminho.write_bytes(b"PK\x03\x04 lixo")
    assert pacote.obter("65043") == (None, False)


def test_zip_sem_idioma_e_ilegivel(pastas):  # noqa: F811
    gravar_pacote(pastas, "65043", {}, pngs=[1])
    assert pacote.obter("65043") == (None, False)


def test_zip_grande_demais(pastas, monkeypatch):  # noqa: F811
    monkeypatch.setattr(pacote, "_ZIP_MAXIMO", 10)
    gravar_pacote(pastas, "65043", {"pt-BR": PT})
    assert pacote.obter("65043") == (None, False)


def test_cache_reaproveitado_enquanto_o_zip_nao_muda(pastas, monkeypatch):  # noqa: F811
    gravar_pacote(pastas, "65043", {"pt-BR": PT})
    primeiro, refeito = pacote.obter("65043")
    assert refeito
    chamadas = []
    real = pacote._montar
    monkeypatch.setattr(pacote, "_montar", lambda *argumentos: chamadas.append(argumentos) or real(*argumentos))
    assert pacote.obter("65043") == (primeiro, False)
    assert chamadas == []


def test_zip_mais_novo_refaz(pastas):  # noqa: F811
    gravar_pacote(pastas, "65043", {"pt-BR": PT})
    pacote.obter("65043")
    caminho = gravar_pacote(pastas, "65043", {"pt-BR": EN})
    os.utime(caminho, (4_000_000_000, 4_000_000_000))
    cat, refeito = pacote.obter("65043")
    assert refeito and cat.conquistas[0].titulo == "Last One Out"


def test_sem_zip_devolve_o_cache(pastas):  # noqa: F811
    caminho = gravar_pacote(pastas, "65043", {"pt-BR": PT})
    cat, _refeito = pacote.obter("65043")
    caminho.unlink()
    assert pacote.obter("65043") == (cat, False)


def test_sem_nada_e_none(pastas):  # noqa: F811
    assert pacote.obter("65043") == (None, False)


def test_falha_inesperada_nao_levanta(pastas, monkeypatch):  # noqa: F811
    gravar_pacote(pastas, "65043", {"pt-BR": PT})
    monkeypatch.setattr(pacote, "_montar", lambda *_argumentos: 1 / 0)
    assert pacote.obter("65043") == (None, False)
