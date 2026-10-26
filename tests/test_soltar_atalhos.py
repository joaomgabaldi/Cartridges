# test_soltar_atalhos.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Arrastar atalhos para a janela: o que entra na pasta de atalhos."""

from cartridges.utils import soltar_atalhos
from cartridges.utils.soltar_atalhos import MAX_ARQUIVOS, MAX_BYTES, Resultado


def arquivo(pasta, nome, conteudo=b"x"):
    caminho = pasta / nome
    caminho.write_bytes(conteudo)
    return caminho


def test_filtra_por_extensao(tmp_path):
    nomes = ["a.lnk", "b.URL", "c.exe", "d.txt"]
    caminhos = [arquivo(tmp_path, nome) for nome in nomes]

    aceitos, ignorados = soltar_atalhos.filtrar(caminhos)

    assert [c.name for c in aceitos] == ["a.lnk", "b.URL"]
    assert ignorados == 2


def test_ignora_nao_local_e_pasta(tmp_path):
    pasta = tmp_path / "pasta.lnk"
    pasta.mkdir()

    assert soltar_atalhos.filtrar([None, pasta]) == ([], 2)


def test_ignora_arquivo_grande(tmp_path):
    grande = arquivo(tmp_path, "grande.lnk", b"x" * (MAX_BYTES + 1))
    no_limite = arquivo(tmp_path, "limite.lnk", b"x" * MAX_BYTES)

    assert soltar_atalhos.filtrar([grande, no_limite]) == ([no_limite], 1)


def test_limita_quantidade(tmp_path):
    caminhos = [arquivo(tmp_path, f"{i}.lnk") for i in range(MAX_ARQUIVOS + 1)]

    aceitos, ignorados = soltar_atalhos.filtrar(caminhos)

    assert aceitos == caminhos[:MAX_ARQUIVOS]
    assert ignorados == 1


def pasta_de_atalhos(tmp_path, schema):
    pasta = tmp_path / "Atalhos"
    pasta.mkdir()
    schema["shortcuts-location"] = str(pasta)
    return pasta


def test_copia_sem_sobrescrever(tmp_path, schema):
    pasta = pasta_de_atalhos(tmp_path, schema)
    arquivo(pasta, "Halo.lnk", b"velho")
    fora = tmp_path / "Downloads"
    fora.mkdir()

    resultado = soltar_atalhos.copiar(
        [arquivo(fora, "Halo.lnk", b"novo"), arquivo(fora, "Doom.lnk")]
    )

    assert resultado == Resultado(copiados=1, ja_existiam=1, ignorados=0)
    assert (pasta / "Halo.lnk").read_bytes() == b"velho"
    assert (pasta / "Doom.lnk").is_file()


def test_atalho_ja_dentro_da_pasta_conta_como_copiado(tmp_path, schema):
    pasta = pasta_de_atalhos(tmp_path, schema)

    resultado = soltar_atalhos.copiar([arquivo(pasta, "Halo.lnk")])

    assert resultado == Resultado(copiados=1, ja_existiam=0, ignorados=0)


def test_pasta_configurada(tmp_path, schema):
    assert soltar_atalhos.pasta_configurada() is False
    schema["shortcuts-location"] = str(tmp_path / "nao-existe")
    assert soltar_atalhos.pasta_configurada() is False
    schema["shortcuts-location"] = str(tmp_path)
    assert soltar_atalhos.pasta_configurada() is True


# ---------------------------------------------------------------------------
# O que acontece ao soltar
# ---------------------------------------------------------------------------


def test_soltar_durante_importacao_nao_copia(tmp_path, schema):
    pasta = pasta_de_atalhos(tmp_path, schema)
    fora = tmp_path / "Downloads"
    fora.mkdir()

    avisos, importar = soltar_atalhos.ao_soltar([arquivo(fora, "Doom.lnk")], True)

    assert avisos == ["Aguarde o fim da importação em andamento."]
    assert importar is False
    assert list(pasta.iterdir()) == []


def test_soltar_sem_pasta(tmp_path, schema):
    avisos, importar = soltar_atalhos.ao_soltar([arquivo(tmp_path, "Doom.lnk")], False)

    assert avisos == [
        "Escolha uma pasta de atalhos em Preferências para importar atalhos."
    ]
    assert importar is False


def test_soltar_sem_atalhos(tmp_path, schema):
    pasta_de_atalhos(tmp_path, schema)

    avisos, importar = soltar_atalhos.ao_soltar([arquivo(tmp_path, "x.exe")], False)

    assert avisos == ["Nenhum atalho para importar."]
    assert importar is False


def test_soltar_importa_e_avisa_ignorados(tmp_path, schema):
    pasta = pasta_de_atalhos(tmp_path, schema)
    fora = tmp_path / "Downloads"
    fora.mkdir()

    avisos, importar = soltar_atalhos.ao_soltar(
        [arquivo(fora, "Doom.lnk"), arquivo(fora, "doom.exe")], False
    )

    assert importar is True
    assert avisos == ["1 arquivo foi ignorado."]
    assert (pasta / "Doom.lnk").is_file()


