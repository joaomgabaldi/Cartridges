"""Filho do passeio: o Cartridges real, isolado, dirigido por um roteiro.

Uso (normalmente chamado por ``tools/passeio.py``)::

    python tools/passeio_app.py <saida>

``<saida>/biblioteca`` é a cópia da biblioteca: todas as pastas do app apontam
para ela, as preferências ficam só em memória e luzes, papel de parede e
iniciar jogo são neutralizados. Cada passo concluído vira uma linha de
``<saida>/passos.jsonl``.
"""

import builtins
import faulthandler
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Iterator, NamedTuple, Optional

RAIZ = Path(__file__).resolve().parent.parent
BUILD = RAIZ / "_build"
# Laço principal parado por mais que isto é travamento: o faulthandler grava a
# pilha e encerra o filho (o pai relata).
LIMITE_TRAVA = 60
REDE = 120  # espera máxima de um passo online
LOCAL = 15  # espera máxima de um passo local


class Esperar(NamedTuple):
    condicao: Callable[[], bool]
    segundos: float
    descricao: str


class Pulado(Exception):
    """O passo não se aplica (sem chave, sem sessões, botão ausente)."""


def preparar(saida: Path) -> dict[str, list]:
    """Isola o app. Devolve o registro das chamadas neutralizadas."""
    biblioteca = saida / "biblioteca"
    os.environ.setdefault("GDK_WIN32_FORCE_DCOMP", "1")
    os.environ.setdefault("GSK_RENDERER", "vulkan")
    sys.path.insert(0, str(RAIZ))
    builtins._ = lambda mensagem: mensagem  # type: ignore[attr-defined]
    builtins.ngettext = lambda s, p, n: s if n == 1 else p  # type: ignore[attr-defined]

    # O schema do _build, compilado numa pasta da saída: o `shared` real chama
    # Gio.Settings.new e abortaria sem um schema instalado.
    schemas = saida / "_schemas"
    schemas.mkdir(exist_ok=True)
    shutil.copy(BUILD / "data" / "io.github.joaomgabaldi.Cartridges.gschema.xml", schemas)
    compilador = shutil.which("glib-compile-schemas") or (
        "C:/msys64/ucrt64/bin/glib-compile-schemas.exe"
    )
    subprocess.run([compilador, str(schemas)], check=True)
    os.environ["GSETTINGS_SCHEMA_DIR"] = str(schemas)

    import gi  # pylint: disable=import-outside-toplevel

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gio  # pylint: disable=import-outside-toplevel

    Gio.Resource.load(str(BUILD / "data" / "cartridges.gresource"))._register()

    import cartridges  # pylint: disable=import-outside-toplevel

    spec = importlib.util.spec_from_file_location(
        "cartridges.shared", BUILD / "cartridges" / "shared.py"
    )
    shared = importlib.util.module_from_spec(spec)
    sys.modules["cartridges.shared"] = shared
    spec.loader.exec_module(shared)  # type: ignore[union-attr]
    cartridges.shared = shared  # type: ignore[attr-defined]

    # As chaves vêm das preferências reais, só lidas. Todo o resto das
    # preferências fica no padrão, em memória: o registro nunca é gravado.
    chaves = {k: shared.schema.get_string(k) for k in ("sgdb-key", "wallhaven-key")}
    fonte = Gio.SettingsSchemaSource.get_default()
    memoria = Gio.memory_settings_backend_new()
    shared.schema = Gio.Settings.new_full(fonte.lookup(shared.APP_ID, True), memoria, None)
    shared.state_schema = Gio.Settings.new_full(
        fonte.lookup(shared.APP_ID + ".State", True), memoria, None
    )
    for chave, valor in chaves.items():
        shared.schema.set_string(chave, valor)

    shared.data_dir = biblioteca.parent
    shared.app_dir = biblioteca
    shared.games_dir = biblioteca / "games"
    shared.covers_dir = biblioteca / "covers"
    shared.logos_dir = biblioteca / "logos"
    shared.wallpapers_dir = biblioteca / "wallpapers"
    shared.fitas_dir = biblioteca / "fitas"
    shared.fitas_arquivo = biblioteca / "fitas.json"
    shared.tuya_conta_arquivo = biblioteca / "tuya_conta.json"
    shared.log_dir = biblioteca / "logs"

    chamadas: dict[str, list] = {"iniciar": [], "luzes": [], "papel": []}
    import cartridges.game as modulo_game  # pylint: disable=import-outside-toplevel
    from cartridges.utils import (  # pylint: disable=import-outside-toplevel
        session_fita,
        session_wallpaper,
    )

    modulo_game.run_executable = lambda *a, **k: chamadas["iniciar"].append(a)

    def sem_luzes(fita: Any, _acao: Any) -> None:
        chamadas["luzes"].append(getattr(fita, "id", None))

    session_fita._conversar = sem_luzes  # pylint: disable=protected-access

    class SemAreaDeTrabalho:
        def __enter__(self) -> None:
            chamadas["papel"].append(True)
            raise OSError("passeio: papel de parede desligado")

        def __exit__(self, *_a: Any) -> bool:
            return False

    session_wallpaper._AreaDeTrabalho = SemAreaDeTrabalho  # pylint: disable=protected-access
    return chamadas


