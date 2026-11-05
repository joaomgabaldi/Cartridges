# test_edicao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A regra da edição (`cartridges.edicao`), sem tela: validar e aplicar o formulário."""

import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from cartridges import shared
from tests.apoio_edicao import girar, jogo, stub_sgdb


@pytest.fixture
def edicao():
    from cartridges import edicao  # noqa: PLC0415

    return edicao


@pytest.fixture
def sgdb(store):
    return stub_sgdb(store)


@pytest.fixture
def aplicativo(monkeypatch):
    """O `shared.aplicativo` com a fila de avisos de verdade e um verificador falso."""
    from cartridges.modelos.avisos import FilaDeAvisos  # noqa: PLC0415

    verificacoes = []
    dialogos = []
    paginas = []
    app = SimpleNamespace(
        avisos=FilaDeAvisos(),
        verificador_de_atualizacoes=SimpleNamespace(check_async=lambda: verificacoes.append(1)),
        pedir_dialogo=lambda titulo, corpo, itens, ao_fechar, preferencias=None: (
            dialogos.append((titulo, corpo)),
            paginas.append(preferencias),
        ),
        verificacoes=verificacoes,
        dialogos=dialogos,
        paginas=paginas,
    )
    monkeypatch.setattr(shared, "aplicativo", app, raising=False)
    return app


def _aplicar(edicao, game, **mudancas):
    """Abre o formulário do jogo, muda o que o teste pede e aplica, como o Aplicar."""
    form = edicao.Formulario.do_jogo(game)
    appid_inicial = form.appid
    for nome, valor in mudancas.items():
        setattr(form, nome, valor)
    assert edicao.validar(form, game) is None
    return edicao.aplicar(form, game, appid_inicial)


def _buscar(form, appid, **dados):
    """Como a busca na Steam: ela também preenche o campo do AppID."""
    form.appid = appid
    form.buscado = {"steam_appid": appid, **dados}


# region Validações


def test_ordem_das_validacoes(edicao):
    form = edicao.Formulario.do_jogo(None)
    form.rastrear_processo = True
    form.appid = "abc"
    form.lancamento = "31/13/2026"

    esperadas = [
        ("nome", "Jogo", "O título do jogo não pode ficar vazio."),
        ("executavel", "x.exe", "O executável não pode ficar vazio."),
        ("lancamento", "2/set./2026", "A data de lançamento informada é inválida. Utilize o formato 2/set./2026."),
        ("appid", " 620 ", "O AppID da Steam deve conter apenas números."),
        ("executavel_do_processo", "x.exe", "Informe o nome do executável para rastrear o tempo de jogo."),
    ]
    for campo, valor, mensagem in esperadas:
        assert edicao.validar(form, None) == mensagem
        setattr(form, campo, valor)
    assert edicao.validar(form, None) is None


def test_titulos_do_erro(edicao):
    assert edicao.titulo_do_erro(True) == "Não foi possível adicionar o jogo"
    assert edicao.titulo_do_erro(False) == "Não foi possível aplicar as alterações"


def test_executavel_vazio_vale_num_jogo_removido(edicao, store):
    """Um zerado não tem linha de executável na tela."""
    zerado = jogo(store, 1, removed=True, status="beaten", executable="")
    form = edicao.Formulario.do_jogo(zerado)
    assert edicao.validar(form, zerado) is None
    vivo = jogo(store, 2, executable="")
    assert edicao.validar(edicao.Formulario.do_jogo(vivo), vivo) == "O executável não pode ficar vazio."


def test_appid_nao_numerico_bloqueia(edicao, store):
    game = jogo(store, 3, steam_appid="620")
    form = edicao.Formulario.do_jogo(game)
    for invalido in ("abc", "６２０", "6 2"):
        form.appid = invalido
        assert edicao.validar(form, game) == "O AppID da Steam deve conter apenas números."
    form.appid = ""
    assert edicao.validar(form, game) is None


# endregion
# region Jogo novo


