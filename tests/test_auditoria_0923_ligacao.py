# test_auditoria_0923_ligacao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Q2: um zerado é ligado ao jogo da biblioteca que ganha o mesmo appID."""

from types import SimpleNamespace

import pytest

from cartridges import shared
from cartridges.utils import session_log
from tests.apoio_edicao import girar, jogo, stub_sgdb


@pytest.fixture
def ligar():
    from cartridges.utils.ligacao_zerado import ligar_zerado  # noqa: PLC0415

    return ligar_zerado


@pytest.fixture
def avisos(monkeypatch):
    """Os textos que chegam à fila de avisos do app."""
    textos: list[str] = []
    fila = SimpleNamespace(adicionar=lambda texto, *_a, **_k: textos.append(texto))
    monkeypatch.setattr(shared, "aplicativo", SimpleNamespace(avisos=fila), raising=False)
    return textos


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
    assert avisos == ["Os dados de Jogo 2 em Jogos Zerados foram transferidos para a biblioteca"]


def test_liga_sem_aplicativo_nao_quebra(store, ligar):
    """Nos testes e no começo da abertura não há fila de avisos: a ligação segue."""
    jogo(store, 3, removed=True, status="beaten", steam_appid="571")
    vivo = jogo(store, 4, steam_appid="571")
    assert ligar(vivo) is True


def test_agendar_liga_na_thread_principal(store):
    from cartridges.utils import ligacao_zerado  # noqa: PLC0415

    zerado = jogo(store, 5, removed=True, status="beaten", steam_appid="572")
    vivo = jogo(store, 6, steam_appid="572")
    ligacao_zerado.agendar(vivo)
    assert store.get(zerado.game_id) is zerado  # ainda não: vai pela fila
    girar()
    assert store.get(zerado.game_id) is None


@pytest.fixture
def fila_das_copias(monkeypatch):
    """A fila das cópias animadas com o executor nas mãos do teste."""
    from cartridges.utils import copias_animadas  # noqa: PLC0415

    fila = []
    monkeypatch.setattr(copias_animadas, "_executor", SimpleNamespace(submit=fila.append))
    yield SimpleNamespace(fila=fila)
    copias_animadas.encerrar()


def _animada(caminho, cor):
    from PIL import Image  # noqa: PLC0415

    caminho.parent.mkdir(parents=True, exist_ok=True)
    quadros = [Image.new("RGB", (60, 90), c) for c in (cor, "black")]
    quadros[0].save(caminho, save_all=True, append_images=quadros[1:], duration=100)
    return caminho


def _copias_de(game_id):
    """As cópias animadas do jogo, gravadas de verdade a partir da capa dele."""
    from cartridges.utils import copias_animadas  # noqa: PLC0415

    capa = shared.covers_dir / f"{game_id}.gif"
    copias = []
    for tamanho in copias_animadas.tamanhos():
        copias.append(copias_animadas.caminho_para(capa, tamanho))
        assert copias_animadas.gerar(capa, copias[-1], tamanho)
    return copias


@pytest.mark.parametrize("capa_do_zerado", ["animada", "estatica"])
def test_a_capa_do_zerado_leva_embora_as_copias_da_capa_anterior(
    store, ligar, schema, fila_das_copias, write_asset, capa_do_zerado
):
    """O nome da cópia é só o id: sem invalidar, o jogo tocaria a animação da
    capa que acabou de ser substituída (ou guardaria cópias órfãs)."""
    from cartridges.utils import copias_animadas  # noqa: PLC0415

    zerado = jogo(store, 30, removed=True, status="beaten", steam_appid="99")
    vivo = jogo(store, 31, steam_appid="99")
    _animada(shared.covers_dir / f"{vivo.game_id}.gif", "red")
    copias = _copias_de(vivo.game_id)
    if capa_do_zerado == "animada":
        _animada(shared.covers_dir / f"{zerado.game_id}.gif", "lime")
    else:
        write_asset("covers", f"{zerado.game_id}.tiff", b"capa-do-zerado")
    # Uma geração da capa anterior ainda na fila, pedida antes da ligação.
    recebidos = []
    capa_velha = shared.covers_dir / f"{vivo.game_id}.gif"
    copias[0].unlink()
    copias_animadas.pedir(capa_velha, copias[0], copias_animadas.tamanhos()[0], recebidos.append)

    assert ligar(vivo) is True
    girar()  # a troca das cópias vai pela fila da thread principal (`_refazer_copias`)
    assert [c for c in copias if c.exists()] == []

    # O pedido da capa velha, invalidado, não entrega nada. (As cópias da capa
    # nova, que a troca pede de novo com o mesmo nome, podem ser geradas.)
    while fila_das_copias.fila:
        fila_das_copias.fila.pop(0)()
    girar()
    assert recebidos == []


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
    `test_ligacao_so_roda_depois_do_pipeline_inteiro` abaixo.
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