class Coletor(logging.Handler):
    """Guarda os registros de WARNING para cima do passo em andamento."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.registros: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        rastro = (
            "".join(traceback.format_exception(*record.exc_info))
            if record.exc_info and record.exc_info[0]
            else None
        )
        self.registros.append(
            {
                "nivel": record.levelno,
                "logger": record.name,
                "mensagem": record.getMessage(),
                "rastro": rastro,
            }
        )


Passo = tuple[str, Any, Callable[[], Iterator[Esperar]]]


class Motor:
    """Executa os passos, um por vez, a partir de um timer do GLib.

    Cada passo é um gerador que devolve ``Esperar``: o motor volta ao laço
    principal e só retoma o gerador quando a condição vale (ou lança
    ``TimeoutError`` nele quando o prazo acaba). Nada de laço aninhado.
    """

    def __init__(self, app: Any, saida: Path) -> None:
        self.app = app
        self.saida = saida
        self.fila: list[Passo] = []
        self.coletor = Coletor()
        self.gerador: Optional[Iterator[Esperar]] = None
        self.espera: Optional[Esperar] = None
        self.atual: Optional[Passo] = None
        self.inicio = self.inicio_espera = 0.0
        self.despejo = open(saida / "despejo.txt", "w", encoding="utf-8")  # pylint: disable=consider-using-with
        self.jsonl = open(saida / "passos.jsonl", "a", encoding="utf-8")  # pylint: disable=consider-using-with

    def iniciar(self) -> None:
        from gi.repository import GLib  # pylint: disable=import-outside-toplevel

        logging.getLogger().addHandler(self.coletor)
        GLib.timeout_add(50, self._tick)

    def _tick(self) -> bool:
        # Um erro aqui removeria o timer (o PyGObject derruba a fonte) e o
        # passeio ficaria parado com a janela aberta: encerra em vez disso.
        try:
            return self._tick_seguro()
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("passeio: erro no motor")
            self._fim()
            return False

    def _tick_seguro(self) -> bool:
        faulthandler.dump_traceback_later(LIMITE_TRAVA, exit=True, file=self.despejo)
        if self.atual is None:
            if not self.fila:
                self._fim()
                return False
            self._comecar(self.fila.pop(0))
            return True
        espera = self.espera
        assert espera is not None
        try:
            pronto = espera.condicao()
        except Exception as erro:  # pylint: disable=broad-exception-caught
            self._avancar(erro)
            return True
        if pronto:
            self._avancar(None)
        elif time.monotonic() - self.inicio_espera > espera.segundos:
            self._avancar(TimeoutError(f"Tempo esgotado: {espera.descricao}"))
        return True

    def _comecar(self, passo: Passo) -> None:
        nome, jogo, fabrica = passo
        self.atual = passo
        self.coletor.registros = []
        self.inicio = time.monotonic()
        (self.saida / "atual.txt").write_text(
            f"{nome}\t{getattr(jogo, 'game_id', '')}\t{getattr(jogo, 'name', '')}",
            encoding="utf-8",
        )
        try:
            self.gerador = fabrica()
        except Exception as erro:  # pylint: disable=broad-exception-caught
            self._concluir("falha", str(erro), traceback.format_exc())
            return
        self._avancar(None)

    def _avancar(self, erro: Optional[BaseException]) -> None:
        assert self.gerador is not None
        try:
            if erro is None:
                self.espera = next(self.gerador)
            else:
                self.espera = self.gerador.throw(erro)
            self.inicio_espera = time.monotonic()
        except StopIteration:
            self._concluir("ok")
        except Pulado as pulo:
            self._concluir("pulado", str(pulo))
        except Exception as falha:  # pylint: disable=broad-exception-caught
            self._concluir("falha", str(falha) or type(falha).__name__, traceback.format_exc())

    def _concluir(self, estado: str, motivo: Optional[str] = None, rastro: Optional[str] = None) -> None:
        nome, jogo, _ = self.atual  # type: ignore[misc]
        linha = {
            "passo": nome,
            "jogo_id": getattr(jogo, "game_id", None),
            "jogo_nome": getattr(jogo, "name", None),
            "estado": estado,
            "motivo": motivo,
            "rastro": rastro,
            "duracao": round(time.monotonic() - self.inicio, 2),
            "registros": list(self.coletor.registros),
        }
        self.jsonl.write(json.dumps(linha, ensure_ascii=False) + "\n")
        self.jsonl.flush()
        print(f"[{estado}] {nome}" + (f" · {linha['jogo_nome']}" if jogo else ""), flush=True)
        self.atual = self.gerador = self.espera = None
        if estado == "falha":
            try:
                arrumar()
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("passeio: não foi possível voltar à biblioteca")

    def _fim(self) -> None:
        faulthandler.cancel_dump_traceback_later()
        (self.saida / "atual.txt").unlink(missing_ok=True)
        self.jsonl.close()
        self.app.quit()


MOTOR: Optional[Motor] = None


# ----------------------------------------------------------------------------
# Ajudantes do roteiro
# ----------------------------------------------------------------------------


def shared() -> Any:
    from cartridges import shared as modulo  # pylint: disable=import-outside-toplevel

    return modulo


def dialogo() -> Any:
    return shared().win.get_visible_dialog()


def pagina() -> Any:
    return shared().win.navigation_view.get_visible_page()


def sem_dialogo() -> bool:
    return dialogo() is None


def ocioso() -> Esperar:
    """Deixa o laço assentar: sem eventos pendentes, ou no máximo 2 s.

    Com a janela desenhando (animação, relógio de quadros), sempre pode haver
    algo pendente; o teto evita que isso vire uma falha falsa.
    """
    from gi.repository import GLib  # pylint: disable=import-outside-toplevel

    teto = time.monotonic() + 2
    return Esperar(
        lambda: not GLib.MainContext.default().pending() or time.monotonic() > teto,
        LOCAL,
        "laço ocioso",
    )


def arrumar() -> None:
    """Depois de uma falha: fecha os diálogos e volta à biblioteca."""
    win = shared().win
    for _ in range(10):
        if (aberto := win.get_visible_dialog()) is None:
            break
        aberto.force_close()
    win.navigation_view.pop_to_page(win.library_page)
    win.search_bar.set_search_mode(False)


def fechar_dialogo(descricao: str) -> Iterator[Esperar]:
    aberto = dialogo()
    if aberto is not None:
        aberto.close()
    yield Esperar(sem_dialogo, LOCAL, f"fechar {descricao}")


def ir_aos_detalhes(jogo: Any) -> Iterator[Esperar]:
    win = shared().win
    win.show_details_page(jogo)
    yield Esperar(
        lambda: pagina() == win.details_page and win.active_game is jogo,
        LOCAL,
        "abrir os detalhes",
    )


def abrir_edicao(jogo: Any) -> Iterator[Esperar]:
    from cartridges.details_dialog import DetailsDialog  # pylint: disable=import-outside-toplevel

    yield from ir_aos_detalhes(jogo)
    shared().win.get_application().activate_action("edit_game", None)
    yield Esperar(lambda: isinstance(dialogo(), DetailsDialog), LOCAL, "abrir a edição")


def salvar_edicao() -> Iterator[Esperar]:
    edicao = dialogo()
    yield Esperar(edicao.apply_button.get_sensitive, REDE, "fim do carregamento da edição")
    edicao.apply_button.emit("clicked")
    yield Esperar(
        sem_dialogo, LOCAL, "fechar a edição ao salvar (outra janela apareceu?)"
    )


# ----------------------------------------------------------------------------
# Roteiro
# ----------------------------------------------------------------------------


def carregar_biblioteca() -> Iterator[Esperar]:
    esperado = len(list(shared().games_dir.glob("*.json")))
    try:
        yield Esperar(
            lambda: shared().store is not None and len(list(shared().store)) >= esperado,
            60,
            f"carregar os {esperado} jogos da pasta",
        )
        yield ocioso()
    finally:
        # Mesmo se nem todos carregarem (um arquivo inválido é um achado), o
        # passeio segue com os que carregaram.
        assert MOTOR is not None
        MOTOR.fila.extend(montar_roteiro(list(shared().store or [])))


def ordenar() -> Iterator[Esperar]:
    chave = shared().state_schema.props.settings_schema.get_key("sort-mode")
    _tipo, modos = chave.get_range().unpack()
    from gi.repository import GLib  # pylint: disable=import-outside-toplevel

    for modo in modos:
        shared().win.activate_action("win.sort_by", GLib.Variant("s", modo))
        yield ocioso()


def buscar() -> Iterator[Esperar]:
    win = shared().win
    win.navigation_view.pop_to_page(win.library_page)
    win.activate_action("win.toggle_search", None)
    yield Esperar(win.search_bar.get_search_mode, LOCAL, "abrir a busca")
    for termo in ("a", "", "zzzqqq-sem-resultado", "ção & ü 100% [x]"):
        win.search_entry.set_text(termo)
        yield ocioso()
    win.activate_action("win.toggle_search", None)
    yield Esperar(lambda: not win.search_bar.get_search_mode(), LOCAL, "fechar a busca")


def jogos_zerados() -> Iterator[Esperar]:
    win = shared().win
    win.navigation_view.pop_to_page(win.library_page)
    win.activate_action("win.show_zerados", None)
    yield Esperar(lambda: pagina() == win.zerados_library_page, LOCAL, "abrir Jogos Zerados")
    yield ocioso()
    win.navigation_view.pop()
    yield Esperar(lambda: pagina() == win.library_page, LOCAL, "voltar à biblioteca")


def preferencias() -> Iterator[Esperar]:
    from cartridges.preferences import CartridgesPreferences  # pylint: disable=import-outside-toplevel

    app = shared().win.get_application()
    for vez in ("abrir", "reabrir"):
        app.activate_action("preferences", None)
        yield Esperar(
            lambda: isinstance(dialogo(), CartridgesPreferences), LOCAL, f"{vez} as Preferências"
        )
        for nome in ("general", "session", "import", "sgdb"):
            dialogo().set_visible_page_name(nome)
            yield ocioso()
        yield from fechar_dialogo("as Preferências")


def sobre() -> Iterator[Esperar]:
    from gi.repository import Adw  # pylint: disable=import-outside-toplevel

    shared().win.get_application().activate_action("about", None)
    yield Esperar(lambda: isinstance(dialogo(), Adw.AboutDialog), LOCAL, "abrir o Sobre")
    yield ocioso()
    yield from fechar_dialogo("o Sobre")


def novidades() -> Iterator[Esperar]:
    win = shared().win
    win.navigation_view.pop_to_page(win.library_page)
    win.activate_action("win.show_news", None)
    yield Esperar(lambda: pagina() == win.news_page, LOCAL, "abrir Novidades")
    yield ocioso()
    win.navigation_view.pop()
    yield Esperar(lambda: pagina() == win.library_page, LOCAL, "voltar à biblioteca")


def detalhes(jogo: Any) -> Iterator[Esperar]:
    yield from ir_aos_detalhes(jogo)
    yield ocioso()


def edicao_cancelar(jogo: Any) -> Iterator[Esperar]:
    yield from abrir_edicao(jogo)
    yield from fechar_dialogo("a edição")


def edicao_salvar(jogo: Any) -> Iterator[Esperar]:
    yield from abrir_edicao(jogo)
    yield from salvar_edicao()


def historico(jogo: Any) -> Iterator[Esperar]:
    from cartridges.session_history import SessionHistoryDialog  # pylint: disable=import-outside-toplevel

    yield from ir_aos_detalhes(jogo)
    win = shared().win
    if not win._playtime_clickable:  # pylint: disable=protected-access
        raise Pulado("jogo sem sessões")
    win.on_playtime_activated()
    yield Esperar(
        lambda: isinstance(dialogo(), SessionHistoryDialog), LOCAL, "abrir o histórico"
    )
    yield ocioso()
    yield from fechar_dialogo("o histórico")


def trocar_status(jogo: Any) -> Iterator[Esperar]:
    from gi.repository import GLib  # pylint: disable=import-outside-toplevel

    from cartridges.game import STATUS_LABELS  # pylint: disable=import-outside-toplevel

    original = jogo.status or ""
    for valor in [*STATUS_LABELS, "", original]:
        yield from ir_aos_detalhes(jogo)
        shared().win.activate_action("win.set_status", GLib.Variant("s", valor))
        yield Esperar(
            lambda v=valor: (jogo.status or "") == v, LOCAL, f"status {valor or 'vazio'}"
        )


def seletor_de_grade(jogo: Any, botao: str, tipo_nome: str, rotulo: str, escolher: bool) -> Iterator[Esperar]:
    """Capa, logo (escolhe o primeiro) ou papel de parede (só abre)."""
    modulo, classe = tipo_nome.rsplit(".", 1)
    tipo = getattr(importlib.import_module(modulo), classe)
    if escolher and not shared().schema.get_string("sgdb-key"):
        raise Pulado("sem chave do SteamGridDB nas preferências")
    yield from abrir_edicao(jogo)
    edicao = dialogo()
    if not getattr(edicao, botao).is_visible():
        edicao.close()
        raise Pulado(f"{rotulo} não aparece na edição deste jogo")
    getattr(edicao, botao).emit("clicked")
    yield Esperar(lambda: isinstance(dialogo(), tipo), LOCAL, f"abrir {rotulo}")
    seletor = dialogo()
    yield Esperar(
        lambda: seletor.stack.get_visible_child_name() in ("results", "empty"),
        REDE,
        f"resultados de {rotulo}",
    )
    if escolher and seletor.stack.get_visible_child_name() == "results":
        seletor.flowbox.emit("child-activated", seletor.flowbox.get_child_at_index(0))
    else:
        seletor.close()
    yield Esperar(lambda: dialogo() is edicao, REDE, f"voltar de {rotulo} à edição")
    yield from salvar_edicao()


def busca_steam(jogo: Any) -> Iterator[Esperar]:
    from cartridges.steam_picker import SteamPicker  # pylint: disable=import-outside-toplevel

    yield from abrir_edicao(jogo)
    edicao = dialogo()
    if not edicao.steam_fetch_button.is_visible():
        edicao.close()
        raise Pulado("busca da Steam não aparece na edição deste jogo")
    edicao.steam_fetch_button.emit("clicked")
    yield Esperar(
        lambda: isinstance(dialogo(), SteamPicker)
        or (dialogo() is edicao and edicao.apply_button.get_sensitive()),
        REDE,
        "resposta da Steam",
    )
    if isinstance(seletor := dialogo(), SteamPicker):
        yield Esperar(
            lambda: seletor.stack.get_visible_child_name() in ("results", "empty"),
            REDE,
            "resultados da Steam",
        )
        if seletor.stack.get_visible_child_name() == "results":
            seletor.listbox.emit("row-activated", seletor.listbox.get_row_at_index(0))
        else:
            seletor.close()
        yield Esperar(lambda: dialogo() is edicao, REDE, "voltar da Steam à edição")
    yield from salvar_edicao()


def atualizar_metadados() -> Iterator[Esperar]:
    from cartridges.metadata_refresh import get_metadata_refresh  # pylint: disable=import-outside-toplevel

    vivos = [g for g in shared().store if not g.removed]
    execucao = get_metadata_refresh()
    if not execucao.start(vivos):
        raise Pulado("atualização de metadados não iniciou (já em andamento?)")
    yield Esperar(lambda: not execucao.running, 30 * len(vivos) + REDE, "atualizar metadados")


def remover(jogo: Any) -> Iterator[Esperar]:
    yield from ir_aos_detalhes(jogo)
    shared().win.get_application().activate_action("remove_game", None)
    yield Esperar(lambda: jogo.removed, LOCAL, "remover o jogo")


def mover_para_zerados(jogo: Any) -> Iterator[Esperar]:
    from gi.repository import GLib  # pylint: disable=import-outside-toplevel

    yield from ir_aos_detalhes(jogo)
    shared().win.activate_action("win.set_status", GLib.Variant("s", "beaten"))
    yield Esperar(lambda: jogo.status == "beaten", LOCAL, "marcar como Zerado")
    yield from ir_aos_detalhes(jogo)
    shared().win.get_application().activate_action("remove_game", None)
    yield Esperar(lambda: jogo.zerado, LOCAL, "ir para Jogos Zerados")


def excluir_zerado(jogo: Any) -> Iterator[Esperar]:
    from gi.repository import Adw  # pylint: disable=import-outside-toplevel

    yield from ir_aos_detalhes(jogo)
    shared().win.activate_action("win.delete_game", None)
    yield Esperar(lambda: isinstance(dialogo(), Adw.AlertDialog), LOCAL, "abrir a confirmação")
    confirmacao = dialogo()
    confirmacao.emit("response", "delete")
    if dialogo() is confirmacao:
        confirmacao.force_close()
    yield Esperar(
        lambda: shared().store.get(jogo.game_id) is None, LOCAL, "excluir o jogo"
    )


def amostra(jogos: list[Any]) -> list[Any]:
    """Até 3 jogos variados: com ID da Steam, sem ID, de Jogos Zerados."""
    escolhidos: list[Any] = []
    filtros = (
        lambda g: bool(g.steam_appid) and not g.removed,
        lambda g: not g.steam_appid and not g.removed,
        lambda g: g.zerado,
    )
    for filtro in filtros:
        achado = next((g for g in jogos if filtro(g) and g not in escolhidos), None)
        if achado is not None:
            escolhidos.append(achado)
    return escolhidos


def montar_roteiro(jogos: list[Any]) -> list[Passo]:
    visiveis = [g for g in jogos if not g.removed or g.zerado]
    vivos = [g for g in visiveis if not g.removed]
    roteiro: list[Passo] = [
        ("Cada ordenação", None, ordenar),
        ("Busca", None, buscar),
        ("Jogos Zerados", None, jogos_zerados),
        ("Preferências", None, preferencias),
        ("Sobre", None, sobre),
        ("Novidades", None, novidades),
    ]
    for g in visiveis:
        roteiro += [
            ("Abrir os detalhes", g, lambda g=g: detalhes(g)),
            ("Abrir a edição e cancelar", g, lambda g=g: edicao_cancelar(g)),
            ("Abrir a edição e salvar", g, lambda g=g: edicao_salvar(g)),
            ("Histórico de sessões", g, lambda g=g: historico(g)),
        ]
        if not g.removed:
            roteiro.append(("Trocar o status", g, lambda g=g: trocar_status(g)))
    for g in amostra(visiveis):
        roteiro += [
            ("Capa do SteamGridDB", g, lambda g=g: seletor_de_grade(
                g, "cover_button_browse", "cartridges.sgdb_picker.SgdbPicker", "o seletor de capa", True)),
            ("Logo do SteamGridDB", g, lambda g=g: seletor_de_grade(
                g, "logo_button_browse", "cartridges.logo_picker.LogoPicker", "o seletor de logo", True)),
            ("Seletor de papel de parede", g, lambda g=g: seletor_de_grade(
                g, "wallpaper_button_browse", "cartridges.wallpaper_picker.WallpaperPicker",
                "o seletor de papel de parede", False)),
            ("Busca da Steam", g, lambda g=g: busca_steam(g)),
        ]
    roteiro.append(("Atualizar metadados", None, atualizar_metadados))
    # Os destrutivos, no fim e em jogos distintos: o último vivo é removido, o
    # penúltimo vai para Jogos Zerados, e o primeiro zerado é excluído.
    if vivos:
        roteiro.append(("Remover um jogo", vivos[-1], lambda g=vivos[-1]: remover(g)))
    if len(vivos) > 1:
        roteiro.append(("Mover para Jogos Zerados", vivos[-2], lambda g=vivos[-2]: mover_para_zerados(g)))
    alvo = next((g for g in visiveis if g.zerado), vivos[-2] if len(vivos) > 1 else None)
    if alvo is not None:
        roteiro.append(("Excluir de Jogos Zerados", alvo, lambda g=alvo: excluir_zerado(g)))
    return roteiro


def main() -> int:
    global MOTOR  # pylint: disable=global-statement
    saida = Path(sys.argv[1]).resolve()
    chamadas = preparar(saida)

    from cartridges.main import CartridgesApplication  # pylint: disable=import-outside-toplevel

    app = CartridgesApplication()
    MOTOR = Motor(app, saida)
    MOTOR.fila.append(("Carregar a biblioteca", None, carregar_biblioteca))

    app.connect_after("activate", lambda *_: MOTOR.iniciar())
    codigo = app.run([sys.argv[0]])
    print(
        f"Chamadas neutralizadas: iniciar jogo {len(chamadas['iniciar'])}, "
        f"luzes {len(chamadas['luzes'])}, papel de parede {len(chamadas['papel'])}",
        flush=True,
    )
    return codigo


if __name__ == "__main__":
    sys.exit(main())