@pytest.mark.parametrize(
    ("data", "rastrear", "aviso"),
    [
        ("31/13/2026", False, "A data de lançamento informada é inválida. Utilize o formato 2/set./2026."),
        ("", True, "Informe o nome do executável para rastrear o tempo de jogo."),
    ],
)
def test_jogo_novo_so_nasce_depois_de_validar(edicao, store, sgdb, data, rastrear, aviso):
    """Uma validação que falha no "Adicionar" não deixa um jogo novo pela metade."""
    form = edicao.Formulario.do_jogo(None)
    form.nome, form.executavel = "Jogo novo", "cmd /c exit"
    form.lancamento, form.rastrear_processo = data, rastrear

    assert edicao.validar(form, None) == aviso
    with pytest.raises(ValueError, match=aviso):
        edicao.aplicar(form, None, "")
    assert list(store) == []
    assert store.proximo_id_importado() == "imported_1"


def test_adicionar_cria_imported_com_proximo_id(edicao, store, sgdb):
    from cartridges.jogo import Jogo  # noqa: PLC0415

    store.add_game(Jogo({"game_id": "imported_1", "source": "imported", "name": "Já", "executable": "a"}), {}, run_pipeline=False)
    form = edicao.Formulario.do_jogo(None)
    assert form.conquistas is True  # o "Adicionar" já vem com as conquistas ligadas
    form.nome, form.executavel = "Jogo novo", "cmd /c exit"
    antes = int(time.time())

    resultado = edicao.aplicar(form, None, "")

    novo = resultado.jogo
    assert (novo.game_id, novo.source, novo.base_source) == ("imported_2", "imported", "imported")
    assert novo.added >= antes
    assert novo.executable == "cmd /c exit"
    assert store.get("imported_2") is novo
    assert not resultado.fechar_sem_gravar and not resultado.sair_dos_detalhes


# endregion
# region Zerado que saiu da store


def test_zerado_que_saiu_da_store_nao_volta(edicao, store, sgdb, app_dirs):
    """Se o zerado saiu da store com o diálogo aberto, aplicar não grava a ficha nem o põe de volta na store."""
    zerado = jogo(store, 40, removed=True, status="beaten", playtime=120)
    form = edicao.Formulario.do_jogo(zerado)
    form.nome = "Outro nome"
    store.excluir(zerado, apagar_sessoes=False)  # a ligação rodou por baixo
    salvou = []
    zerado.salvar.connect(lambda: salvou.append(1))

    resultado = edicao.aplicar(form, zerado, "")

    assert resultado.fechar_sem_gravar is True
    assert salvou == []
    assert zerado.name == "Jogo 40"
    assert store.get(zerado.game_id) is None
    assert sgdb.pedidos == []


def test_jogo_vivo_fora_da_store_e_gravado(edicao, store, sgdb):
    """O guarda é só do zerado: um jogo vivo nunca é apagado por baixo."""
    vivo = jogo(None, 41)
    resultado = _aplicar(edicao, vivo, nome="Novo")
    assert not resultado.fechar_sem_gravar
    assert store.get(vivo.game_id) is vivo


# endregion
# region AppID e Ludusavi


def test_appid_digitado_manda_sobre_o_buscado(edicao, store, sgdb):
    from cartridges.utils.steam import STEAM_METADATA_VERSION  # noqa: PLC0415

    game = jogo(store, 30, steam_appid="10")
    form = edicao.Formulario.do_jogo(game)
    _buscar(form, "620")
    form.appid = "10"  # de volta ao antigo depois da busca
    edicao.aplicar(form, game, "10")
    assert game.steam_appid == "10"
    assert game.steam_checked == 0

    form = edicao.Formulario.do_jogo(game)
    _buscar(form, "620")
    form.appid = ""  # apagado depois da busca
    edicao.aplicar(form, game, "10")
    assert game.steam_appid is None

    form = edicao.Formulario.do_jogo(game)
    _buscar(form, "620")  # sem mexer no campo: vale o da busca, carimbado
    edicao.aplicar(form, game, "")
    assert game.steam_appid == "620"
    assert game.steam_checked == STEAM_METADATA_VERSION


