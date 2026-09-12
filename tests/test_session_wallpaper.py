# test_session_wallpaper.py
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

import pytest
from PIL import Image

from cartridges import shared
from cartridges.utils import session_wallpaper
from cartridges.utils.wallhaven import consultas


def _arte(largura: int, altura: int) -> Image.Image:
    """Uma imagem com um quadrante marcado, para o corte ser verificável."""
    imagem = Image.new("RGB", (largura, altura), (10, 10, 10))
    for x in range(largura // 4, largura // 2):
        for y in range(altura // 4, altura // 2):
            imagem.putpixel((x, y), (255, 0, 0))
    return imagem


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
                for p, q in zip(a.convert("L").getdata(), b.convert("L").getdata())
            )
            # Reamostragem não é exata; o que se afirma é o enquadramento, e
            # um quadro diferente daria centenas de níveis de diferença.
            assert diferenca < 40, f"posição {posicao} enquadrou diferente"

    def test_posicao_move_o_corte(self) -> None:
        original = _arte(3840, 2160)
        esquerda = session_wallpaper.enquadrar(original, 1080, 1920, 0.0)
        direita = session_wallpaper.enquadrar(original, 1080, 1920, 1.0)
        assert list(esquerda.getdata()) != list(direita.getdata())

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

    def test_capa_aparece_inteira(self, app_dirs) -> None:
        """A capa não é cortada: 2:3 num monitor 9:16 perderia o título."""
        capa = app_dirs.covers / "capa.png"
        _arte(600, 900).save(capa)
        quadro = session_wallpaper.da_capa(capa, 1080, 1920)
        assert quadro.size == (1080, 1920)


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
        from cartridges.utils import wallhaven  # noqa: PLC0415

        pedidos = []

        class Resposta:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": []}

        def get(url, **_kwargs):
            pedidos.append(url)
            return Resposta()

        monkeypatch.setattr(wallhaven.requests, "get", get)

        wallhaven.buscar("Halo", 1920, 1920, formato="landscape")
        wallhaven.buscar("Halo", 1920, 1920)

        assert "ratios=landscape" in pedidos[0]
        assert "atleast=1920x1920" in pedidos[0]
        assert "ratios" not in pedidos[1]

    def test_melhor_para_desce_do_formato_pedido_para_qualquer_um(
        self, monkeypatch
    ) -> None:
        from cartridges.utils import wallhaven  # noqa: PLC0415

        degraus = []

        def buscar(_consulta, _largura, _altura, formato=None, **_kwargs):
            degraus.append(formato)
            return [{"id": "x"}] if formato is None else []

        monkeypatch.setattr(wallhaven, "buscar", buscar)

        assert wallhaven.melhor_para("Halo", 1920, 1080, "landscape") == {"id": "x"}
        assert degraus == ["landscape", None]


class TestEscolhaPorJogo:
    def test_sem_sidecar_e_automatico(self, jogo) -> None:
        assert session_wallpaper.escolha(jogo) == "auto"

    def test_escolha_manual_trava_e_guarda_a_faixa(self, jogo, tmp_path) -> None:
        origem = tmp_path / "escolhida.jpg"
        _arte(3840, 2160).save(origem)

        destino = session_wallpaper.salvar_escolha(
            jogo.game_id, jogo.name, origem, 0.25
        )
        assert destino is not None and destino.is_file()
        assert session_wallpaper.escolha(jogo) == "manual"

        gravado = json.loads(
            (shared.wallpapers_dir / f"{jogo.game_id}.json").read_text(encoding="utf-8")
        )
        assert gravado["locked"] is True
        assert gravado["position"] == 0.25

    def test_renomear_nao_desfaz_a_escolha_manual(self, jogo, tmp_path) -> None:
        """A busca automática reabre com o nome novo; a escolha à mão, não."""
        origem = tmp_path / "escolhida.jpg"
        _arte(3840, 2160).save(origem)
        session_wallpaper.salvar_escolha(jogo.game_id, jogo.name, origem, 0.5)

        jogo.name = "Outro nome qualquer"
        assert session_wallpaper.escolha(jogo) == "manual"

    def test_nao_trocar_e_um_estado_proprio(self, jogo) -> None:
        session_wallpaper.nao_trocar(jogo.game_id, jogo.name)
        assert session_wallpaper.escolha(jogo) == "none"
        assert session_wallpaper.imagem_escolhida(jogo.game_id) is None

    def test_redefinir_volta_ao_automatico(self, jogo, tmp_path) -> None:
        origem = tmp_path / "escolhida.jpg"
        _arte(3840, 2160).save(origem)
        session_wallpaper.salvar_escolha(jogo.game_id, jogo.name, origem, 0.5)

        session_wallpaper.redefinir(jogo.game_id)
        assert session_wallpaper.escolha(jogo) == "auto"
        assert session_wallpaper.imagem_escolhida(jogo.game_id) is None

    def test_arquivo_manual_sumido_volta_ao_automatico(self, jogo, tmp_path) -> None:
        """Não é "não trocar": é uma escolha que se perdeu, e a busca volta."""
        origem = tmp_path / "escolhida.jpg"
        _arte(64, 64).save(origem)
        destino = session_wallpaper.salvar_escolha(jogo.game_id, jogo.name, origem, 0.5)
        assert destino is not None
        destino.unlink()

        assert session_wallpaper.escolha(jogo) == "auto"


class _AreaFalsa:
    """O bastante da IDesktopWallpaper para a ida e a volta, sem tocar na tela."""

    def __init__(self, papeis, recusa=()):
        self.papeis = dict(papeis)
        self.recusa = set(recusa)
        self.vestidos: list = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def papel(self, monitor):
        return self.papeis.get(monitor)

    def vestir(self, monitor, caminho):
        if monitor in self.recusa:
            return False
        self.vestidos.append((monitor, caminho))
        self.papeis[monitor] = caminho
        return True


class TestRestauro:
    def test_restaurar_sem_sessao_nao_faz_nada(self, schema) -> None:
        schema["session-wallpaper-saved"] = ""
        session_wallpaper.restaurar()  # não pode levantar nem tocar em COM
        assert schema.get_string("session-wallpaper-saved") == ""

    def test_a_marca_fica_quando_a_devolucao_falha(self, schema, monkeypatch):
        """Sem COM na volta, a chave com os originais continua em disco.

        Ela é o único registro do papel de parede de verdade. Apagada, ele se
        perdia para sempre; mantida, o arranque seguinte tenta de novo, e a
        sessão seguinte não a sobrescreve (veja o teste dos originais abaixo).
        """
        guardado = json.dumps({"M1": "c:/a.jpg"})
        schema["session-wallpaper-saved"] = guardado

        def sem_com(*_args, **_kwargs):
            raise OSError("sem área de trabalho neste ambiente")

        monkeypatch.setattr(session_wallpaper, "_AreaDeTrabalho", sem_com)
        session_wallpaper.restaurar()
        assert schema.get_string("session-wallpaper-saved") == guardado

    def test_monitor_so_com_a_cor_de_fundo_tambem_volta(self, schema, monkeypatch):
        """Original vazio quer dizer "sem imagem", e é a esse estado que ele volta."""
        schema["session-wallpaper-saved"] = json.dumps({"M1": "", "M2": "c:/b.jpg"})
        area = _AreaFalsa({})
        monkeypatch.setattr(session_wallpaper, "_AreaDeTrabalho", lambda: area)

        session_wallpaper.restaurar()

        assert sorted(area.vestidos) == [("M1", ""), ("M2", "c:/b.jpg")]
        assert schema.get_string("session-wallpaper-saved") == ""

    def test_monitor_que_nao_voltou_fica_na_chave(self, schema, monkeypatch):
        """A volta que falha num monitor só não apaga o original dele.

        O caso de verdade: o papel de parede original mora no iCloud Drive, e
        sem rede o Windows recusa o arquivo. Apagada a chave, aquele monitor
        ficava com a arte do jogo e ninguém tentava de novo.
        """
        schema["session-wallpaper-saved"] = json.dumps(
            {"M1": "c:/a.jpg", "M2": "c:/icloud.png"}
        )
        area = _AreaFalsa({}, recusa={"M2"})
        monkeypatch.setattr(session_wallpaper, "_AreaDeTrabalho", lambda: area)

        session_wallpaper.restaurar()

        assert area.vestidos == [("M1", "c:/a.jpg")]
        assert schema.get_string("session-wallpaper-saved") == json.dumps(
            {"M2": "c:/icloud.png"}
        )

    def test_sessao_encerrada_nao_veste(self, schema, monkeypatch, tmp_path):
        """A arte que fica pronta depois do fim da sessão não vai para a parede."""
        area = _AreaFalsa({"M1": "c:/original.jpg"})
        monkeypatch.setattr(session_wallpaper, "_AreaDeTrabalho", lambda: area)
        quadro = tmp_path / "quadro.jpg"
        quadro.write_bytes(b"jpg")

        sessao = session_wallpaper._sessao
        session_wallpaper.restaurar()  # o jogo fechou enquanto a arte baixava
        session_wallpaper._vestir(sessao, [("M1", quadro)])

        assert area.vestidos == []
        assert schema.get_string("session-wallpaper-saved") == ""
        assert not quadro.exists()

    def test_originais_sao_gravados_sem_sobrescrever_os_de_antes(
        self, schema, monkeypatch, tmp_path
    ):
        """Quem já consta na chave fica com o valor de lá; quem falta é lido.

        M1 consta de uma devolução que falhou, e o que ele mostra agora é arte
        nossa. M3 não responde, e sem original não é vestido.
        """
        schema["session-wallpaper-saved"] = json.dumps({"M1": "c:/original.jpg"})
        area = _AreaFalsa({"M1": "c:/arte-velha.jpg", "M2": "c:/m2.jpg", "M3": None})
        monkeypatch.setattr(session_wallpaper, "_AreaDeTrabalho", lambda: area)
        quadros = [(m, tmp_path / f"{m}.jpg") for m in ("M1", "M2", "M3")]

        session_wallpaper._vestir(session_wallpaper._sessao, quadros)

        assert json.loads(schema.get_string("session-wallpaper-saved")) == {
            "M1": "c:/original.jpg",
            "M2": "c:/m2.jpg",
        }
        assert [monitor for monitor, _ in area.vestidos] == ["M1", "M2"]


@pytest.fixture
def jogo(write_record):
    """Um jogo qualquer, gravado como a biblioteca o grava."""
    from cartridges.game import Game

    write_record("jogo-teste", name="Watch Dogs: Legion")
    return Game(
        {
            "game_id": "jogo-teste",
            "name": "Watch Dogs: Legion",
            "source": "shortcuts",
        }
    )


class TestTelaDeEscolha:
    def test_o_template_resolve_todos_os_filhos(self, win, monkeypatch) -> None:
        """Um nome errado no .blp só aparece ao construir a janela.

        Nenhum outro teste instancia esta tela, e um ``Gtk.Template.Child``
        que não casa com o template levanta na construção — o app inteiro
        deixaria de abrir a edição de qualquer jogo.
        """
        from cartridges import wallpaper_picker

        monkeypatch.setattr(wallpaper_picker, "buscar", lambda *a, **k: [])
        monkeypatch.setattr(wallpaper_picker, "alvo", lambda: (1080, 1920))

        picker = wallpaper_picker.WallpaperPicker("Watch Dogs", lambda *_: None, lambda: None)

        for filho in (
            picker.search_entry,
            picker.flowbox,
            picker.stack,
            picker.status_page,
            picker.none_button,
            picker.adjust_picture,
            picker.adjust_scale,
            picker.adjust_adjustment,
            picker.adjust_apply,
        ):
            assert filho is not None

        # A célula acompanha a proporção do monitor, não um número no template.
        assert picker.cell_width == round(260 * 1080 / 1920)
        picker.close()
