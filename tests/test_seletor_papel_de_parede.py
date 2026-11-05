# test_seletor_papel_de_parede.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O seletor do papel de parede da sessão (`cartridges.modelos.seletores.SeletorDePapelDeParede`).

Nenhum teste fala com a rede: o wallhaven e o download são falsos, e os monitores também (nada aqui depende
da máquina). A interface (`SeletorDePapelDeParede.qml`) tem os seus testes em `test_qml_edicao.py`.
"""

import gc
import io
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageChops, ImageStat
from PySide6.QtCore import QUrl

from cartridges import shared
from cartridges.modelos import seletores
from cartridges.modelos.seletores import SeletorDePapelDeParede
from cartridges.utils.session_wallpaper import Monitor, Posicoes, enquadrar
from cartridges.utils.wallhaven import WallhavenError
from tests.apoio_seletores import (  # noqa: F401  (as fixtures vêm junto)
    DownloadFalso,
    WallhavenFalso,
    lista_do_wallhaven,
    baixar,
    chave,
    esperar as _esperar,
    temp,
    vazio_de as _vazio_de,
)

RAIZ = Path(__file__).resolve().parent.parent

PRINCIPAL = Monitor("1", 0, 0, 1920, 1080)
EM_PE = Monitor("2", 1920, 0, 1080, 1920)
DEITADO = Monitor("3", 3000, 0, 1920, 1080)


def arte_bytes() -> bytes:
    """Larga, metade vermelha e metade azul: a faixa escolhida muda a cor do corte em pé."""
    imagem = Image.new("RGB", (160, 90), "red")
    imagem.paste("blue", (80, 0, 160, 90))
    saida = io.BytesIO()
    imagem.save(saida, "PNG")
    return saida.getvalue()


class DestinoDoPapel:
    def __init__(self):
        self.papeis: list[tuple[Path, Posicoes]] = []
        self.sem_troca = 0

    def entregar_papel_baixado(self, arquivo, posicoes):
        self.papeis.append((arquivo, posicoes))

    def nao_trocar_papel(self):
        self.sem_troca += 1


@pytest.fixture
def wallhaven(monkeypatch):
    falso = WallhavenFalso()
    monkeypatch.setattr(seletores, "buscar", falso)
    return falso


@pytest.fixture
def arte(baixar):
    baixar.conteudo = arte_bytes()
    return baixar


def criar(monitores=(PRINCIPAL, EM_PE)):
    destino = DestinoDoPapel()
    seletor = SeletorDePapelDeParede(destino)
    seletor.monitores = lambda: list(monitores)
    seletor.atraso_da_busca_ms = 40
    return seletor, destino


def prontos(seletor, n=None):
    return (
        not seletor.buscando
        and seletor.rowCount() > 0
        and (n is None or seletor.rowCount() == n)
    )


def miniatura(seletor, linha=0) -> Path:
    url = seletor.data(seletor.index(linha, 0), seletor.Papel.Miniatura)
    return Path(QUrl(url).toLocalFile())


def corte(seletor, linha, papel):
    return seletor.cortes.data(seletor.cortes.index(linha, 0), papel)


def ajustar(seletor, linha=0):
    seletor.escolher(linha)
    assert _esperar(lambda: seletor.ajustando)


def media(caminho) -> tuple[float, float, float]:
    with Image.open(caminho) as imagem:
        return tuple(ImageStat.Stat(imagem.convert("RGB")).mean)


def test_miniatura_e_arquivo_usam_o_mesmo_corte(app_qt, wallhaven, arte, temp):
    seletor, destino = criar()
    seletor.abrir("Jogo")
    assert _esperar(lambda: prontos(seletor, 3))
    # A célula é a tela em miniatura: o formato do monitor em pé, na proporção 9:16.
    assert (seletor.larguraDaCelula, seletor.alturaDaCelula) == (146, 260)
    with Image.open(miniatura(seletor)) as pequena:
        assert pequena.size == (146, 260)
        pequena = pequena.convert("RGB")
    ajustar(seletor)
    seletor.usarEstaImagem()
    arquivo, posicoes = destino.papeis[0]
    # O arquivo final cortado pela mesma `enquadrar`, na faixa da miniatura (o meio): o mesmo quadro.
    with Image.open(arquivo) as original:
        final = enquadrar(original.convert("RGB"), 1080, 1920, posicoes.retrato).resize((146, 260), Image.LANCZOS)
    diferenca = ImageStat.Stat(ImageChops.difference(pequena, final)).mean
    assert max(diferenca) < 12, diferenca
    assert posicoes.retrato == 0.5


def test_o_corte_pede_o_minimo_dos_monitores_e_dois_degraus(app_qt, wallhaven, arte, temp):
    seletor, _ = criar()
    seletor.abrir("Portal")
    assert _esperar(lambda: prontos(seletor, 3))
    # O formato dos monitores primeiro, qualquer formato depois, ambos com o mesmo mínimo.
    assert wallhaven.pedidos == [("Portal", (1080, 1920), "portrait"), ("Portal", (1080, 1920), None)]
    seletor.fechar()


def test_deslizar_muda_a_posicao_do_monitor(app_qt, wallhaven, arte, temp):
    seletor, _ = criar()
    seletor.abrir("Jogo")
    assert _esperar(lambda: prontos(seletor, 3))
    ajustar(seletor)
    cortes = seletor.cortes
    assert cortes.rowCount() == 1
    papeis = cortes.Papel
    assert corte(seletor, 0, papeis.Posicao) == 50 and corte(seletor, 0, papeis.Desliza) is True
    assert corte(seletor, 0, papeis.Dica) == "Arraste para escolher a faixa da imagem"
    seletor.definirPosicao(0, 0)
    vermelho = media(QUrl(corte(seletor, 0, papeis.Previa)).toLocalFile())
    seletor.definirPosicao(0, 100)
    azul = media(QUrl(corte(seletor, 0, papeis.Previa)).toLocalFile())
    assert vermelho[0] > 240 and vermelho[2] < 15
    assert azul[2] > 240 and azul[0] < 15
    # Cada posição mexe só no arquivo da prévia: a anterior sai, nada se acumula.
    assert corte(seletor, 0, papeis.Posicao) == 100
    seletor.fechar()
    assert _vazio_de(temp) == []


def test_arranjo_misto_tem_dois_cortes_e_a_arte_na_proporcao_nao_desliza(app_qt, wallhaven, arte, temp):
    seletor, _ = criar((PRINCIPAL, EM_PE, DEITADO))
    seletor.abrir("Jogo")
    assert _esperar(lambda: prontos(seletor, 3))
    # No arranjo misto a grade é deitada (16:9).
    assert (seletor.larguraDaCelula, seletor.alturaDaCelula) == (260, 146)
    ajustar(seletor)
    papeis = seletor.cortes.Papel
    assert seletor.cortes.rowCount() == 2
    # Em pé primeiro ou deitado primeiro, o que importa: só o em pé desliza (a arte 16:9 cabe no deitado).
    desliza = {corte(seletor, i, papeis.Orientacao): corte(seletor, i, papeis.Desliza) for i in range(2)}
    assert desliza == {"retrato": True, "paisagem": False}
    seletor.fechar()


def test_usar_esta_imagem_entrega_posicoes(app_qt, wallhaven, arte, temp):
    seletor, destino = criar((PRINCIPAL, EM_PE, DEITADO))
    seletor.abrir("Jogo")
    assert _esperar(lambda: prontos(seletor, 3))
    ajustar(seletor, 1)
    papeis = seletor.cortes.Papel
    em_pe = next(i for i in range(2) if corte(seletor, i, papeis.Orientacao) == "retrato")
    seletor.definirPosicao(em_pe, 25)
    seletor.usarEstaImagem()
    ((arquivo, posicoes),) = destino.papeis
    assert posicoes == Posicoes(retrato=0.25, paisagem=0.5)
    # O original, num temporário fora da pasta do seletor: é de quem o recebe.
    assert arquivo.parent == temp and arquivo.suffix == ".jpg" and arquivo.read_bytes() == arte_bytes()
    assert seletor.aberto is False
    assert _vazio_de(temp) == [arquivo.name]


def test_voltar_volta_a_grade_e_apaga_o_original(app_qt, wallhaven, arte, temp):
    seletor, destino = criar()
    seletor.abrir("Jogo")
    assert _esperar(lambda: prontos(seletor, 3))
    ajustar(seletor)
    seletor.voltar()
    assert seletor.ajustando is False and seletor.aberto is True and seletor.vazio is False
    assert seletor.rowCount() == 3 and seletor.cortes.rowCount() == 0
    assert len(list(next(temp.iterdir()).iterdir())) == 3  # só as miniaturas
    # De novo na grade: dá para escolher outra.
    ajustar(seletor, 2)
    seletor.fechar()
    assert _vazio_de(temp) == [] and destino.papeis == []


def test_nao_trocar(app_qt, wallhaven, arte, temp):
    seletor, destino = criar()
    seletor.abrir("Jogo")
    assert _esperar(lambda: prontos(seletor, 3))
    seletor.naoTrocar()
    assert destino.sem_troca == 1 and destino.papeis == [] and seletor.aberto is False
    assert _vazio_de(temp) == []


def test_fechar_com_download_cancela_e_limpa(app_qt, wallhaven, baixar, temp, app_dirs):
    seletor, destino = criar()
    seletor.abrir("Jogo")
    assert _esperar(lambda: prontos(seletor, 3))
    baixar.soltar.clear()
    baixar.comecou.clear()
    seletor.escolher(0)
    assert _esperar(baixar.comecou.is_set) and seletor.baixando is True
    seletor.fechar()
    assert baixar.cancelado.wait(5)
    assert _esperar(lambda: False, 0.3) is False
    assert destino.papeis == [] and seletor.ajustando is False
    for pasta in (shared.covers_dir, shared.logos_dir, shared.wallpapers_dir, temp):
        assert _vazio_de(pasta) == [], pasta
    # O limite do download é o dos papéis de parede, e não o das capas.
    assert baixar.limites[-1] == seletores.MAX_WALLPAPER_BYTES


def test_fechar_com_miniaturas_a_caminho_limpa(app_qt, wallhaven, baixar, temp):
    seletor, destino = criar()
    baixar.soltar.clear()
    seletor.abrir("Jogo")
    assert baixar.comecou.wait(5)
    seletor.fechar()
    baixar.soltar.set()
    assert _esperar(lambda: False, 0.5) is False
    assert _vazio_de(temp) == [] and seletor.rowCount() == 0 and destino.papeis == []


def test_sem_resultado_e_falha_da_busca(app_qt, wallhaven, arte, temp):
    wallhaven.achados = []
    seletor, _ = criar()
    seletor.abrir("Jogo")
    assert _esperar(lambda: seletor.vazio)
    assert (seletor.tituloDoEstado, seletor.descricaoDoEstado) == ("Nenhum papel de parede encontrado", "Tente buscar por outro nome.")
    assert seletor.erro is False
    wallhaven.erro = WallhavenError("rede fora")
    seletor.busca = "Outro"
    seletor.buscarAgora()
    assert _esperar(lambda: seletor.erro)
    assert seletor.tituloDoEstado == "Não foi possível concluir a busca"
    seletor.fechar()
    assert _vazio_de(temp) == []


def test_busca_vazia_e_sem_chave_do_wallhaven(app_qt, wallhaven, arte, temp, schema):
    # A chave do wallhaven é opcional, e a do SteamGridDB nada tem a ver com este seletor.
    schema.set_string("sgdb-key", "")
    seletor, _ = criar()
    seletor.abrir("Jogo")
    assert _esperar(lambda: prontos(seletor, 3))
    seletor.busca = ""
    seletor.buscarAgora()
    assert seletor.vazio and seletor.tituloDoEstado == "Digite o nome de um jogo"
    seletor.fechar()


def test_imagem_ilegivel_mostra_o_erro(app_qt, wallhaven, baixar, temp):
    seletor, _ = criar()
    seletor.abrir("Jogo")
    assert _esperar(lambda: prontos(seletor, 3))
    baixar.conteudo = b"isto nao e uma imagem"
    seletor.escolher(0)
    assert _esperar(lambda: seletor.erro)
    assert seletor.tituloDoEstado == "Não foi possível abrir a imagem" and seletor.ajustando is False
    seletor.fechar()
    assert _vazio_de(temp) == []


def test_download_que_falha_mostra_o_erro(app_qt, wallhaven, baixar, temp):
    import requests  # noqa: PLC0415

    seletor, _ = criar()
    seletor.abrir("Jogo")
    assert _esperar(lambda: prontos(seletor, 3))
    baixar.falhar = requests.ConnectionError("fora")
    seletor.escolher(0)
    assert _esperar(lambda: seletor.erro)
    assert seletor.tituloDoEstado == "Não foi possível baixar a imagem"
    seletor.fechar()


def test_destino_morto_nao_vaza_nem_quebra(app_qt, wallhaven, arte, temp):
    seletor, destino = criar()
    seletor.abrir("Jogo")
    assert _esperar(lambda: prontos(seletor, 3))
    ajustar(seletor)
    del destino
    gc.collect()
    seletor.usarEstaImagem()
    assert seletor.aberto is False
    assert _vazio_de(temp) == []


def test_session_wallpaper_importa_sem_gi():
    codigo = (
        "import builtins, sys; builtins._ = lambda m: m; sys.path.insert(0, sys.argv[1]);"
        "import cartridges.utils.session_wallpaper, cartridges.utils.wallhaven, cartridges.modelos.seletores;"
        "sys.exit(1 if 'gi' in sys.modules else 0)"
    )
    resultado = subprocess.run([sys.executable, "-c", codigo, str(RAIZ)], capture_output=True, text=True, check=False)
    assert resultado.returncode == 0, resultado.stderr


# -- ligação com o `ModeloDaEdicao` -----------------------------------------------------------------


@pytest.fixture
def edicao(app_qt, store, baixar, temp):
    from cartridges.modelos.edicao import ModeloDaEdicao  # noqa: PLC0415

    modelo = ModeloDaEdicao(SimpleNamespace(pedir_dialogo=lambda *a: None))
    modelo.adicionar()
    yield modelo
    modelo.cancelar()


def test_o_papel_baixado_vira_escolha_temporaria_da_edicao(edicao, temp):
    arquivo = temp / "papel.jpg"
    arquivo.write_bytes(b"x")
    edicao.entregar_papel_baixado(arquivo, Posicoes(retrato=0.3))
    escolha = edicao._form.papel_de_parede  # noqa: SLF001
    assert (escolha.modo, escolha.arquivo, escolha.posicoes, escolha.temporario) == ("manual", arquivo, Posicoes(retrato=0.3), True)
    # Cancelar apaga o temporário.
    edicao.cancelar()
    assert not arquivo.exists()


def test_nao_trocar_e_o_papel_trocado_apaga_o_anterior(edicao, temp):
    primeiro = temp / "um.jpg"
    primeiro.write_bytes(b"x")
    edicao.entregar_papel_baixado(primeiro, Posicoes())
    edicao.nao_trocar_papel()
    assert edicao._form.papel_de_parede.modo == "none"  # noqa: SLF001
    assert not primeiro.exists()


def test_papel_entregue_a_edicao_fechada_e_apagado(edicao, temp):
    edicao.cancelar()
    arquivo = temp / "tarde.jpg"
    arquivo.write_bytes(b"x")
    edicao.entregar_papel_baixado(arquivo, Posicoes())
    assert not arquivo.exists()


def test_o_fechar_da_edicao_fecha_o_seletor_do_papel(edicao, wallhaven, arte, temp):
    seletor = edicao.seletorDePapelDeParede
    seletor.monitores = lambda: [PRINCIPAL, EM_PE]
    seletor.abrir("Jogo")
    assert _esperar(lambda: prontos(seletor, 3))
    edicao.cancelar()
    assert seletor.aberto is False and _vazio_de(temp) == []


# -- um arquivo do disco vai à mesma etapa de ajuste  ---------------------------------


def test_arquivo_do_disco_abre_direto_no_ajuste(app_qt, tmp_path, temp):
    seletor, destino = criar()
    arquivo = tmp_path / "parede.png"
    arquivo.write_bytes(arte_bytes())
    seletor.abrirArquivo(QUrl.fromLocalFile(str(arquivo)))
    assert seletor.soArquivo is True
    assert _esperar(lambda: seletor.ajustando)
    seletor.definirPosicao(0, 100)
    seletor.usarEstaImagem()
    ((entregue, posicoes),) = destino.papeis
    assert posicoes.retrato == 1.0
    # Uma cópia em %TEMP%: o arquivo da pessoa nunca é apagado nem entregue.
    assert entregue != arquivo and entregue.parent == temp and entregue.read_bytes() == arquivo.read_bytes()
    assert arquivo.exists() and _vazio_de(temp) == [entregue.name]


def test_arquivo_do_disco_voltar_desiste(app_qt, tmp_path, temp):
    seletor, destino = criar()
    arquivo = tmp_path / "parede.png"
    arquivo.write_bytes(arte_bytes())
    seletor.abrirArquivo(QUrl.fromLocalFile(str(arquivo)))
    assert _esperar(lambda: seletor.ajustando)
    seletor.voltar()
    assert seletor.aberto is False and destino.papeis == [] and _vazio_de(temp) == [] and arquivo.exists()


def test_arquivo_do_disco_ilegivel_mostra_o_erro(app_qt, tmp_path, temp):
    seletor, _ = criar()
    arquivo = tmp_path / "parede.png"
    arquivo.write_bytes(b"nada")
    seletor.abrirArquivo(QUrl.fromLocalFile(str(arquivo)))
    assert _esperar(lambda: seletor.erro)
    assert (seletor.tituloDoEstado, seletor.descricaoDoEstado) == ("Não foi possível abrir a imagem", "Tente outra imagem.")
    seletor.fechar()
    assert _vazio_de(temp) == []


# -- falhas ao abrir o arquivo -----------------------------------------------------------------------------


def test_arquivo_do_disco_com_excecao_inesperada_mostra_o_erro(app_qt, tmp_path, temp, monkeypatch):
    # Uma exceção que o PIL não declara: antes, a thread morria e o seletor ficava carregando para sempre.
    def estoura(*_a, **_k):
        raise RuntimeError("inesperado")

    monkeypatch.setattr(seletores.Image, "open", estoura)
    seletor, _ = criar()
    arquivo = tmp_path / "parede.png"
    arquivo.write_bytes(arte_bytes())
    seletor.abrirArquivo(QUrl.fromLocalFile(str(arquivo)))
    assert _esperar(lambda: seletor.erro)
    assert seletor.tituloDoEstado == "Não foi possível abrir a imagem" and seletor.buscando is False
    seletor.fechar()
    assert _vazio_de(temp) == []


def test_arquivo_grande_do_disco_nao_tem_limite(app_qt, tmp_path, temp, monkeypatch):
    monkeypatch.setattr(seletores, "MAX_WALLPAPER_BYTES", 10, raising=False)
    seletor, _ = criar()
    arquivo = tmp_path / "parede.png"
    arquivo.write_bytes(arte_bytes())
    seletor.abrirArquivo(QUrl.fromLocalFile(str(arquivo)))
    assert _esperar(lambda: seletor.ajustando)
    seletor.fechar()


def test_fechar_para_as_miniaturas_da_fila(app_qt, wallhaven, baixar, temp):
    wallhaven.achados = lista_do_wallhaven(24)
    baixar.soltar.clear()
    seletor, _ = criar()
    seletor.abrir("Jogo")
    assert baixar.comecou.wait(5)
    seletor.fechar()
    baixar.soltar.set()
    assert _esperar(lambda: False, 0.8) is False
    # Só as que já estavam em voo (6 threads) chegaram a pedir; as 18 da fila não pedem nada.
    assert len(baixar.urls) <= 6
    assert _vazio_de(temp) == []


# -- arquivo do disco que não abre  --------------------------


def test_b9_bomba_na_tela_de_parede_sai_do_spinner(app_qt, tmp_path, temp, monkeypatch):
    arquivo = tmp_path / "enorme.png"
    Image.new("RGB", (100, 100)).save(arquivo)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    seletor, _ = criar()
    seletor.abrirArquivo(QUrl.fromLocalFile(str(arquivo)))
    assert _esperar(lambda: seletor.erro)
    assert seletor.tituloDoEstado == "Não foi possível abrir a imagem" and seletor.buscando is False
    seletor.fechar()
    assert _vazio_de(temp) == []


def test_h7_falha_de_leitura_nao_diz_nenhum_encontrado(app_qt, tmp_path, temp):
    seletor, _ = criar()
    seletor.abrirArquivo(QUrl.fromLocalFile(str(tmp_path / "sumiu.png")))
    assert _esperar(lambda: seletor.erro)
    assert "Nenhum papel de parede" not in seletor.tituloDoEstado
    assert (seletor.tituloDoEstado, seletor.descricaoDoEstado) == ("Não foi possível abrir a imagem", "Tente outra imagem.")
    seletor.fechar()


def test_as_caixas_da_previa_do_ajuste_sao_as_da_main():
    """`PREVIEW_MAX`, `HYBRID_LANDSCAPE_MAX` e `HYBRID_PORTRAIT_MAX` são os da versão anterior (GTK)."""
    from cartridges.modelos import seletores  # noqa: PLC0415

    assert (seletores.CAIXA_UNICA, seletores.CAIXA_DEITADA, seletores.CAIXA_EM_PE) == ((800, 440), (600, 340), (220, 340))


def test_buscar_no_ajuste_volta_a_grade(app_qt, wallhaven, arte, temp):
    """Com o campo ativo, digitar ou dar Enter na etapa de ajuste faz a busca e sai dela."""
    seletor, _ = criar()
    seletor.abrir("Jogo")
    assert _esperar(lambda: prontos(seletor, 3))
    ajustar(seletor)
    assert seletor.ajustando is True
    seletor.buscarAgora()
    assert seletor.ajustando is False and seletor.cortes.rowCount() == 0
    seletor.fechar()