def test_appid_com_espacos_grava_cortado(edicao, store, sgdb):
    game = jogo(store, 31, steam_appid="620")
    _aplicar(edicao, game, appid=" 400 ")
    assert game.steam_appid == "400"


def test_campo_do_appid_intocado_nao_mexe_no_appid(edicao, store, sgdb):
    game = jogo(store, 32, steam_appid="620", ludusavi_nome="Portal", steam_checked=3)
    _aplicar(edicao, game, nome="Outro")
    assert (game.steam_appid, game.ludusavi_nome, game.steam_checked) == ("620", "Portal", 3)


def test_mudar_appid_zera_ludusavi_e_aviso(edicao, store, sgdb):
    game = jogo(store, 33, steam_appid="620", ludusavi_nome="Portal", saves_local_desconhecido_avisado=True)
    _aplicar(edicao, game, appid="400")
    assert game.steam_appid == "400"
    assert game.ludusavi_nome == ""
    assert game.saves_local_desconhecido_avisado is False

    mesmo = jogo(store, 34, steam_appid="10", ludusavi_nome="Jogo", saves_local_desconhecido_avisado=True)
    form = edicao.Formulario.do_jogo(mesmo)
    _buscar(form, "10")  # a busca devolveu o mesmo appID: nada a zerar
    form.executavel = "y.exe"
    edicao.aplicar(form, mesmo, "10")
    assert (mesmo.ludusavi_nome, mesmo.saves_local_desconhecido_avisado) == ("Jogo", True)


def test_ludusavi_escolhido_ganha_do_zeramento(edicao, store, sgdb):
    game = jogo(store, 35, steam_appid="10", ludusavi_nome="Antigo", backup_dos_saves_desligado=True)
    _aplicar(edicao, game, appid="620", ludusavi_escolhido="Portal 2")
    assert game.steam_appid == "620"
    assert game.ludusavi_nome == "Portal 2"
    assert game.backup_dos_saves_desligado is False


def test_ludusavi_nenhum_desliga_o_backup(edicao, store, sgdb):
    game = jogo(store, 36, ludusavi_nome="Portal")
    _aplicar(edicao, game, ludusavi_escolhido="")
    assert game.ludusavi_nome == ""
    assert game.backup_dos_saves_desligado is True


def test_mudar_o_appid_nao_mexe_no_backup_desligado(edicao, store, sgdb):
    game = jogo(store, 37, steam_appid="10", backup_dos_saves_desligado=True)
    _aplicar(edicao, game, appid="620")
    assert game.backup_dos_saves_desligado is True


# endregion
# region Buscados


def test_hltb_parcial_preserva_as_outras_chaves(edicao, store, sgdb):
    game = jogo(store, 50, hltb_id=1, hltb_main=100, hltb_main_extra=200, hltb_completionist=300)
    form = edicao.Formulario.do_jogo(game)
    form.buscado = {"hltb": {"hltb_id": 2, "hltb_main": 150}}
    edicao.aplicar(form, game, "")
    assert (game.hltb_id, game.hltb_main, game.hltb_main_extra, game.hltb_completionist) == (2, 150, 200, 300)


def test_buscados_so_entram_quando_chegaram(edicao, store, sgdb):
    game = jogo(store, 51, metacritic=90, gamepad_recommended=True, description="d", steam_review="r")
    _aplicar(edicao, game, nome="Outro")
    assert (game.metacritic, game.gamepad_recommended, game.description, game.steam_review) == (90, True, "d", "r")

    form = edicao.Formulario.do_jogo(game)
    form.buscado = {"gamepad_recommended": False, "metacritic": 70}
    edicao.aplicar(form, game, "")
    assert game.gamepad_recommended is False  # False é resposta, não ausência
    assert (game.metacritic, game.description) == (70, "d")


