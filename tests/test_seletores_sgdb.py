# test_seletores_sgdb.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Os seletores de capa e de logo do SteamGridDB (`kyron.modelos.seletores`).

Nenhum teste fala com a rede: o SteamGridDB e o download são falsos. Os modelos são testados sem
tela; a interface (`SeletorDeImagens.qml`) tem os seus testes em `test_qml_edicao.py`.
"""

import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from kyron import shared
from kyron.modelos import seletores
from kyron.utils.name_cleaner import clean_for_search
from kyron.utils.busca_do_seletor import tamanho_baixado
from kyron.utils.steamgriddb import SgdbAuthError, SgdbError
from tests.apoio_seletores import (  # noqa: F401  (as fixtures vêm junto)
    Destino,
    SgdbFalso,
    baixar,
    chave,
    criar as _criar,
    esperar as _esperar,
    lista_de_grades,
    lista_de_logos,
    png_bytes,
    prontos as _prontos,
    temp,
    vazio_de as _vazio_de,
)

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(params=[seletores.SeletorDoSgdb, seletores.SeletorDeLogo], ids=["capa", "logo"])
def classe(request):
    return request.param


def test_busca_com_atraso_descarta_a_velha(classe, baixar, temp):
    sgdb = SgdbFalso()
    seletor, _ = _criar(classe, sgdb)
    seletor.abrir("Jogo")
    assert _esperar(lambda: _prontos(seletor, 3))
    # Digitar rápido: só a última consulta sai, depois do atraso.
    seletor.busca = "Jogo A"
    seletor.busca = "Jogo AB"
    assert sgdb.consultas == ["Jogo"]
    assert _esperar(lambda: sgdb.consultas == ["Jogo", "Jogo AB"])
    assert _esperar(lambda: _prontos(seletor, 3))
    # Uma busca nova invalida a que ainda corre: o resultado velho é descartado e o arquivo dele apagado.
    seletor.busca = "lento"
    seletor.buscarAgora()
    assert _esperar(lambda: "lento" in sgdb.consultas)
    seletor.busca = "Novo"
    seletor.buscarAgora()
    assert _esperar(lambda: _prontos(seletor, 3))
    sgdb.lento.set()
    assert _esperar(lambda: False, 0.4) is False
    assert seletor.rowCount() == 3
    assert not any("velh" in u for u in baixar.urls)
    seletor.fechar()


def test_escolher_entrega_o_arquivo(classe, baixar, temp):
    seletor, destino = _criar(classe)
    seletor.abrir("Jogo")
    assert _esperar(lambda: _prontos(seletor, 3))
    seletor.escolher(1)
    assert _esperar(lambda: destino.capas or destino.logos)
    (entregue,) = destino.capas or destino.logos
    # O original baixado é um temporário em %TEMP% (fora da pasta do seletor), de quem recebe.
    assert entregue.is_file() and entregue.parent == temp and entregue.suffix == ".png"
    assert entregue.read_bytes() == png_bytes()
    assert baixar.urls[-1].endswith("1.png") and not baixar.urls[-1].endswith("-t.png")
    assert seletor.aberto is False and seletor.baixando is False
    # As miniaturas do seletor saíram com ele: sobra só o entregue.
    assert _vazio_de(temp) == [entregue.name]


def test_as_linhas_entram_uma_a_uma_quando_a_miniatura_chega(classe, baixar, temp):
    """Até a primeira miniatura, o seletor só busca (spinner central); a linha entra quando a miniatura chega."""
    seletor, _ = _criar(classe)
    baixar.soltar.clear()
    seletor.abrir("Jogo")
    assert baixar.comecou.wait(5)
    assert seletor.buscando is True and seletor.rowCount() == 0
    baixar.soltar.set()
    assert _esperar(lambda: _prontos(seletor, 3))
    assert seletor.rowCount() == 3 and seletor.buscando is False
    seletor.fechar()


def test_escolher_nao_interrompe_as_miniaturas(baixar, temp, monkeypatch):
    """A escolha tem a sua geração; a miniatura que faltava chega durante o download e depois dele."""
    import threading  # noqa: PLC0415

    liberar = threading.Event()

    def download(url, timeout=10, max_bytes=0, ao_progredir=None):
        if url.endswith("2-t.png"):
            assert liberar.wait(5)
        return baixar(url, timeout, max_bytes, ao_progredir)

    monkeypatch.setattr(seletores, "download_bytes", download)
    seletor, destino = _criar(seletores.SeletorDoSgdb)
    destino.convertida = False  # a escolha volta à grade, e a terceira miniatura ainda não veio
    seletor.abrir("Jogo")
    assert _esperar(lambda: seletor.rowCount() == 2)
    seletor.escolher(0)
    assert _esperar(lambda: destino.capas)
    assert _esperar(lambda: seletor.baixando is False)
    assert seletor.aberto is True and seletor.buscando is True and seletor.rowCount() == 2
    liberar.set()
    assert _esperar(lambda: seletor.rowCount() == 3 and seletor.buscando is False)
    seletor.fechar()


def test_fechar_o_seletor_durante_a_conversao_mantem_a_capa_do_editor(edicao, temp, monkeypatch):
    """Quem desistiu (fechou o seletor) não vê a capa mudar depois; nada de temporário sobra."""
    import threading  # noqa: PLC0415

    from kyron import edicao as regra  # noqa: PLC0415

    liberar = threading.Event()
    original = regra.preparar_capa

    def devagar(arquivo):
        assert liberar.wait(5)
        return original(arquivo)

    monkeypatch.setattr(regra, "preparar_capa", devagar)
    seletor = edicao.seletorDeCapa
    seletor.abrir("Jogo")
    assert _esperar(lambda: _prontos(seletor, 3))
    seletor.escolher(0)
    assert _esperar(lambda: edicao.convertendoCapa)
    seletor.fechar()
    liberar.set()
    assert _esperar(lambda: not edicao.convertendoCapa)
    assert edicao.temCapa is False
    edicao.cancelar()
    assert _vazio_de(temp) == []


def test_enter_no_campo_busca_mesmo_durante_o_download(baixar, temp):
    """O campo está ativo, então o Enter também busca (a busca nova cancela o download)."""
    seletor, _ = _criar(seletores.SeletorDoSgdb)
    seletor.abrir("Jogo")
    assert _esperar(lambda: _prontos(seletor, 3))
    baixar.soltar.clear()
    baixar.comecou.clear()
    seletor.escolher(0)
    assert _esperar(baixar.comecou.is_set) and seletor.baixando is True
    seletor.buscarAgora()
    assert seletor.baixando is False
    baixar.soltar.set()
    seletor.fechar()


def test_capa_que_nao_converte_volta_a_grade(baixar, temp):
    """O seletor da capa só fecha com a capa pronta; se a conversão falha, a grade volta."""
    seletor, destino = _criar(seletores.SeletorDoSgdb)
    destino.convertida = False
    seletor.abrir("Jogo")
    assert _esperar(lambda: _prontos(seletor, 3))
    seletor.escolher(1)
    assert _esperar(lambda: destino.capas)
    assert _esperar(lambda: seletor.baixando is False)
    assert seletor.aberto is True and seletor.vazio is False and seletor.rowCount() == 3
    seletor.fechar()


def test_fechar_com_download_cancela_e_limpa(classe, baixar, temp, app_dirs):
    seletor, destino = _criar(classe)
    seletor.abrir("Jogo")
    assert _esperar(lambda: _prontos(seletor, 3))
    baixar.soltar.clear()
    baixar.comecou.clear()
    seletor.escolher(0)
    assert _esperar(baixar.comecou.is_set) and seletor.baixando is True
    seletor.fechar()
    # O download é cancelado pelo progresso; nada chega a uma tela fechada.
    assert baixar.cancelado.wait(5)
    assert _esperar(lambda: False, 0.3) is False
    assert destino.capas == [] and destino.logos == []
    for pasta in (shared.covers_dir, shared.logos_dir, shared.wallpapers_dir, temp):
        assert _vazio_de(pasta) == [], pasta


def test_fechar_com_previas_a_caminho_limpa(classe, baixar, temp):
    seletor, destino = _criar(classe)
    baixar.soltar.clear()
    seletor.abrir("Jogo")
    assert baixar.comecou.wait(5)
    seletor.fechar()
    baixar.soltar.set()
    assert _esperar(lambda: False, 0.5) is False
    assert _vazio_de(temp) == [] and seletor.rowCount() == 0
    assert destino.capas == [] and destino.logos == []


def test_resultado_atrasado_nao_entra_em_outra_abertura(classe, baixar, temp):
    seletor, _ = _criar(classe)
    baixar.soltar.clear()
    seletor.abrir("Jogo")
    assert baixar.comecou.wait(5)
    seletor.fechar()
    seletor.abrir("Outro")
    baixar.soltar.set()
    assert _esperar(lambda: _prontos(seletor, 3))
    seletor.fechar()
    assert _vazio_de(temp) == []


def test_sem_resultado_mostra_vazio(classe, baixar, temp):
    seletor, _ = _criar(classe, SgdbFalso(grids=[], logos=[]))
    seletor.abrir("Jogo")
    assert _esperar(lambda: seletor.vazio)
    assert seletor.erro is False and seletor.buscando is False
    nada = "Nenhuma capa encontrada" if classe is seletores.SeletorDoSgdb else "Nenhum logo encontrado"
    assert (seletor.tituloDoEstado, seletor.descricaoDoEstado) == (nada, "Tente buscar por outro nome.")
    seletor.fechar()
    assert _vazio_de(temp) == []


def test_busca_vazia_e_sem_chave(classe, baixar, schema):
    seletor, _ = _criar(classe)
    seletor.abrir("")
    assert seletor.vazio and seletor.tituloDoEstado == "Digite o nome de um jogo"
    schema.set_string("sgdb-key", "")
    seletor.busca = "Jogo"
    seletor.buscarAgora()
    assert seletor.tituloDoEstado == "Chave da API não configurada"
    assert seletor.descricaoDoEstado == "Configure a chave da API do SteamGridDB nas Preferências."
    assert seletor.sgdb.consultas == []
    seletor.fechar()


def test_chave_invalida_mostra_erro(classe, baixar, temp):
    seletor, _ = _criar(classe, SgdbFalso(erro=SgdbAuthError("x")))
    seletor.abrir("Jogo")
    assert _esperar(lambda: seletor.erro)
    assert seletor.vazio is True
    assert (seletor.tituloDoEstado, seletor.descricaoDoEstado) == (
        "Chave da API inválida",
        "Verifique a chave da API do SteamGridDB nas Preferências.",
    )
    seletor.sgdb.erro = SgdbError("fora do ar")
    seletor.buscarAgora()
    assert _esperar(lambda: seletor.tituloDoEstado == "Não foi possível concluir a busca")
    assert seletor.descricaoDoEstado == "Verifique a conexão e tente novamente." and seletor.erro is True
    seletor.fechar()


def test_download_que_falha_mostra_erro_e_nao_entrega(classe, baixar, temp):
    import requests  # noqa: PLC0415

    seletor, destino = _criar(classe)
    seletor.abrir("Jogo")
    assert _esperar(lambda: _prontos(seletor, 3))
    baixar.falhar = requests.RequestException("x")
    seletor.escolher(0)
    assert _esperar(lambda: seletor.erro)
    esperado = "Não foi possível baixar a capa" if classe is seletores.SeletorDoSgdb else "Não foi possível baixar o logo"
    assert seletor.tituloDoEstado == esperado
    assert seletor.descricaoDoEstado == "Tente novamente."
    assert seletor.baixando is False and seletor.aberto is True
    assert destino.capas == [] and destino.logos == []
    seletor.fechar()
    assert _vazio_de(temp) == []


def test_animadas_filtra(baixar, temp, schema):
    sgdb = SgdbFalso(grids=lista_de_grades(20))
    seletor, _ = _criar(seletores.SeletorDoSgdb, sgdb)
    seletor.abrir("Jogo")
    assert _esperar(lambda: _prontos(seletor, 20))
    assert seletor.animadas is False
    assert sgdb.grids_pedidas == [(1, False, seletores.PORTRAIT_DIMENSIONS)]
    assert all("-t.png" in u for u in baixar.urls), "parada: a miniatura leve"
    assert not any(seletor.data(seletor.index(i, 0), seletor.Papel.Animada) for i in range(20))
    baixar.urls.clear()
    seletor.animadas = True
    assert _esperar(lambda: _prontos(seletor, 12))
    # Animadas: o pedido muda, são menos e a prévia é a própria imagem animada.
    assert sgdb.grids_pedidas[-1] == (1, True, seletores.PORTRAIT_DIMENSIONS)
    assert all(not u.endswith("-t.png") for u in baixar.urls)
    assert all(seletor.data(seletor.index(i, 0), seletor.Papel.Animada) for i in range(12))
    assert baixar.limites[-1] == seletores.MAX_ANIMATED_IMAGE_BYTES
    seletor.fechar()


def test_a_previa_animada_so_toca_a_copia_reduzida(baixar, temp, schema, monkeypatch):
    """A original (até 200 MB) nunca é fonte animada; só a cópia reduzida, quando chega."""
    pedidos = []
    monkeypatch.setattr(seletores.copias_animadas, "pedir", lambda origem, destino, tamanho, pronto: pedidos.append((destino, pronto)))
    seletor, _ = _criar(seletores.SeletorDoSgdb, SgdbFalso(grids=lista_de_grades(2)))
    seletor.animadas = True  # sem aberto, não faz nada: abre antes
    seletor.abrir("Jogo")
    seletor.animadas = True
    assert _esperar(lambda: _prontos(seletor, 2) and len(pedidos) == 2)
    copia = lambda i: seletor.data(seletor.index(i, 0), seletor.Papel.CopiaAnimada)  # noqa: E731
    assert copia(0) == "" and copia(1) == ""
    destino, pronto = pedidos[0]
    pronto("falhou")
    assert copia(0) == ""
    pronto("pronta")
    assert copia(0).endswith(destino.name)
    seletor.fechar()


def test_animadas_comeca_pela_preferencia(baixar, temp, schema):
    schema.set_boolean("sgdb-animated", True)
    seletor, _ = _criar(seletores.SeletorDoSgdb)
    seletor.abrir("Jogo")
    assert seletor.animadas is True
    assert _esperar(lambda: _prontos(seletor, 3))
    seletor.fechar()


def test_usar_o_titulo(baixar, temp):
    seletor, destino = _criar(seletores.SeletorDeLogo)
    seletor.abrir("Jogo")
    assert _esperar(lambda: _prontos(seletor, 3))
    seletor.usarTitulo()
    assert destino.titulos == 1 and seletor.aberto is False
    assert _vazio_de(temp) == []


def test_o_campo_vem_com_o_nome_limpo(classe, baixar, temp):
    sgdb = SgdbFalso()
    seletor, _ = _criar(classe, sgdb)
    seletor.abrir("  The Game (2020)  ")
    assert seletor.busca == seletores.clean_game_name("  The Game (2020)  ") != ""
    seletor.fechar()


def test_logos_vem_na_ordem_da_pagina(baixar, temp):
    # O que a página escolheria sozinha vem primeiro; os outros não são filtrados.
    logos = [
        {"id": 1, "url": "https://x/l1.png", "thumb": "https://x/l1-t.png", "style": "white", "width": 600, "height": 200, "score": 1, "mime": "image/png"},
        {"id": 2, "url": "https://x/l2.png", "thumb": "https://x/l2-t.png", "style": "official", "width": 600, "height": 200, "score": 50, "mime": "image/png"},
    ]  # fmt: skip
    seletor, _ = _criar(seletores.SeletorDeLogo, SgdbFalso(logos=logos))
    seletor.abrir("Jogo")
    assert _esperar(lambda: _prontos(seletor, 2))
    assert [u[-8:] for u in baixar.urls] == ["l2-t.png", "l1-t.png"]
    seletor.fechar()


def test_busca_do_seletor_sem_gi():
    codigo = (
        "import builtins, sys; builtins._ = lambda m: m; sys.path.insert(0, sys.argv[1]);"
        "import kyron.utils.busca_do_seletor, kyron.modelos.seletores;"
        "sys.exit(1 if 'gi' in sys.modules else 0)"
    )
    resultado = subprocess.run([sys.executable, "-c", codigo, str(RAIZ)], capture_output=True, text=True, check=False)
    assert resultado.returncode == 0, resultado.stderr


# -- ligação com o `ModeloDaEdicao` -----------------------------------------------------------------


@pytest.fixture
def edicao(app_qt, store, baixar, temp):
    from kyron.modelos.edicao import ModeloDaEdicao  # noqa: PLC0415

    modelo = ModeloDaEdicao(SimpleNamespace(pedir_dialogo=lambda *a: None))
    for seletor in (modelo.seletorDeCapa, modelo.seletorDeLogo):
        seletor.sgdb = SgdbFalso()
    modelo.adicionar()
    yield modelo
    modelo.cancelar()


def test_capa_baixada_vira_provisoria_da_edicao(edicao, temp):
    seletor = edicao.seletorDeCapa
    seletor.abrir("Jogo")
    assert _esperar(lambda: _prontos(seletor, 3))
    seletor.escolher(0)
    assert _esperar(lambda: edicao.temCapa and not edicao.ocupado)
    provisoria = edicao._form.capa  # noqa: SLF001
    # O original baixado saiu; ficou só a capa pronta (TIFF), que é da edição até o Aplicar.
    assert provisoria.suffix == ".tiff" and _vazio_de(temp) == [provisoria.name]
    edicao.cancelar()
    assert _vazio_de(temp) == []


def test_capa_baixada_com_a_edicao_fechada_e_descartada(edicao, temp):
    edicao.cancelar()
    arquivo = temp / "baixada.png"
    arquivo.write_bytes(png_bytes())
    edicao.entregar_capa_baixada(arquivo)
    assert not arquivo.exists()


def test_logo_baixado_vira_escolha_temporaria(edicao, temp):
    seletor = edicao.seletorDeLogo
    seletor.abrir("Jogo")
    assert _esperar(lambda: _prontos(seletor, 3))
    seletor.escolher(0)
    assert _esperar(lambda: edicao._form.logo is not None)  # noqa: SLF001
    escolha = edicao._form.logo  # noqa: SLF001
    assert (escolha.modo, escolha.temporario) == ("manual", True) and escolha.arquivo.is_file()
    assert edicao.logoSubtitulo == "Escolhido manualmente"
    edicao.cancelar()
    assert _vazio_de(temp) == []


def test_usar_o_titulo_vira_escolha_de_titulo(edicao):
    seletor = edicao.seletorDeLogo
    seletor.abrir("Jogo")
    seletor.usarTitulo()
    assert edicao._form.logo.modo == "title"  # noqa: SLF001
    assert edicao.logoSubtitulo == "Sem logo; o título é exibido"


def test_download_com_a_edicao_morta_apaga_o_temporario(classe, baixar, temp):
    seletor = classe(Destino())  # sem referência forte: o destino morre ao fim da linha
    seletor.sgdb = SgdbFalso()
    seletor.abrir("Jogo")
    assert _esperar(lambda: _prontos(seletor, 3))
    seletor.escolher(0)
    assert _esperar(lambda: not seletor.aberto)
    assert _vazio_de(temp) == []


def test_busca_com_resposta_inesperada_nao_deixa_carregando(classe, baixar, temp):
    seletor, _ = _criar(classe, SgdbFalso(grids=[1], logos=[1]))
    seletor.abrir("Jogo")
    assert _esperar(lambda: seletor.erro)
    assert seletor.buscando is False and seletor.tituloDoEstado == "Não foi possível concluir a busca"
    seletor.fechar()


def test_download_que_estoura_nao_deixa_baixando(classe, baixar, temp):
    seletor, destino = _criar(classe)
    seletor.abrir("Jogo")
    assert _esperar(lambda: _prontos(seletor, 3))
    baixar.falhar = ValueError("inesperado")
    seletor.escolher(0)
    assert _esperar(lambda: seletor.erro)
    assert seletor.baixando is False and destino.capas == [] and destino.logos == []
    seletor.fechar()


# -- o tamanho baixado ("Baixando…") e o nome da prévia --------------------------------------------

MB = 1024 * 1024
FUGA = "..{0}..{0}fuga".format(chr(92))  # um id de API com barras invertidas


def test_formata_mb_com_virgula():
    assert tamanho_baixado(4_582_277, 21 * MB) == "4,4 MB de 21,0 MB"


def test_formata_kb_abaixo_de_um_mega():
    assert tamanho_baixado(40 * 1024, 512 * 1024) == "40 KB de 512 KB"
    assert tamanho_baixado(MB, None) == "1,0 MB"


def test_kb_arredonda_para_cima():
    assert tamanho_baixado(300, None) == "1 KB"
    assert tamanho_baixado(1536, 4096) == "2 KB de 4 KB"


def test_quase_um_mega_ja_e_mb():
    assert tamanho_baixado(1_048_000, None) == "1,0 MB"


def test_previa_do_sgdb_fica_na_pasta_temporaria(classe, baixar, temp):
    # O id e o endereço da API nunca viram nome de arquivo: um id "..\x" gravava fora da pasta.
    sgdb = SgdbFalso(
        grids=[{"id": FUGA, "url": "https://x/a.png", "thumb": "https://x/t/x.bat"}],
        logos=[{"id": FUGA, "url": "https://x/a.png", "thumb": "https://x/t/x.bat", "style": "white",
                "width": 600, "height": 200, "score": 1, "mime": "image/png"}],
    )  # fmt: skip
    seletor, _ = _criar(classe, sgdb)
    seletor.abrir("Jogo")
    assert _esperar(lambda: _prontos(seletor, 1))

    arquivos = [p for p in temp.rglob("*") if p.is_file()]
    assert len(arquivos) == 1
    assert arquivos[0].suffix == ".png" and "fuga" not in str(arquivos[0].relative_to(temp))
    assert temp in arquivos[0].parents
    seletor.fechar()


class _SgdbComJogos(SgdbFalso):
    def __init__(self, jogos):
        super().__init__()
        self.jogos = jogos

    def search_games(self, consulta):
        self.consultas.append(consulta)
        return self.jogos


def _primeiro(jogos, consulta):
    seletor, _ = _criar(seletores.SeletorDoSgdb, _SgdbComJogos(jogos))
    return seletor._primeiro_id(consulta), seletor.sgdb


def test_primeiro_id_escolhe_como_o_caminho_automatico():
    achado, _ = _primeiro([{"id": 111, "name": "Halo Infinite Multiplayer"}, {"id": 222, "name": "Halo"}], "Halo")
    assert achado == 222


def test_primeiro_id_limpa_a_consulta():
    _, sgdb = _primeiro([{"id": 1, "name": "Assassin's Creed Shadows"}], "Assassin’s Creed Shadows")
    assert sgdb.consultas == [clean_for_search("Assassin’s Creed Shadows")]


def test_primeiro_id_sem_ninguem_no_ranking_fica_com_o_primeiro():
    achado, _ = _primeiro([{"id": 7, "name": "Totalmente Outro"}, {"id": 8, "name": "Nada A Ver"}], "Halo")
    assert achado == 7


def test_primeiro_id_ignora_item_sem_id():
    achado, _ = _primeiro([{"name": "Halo"}, "lixo", {"id": 5, "name": "Halo"}], "Halo")
    assert achado == 5
