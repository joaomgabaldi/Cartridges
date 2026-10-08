# passeio_app.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

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
import tempfile
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
    os.environ.setdefault("GDK_DEBUG", "dcomp")
    os.environ.setdefault("GSK_RENDERER", "vulkan")
    sys.path.insert(0, str(RAIZ))
    builtins._ = lambda mensagem: mensagem  # type: ignore[attr-defined]
    builtins.ngettext = lambda s, p, n: s if n == 1 else p  # type: ignore[attr-defined]

    # O schema do _build, compilado numa pasta da saída: o `shared` real chama
    # Gio.Settings.new e abortaria sem um schema instalado.
    schemas = saida / "_schemas"
    schemas.mkdir(exist_ok=True)
    shutil.copy(BUILD / "data" / "io.github.joaomgabaldi.Cartridges.gschema.xml", schemas)
    # Fora do PATH, o do mesmo ucrt64/bin do Python que roda o passeio.
    compilador = shutil.which("glib-compile-schemas") or str(
        Path(sys.executable).with_name("glib-compile-schemas.exe")
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

    # O evento nomeado com que uma segunda cópia acorda a primeira é do
    # sistema inteiro: com o app instalado aberto ao mesmo tempo, uma segunda
    # abertura dele acordaria o passeio. Nome próprio.
    from cartridges.utils import single_instance  # pylint: disable=import-outside-toplevel

    single_instance._EVENT_NAME = "Local\\Cartridges.Passeio.Present"  # pylint: disable=protected-access

    # As chaves vêm das preferências reais, só lidas. Todo o resto das
    # preferências fica no padrão, em memória: o registro nunca é gravado.
    chaves = {k: shared.schema.get_string(k) for k in ("sgdb-key", "wallhaven-key")}
    # Geometria real da janela, só lida: sem isto o schema em memória começa
    # no padrão pequeno e os diálogos do libadwaita rodam em modo "bottom
    # sheet" (a janela do passeio saía com ~104 px de altura). x/y não: a
    # janela pode abrir numa posição inválida se o monitor mudou.
    geometria = {
        "width": shared.state_schema.get_int("width"),
        "height": shared.state_schema.get_int("height"),
        "is-maximized": shared.state_schema.get_boolean("is-maximized"),
    }
    tokens_steam = shared.state_schema.get_string("steam-limiter-tokens-history")
    fonte = Gio.SettingsSchemaSource.get_default()
    memoria = Gio.memory_settings_backend_new()
    shared.schema = Gio.Settings.new_full(fonte.lookup(shared.APP_ID, True), memoria, None)
    shared.state_schema = Gio.Settings.new_full(
        fonte.lookup(shared.APP_ID + ".State", True), memoria, None
    )
    for chave, valor in chaves.items():
        shared.schema.set_string(chave, valor)
    shared.state_schema.set_int("width", geometria["width"])
    shared.state_schema.set_int("height", geometria["height"])
    shared.state_schema.set_boolean("is-maximized", geometria["is-maximized"])
    shared.state_schema.set_string("steam-limiter-tokens-history", tokens_steam)

    shared.data_dir = biblioteca.parent
    shared.app_dir = biblioteca
    shared.games_dir = biblioteca / "games"
    shared.covers_dir = biblioteca / "covers"
    shared.logos_dir = biblioteca / "logos"
    shared.wallpapers_dir = biblioteca / "wallpapers"
    shared.fitas_dir = biblioteca / "fitas"
    shared.fitas_arquivo = biblioteca / "fitas.json"
    shared.tuya_conta_arquivo = biblioteca / "tuya_conta.json"
    shared.conquistas_dir = biblioteca / "conquistas"
    shared.conquistas_cache_dir = biblioteca / "cache" / "conquistas"
    # O `limpar` da inicialização apaga cópias órfãs daqui: sem apontar para a
    # cópia da biblioteca, ele mexeria no cache real.
    shared.capas_animadas_dir = biblioteca / "cache" / "capas_animadas"
    shared.contas_dir = biblioteca / "contas"
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
        # `record.getMessage()` pode lançar (ex.: `%s` sem argumento, num log
        # malformado do próprio app) — e essa exceção cairia dentro do código
        # do app, não do passeio. Um substituto vale mais que travar o app.
        try:
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
        except Exception:  # pylint: disable=broad-exception-caught
            self.registros.append(
                {
                    "nivel": 40,
                    "logger": getattr(record, "name", ""),
                    "mensagem": f"registro ilegível: {record.msg!r}",
                    "rastro": None,
                }
            )


def _pilhas_das_threads() -> str:
    """As pilhas de todas as threads, agora. `faulthandler` exige um arquivo
    com descritor real; um arquivo à parte, fechado antes da leitura, evita
    qualquer questão de buffer."""
    with tempfile.TemporaryDirectory() as pasta:
        caminho = Path(pasta) / "pilhas.txt"
        with open(caminho, "w", encoding="utf-8") as arquivo:
            faulthandler.dump_traceback(file=arquivo, all_threads=True)
        return caminho.read_text(encoding="utf-8")


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
        self.erro = False
        self.despejo = open(saida / "despejo.txt", "w", encoding="utf-8")  # pylint: disable=consider-using-with
        self.jsonl = open(saida / "passos.jsonl", "a", encoding="utf-8")  # pylint: disable=consider-using-with

    def iniciar(self) -> None:
        # O coletor já está pendurado no logger raiz desde `setup_logging`
        # (ver `main`): pendurar de novo aqui duplicaria cada registro.
        from gi.repository import GLib  # pylint: disable=import-outside-toplevel

        GLib.timeout_add(50, self._tick)

    def _tick(self) -> bool:
        # Um erro aqui removeria o timer (o PyGObject derruba a fonte) e o
        # passeio ficaria parado com a janela aberta: encerra em vez disso.
        try:
            return self._tick_seguro()
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("passeio: erro no motor")
            self.erro = True
            # Mantém atual.txt: sem isto o passo em andamento desaparecia do
            # relatório e o passeio saía com código 0, escondendo o erro.
            self._fim(manter_atual=True)
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
            rastro = traceback.format_exc()
            if isinstance(falha, TimeoutError):
                # "Tempo esgotado" sem pilha não diz onde o app travou: soma
                # as pilhas de todas as threads no momento do estouro.
                rastro = rastro.rstrip() + "\n\n--- pilhas de todas as threads ---\n" + _pilhas_das_threads()
            self._concluir("falha", str(falha) or type(falha).__name__, rastro)

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
        # json.dumps com ensure_ascii=False pode lançar num par substituto
        # (surrogate) isolado, que um nome de jogo malformado pode conter — o
        # ascii default escapa em vez de lançar.
        self.jsonl.write(json.dumps(linha) + "\n")
        self.jsonl.flush()
        # Só depois de a linha estar gravada: tudo que for logado antes do
        # primeiro passo (setup_logging, load_games_from_disk, managers) cai
        # aqui, em "Carregar a biblioteca", em vez de ser descartado.
        self.coletor.registros = []
        # Apagado assim que o passo conclui: se o app cair entre dois passos,
        # atual.txt não existir mais evita culpar o passo anterior.
        (self.saida / "atual.txt").unlink(missing_ok=True)
        print(f"[{estado}] {nome}" + (f" · {linha['jogo_nome']}" if jogo else ""), flush=True)
        self.atual = self.gerador = self.espera = None
        if estado == "falha":
            try:
                arrumar()
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("passeio: não foi possível voltar à biblioteca")

    def _fim(self, manter_atual: bool = False) -> None:
        # Rearma em vez de cancelar: o encerramento do GTK também pode travar,
        # e sem o watchdog o processo ficaria pendurado sem ninguém avisando.
        faulthandler.dump_traceback_later(LIMITE_TRAVA, exit=True, file=self.despejo)
        if not manter_atual:
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
    win = shared().win
    # A geometria em memória copia a real (ver `preparar`), mas a janela pode
    # ter sido minimizada da última vez: sem isto ela nunca aparece na tela.
    win.unminimize()
    win.present()
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
        (MOTOR.saida / "janela.txt").write_text(
            f"{win.get_width()}x{win.get_height()}", encoding="utf-8"
        )
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


# ----------------------------------------------------------------------------
# Tarefas em andamento: o botão do canto e a janela solta
# ----------------------------------------------------------------------------

# A tarefa de teste que os passos 2 a 4 dividem: a janela solta tem de seguir
# aberta de um passo para o outro, e a tarefa com ela.
TAREFA: Optional[Any] = None
NOME_TAREFA = "Tarefa do passeio"


def botao_tarefas() -> Any:
    return shared().win.botao_tarefas


def altura_canto() -> float:
    return shared().win.session_overlay.get_height()


def tarefas_paradas() -> bool:
    from cartridges.utils import tarefas  # pylint: disable=import-outside-toplevel

    return tarefas.lista.get_n_items() == 0


def escurecer_botao() -> None:
    """O botão escondido de imediato e o mouse fora do canto: o ponto de partida
    de cada conferência, sem esperar os 10 s da entrada nem a saída animada."""
    botao = botao_tarefas()
    botao._no_canto = False  # pylint: disable=protected-access
    botao._esconder(animado=False)  # pylint: disable=protected-access


def bloco_da_tarefa(janela: Any) -> Optional[Any]:
    """O bloco da tarefa de teste na janela solta: nome, contagem e barra."""
    filho = janela.caixa.get_first_child()
    while filho is not None:
        if filho.get_first_child().get_label() == NOME_TAREFA:
            return filho
        filho = filho.get_next_sibling()
    return None


def contagem_da_tarefa(janela: Any) -> str:
    if (bloco := bloco_da_tarefa(janela)) is None:
        return ""
    return bloco.get_first_child().get_next_sibling().get_label()


def bordas_visiveis(janela: Any) -> Optional[tuple[float, float, float]]:
    """(esquerda, base, escala) da parte visível da janela, em pixels do Windows,
    ou None sem HWND. O retângulo do Windows inclui a sombra que o GTK desenha."""
    import ctypes  # pylint: disable=import-outside-toplevel
    from ctypes import wintypes  # pylint: disable=import-outside-toplevel

    from cartridges.utils import window_geometry  # pylint: disable=import-outside-toplevel

    hwnd = window_geometry._hwnd(janela)  # pylint: disable=protected-access
    if hwnd is None:
        return None
    rect = wintypes.RECT()
    if not window_geometry._user32.GetWindowRect(hwnd, ctypes.byref(rect)):  # pylint: disable=protected-access
        return None
    surface = janela.get_surface()
    escala = surface.get_scale() if hasattr(surface, "get_scale") else 1
    sombra = janela.get_surface_transform()
    return (
        rect.left + sombra[0] * escala,
        rect.top + (sombra[1] + janela.get_height()) * escala,
        escala,
    )


def encerrar_tarefa_de_teste() -> None:
    """Limpeza dos passos das tarefas: principal de volta à tela, tarefa
    terminada, janela solta fechada e o botão em repouso. A principal primeiro:
    fechar a solta com a principal escondida encerraria o app."""
    global TAREFA  # pylint: disable=global-statement
    from cartridges.tarefas_janela import TarefasJanela  # pylint: disable=import-outside-toplevel

    shared().win.present()
    if TAREFA is not None:
        TAREFA.terminar()
        TAREFA = None
    if TarefasJanela.aberta is not None:
        TarefasJanela.aberta.close()
    escurecer_botao()


def tarefas_botao_entra_e_recua() -> Iterator[Esperar]:
    from cartridges.utils import tarefas  # pylint: disable=import-outside-toplevel

    botao = botao_tarefas()
    escurecer_botao()
    tarefa = tarefas.comecar(NOME_TAREFA, 3)
    try:
        yield Esperar(
            lambda: botao.revealer.get_reveal_child() and botao.revealer.get_child_revealed(),
            LOCAL,
            "o botão das tarefas entrar",
        )
        assert botao.get_can_target(), "o botão à vista não aceita clique"
        # 10 s à vista e o deslizar de volta.
        yield Esperar(
            lambda: not botao.revealer.get_reveal_child() and not botao.revealer.get_child_revealed(),
            15,
            "o botão das tarefas recuar sozinho",
        )
        assert not botao.get_can_target(), "o botão recuado ainda aceita clique"
    finally:
        tarefa.terminar()
        escurecer_botao()
    yield Esperar(tarefas_paradas, LOCAL, "o quadro de tarefas esvaziar")


def abrir_janela_das_tarefas() -> Iterator[Esperar]:
    """Do passo 2. Devolve True se a posição não pôde ser conferida (sem HWND)."""
    global TAREFA  # pylint: disable=global-statement
    from cartridges.tarefas_janela import TarefasJanela  # pylint: disable=import-outside-toplevel
    from cartridges.utils import tarefas, window_geometry  # pylint: disable=import-outside-toplevel

    win = shared().win
    botao = botao_tarefas()
    TAREFA = tarefa = tarefas.comecar(NOME_TAREFA, 3)
    yield Esperar(lambda: not tarefas_paradas(), LOCAL, "a tarefa entrar no quadro")
    escurecer_botao()
    assert not botao.revealer.get_reveal_child(), "o botão não escondeu"

    # Longe da borda: nada. Rente à borda, embaixo: o botão entra.
    botao._ao_mover(None, 30, altura_canto() - 10)  # pylint: disable=protected-access
    assert not botao.revealer.get_reveal_child(), "o botão apareceu fora da faixa da borda"
    botao._ao_mover(None, 8, altura_canto() - 10)  # pylint: disable=protected-access
    assert botao.revealer.get_reveal_child(), "a borda não trouxe o botão"

    botao.botao.emit("clicked")
    yield Esperar(
        lambda: TarefasJanela.aberta is not None and TarefasJanela.aberta.get_visible(),
        LOCAL,
        "a janela das tarefas abrir",
    )
    janela = TarefasJanela.aberta
    assert janela.get_transient_for() is None, "a janela das tarefas está presa à principal"
    assert not janela.get_modal(), "a janela das tarefas é modal"
    assert not janela.get_resizable(), "a janela das tarefas é redimensionável"
    assert win.get_visible_dialog() is None, "a janela das tarefas prendeu a biblioteca num diálogo"

    assert bloco_da_tarefa(janela) is not None, "o bloco da tarefa não apareceu na janela"
    assert contagem_da_tarefa(janela) == "0 de 3", f"contagem inicial: {contagem_da_tarefa(janela)!r}"
    tarefa.atualizar(2)
    yield Esperar(
        lambda: contagem_da_tarefa(janela) == "2 de 3", LOCAL, "a contagem virar 2 de 3"
    )

    # A posição só vale depois do "map" + 30 ms: a janela sai invisível e volta a
    # 1 de opacidade quando já está no lugar.
    yield Esperar(lambda: janela.get_opacity() == 1, LOCAL, "a janela das tarefas ir para o canto")
    yield ocioso()
    sem_posicao = False
    solta, principal = bordas_visiveis(janela), bordas_visiveis(win)
    if solta is None or principal is None:
        sem_posicao = True
    else:
        escala = solta[2]
        margem = window_geometry._MARGEM_BOTAO * escala  # pylint: disable=protected-access
        acima = (
            window_geometry._MARGEM_BOTAO  # pylint: disable=protected-access
            + window_geometry._ALTURA_BOTAO  # pylint: disable=protected-access
            + window_geometry._FOLGA_BOTAO  # pylint: disable=protected-access
        ) * escala
        assert solta[1] < principal[1], "a janela solta não ficou acima da base da principal"
        assert abs((solta[0] - principal[0]) - margem) <= 4, (
            f"esquerda da janela solta a {solta[0] - principal[0]:.0f} px da principal "
            f"(esperado {margem:.0f})"
        )
        assert abs((principal[1] - solta[1]) - acima) <= 4, (
            f"base da janela solta a {principal[1] - solta[1]:.0f} px acima da principal "
            f"(esperado {acima:.0f})"
        )

    # Um segundo clique traz a mesma janela, não abre outra.
    botao._ao_mover(None, 8, altura_canto() - 10)  # pylint: disable=protected-access
    assert botao.revealer.get_reveal_child(), "a borda não trouxe o botão de novo"
    botao.botao.emit("clicked")
    yield ocioso()
    assert TarefasJanela.aberta is janela, "o segundo clique abriu outra janela das tarefas"
    return sem_posicao


def tarefas_borda_e_janela() -> Iterator[Esperar]:
    try:
        sem_posicao = yield from abrir_janela_das_tarefas()
    except BaseException:
        encerrar_tarefa_de_teste()
        raise
    # A janela e a tarefa seguem abertas para os dois passos seguintes.
    if sem_posicao:
        raise Pulado("sem HWND: a posição da janela solta não foi conferida")


def tarefas_fechar_principal() -> Iterator[Esperar]:
    from cartridges.tarefas_janela import TarefasJanela  # pylint: disable=import-outside-toplevel
    from cartridges.utils import window_geometry  # pylint: disable=import-outside-toplevel

    win = shared().win
    try:
        assert TarefasJanela.aberta is not None and TAREFA is not None, (
            "o passo anterior não deixou a janela das tarefas aberta"
        )
        antes = window_geometry.read(win)
        win.close()
        yield ocioso()
        assert not win.get_visible(), "fechar a principal com tarefa rodando não a escondeu"
        assert TarefasJanela.aberta is not None, "a janela das tarefas sumiu com a principal"
        win.present()
        yield Esperar(win.get_visible, LOCAL, "a principal voltar à tela")
        yield ocioso()
        depois = window_geometry.read(win)
        sem_posicao = antes is None or depois is None
        if not sem_posicao:
            # O "map" da principal reaparecida não pode devolvê-la à posição e ao
            # tamanho da abertura: tem de ser onde estava ao ser escondida.
            assert all(abs(a - d) <= 4 for a, d in zip(antes[:4], depois[:4])), (
                f"a principal voltou em outro lugar: {antes[:4]} -> {depois[:4]}"
            )
    except BaseException:
        encerrar_tarefa_de_teste()
        raise
    # Depois do `try`, com a principal de volta e a janela solta aberta para o
    # passo seguinte: o `Pulado` não pode passar pelo `encerrar_tarefa_de_teste`.
    if sem_posicao:
        raise Pulado("sem HWND: a posição da principal reaparecida não foi conferida")


def tarefas_esc_fecha() -> Iterator[Esperar]:
    from gi.repository import Gtk  # pylint: disable=import-outside-toplevel

    from cartridges.tarefas_janela import TarefasJanela  # pylint: disable=import-outside-toplevel

    try:
        janela = TarefasJanela.aberta
        assert janela is not None, "a janela das tarefas não estava aberta"
        # O atalho que a própria janela registra: o gatilho tem de ser o Esc, e a
        # ação dele (a mesma que o controlador dispara) é que fecha a janela.
        atalho = None
        controladores = janela.observe_controllers()
        for i in range(controladores.get_n_items()):
            controlador = controladores.get_item(i)
            if isinstance(controlador, Gtk.ShortcutController):
                for j in range(controlador.get_n_items()):
                    candidato = controlador.get_item(j)
                    if candidato.get_trigger().to_string() == "Escape":
                        atalho = candidato
        assert atalho is not None, "a janela das tarefas não tem atalho para o Esc"
        atalho.get_action().activate(Gtk.ShortcutActionFlags.EXCLUSIVE, janela, None)
        yield Esperar(lambda: TarefasJanela.aberta is None, LOCAL, "o Esc fechar a janela das tarefas")
    finally:
        encerrar_tarefa_de_teste()
    yield Esperar(tarefas_paradas, LOCAL, "o quadro de tarefas esvaziar")


def tarefas_onde_nao_aparece(jogo: Any) -> Iterator[Esperar]:
    from cartridges.utils import tarefas  # pylint: disable=import-outside-toplevel

    if jogo is None:
        raise Pulado("a biblioteca não tem jogo")
    win = shared().win
    botao = botao_tarefas()

    def chamar_pela_borda() -> bool:
        escurecer_botao()
        botao._ao_mover(None, 8, altura_canto() - 10)  # pylint: disable=protected-access
        return botao.revealer.get_reveal_child()

    tarefa = tarefas.comecar(NOME_TAREFA, 3)
    try:
        yield Esperar(lambda: not tarefas_paradas(), LOCAL, "a tarefa entrar no quadro")

        yield from ir_aos_detalhes(jogo)
        assert not chamar_pela_borda(), "o botão apareceu nos detalhes do jogo"

        yield from abrir_edicao(jogo)
        assert not chamar_pela_borda(), "o botão apareceu com a edição aberta"
        yield from fechar_dialogo("a edição")

        win.show_session_blocker(jogo)
        try:
            assert not chamar_pela_borda(), "o botão apareceu durante uma sessão"
        finally:
            win.hide_session_blocker()

        win.navigation_view.pop_to_page(win.library_page)
        win.activate_action("win.show_zerados", None)
        yield Esperar(lambda: pagina() == win.zerados_library_page, LOCAL, "abrir Jogos Zerados")
        assert chamar_pela_borda(), "o botão não apareceu em Jogos Zerados"

        win.navigation_view.pop_to_page(win.library_page)
        yield Esperar(lambda: pagina() == win.library_page, LOCAL, "voltar à biblioteca")
        assert chamar_pela_borda(), "o botão não apareceu na biblioteca"
    finally:
        tarefa.terminar()
        escurecer_botao()
    yield Esperar(tarefas_paradas, LOCAL, "o quadro de tarefas esvaziar")


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
    alvo_tarefas = vivos[0] if vivos else None
    roteiro: list[Passo] = [
        ("Cada ordenação", None, ordenar),
        ("Busca", None, buscar),
        ("Jogos Zerados", None, jogos_zerados),
        ("Preferências", None, preferencias),
        ("Sobre", None, sobre),
        ("Novidades", None, novidades),
        ("Tarefas: o botão entra e recua", None, tarefas_botao_entra_e_recua),
        ("Tarefas: a borda traz o botão e o clique abre a janela", None, tarefas_borda_e_janela),
        ("Tarefas: fechar a principal com tarefa só a esconde", None, tarefas_fechar_principal),
        ("Tarefas: Esc fecha a janela", None, tarefas_esc_fecha),
        ("Tarefas: onde o botão não aparece", alvo_tarefas, lambda g=alvo_tarefas: tarefas_onde_nao_aparece(g)),
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
    # cp1252 no stdout (console padrão do Windows) lança em qualquer nome de
    # jogo fora dessa página de código; troca por "?" em vez de derrubar o
    # processo no meio do roteiro.
    sys.stdout.reconfigure(errors="replace")
    saida = Path(sys.argv[1]).resolve()
    chamadas = preparar(saida)

    from cartridges.main import CartridgesApplication  # pylint: disable=import-outside-toplevel
    import cartridges.main as modulo_main  # pylint: disable=import-outside-toplevel
    from gi.repository import Gio  # pylint: disable=import-outside-toplevel

    app = CartridgesApplication()
    # Sem isto, uma segunda cópia do passeio (ou qualquer app com o mesmo ID
    # rodando por acaso) vira instância secundária: o GLib do MSYS2 sobe um
    # gdbus.exe, o app.run() só repassa o "activate" e devolve 0 na hora, sem
    # rodar um único passo. Ver cartridges/utils/single_instance.py:20-29.
    app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
    MOTOR = Motor(app, saida)
    MOTOR.fila.append(("Carregar a biblioteca", None, carregar_biblioteca))

    # `setup_logging` roda no início do `do_activate` real, antes da janela e
    # da carga da biblioteca — e substitui os handlers do logger raiz
    # (dictConfig). Pendurar o coletor só depois de `iniciar` (via
    # `connect_after`) perderia tudo isso: os avisos de "Skipping malformed
    # game record", por exemplo, aconteceriam antes do coletor existir na
    # cadeia. Por isso o coletor entra aqui, logo que o `setup_logging` real
    # termina, uma única vez.
    setup_logging_original = modulo_main.setup_logging

    def setup_logging_com_coletor() -> None:
        # O coletor entra mesmo se o `setup_logging` real lançar: sem ele
        # pendurado, um passeio inteiro roda sem capturar aviso nenhum.
        try:
            setup_logging_original()
        finally:
            logging.getLogger().addHandler(MOTOR.coletor)

    modulo_main.setup_logging = setup_logging_com_coletor

    app.connect_after("activate", lambda *_: MOTOR.iniciar())
    (saida / "atual.txt").write_text("Abrir o app", encoding="utf-8")
    faulthandler.dump_traceback_later(LIMITE_TRAVA, exit=True, file=MOTOR.despejo)
    codigo = app.run([sys.argv[0]])
    if MOTOR.erro:
        # O motor travou no próprio laço (ver `_tick`): o app pode ter saído
        # com 0 mesmo assim, mas o passeio não terminou o roteiro.
        codigo = 1
    print(
        f"Chamadas neutralizadas: iniciar jogo {len(chamadas['iniciar'])}, "
        f"luzes {len(chamadas['luzes'])}, papel de parede {len(chamadas['papel'])}",
        flush=True,
    )
    return codigo


if __name__ == "__main__":
    sys.exit(main())