# Todo campo de metadados que a ficha guarda, com valor diferente do padrão da classe: um que a edição esquece aparece como mudança.
PERSISTED_METADATA = {
    "developer": "Team Cherry",
    "publisher": "Team Cherry",
    "release_date": "24/fev./2017",
    "metacritic": 90,
    "steam_review": "Extremamente positivas",
    "genre": "Metroidvania",
    "controller_support": "full",
    "gamepad_recommended": True,
    "description": "Forje seu caminho em Hollow Knight!",
    "steam_appid": "367520",
    "steam_checked": 1,
    "hltb_id": 26286,
    "hltb_main": 90000,
    "hltb_main_extra": 140000,
    "hltb_completionist": 230000,
    "hltb_chapters": [{"number": 1, "name": "Prólogo", "hltb_main": 3600}],
    "track_updates": True,
    "process_executable": "hollow_knight.exe",
    "status": "beaten",
    "rating": 4,
    "notes": "Parei no capítulo 4.\nSenha do cofre: 8815",
    "conquistas": False,
    "ludusavi_nome": "Hollow Knight",
    "backup_dos_saves_desligado": True,
    "saves_local_desconhecido_avisado": True,
    "update_available_ts": 5,
    "update_url": "https://x",
    "run_as_admin": True,
}


# O que a ficha guarda e não é metadado do jogo: identidade, contas do app, o rastreio e o aviso dispensado.
NOT_GAME_METADATA = {
    "added", "blacklisted", "comando_a_conferir", "executable", "game_id", "install_size", "install_size_ts",
    "idioma_proprio", "idiomas_steam", "inis", "appid_manual", "nome_proprio",
    "last_played", "name", "playtime", "removed", "shortcut_mtime", "shortcut_path", "source", "track_process",
    "update_dismissed_ts", "version",
}  # fmt: skip


def test_the_guard_covers_every_persisted_field():
    """Campo novo em `PERSISTED_ATTRS` obriga a pô-lo na guarda acima ou a dizer aqui por que ele não pertence a ela."""
    from cartridges.jogo import PERSISTED_ATTRS  # noqa: PLC0415

    cobertos = set(PERSISTED_METADATA) | NOT_GAME_METADATA
    assert set(PERSISTED_ATTRS) - cobertos == set(), "campo fora da guarda"
    assert cobertos - set(PERSISTED_ATTRS) == set(), "a guarda lista um campo que ninguém grava"


def test_aplicar_sem_mudar_nada_nao_custa_nada(edicao, store, sgdb):
    game = jogo(store, 52, executable="x.exe", **PERSISTED_METADATA)
    _aplicar(edicao, game)
    for campo, valor in PERSISTED_METADATA.items():
        assert getattr(game, campo) == valor, f"aplicar perdeu {campo}"


def test_mudar_um_campo_deixa_os_outros(edicao, store, sgdb):
    game = jogo(store, 53, executable="x.exe", **PERSISTED_METADATA)
    _aplicar(edicao, game, nome="Hollow Knight")
    assert game.name == "Hollow Knight"
    for campo, valor in PERSISTED_METADATA.items():
        assert getattr(game, campo) == valor, f"mudar o título perdeu {campo}"


def test_genero_e_controle(edicao, store, sgdb):
    """Espaço é vazio, e "não informado" desfaz um valor."""
    game = jogo(store, 54, genre="Metroidvania", controller_support="full")
    form = edicao.Formulario.do_jogo(game)
    assert (form.genero, form.controle) == ("Metroidvania", "full")
    _aplicar(edicao, game, genero="  Soulslike  ", controle="partial")
    assert (game.genre, game.controller_support) == ("Soulslike", "partial")
    _aplicar(edicao, game, genero="   ", controle=None)
    assert (game.genre, game.controller_support) == (None, None)


def test_valores_desconhecidos_abrem_como_vazios(edicao, store):
    game = jogo(store, 55, controller_support="talvez", status="estranho", rating=9)
    form = edicao.Formulario.do_jogo(game)
    assert (form.controle, form.status, form.nota) == (None, "", 5)