def test_ligacao_so_roda_depois_do_pipeline_inteiro(store):
    """A ligação espera o pipeline do jogo terminar por inteiro.

    Um manager parecido com o SteamAPIManager marca `ligar_zerado` e termina
    na hora; um segundo, parecido com o SGDB (`run_after` do primeiro), só
    termina quando o teste manda. Enquanto ele não termina, a fusão não pode
    ter acontecido. Usa o `Store.add_game` e o `Pipeline` de verdade.
    """
    from cartridges.jogo import Jogo  # noqa: PLC0415
    from cartridges.store.managers.manager import Manager  # noqa: PLC0415

    class _FingeSteam(Manager):
        """No lugar do SteamAPIManager: marca a ligação e termina na hora."""

        def main(self, game, additional_data: dict) -> None:
            additional_data["ligar_zerado"] = True

    class _FingeSgdb(Manager):
        """No lugar do SGDB: só termina quando o teste chamar `pronto()`."""

        run_after = (_FingeSteam,)
        blocking = False

        def __init__(self) -> None:
            super().__init__()
            self.pronto = None

        def main(self, game, additional_data: dict) -> None:  # pragma: no cover
            raise AssertionError("main não deveria rodar: process_game é sobrescrito")

        def process_game(self, game, additional_data, callback) -> None:
            self.pronto = lambda: callback(self)

    sgdb_falso = _FingeSgdb()
    store.pipeline_managers = {_FingeSteam(), sgdb_falso}

    zerado = jogo(store, 21, removed=True, status="beaten", steam_appid="800", playtime=10)
    vivo = Jogo(
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
    girar()
    assert store.get(zerado.game_id) is not None

    sgdb_falso.pronto()  # agora o pipeline termina de verdade
    girar()

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


def test_edicao_troca_appid_e_liga(store, avisos):
    """O segundo gatilho: aplicar a edição liga quando o appID buscado difere
    do que o jogo já tinha."""
    from cartridges import edicao  # noqa: PLC0415

    stub_sgdb(store)
    zerado = jogo(store, 14, removed=True, status="beaten", steam_appid="640", playtime=120)
    vivo = jogo(store, 15, executable="x.exe")

    form = edicao.Formulario.do_jogo(vivo)
    form.appid = "640"
    form.buscado = {"steam_appid": "640"}
    edicao.aplicar(form, vivo, "")

    assert vivo.steam_appid == "640"
    assert store.get(zerado.game_id) is None
    assert vivo.playtime == 120
    assert "Os dados de Jogo 15 em Jogos Zerados foram transferidos para a biblioteca" in avisos


def _detalhes_de(store, jogo_mostrado):
    from cartridges.modelos.detalhes import DetalhesDoJogo  # noqa: PLC0415

    modelo = DetalhesDoJogo(store)
    assert modelo.mostrar(jogo_mostrado.game_id)
    modelo.sairam = []
    modelo.sair.connect(lambda: modelo.sairam.append(1))
    return modelo


def test_fecha_a_tela_de_detalhes_do_zerado_fundido(store, ligar):
    """Se a página de detalhes do zerado fundido estiver aberta, ela sai.

    Sem isso, ela seguiria um jogo que não existe mais na store, e qualquer
    ação nela (mudar status, editar) reviveria o arquivo apagado, contando o
    tempo em dobro numa próxima ligação."""
    zerado = jogo(store, 27, removed=True, status="beaten", steam_appid="960")
    vivo = jogo(store, 28, steam_appid="960")
    detalhes = _detalhes_de(store, zerado)

    assert ligar(vivo) is True
    girar()
    assert detalhes.sairam == [1]


def test_nao_fecha_a_tela_de_detalhes_de_outro_jogo(store, ligar):
    """Só sai se for a do próprio zerado fundido."""
    jogo(store, 29, removed=True, status="beaten", steam_appid="970")
    vivo = jogo(store, 30, steam_appid="970")
    outro = jogo(store, 31)
    detalhes = _detalhes_de(store, outro)

    assert ligar(vivo) is True
    girar()
    assert detalhes.sairam == []


def test_brilho_proprio_do_zerado_vai_para_o_jogo(store, ligar):
    from cartridges.utils import session_fita  # noqa: PLC0415

    zerado = jogo(store, 1, removed=True, status="beaten", steam_appid="570")
    vivo = jogo(store, 2, steam_appid="570")
    session_fita.salvar_brilho(zerado.game_id, zerado.name, 300)

    assert ligar(vivo) is True
    assert session_fita.brilho_escolhido(vivo.game_id) == 300
    assert not session_fita.escolhida(vivo.game_id)
