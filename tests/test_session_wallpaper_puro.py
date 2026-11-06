# test_session_wallpaper_puro.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O enquadramento e a escada de busca do papel de parede da sessão.

A promessa da tela de escolha é uma só: a miniatura de 146px e o arquivo de
1080px mostram o MESMO quadro. Ela vale porque as duas passam pela mesma
``enquadrar``, e é isso que o primeiro grupo de testes prende — se alguém
"otimizar" um dos dois caminhos para cortar direto em pixels, a grade passa a
mentir sobre o que vai para o monitor, e nada na tela denuncia isso.

O segundo grupo é a guarda de duas palavras da busca. Cortar o subtítulo
resgata dez jogos de uma biblioteca de 92, e sem a guarda resgata errado:
"Aliens: Dark Descent" vira "Aliens" e traz o filme.
"""

import json
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from kyron import shared
from kyron.utils import session_wallpaper
from kyron.utils.wallhaven import consultas


def _arte(largura: int, altura: int) -> Image.Image:
    """Uma imagem com um quadrante marcado, para o corte ser verificável."""
    imagem = Image.new("RGB", (largura, altura), (10, 10, 10))
    for x in range(largura // 4, largura // 2):
        for y in range(altura // 4, altura // 2):
            imagem.putpixel((x, y), (255, 0, 0))
    return imagem


def _tamanho(caminho) -> tuple[int, int]:
    with Image.open(caminho) as imagem:
        return imagem.size


PRINCIPAL = session_wallpaper.Monitor("M1", 0, 0, 1920, 1080)
DEITADO = session_wallpaper.Monitor("M2", 1920, 0, 2560, 1440)
EM_PE = session_wallpaper.Monitor("M3", -1080, -476, 1080, 1920)


class _AreaComMonitores:
    """O bastante da IDesktopWallpaper para a preparação da arte."""

    def __init__(self, monitores):
        self.monitores = monitores

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def em_apresentacao(self):
        return False

    def ligados(self):
        return list(self.monitores)


class TestEnquadramento:
    def test_miniatura_e_arquivo_dao_o_mesmo_quadro(self) -> None:
        """A miniatura de 432px e o original de 3840px, lado a lado.

        Os dois são reduzidos ao mesmo tamanho e comparados: o corte é em
        proporção, então o quadro tem de ser o mesmo apesar da diferença de
        resolução entre as fontes.
        """
        original = _arte(3840, 2160)
        miniatura = original.resize((432, 243), Image.LANCZOS)

        for posicao in (0.0, 0.5, 1.0):
            grande = session_wallpaper.enquadrar(original, 1080, 1920, posicao)
            pequena = session_wallpaper.enquadrar(miniatura, 146, 260, posicao)

            a = grande.resize((36, 64), Image.LANCZOS)
            b = pequena.resize((36, 64), Image.LANCZOS)
            diferenca = max(
                abs(int(p) - int(q))
                for p, q in zip(a.convert("L").get_flattened_data(), b.convert("L").get_flattened_data())
            )
            # Reamostragem não é exata; o que se afirma é o enquadramento, e
            # um quadro diferente daria centenas de níveis de diferença.
            assert diferenca < 40, f"posição {posicao} enquadrou diferente"

    def test_posicao_move_o_corte(self) -> None:
        original = _arte(3840, 2160)
        esquerda = session_wallpaper.enquadrar(original, 1080, 1920, 0.0)
        direita = session_wallpaper.enquadrar(original, 1080, 1920, 1.0)
        assert list(esquerda.get_flattened_data()) != list(direita.get_flattened_data())

    def test_saida_tem_exatamente_o_tamanho_do_monitor(self) -> None:
        for origem in ((3840, 2160), (1080, 2400), (600, 900)):
            quadro = session_wallpaper.enquadrar(_arte(*origem), 1080, 1920)
            assert quadro.size == (1080, 1920)

    def test_eixo_do_corte(self) -> None:
        # Arte larga num monitor em pé: sobra largura, o corte é lateral.
        assert session_wallpaper.eixo_do_corte(3840, 2160, 1080, 1920)
        # Arte mais alta que o monitor: sobra altura, o corte é vertical.
        assert not session_wallpaper.eixo_do_corte(1080, 2400, 1080, 1920)
        # Já na proporção exata: nada sobra, e o eixo lateral é o padrão.
        assert session_wallpaper.eixo_do_corte(1080, 1920, 1080, 1920)

    def test_corta_so_quando_a_proporcao_difere(self) -> None:
        assert not session_wallpaper.corta(3840, 2160, 1920, 1080)
        # A cópia reduzida da tela de ajuste arredonda: continua sendo 16:9.
        assert not session_wallpaper.corta(1564, 880, 1920, 1080)
        assert session_wallpaper.corta(1920, 1200, 1920, 1080)
        assert session_wallpaper.corta(3840, 2160, 1080, 1920)

    def test_capa_aparece_inteira(self, app_dirs) -> None:
        """A capa não é cortada: 2:3 num monitor 9:16 perderia o título."""
        capa = app_dirs.covers / "capa.png"
        _arte(600, 900).save(capa)
        quadro = session_wallpaper.da_capa(capa, 1080, 1920)
        assert quadro.size == (1080, 1920)


class TestMonitoresAlvo:
    def test_o_principal_fica_fora_e_os_outros_entram(self) -> None:
        assert session_wallpaper.alvos([PRINCIPAL, DEITADO, EM_PE]) == [DEITADO, EM_PE]

    def test_so_o_principal_nao_tem_alvo(self) -> None:
        assert session_wallpaper.alvos([PRINCIPAL]) == []

    def test_grade_em_pe_so_com_todos_em_pe(self) -> None:
        formatos = session_wallpaper.formatos([PRINCIPAL, EM_PE])
        assert formatos.grade == (1080, 1920)
        assert formatos.ratio == "portrait"

    def test_grade_deitada_com_todos_deitados(self) -> None:
        formatos = session_wallpaper.formatos([PRINCIPAL, DEITADO])
        assert formatos.grade == (2560, 1440)
        assert formatos.ratio == "landscape"

    def test_hibrido_tem_grade_deitada_e_minimo_dos_dois(self) -> None:
        formatos = session_wallpaper.formatos([PRINCIPAL, DEITADO, EM_PE])
        assert formatos.grade == (2560, 1440)
        assert formatos.ratio == "landscape"
        # Largura do deitado e altura do em pé: nenhum dos dois cortes estica.
        assert formatos.minimo == (2560, 1920)

    def test_sem_alvo_a_grade_cai_no_padrao_deitado(self) -> None:
        formatos = session_wallpaper.formatos([PRINCIPAL])
        assert formatos.grade == session_wallpaper.PAISAGEM_PADRAO
        assert formatos.minimo == session_wallpaper.PAISAGEM_PADRAO


class TestConsultas:
    def test_nome_limpo_vem_primeiro(self) -> None:
        assert consultas("Watch Dogs: Legion")[0] == "Watch Dogs: Legion"

    def test_sublinhado_e_apostrofo_viram_busca_utilizavel(self) -> None:
        assert consultas("Watch_Dogs 2")[0] == "Watch Dogs 2"
        assert consultas("Assassin\u2019s Creed Shadows")[0] == (
            "Assassin's Creed Shadows"
        )

    def test_edicao_sai_num_degrau_proprio(self) -> None:
        formas = consultas("Conan Exiles Enhanced")
        assert "Conan Exiles" in formas

    def test_subtitulo_cai_quando_sobram_duas_palavras(self) -> None:
        assert "The Outer Worlds" in consultas("The Outer Worlds: Spacer's Choice")

    def test_subtitulo_nao_cai_para_uma_palavra_so(self) -> None:
        """A guarda que separa o jogo do filme de mesmo nome."""
        for nome, generico in (
            ("Aliens: Dark Descent", "Aliens"),
            ("Vampire: The Masquerade", "Vampire"),
            ("Commandos: Origins", "Commandos"),
        ):
            assert generico not in consultas(nome)


class TestBuscaPorFormato:
    def test_formato_vira_ratios_e_o_minimo_vira_atleast(self, monkeypatch) -> None:
        from kyron.utils import download, wallhaven  # noqa: PLC0415

        pedidos = []

        class Resposta:
            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size=1):  # lido por get_capped
                return iter(())

            def json(self):
                return {"data": []}

        def get(url, **_kwargs):
            pedidos.append(url)
            return Resposta()

        monkeypatch.setattr(download, "_get", get)

        wallhaven.buscar("Halo", 1920, 1920, formato="landscape")
        wallhaven.buscar("Halo", 1920, 1920)

        assert "ratios=landscape" in pedidos[0]
        assert "atleast=1920x1920" in pedidos[0]
        assert "ratios" not in pedidos[1]

    def test_melhor_para_desce_do_formato_pedido_para_qualquer_um(
        self, monkeypatch
    ) -> None:
        from kyron.utils import wallhaven  # noqa: PLC0415

        degraus = []

        def buscar(_consulta, _largura, _altura, formato=None, **_kwargs):
            degraus.append(formato)
            return [{"id": "x"}] if formato is None else []

        monkeypatch.setattr(wallhaven, "buscar", buscar)

        assert wallhaven.melhor_para("Halo", 1920, 1080, "landscape") == {"id": "x"}
        assert degraus == ["landscape", None]