def test_nota_e_status(edicao, store, sgdb):
    game = jogo(store, 56, rating=4, status="beaten")
    _aplicar(edicao, game, nota=0, status="playing")
    assert (game.rating, game.status) == (0, "playing")
    _aplicar(edicao, game, status="")
    assert game.status == ""


def test_nome_do_processo_vem_do_comando(edicao, store):
    game = jogo(store, 57, executable='start "" "C:\\Jogos\\HK\\hollow_knight.exe"')
    assert edicao.Formulario.do_jogo(game).executavel_do_processo == "hollow_knight.exe"
    assert edicao.exe_name_from_command("steam://rungameid/620") == ""
    assert edicao.exe_name_from_command('explorer.exe "C:\\a\\b.exe"') == "b.exe"


# endregion
# region Atualizações


def test_desligar_notificar_zera_o_aviso(edicao, store, sgdb, aplicativo):
    game = jogo(store, 60, track_updates=True, update_available_ts=5, update_url="https://x", update_dismissed_ts=3)
    _aplicar(edicao, game, notificar_atualizacoes=False)
    assert (game.track_updates, game.update_available_ts, game.update_url) == (False, 0, "")
    assert game.update_dismissed_ts == 3
    assert aplicativo.verificacoes == []


def test_ligar_notificar_pede_verificacao(edicao, store, sgdb, aplicativo):
    game = jogo(store, 61)
    _aplicar(edicao, game, notificar_atualizacoes=True)
    assert game.track_updates is True
    assert aplicativo.verificacoes == [1]

    _aplicar(edicao, game)  # já estava ligado: sem nova verificação
    assert aplicativo.verificacoes == [1]


def test_ligar_notificar_sem_aplicativo_nao_quebra(edicao, store, sgdb):
    game = jogo(store, 62)
    _aplicar(edicao, game, notificar_atualizacoes=True)
    assert game.track_updates is True


# endregion
# region Rastreio do processo


def _pasta_de_jogo(tmp_path):
    """Pasta que o app reconhece como a de um jogo só: tem desinstalador."""
    pasta = tmp_path / "Jogo"
    pasta.mkdir()
    (pasta / "unins000.exe").write_bytes(b"")
    (pasta / "jogo.exe").write_bytes(b"")
    return f'"{pasta / "jogo.exe"}"'


def test_rastrear_sem_nome_e_forcado_desligado(edicao, store, sgdb, tmp_path):
    """Com a pasta reconhecida ou a identidade do pacote, o tempo já é contado: o switch escondido não trava o Aplicar."""
    for comando in (_pasta_de_jogo(tmp_path), "explorer.exe shell:AppsFolder\\Pacote_8wekyb3d8bbwe!App"):
        assert edicao.acompanha_sem_nome(comando)
        form = edicao.Formulario.do_jogo(None)
        form.nome, form.executavel = "Jogo com pasta", comando
        form.rastrear_processo, form.executavel_do_processo = True, ""
        assert edicao.validar(form, None) is None
        novo = edicao.aplicar(form, None, "").jogo
        assert novo.track_process is False

    assert not edicao.acompanha_sem_nome("steam://rungameid/620")


# endregion
# region Zerados


@pytest.mark.parametrize(
    ("numero", "executavel", "volta"),
    [(24, "", False), (26, "x", True)],
    ids=["sem-executavel", "com-executavel"],
)
def test_desmarcar_pela_edicao_passa_pela_mesma_regra(edicao, store, sgdb, tmp_path, numero, executavel, volta):
    atalho = tmp_path / "Jogo.lnk"
    atalho.write_bytes(b"")
    game = jogo(store, numero, removed=True, status="beaten", executable=executavel, shortcut_path=str(atalho))

    resultado = _aplicar(edicao, game, status="")

    # Chegar ao status vazio prova que o executável vazio não barrou a edição.
    assert game.status == ""
    assert game.removed is not volta
    assert resultado.sair_dos_detalhes is not volta