def test_soltar_atalho_repetido_importa_e_avisa(tmp_path, schema):
    pasta = pasta_de_atalhos(tmp_path, schema)
    arquivo(pasta, "Doom.lnk")
    fora = tmp_path / "Downloads"
    fora.mkdir()

    avisos, importar = soltar_atalhos.ao_soltar([arquivo(fora, "Doom.lnk")], False)

    assert importar is True
    assert avisos == ["1 atalho já estava na pasta de atalhos."]


# ---------------------------------------------------------------------------
# A janela
# ---------------------------------------------------------------------------


class AppFalso:
    def __init__(self, importando=False):
        from gi.repository import Gio  # noqa: PLC0415

        self.acao = Gio.SimpleAction.new("import", None)
        self.acao.set_enabled(not importando)
        self.importacoes = []

    def lookup_action(self, nome):
        assert nome == "import"
        return self.acao

    def on_import_action(self, **kwargs):
        self.importacoes.append(kwargs)


def lista_de_arquivos(*caminhos):
    from gi.repository import Gdk, Gio  # noqa: PLC0415

    return Gdk.FileList.new_from_list([Gio.File.new_for_path(str(c)) for c in caminhos])


def test_janela_mostra_e_esconde_o_aviso(real_window):
    real_window._ao_entrar_arrasto()
    assert real_window.aviso_de_soltar.get_visible()

    real_window._ao_sair_arrasto()
    assert not real_window.aviso_de_soltar.get_visible()


def test_janela_copia_e_importa_ao_soltar(real_window, monkeypatch, tmp_path, schema):
    pasta = pasta_de_atalhos(tmp_path, schema)
    fora = tmp_path / "Downloads"
    fora.mkdir()
    app = AppFalso()
    monkeypatch.setattr(real_window, "get_application", lambda: app)
    real_window._ao_entrar_arrasto()

    real_window._ao_soltar(None, lista_de_arquivos(arquivo(fora, "Doom.lnk")), 0, 0)

    assert (pasta / "Doom.lnk").is_file()
    assert len(app.importacoes) == 1
    assert app.importacoes[0]["varrer_atalhos"] is True
    assert not real_window.aviso_de_soltar.get_visible()


def test_janela_nao_importa_durante_importacao(real_window, monkeypatch, tmp_path, schema):
    pasta = pasta_de_atalhos(tmp_path, schema)
    fora = tmp_path / "Downloads"
    fora.mkdir()
    app = AppFalso(importando=True)
    monkeypatch.setattr(real_window, "get_application", lambda: app)

    real_window._ao_soltar(None, lista_de_arquivos(arquivo(fora, "Doom.lnk")), 0, 0)

    assert app.importacoes == []
    assert list(pasta.iterdir()) == []


def test_janela_recusa_soltar_com_dialogo_aberto(real_window, monkeypatch, tmp_path, schema):
    pasta = pasta_de_atalhos(tmp_path, schema)
    fora = tmp_path / "Downloads"
    fora.mkdir()
    app = AppFalso()
    monkeypatch.setattr(real_window, "get_application", lambda: app)
    monkeypatch.setattr(real_window, "get_visible_dialog", lambda: object())

    assert not real_window._ao_entrar_arrasto()
    assert not real_window.aviso_de_soltar.get_visible()
    assert real_window._ao_soltar(None, lista_de_arquivos(arquivo(fora, "Doom.lnk")), 0, 0) is False

    assert app.importacoes == []
    assert list(pasta.iterdir()) == []


def test_aviso_tem_moldura_tracejada(real_window):
    moldura = real_window.aviso_de_soltar.get_first_child()

    assert moldura.has_css_class("moldura-de-soltar")


def test_aviso_aparece_opaco_e_some_ao_sair(real_window):
    real_window._ao_entrar_arrasto()
    assert real_window.aviso_de_soltar.get_opacity() == 1

    real_window._ao_sair_arrasto()
    assert real_window.aviso_de_soltar.get_opacity() == 0
    assert not real_window.aviso_de_soltar.get_visible()


class FilaFalsa:
    def __init__(self):
        self.na_tela = []

    def add(self, toast):
        self.na_tela.append(toast)

    def dismiss(self, toast):
        self.na_tela.remove(toast)


def test_janela_avisa_que_esta_importando_ate_terminar(real_window, monkeypatch, tmp_path, schema):
    pasta_de_atalhos(tmp_path, schema)
    fora = tmp_path / "Downloads"
    fora.mkdir()
    app = AppFalso()
    fila = FilaFalsa()
    monkeypatch.setattr(real_window, "get_application", lambda: app)
    monkeypatch.setattr(real_window, "toast_queue", fila)

    real_window._ao_soltar(None, lista_de_arquivos(arquivo(fora, "Doom.lnk")), 0, 0)

    assert [t.get_title() for t in fila.na_tela] == ["Importando atalhos…"]
    app.importacoes[0]["ao_terminar"]()
    assert fila.na_tela == []
