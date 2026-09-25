# test_auditoria_0923_ligacao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Q2: um zerado é ligado ao jogo da biblioteca que ganha o mesmo appID."""

import pytest

from cartridges import shared
from cartridges.game import Game
from cartridges.utils import session_log
from tests.test_zerados import jogo


@pytest.fixture
def ligar(real_window):
    from cartridges.utils.ligacao_zerado import ligar_zerado  # noqa: PLC0415

    return ligar_zerado


@pytest.fixture
def avisos(real_window, monkeypatch):
    """Os títulos dos toasts que a janela recebe."""
    titulos: list[str] = []
    monkeypatch.setattr(
        real_window.toast_queue, "add", lambda toast, *_a: titulos.append(toast.get_title())
    )
    return titulos


def _stub_sgdb(store):
    from cartridges.store.managers.sgdb_manager import SgdbManager  # noqa: PLC0415

    class StubSgdb:
        signals: set = set()

        def reset_cancellable(self):
            pass

        def collect_errors(self):
            return []

        def process_game(self, game, _data, callback):
            game.set_loading(-1)
            callback(self)

    store.managers[SgdbManager] = StubSgdb()


def test_liga_e_transfere_tudo(store, ligar, write_asset, avisos):
    zerado = jogo(store, 1, removed=True, status="beaten", steam_appid="570",
                  playtime=3600, last_played=500, rating=4, notes="final secreto")
    vivo = jogo(store, 2, steam_appid="570", playtime=60, last_played=900)
    session_log.record(zerado.game_id, 3600, 1_700_000_000)
    write_asset("covers", f"{zerado.game_id}.tiff", b"capa-do-zerado")

    assert ligar(vivo) is True
    assert store.get(zerado.game_id) is None
    assert not (shared.games_dir / f"{zerado.game_id}.json").exists()
    assert vivo.playtime == 3660
    assert vivo.last_played == 900
    assert (vivo.status, vivo.rating, vivo.notes) == ("beaten", 4, "final secreto")
    assert [s["seconds"] for s in session_log.load(vivo.game_id)] == [3600]
    assert (shared.covers_dir / f"{vivo.game_id}.tiff").read_bytes() == b"capa-do-zerado"
    assert "Os dados de Jogo 2 em Jogos Zerados foram transferidos para a biblioteca" in avisos


def test_so_preenche_o_vazio(store, ligar):
    jogo(store, 3, removed=True, status="beaten", steam_appid="10", rating=2, notes="a")
    vivo = jogo(store, 4, steam_appid="10", status="playing", rating=5, notes="b")
    assert ligar(vivo) is True
    assert (vivo.status, vivo.rating, vivo.notes) == ("playing", 5, "b")


def test_dois_zerados_nao_liga(store, ligar):
    jogo(store, 5, removed=True, status="beaten", steam_appid="20")
    jogo(store, 6, removed=True, status="beaten", steam_appid="20")
    vivo = jogo(store, 7, steam_appid="20")
    assert ligar(vivo) is False


def test_dois_vivos_nao_liga(store, ligar):
    jogo(store, 8, removed=True, status="beaten", steam_appid="30")
    vivo = jogo(store, 9, steam_appid="30")
    jogo(store, 10, steam_appid="30")
    assert ligar(vivo) is False


def test_rotina_da_steam_so_marca_a_ligacao(store, monkeypatch):
    """`SteamAPIManager.main` não liga na hora: só marca `additional_data`.

    Quem liga de fato, e só depois que o pipeline inteiro termina (SGDB
    incluído), é `Store._ao_avancar_pipeline` — ver
    `test_ligacao_so_roda_depois_do_pipeline_inteiro` abaixo. Ligar aqui, na
    hora, é exatamente o bug que causava a corrida com a capa do SGDB.
    """
    from cartridges.store.managers import steam_api_manager  # noqa: PLC0415

    gerente = steam_api_manager.SteamAPIManager()
    monkeypatch.setattr(gerente.steam_api_helper, "resolve", lambda _n: ("570", {}))
    vivo = jogo(store, 11)

    dados = {}
    gerente.main(vivo, dados)
    assert dados.get("ligar_zerado") is True

    vivo.steam_appid = None
    dados_sem_ligacao = {"sem_ligacao": True}
    gerente.main(vivo, dados_sem_ligacao)
    assert "ligar_zerado" not in dados_sem_ligacao


def test_ligacao_so_roda_depois_do_pipeline_inteiro(real_window, store, flush_idle):
    """A ligação espera o pipeline do jogo terminar por inteiro.

    Um manager parecido com o SteamAPIManager marca `ligar_zerado` e termina
    na hora; um segundo, parecido com o SGDB (`run_after` do primeiro), só
    termina quando o teste manda. Enquanto ele não termina, a fusão não pode
    ter acontecido — é exatamente a corrida com o download de capa do SGDB
    que este teste prova que não existe mais. Não faz stub de `agendar`: usa
    o `Store.add_game` e o `Pipeline` de verdade.
    """
    from cartridges.store.managers.manager import Manager  # noqa: PLC0415

    class _FingeSteam(Manager):
        """No lugar do SteamAPIManager: marca a ligação e termina na hora."""

        def main(self, game: Game, additional_data: dict) -> None:
            additional_data["ligar_zerado"] = True

    class _FingeSgdb(Manager):
        """No lugar do SGDB: só termina quando o teste chamar `pronto()`."""

        run_after = (_FingeSteam,)
        blocking = False

        def __init__(self) -> None:
            super().__init__()
            self.pronto = None

        def main(self, game: Game, additional_data: dict) -> None:  # pragma: no cover
            raise AssertionError("main não deveria rodar: process_game é sobrescrito")

        def process_game(self, game, additional_data, callback) -> None:
            self.pronto = lambda: callback(self)

    sgdb_falso = _FingeSgdb()
    store.pipeline_managers = {_FingeSteam(), sgdb_falso}

    zerado = jogo(store, 21, removed=True, status="beaten", steam_appid="800", playtime=10)
    vivo = Game(
        {
            "source": "shortcuts",
            "game_id": "shortcuts_z22",
            "name": "Jogo 22",
            "executable": "x",
            "added": 0,
            "steam_appid": "800",
        }
    )

    pipeline = store.add_game(vivo, {})
    assert pipeline is not None

    # O manager que marcou a ligação já terminou, mas o "SGDB" ainda está
    # rodando: a fusão não pode ter acontecido ainda.
    flush_idle()
    assert store.get(zerado.game_id) is not None

    sgdb_falso.pronto()  # agora o pipeline termina de verdade
    flush_idle()

    assert store.get(zerado.game_id) is None
    assert vivo.playtime == 10