def test_zerado_que_vira_desinstalado_sai_dos_detalhes(edicao, store, sgdb):
    zerado = jogo(store, 70, removed=True, status="beaten")  # sem atalho na pasta
    assert _aplicar(edicao, zerado, status="playing").sair_dos_detalhes is True
    assert zerado.removed is True

    outro = jogo(store, 71, removed=True, status="beaten")
    assert _aplicar(edicao, outro, nome="Outro nome").sair_dos_detalhes is False
    vivo = jogo(store, 72, status="beaten")
    assert _aplicar(edicao, vivo, status="").sair_dos_detalhes is False


# endregion
# region Capa, logo e papel de parede


def test_sem_capa_pede_sgdb(edicao, store, sgdb, app_dirs):
    game = jogo(store, 80)
    _aplicar(edicao, game)
    assert sgdb.pedidos == [game.game_id]
    assert game.loading == 0

    com_capa = jogo(store, 81)
    Image.new("RGB", (6, 9), "red").save(app_dirs.covers / f"{com_capa.game_id}.tiff")
    _aplicar(edicao, com_capa)
    assert sgdb.pedidos == [game.game_id]


def test_erro_amigavel_do_sgdb_vira_dialogo(edicao, store, aplicativo):
    from cartridges.errors.friendly_error import FriendlyError  # noqa: PLC0415

    stub_sgdb(store, erros=[FriendlyError("Não foi possível autenticar no SteamGridDB", "Verifique a chave."), ValueError("x")])
    _aplicar(edicao, jogo(store, 82))
    assert aplicativo.dialogos == [("Não foi possível autenticar no SteamGridDB", "Verifique a chave.")]


def test_erro_do_sgdb_oferece_as_preferencias_do_sgdb(edicao, store, aplicativo):
    from cartridges.errors.friendly_error import FriendlyError  # noqa: PLC0415

    stub_sgdb(store, erros=[FriendlyError("Não foi possível autenticar no SteamGridDB", "Verifique a chave.")])
    _aplicar(edicao, jogo(store, 84))
    assert aplicativo.paginas == ["sgdb"]


def test_capa_que_nao_grava_nao_derruba_o_aplicar(edicao, store, sgdb, monkeypatch, tmp_path, caplog):
    game = jogo(store, 83)
    capa = tmp_path / "nova.tiff"
    Image.new("RGB", (60, 90), "green").save(capa)

    def recusa(*_args):
        raise PermissionError(5, "Acesso negado")

    monkeypatch.setattr(edicao, "save_cover", recusa)
    _aplicar(edicao, game, capa=capa, capa_mudou=True, nome="Outro nome")
    girar()

    assert game.name == "Outro nome"
    assert store.get(game.game_id) is game
    assert "Could not save the cover" in caplog.text
    assert capa.exists(), "a provisória ainda é a capa desta sessão"
    assert sgdb.pedidos == []


@pytest.fixture
def abandonadas(monkeypatch):
    from cartridges.utils import copias_animadas  # noqa: PLC0415

    lista = []
    monkeypatch.setattr(copias_animadas, "abandonar", lista.append)
    return lista


def test_capa_aplicada_e_lida_ate_a_recarga(edicao, store, sgdb, app_dirs, tmp_path, abandonadas):
    """A provisória só sai depois da recarga que o `save_cover` agenda: até lá a tela de detalhes ainda pode lê-la."""
    game = jogo(store, 84)
    provisoria = tmp_path / "escolhida.tiff"
    Image.new("RGB", (60, 90), "red").save(provisoria)

    _aplicar(edicao, game, capa=provisoria, capa_mudou=True)
    assert provisoria.exists()
    assert (app_dirs.covers / f"{game.game_id}.tiff").is_file()

    girar()
    assert not provisoria.exists()
    assert abandonadas == [provisoria]
    assert sgdb.pedidos == []


def test_provisoria_presa_ainda_abandona_as_copias(edicao, store, sgdb, tmp_path, abandonadas, monkeypatch):
    """Um antivírus segurando a provisória não pode deixar a geração dela na fila."""
    game = jogo(store, 85)
    provisoria = tmp_path / "a.tiff"
    Image.new("RGB", (60, 90), "red").save(provisoria)
    unlink = Path.unlink

    def unlink_preso(self, missing_ok=False):
        if self == provisoria:
            raise PermissionError(32, "arquivo em uso")
        return unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink_preso)
    _aplicar(edicao, game, capa=provisoria, capa_mudou=True)
    girar()
    assert abandonadas == [provisoria]


def test_excluir_a_capa(edicao, store, sgdb, app_dirs):
    game = jogo(store, 86)
    capa = app_dirs.covers / f"{game.game_id}.tiff"
    Image.new("RGB", (6, 9), "red").save(capa)
    _aplicar(edicao, game, capa=None, capa_mudou=True)
    assert not capa.exists()
    assert sgdb.pedidos == [game.game_id]


def test_logo_e_parede_sao_gravados_com_o_nome_final(edicao, store, sgdb, tmp_path):
    from cartridges.utils import game_logo, session_wallpaper  # noqa: PLC0415

    game = jogo(store, 87)
    logo = tmp_path / "logo_tmp.png"
    Image.new("RGBA", (40, 12)).save(logo)
    parede = tmp_path / "parede_tmp.jpg"
    Image.new("RGB", (64, 36), "blue").save(parede)
    posicoes = session_wallpaper.Posicoes(retrato=0.2, paisagem=0.8)

    _aplicar(
        edicao,
        game,
        nome="Nome final",
        logo=edicao.Escolha("manual", logo, temporario=True),
        papel_de_parede=edicao.Escolha("manual", parede, posicoes=posicoes, temporario=True),
    )

    assert game_logo.logo_choice(game) == "manual"
    assert session_wallpaper.escolha(game) == "manual"
    assert session_wallpaper.posicoes_escolhidas(game.game_id) == posicoes
    assert not logo.exists(), "o logo já foi copiado para a pasta dos logos"
    assert not parede.exists(), "a imagem já foi copiada para a pasta das paredes"


def test_logo_de_um_arquivo_do_disco_nao_e_apagado(edicao, store, sgdb, tmp_path):
    game = jogo(store, 88)
    logo = tmp_path / "meu_logo.png"
    Image.new("RGBA", (40, 12)).save(logo)
    _aplicar(edicao, game, logo=edicao.Escolha("manual", logo))
    assert logo.exists()


def test_titulo_e_nao_trocar_e_voltar_ao_automatico(edicao, store, sgdb):
    from cartridges.utils import game_logo, session_wallpaper  # noqa: PLC0415

    game = jogo(store, 89)
    _aplicar(edicao, game, logo=edicao.Escolha("title"), papel_de_parede=edicao.Escolha("none"))
    assert game_logo.logo_choice(game) == "title"
    assert session_wallpaper.escolha(game) == "none"

    _aplicar(edicao, game, nome="Intocado")  # sem escolha: nada muda
    assert game_logo.logo_choice(game) == "title"

    _aplicar(edicao, game, logo=edicao.Escolha("auto"), papel_de_parede=edicao.Escolha("auto"))
    assert game_logo.logo_choice(game) == "auto"
    assert session_wallpaper.escolha(game) == "auto"


# endregion


def test_edicao_sem_gi():
    codigo = (
        "import builtins, sys; builtins._ = lambda m: m; "
        "builtins.ngettext = lambda s, p, n: s if n == 1 else p; "
        "import cartridges.edicao, cartridges.utils.ligacao_zerado, cartridges.utils.session_wallpaper; "
        "assert 'gi' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", codigo], check=True, cwd=Path(__file__).resolve().parent.parent)


# region Capa preparada e capa presa


def test_preparar_capa_de_imagem_parada_deixa_so_um_tiff(edicao, tmp_path, monkeypatch):
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(temp))
    origem = tmp_path / "larga.png"
    Image.new("RGB", (300, 100), "red").save(origem)
    capa = edicao.preparar_capa(origem)
    assert capa is not None and capa.suffix == ".tiff" and list(temp.iterdir()) == [capa]
    with Image.open(capa) as pronta:
        assert pronta.size == shared.image_size