def test_nao_sobrescreve_escolha_travada_do_jogo(store, ligar, tmp_path):
    """"Escolha própria" é qualquer decisão travada do jogo, não só um
    arquivo manual: "usar o título" no logo e "não trocar" na parede também
    são decisões do jogo, e a ligação não pode desfazê-las."""
    from cartridges.utils import game_logo, session_wallpaper  # noqa: PLC0415

    zerado = jogo(store, 23, removed=True, status="beaten", steam_appid="900")
    vivo = jogo(store, 24, steam_appid="900")

    logo_zerado = tmp_path / "logo.png"
    logo_zerado.write_bytes(b"logo-zerado")
    game_logo.save_manual_logo(zerado.game_id, zerado.name, logo_zerado)
    game_logo.use_title_instead(vivo.game_id, vivo.name)

    parede_zerado = tmp_path / "parede.jpg"
    parede_zerado.write_bytes(b"parede-zerado")
    session_wallpaper.salvar_escolha(
        zerado.game_id, zerado.name, parede_zerado, session_wallpaper.Posicoes()
    )
    session_wallpaper.nao_trocar(vivo.game_id, vivo.name)

    assert ligar(vivo) is True
    assert game_logo.logo_choice(vivo) == "title"
    assert session_wallpaper.escolha(vivo) == "none"


def test_edicao_troca_appid_e_liga(store, real_window, avisos):
    """O segundo gatilho: `DetailsDialog.apply_preferences` liga quando o
    appID buscado (`fetched_steam_appid`) difere do que o jogo já tinha."""
    from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415

    _stub_sgdb(store)
    zerado = jogo(store, 14, removed=True, status="beaten", steam_appid="640", playtime=120)
    vivo = jogo(store, 15, executable="x.exe")

    dialog = DetailsDialog(vivo)
    dialog.fetched_steam_appid = "640"
    dialog.apply_preferences()

    assert vivo.steam_appid == "640"
    assert store.get(zerado.game_id) is None
    assert vivo.playtime == 120
    assert "Os dados de Jogo 15 em Jogos Zerados foram transferidos para a biblioteca" in avisos


def test_fecha_a_tela_de_detalhes_do_zerado_fundido(store, ligar, real_window, monkeypatch):
    """Se a tela de detalhes do zerado fundido estiver aberta, ela fecha.

    Sem isso, `active_game` continuaria apontando para um jogo que não existe
    mais na store, e qualquer ação nela (mudar status, editar) reviveria o
    arquivo apagado, contando o tempo em dobro numa próxima ligação."""
    zerado = jogo(store, 27, removed=True, status="beaten", steam_appid="960")
    vivo = jogo(store, 28, steam_appid="960")

    real_window.active_game = zerado
    monkeypatch.setattr(
        real_window.navigation_view, "get_visible_page", lambda: real_window.details_page
    )
    fechou = []
    monkeypatch.setattr(real_window.navigation_view, "pop", lambda: fechou.append(1))

    assert ligar(vivo) is True
    assert fechou == [1]


def test_nao_fecha_a_tela_de_detalhes_de_outro_jogo(store, ligar, real_window, monkeypatch):
    """Só fecha a tela se for a do próprio zerado fundido: a de outro jogo,
    aberta por coincidência ao mesmo tempo, fica onde estava."""
    zerado = jogo(store, 29, removed=True, status="beaten", steam_appid="970")
    vivo = jogo(store, 30, steam_appid="970")
    outro = jogo(store, 31)

    real_window.active_game = outro
    monkeypatch.setattr(
        real_window.navigation_view, "get_visible_page", lambda: real_window.details_page
    )
    fechou = []
    monkeypatch.setattr(real_window.navigation_view, "pop", lambda: fechou.append(1))

    assert ligar(vivo) is True
    assert fechou == []


def test_apply_fecha_sem_salvar_se_o_zerado_sumiu_da_store(store, real_window, monkeypatch):
    """Se a ligação por appID apagar o zerado enquanto a tela de detalhes dele
    está aberta (Editar aberto, import termina em outra thread e funde), o
    Aplicar não pode ressuscitá-lo — fecharia a store apagou, save() gravaria
    de novo o arquivo e o tempo contaria em dobro numa fusão futura."""
    from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415

    zerado = jogo(store, 40, removed=True, status="beaten", playtime=120)
    dialog = DetailsDialog(zerado)
    store.excluir(zerado, apagar_sessoes=False)  # a ligação já rodou por baixo

    salvou = []
    monkeypatch.setattr(zerado, "save", lambda: salvou.append(1))
    fechou = []
    monkeypatch.setattr(dialog, "close", lambda: fechou.append(1))

    dialog.apply_preferences()

    assert salvou == []
    assert fechou == [1]
    assert store.get(zerado.game_id) is None