def test_preparar_capa_animada_segue_como_esta(edicao, tmp_path):
    origem = tmp_path / "anim.gif"
    quadros = [Image.new("RGB", (40, 60), cor) for cor in ("red", "blue")]
    quadros[0].save(origem, save_all=True, append_images=quadros[1:], duration=50, loop=0)
    capa = edicao.preparar_capa(origem)
    assert capa is not None and capa.suffix == ".gif"
    capa.unlink()


def test_preparar_capa_ilegivel_devolve_none_sem_deixar_temporario(edicao, tmp_path, monkeypatch):
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(temp))
    origem = tmp_path / "quebrada.png"
    origem.write_bytes(b"nao e uma imagem")
    assert edicao.preparar_capa(origem) is None
    assert list(temp.iterdir()) == []


def test_capa_presa_fica_como_a_da_sessao_e_um_aplicar_bom_a_solta(edicao, store, sgdb, app_dirs, tmp_path, monkeypatch):
    game = jogo(store, 88)
    provisoria = tmp_path / "p.tiff"
    Image.new("RGB", (60, 90), "green").save(provisoria)
    real = edicao.save_cover

    def recusa(*_args):
        raise PermissionError(5, "Acesso negado")

    monkeypatch.setattr(edicao, "save_cover", recusa)
    resultado = _aplicar(edicao, game, capa=provisoria, capa_mudou=True)
    girar()
    assert resultado.capa_presa is True
    assert game.get_cover_path() == provisoria and provisoria.exists()

    monkeypatch.setattr(edicao, "save_cover", real)
    outra = tmp_path / "o.tiff"
    Image.new("RGB", (60, 90), "blue").save(outra)
    assert _aplicar(edicao, game, capa=outra, capa_mudou=True).capa_presa is False
    girar()
    assert game.get_cover_path() == app_dirs.covers / f"{game.game_id}.tiff"


def test_estado_do_logo_e_do_papel(edicao, store):
    game = jogo(store, 89)
    form = edicao.Formulario.do_jogo(game)
    assert (edicao.estado_do_logo(form, game), edicao.estado_do_papel(form, game)) == ("auto", "auto")
    form.logo, form.papel_de_parede = edicao.Escolha("title"), edicao.Escolha("none")
    assert (edicao.estado_do_logo(form, game), edicao.estado_do_papel(form, game)) == ("title", "none")
    assert edicao.estado_do_logo(edicao.Formulario(), None) == "auto"


# endregion


def test_jogo_adicionado_a_mao_durante_a_importacao_nao_entra_no_desfazer(edicao, store, sgdb, monkeypatch):
    from cartridges.importer.importer import Importer  # noqa: PLC0415

    monkeypatch.setattr(Importer, "summary_toast", None)
    importer = Importer(SimpleNamespace(avisos=None))
    form = edicao.Formulario.do_jogo(None)
    form.nome, form.executavel = "Jogo novo", "cmd /c exit"

    novo = edicao.aplicar(form, None, "").jogo

    assert novo.game_id not in store.new_game_ids
    importer.imported_game_ids = store.new_game_ids  # o que o fim da importação guarda para o "Desfazer"
    importer.undo_import()
    assert novo.removed is False


def test_edicao_usa_o_temporario_do_save_cover():
    from cartridges import edicao as modulo  # noqa: PLC0415
    from cartridges.utils import save_cover  # noqa: PLC0415

    assert modulo._temporario is save_cover._temporario  # noqa: SLF001


def test_appid_digitado_liga_appid_manual_e_apagado_desliga(edicao, store, sgdb):
    game = jogo(store, 60, steam_appid="620")
    _aplicar(edicao, game, appid="400")
    assert game.appid_manual is True
    _aplicar(edicao, game, appid="")
    assert game.appid_manual is False and game.steam_appid is None


def test_appid_do_campo_intocado_nao_liga_appid_manual(edicao, store, sgdb):
    game = jogo(store, 61, steam_appid="620")
    _aplicar(edicao, game)
    assert game.appid_manual is False
