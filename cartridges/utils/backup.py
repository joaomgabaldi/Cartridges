# backup.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O backup completo: a biblioteca inteira e as configurações num .zip.

Leva tudo o que o app guarda de você — o registro de cada jogo, a capa, o logo,
o papel de parede e a cor das fitas de cada um, as fitas configuradas, o
histórico de sessões e as configurações — para que uma instalação nova fique
idêntica à antiga. Fica fora só o que vale nesta máquina e em mais nenhuma: a
conta da Tuya (um blob DPAPI não decifra em outra conta do Windows), os logs e
o caminho de volta de uma sessão em andamento.

Restaurar substitui, não mescla, e não acontece com o app aberto: a varredura
do HowLongToBeat e a do tamanho no disco gravariam os jogos antigos por cima
dos restaurados. `agendar` deixa o zip na pasta do app e o app fecha; na
abertura seguinte, `aplicar_pendente` faz a troca antes de qualquer coisa ler
os dados.
"""

import json
import logging
import re
import shutil
import zipfile
from hashlib import sha256
from pathlib import Path, PurePosixPath
from time import time
from typing import Any, Callable, Iterable, Optional

from gi.repository import Gio, GLib

from cartridges import shared
from cartridges.game import Game
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.utils import game_logo, session_fita, session_log, session_wallpaper
from cartridges.utils.name_cleaner import clean_for_search

VERSAO = 4

_MANIFESTO = "backup.json"

# O caminho de volta de uma sessão em andamento nesta máquina: as telas e as
# fitas como estavam antes do jogo. Restaurado noutra máquina, ou depois de a
# sessão acabar, "desfaria" uma troca que nunca aconteceu.
_CHAVES_DE_SESSAO = frozenset({"session-wallpaper-saved", "fita-estado-anterior"})

# Do schema de estado, só a ordenação é escolha de alguém. Tamanho e posição da
# janela, o balde do limitador da Steam e a última novidade vista são da máquina.
_CHAVES_DE_ESTADO = ("sort-mode",)

# Campos que representam a opinião do usuário sobre um jogo — os únicos que o
# backup por jogo leva. Tudo que é identidade (executable, game_id, source,
# shortcut_*) ou metadado online (developer, steam_appid como dado, hltb_*)
# fica de fora: identidade nunca viaja, e metadado online o próprio pipeline
# de import recarrega sozinho assim que o jogo existir.
CAMPOS_OPINIAO = (
    "hidden",
    "last_played",
    "playtime",
    "status",
    "rating",
    "notes",
    "run_as_admin",
    "track_process",
    "process_executable",
    "track_updates",
)


def identidade(jogo: Any) -> str:
    """A identidade portátil de ``jogo``: sobrevive a outra máquina e a outro
    caminho de instalação, ao contrário do ``game_id`` (que para um atalho é
    derivado do caminho do executável).

    ``steam:<appid>`` quando o jogo tem um appID da Steam — é o mesmo jogo em
    qualquer PC. Sem appID, cai para o nome limpo (``clean_for_search``, a
    mesma normalização já usada para buscar na Steam) — mais frágil, mas é o
    único sinal que sobra para um jogo que a Steam não conhece.
    """
    if getattr(jogo, "steam_appid", None):
        return f"steam:{jogo.steam_appid}"
    return f"nome:{clean_for_search(jogo.name).casefold()}"


def _hash_identidade(identidade_str: str) -> str:
    """A identidade como nome de arquivo/chave de manifesto: curta, sem
    caracteres que o zip ou o nome de um arquivo recusariam. Mesmo mecanismo
    de ``ShortcutsSourceIterable._game_id`` (sha256 truncado), chave diferente."""
    return sha256(identidade_str.encode("utf-8")).hexdigest()[:16]


def _agrupar_por_identidade(jogos: Iterable[Any]) -> dict[str, tuple[str, list[Any]]]:
    """Agrupa ``jogos`` pela identidade portátil.

    Cada grupo carrega o tipo da identidade (``"steam"`` ou ``"nome"``) e a
    lista de jogos que caíram nela. Mais de um jogo no mesmo grupo quer dizer
    coisas diferentes dependendo do tipo — appID repetido é o mesmo jogo
    (cópia Steam e cópia pirata, por exemplo), nome repetido sem appID é uma
    coincidência que ninguém aqui tem como desfazer. Quem chama decide o que
    fazer com cada caso; esta função só constata a colisão.
    """
    grupos: dict[str, tuple[str, list[Any]]] = {}
    for jogo in jogos:
        ident = identidade(jogo)
        tipo = ident.split(":", 1)[0]
        chave = _hash_identidade(ident)
        if chave in grupos:
            grupos[chave][1].append(jogo)
        else:
            grupos[chave] = (tipo, [jogo])
    return grupos


def _salvar_e_atualizar(jogo: Game) -> bool:
    """``jogo.save()``/``jogo.update()`` emitem sinais GObject que managers
    como o ``DisplayManager`` respondem tocando widgets diretamente — só é
    seguro chamar na thread principal. Marshallado com ``GLib.idle_add`` por
    quem roda em thread de fundo (a varredura de appID, o casamento do
    restore). Devolve ``False`` porque é isso que ``GLib.idle_add`` espera
    para não repetir a chamada."""
    jogo.save()
    jogo.update()
    return False


def _forcar_appids(
    jogos: list[Game],
    progresso: Optional[Callable[[int, int], None]],
    cancelado: Optional[Callable[[], bool]],
) -> bool:
    """Roda a busca de appID da Steam nos ``jogos`` passados, em primeiro
    plano (sem depender do pipeline assíncrono de import). Reaproveita o
    ``SteamAPIManager`` já registrado no store — mesmo rate limiter da
    varredura normal, não um novo a cada chamada.

    ``progresso``, se passado, é chamado como ``progresso(indice, total)`` —
    dois inteiros separados, a mesma convenção de todo outro uso de
    ``GLib.idle_add`` com múltiplos argumentos no projeto (e a que as Tasks 6
    e 9 já pressupõem: ``restaurar``'s ``Callable[[int, int], None]`` e o
    ``atualizar_progresso(indice, total)`` da tela de preferências). Assim
    como ``_salvar_e_atualizar``, a chamada é marshallada com
    ``GLib.idle_add`` porque quem roda a varredura está em thread de fundo e
    ``progresso`` normalmente atualiza uma barra de progresso na UI.

    Devolve ``False`` se ``cancelado`` disparar no meio: os jogos processados
    até ali ficam com o appID que a busca achou (resolver appID é
    enriquecimento de metadado, não é "aplicar o backup"), mas nenhum jogo
    depois do ponto do cancelamento é tocado.
    """
    gerente = shared.store.managers[SteamAPIManager]
    total = len(jogos)
    for indice, jogo in enumerate(jogos, start=1):
        if cancelado is not None and cancelado():
            return False
        gerente.run(jogo, {})
        GLib.idle_add(_salvar_e_atualizar, jogo)
        if progresso is not None:
            GLib.idle_add(progresso, indice, total)
    return True


def _pendente() -> Path:
    return shared.app_dir / "restaurar.zip"


def _chaves_do_app() -> list[str]:
    return [
        chave
        for chave in shared.schema.props.settings_schema.list_keys()
        if chave not in _CHAVES_DE_SESSAO
    ]


def ler_configuracoes() -> dict[str, Any]:
    """As configurações como vão no backup. Chamar na thread principal.

    Genérico de propósito: uma chave nova no schema entra no backup sozinha, em
    vez de depender de alguém lembrar de acrescentá-la a uma lista.
    """
    return {
        "settings": {
            chave: shared.schema.get_value(chave).unpack() for chave in _chaves_do_app()
        },
        "state": {
            chave: shared.state_schema.get_value(chave).unpack()
            for chave in _CHAVES_DE_ESTADO
        },
    }


def _variante(chave: Gio.SettingsSchemaKey, valor: Any) -> Optional[GLib.Variant]:
    """``valor`` como o schema o guarda, ou ``None`` se o schema não o aceita."""
    tipo = chave.get_value_type().dup_string()
    # GLib.Variant("b", ...) aceita qualquer coisa e a torna verdadeira; um
    # "sim" digitado à mão ligaria a opção em vez de ser descartado.
    if tipo == "b" and not isinstance(valor, bool):
        return None
    try:
        variante = GLib.Variant(tipo, valor)
    except (TypeError, ValueError, OverflowError):
        return None
    # Fora das opções do schema (um `sort-mode` que não existe): o GSettings
    # recusaria com um aviso crítico e deixaria o valor de antes no lugar.
    return variante if chave.range_check(variante) else None


def _aplicar(settings: Any, valores: Any, chaves: Iterable[str]) -> None:
    valores = valores if isinstance(valores, dict) else {}
    schema = settings.props.settings_schema
    for chave in chaves:
        variante = None
        if chave in valores:
            variante = _variante(schema.get_key(chave), valores[chave])
            if variante is None:
                logging.warning("Configuração %s ignorada no backup: valor inválido", chave)
        if variante is None:
            # Idêntico ao backup: o que ele não tem, ou tem num valor que esta
            # versão não aceita, fica no padrão.
            settings.reset(chave)
        else:
            settings.set_value(chave, variante)


def aplicar_configuracoes(configuracoes: dict[str, Any]) -> None:
    """Deixa as configurações como estão em ``configuracoes``."""
    _aplicar(shared.schema, configuracoes.get("settings"), _chaves_do_app())
    _aplicar(shared.state_schema, configuracoes.get("state"), _CHAVES_DE_ESTADO)
    Gio.Settings.sync()


def _incluir(arquivo: zipfile.ZipFile, caminho: Path, nome: str) -> None:
    # As imagens já vêm comprimidas: passar deflate nelas custa segundos e não
    # ganha nada. Só o texto (registros, sidecars, histórico) é comprimido.
    compressao = (
        zipfile.ZIP_DEFLATED if caminho.suffix in (".json", ".jsonl") else zipfile.ZIP_STORED
    )
    try:
        arquivo.write(caminho, nome, compress_type=compressao)
    except FileNotFoundError:
        # Apagado entre a listagem e a leitura (uma capa trocada agora): o
        # backup sai sem ele, em vez de não sair.
        logging.debug("%s sumiu durante o backup", caminho)


def _jogos_exportaveis(jogos_ativos: list[Any]) -> dict[str, Any]:
    """hash -> jogo, só para identidades sem colisão entre jogos locais.

    Duas cópias locais do mesmo jogo (mesmo appID, ou mesmo nome sem appID)
    não têm como decidir de qual delas vem a opinião a exportar — a
    identidade sai do backup inteira, dos dois lados, em vez de chutar uma.
    """
    grupos = _agrupar_por_identidade(jogos_ativos)
    return {chave: alvos[0] for chave, (_tipo, alvos) in grupos.items() if len(alvos) == 1}


def _entrada_do_jogo(jogo: Any, sessoes: list[dict[str, int]]) -> dict[str, Any]:
    entrada: dict[str, Any] = {campo: getattr(jogo, campo) for campo in CAMPOS_OPINIAO}
    entrada["identidade_exibicao"] = jogo.steam_appid or jogo.name
    entrada["sessoes"] = sessoes

    if session_wallpaper.escolha(jogo) == "manual":
        posicoes = session_wallpaper.posicoes_escolhidas(jogo.game_id)
        entrada["wallpaper_posicao_retrato"] = posicoes.retrato
        entrada["wallpaper_posicao_paisagem"] = posicoes.paisagem

    cor = session_fita.cor_escolhida(jogo.game_id)
    if cor is not None:
        entrada["fita_matiz"] = cor.matiz
        entrada["fita_saturacao"] = cor.saturacao
        entrada["fita_brilho"] = cor.brilho

    return entrada


def _assets_do_jogo(jogo: Any) -> list[tuple[Path, str]]:
    """Lista (caminho_no_disco, nome_no_zip) dos arquivos deste jogo, só os
    escolhidos à mão — um logo/parede automático é recarregado sozinho pelo
    pipeline normal, não vale o espaço no backup."""
    assets: list[tuple[Path, str]] = []

    capa = jogo.get_cover_path()
    if capa is not None:
        assets.append((capa, f"capa{capa.suffix.lower()}"))

    if game_logo.logo_choice(jogo) == "manual":
        logo = game_logo.cached_logo_path(jogo)
        if logo is not None:
            assets.append((logo, f"logo{logo.suffix.lower()}"))

    if session_wallpaper.escolha(jogo) == "manual":
        parede = session_wallpaper.imagem_escolhida(jogo.game_id)
        if parede is not None:
            assets.append((parede, f"wallpaper{parede.suffix.lower()}"))

    return assets


def exportar(destino: Path, configuracoes: dict[str, Any]) -> None:
    """Grava o backup em ``destino``. Pode rodar fora da thread principal."""
    jogos_ativos = [jogo for jogo in shared.store if not jogo.removed]
    exportaveis = _jogos_exportaveis(jogos_ativos)
    game_id_para_hash = {jogo.game_id: chave for chave, jogo in exportaveis.items()}

    sessoes_por_hash: dict[str, list[dict[str, int]]] = {}
    for sessao in session_log.load():
        chave = game_id_para_hash.get(sessao["game_id"])
        if chave is not None:
            sessoes_por_hash.setdefault(chave, []).append(
                {"end": sessao["end"], "seconds": sessao["seconds"]}
            )

    jogos_manifesto = {
        chave: _entrada_do_jogo(jogo, sessoes_por_hash.get(chave, []))
        for chave, jogo in exportaveis.items()
    }

    manifesto = {
        "version": VERSAO,
        "app_version": shared.VERSION,
        "created": int(time()),
        **configuracoes,
        "jogos": jogos_manifesto,
    }

    # Temporário + troca: exportar por cima de um backup antigo e cair no meio
    # deixaria o antigo perdido e o novo ilegível.
    temporario = destino.with_name(destino.name + ".tmp")
    try:
        # strict_timestamps=False: um arquivo com data anterior a 1980 (que o
        # formato zip não representa) entra com 1980, em vez de abortar tudo.
        with zipfile.ZipFile(temporario, "w", strict_timestamps=False) as arquivo:
            arquivo.writestr(
                _MANIFESTO,
                json.dumps(manifesto, indent=2, ensure_ascii=False),
                compress_type=zipfile.ZIP_DEFLATED,
            )
            for chave, jogo in exportaveis.items():
                for caminho, nome_do_asset in _assets_do_jogo(jogo):
                    _incluir(arquivo, caminho, f"jogos/{chave}/{nome_do_asset}")
            if shared.fitas_arquivo.is_file():
                _incluir(arquivo, shared.fitas_arquivo, "fitas.json")
        temporario.replace(destino)
    finally:
        temporario.unlink(missing_ok=True)


_HASH_RE = re.compile(r"^[0-9a-f]{16}$")

# Nome base -> extensões aceitas para cada tipo de asset por jogo.
_EXTENSOES_ASSET = {
    "capa": (".tiff", ".gif", ".webp"),
    "logo": (".png", ".webp", ".jpg", ".jpeg"),
    "wallpaper": (".jpg", ".jpeg", ".png", ".webp"),
}


def _nome_valido(nome: str) -> bool:
    """Só o que `exportar` grava: o manifesto, ``fitas.json``, ou um asset de
    jogo em ``jogos/<hash de 16 hex>/<capa|logo|wallpaper><extensão conhecida>``.
    Nada absoluto, nada com ``..``, nada fora dessas três formas."""
    if nome in (_MANIFESTO, "fitas.json"):
        return True
    if "\\" in nome or ":" in nome:
        return False

    partes = PurePosixPath(nome).parts
    if len(partes) != 3 or partes[0] != "jogos":
        return False
    _pasta, hash_id, arquivo = partes
    if not _HASH_RE.match(hash_id):
        return False

    base, ponto, extensao = arquivo.partition(".")
    if not ponto:
        return False
    return base in _EXTENSOES_ASSET and f".{extensao}" in _EXTENSOES_ASSET[base]


def validar(caminho: Path) -> dict[str, Any]:
    """O manifesto de um backup por jogo. ``ValueError`` se não for um."""
    try:
        with zipfile.ZipFile(caminho) as arquivo:
            for nome in arquivo.namelist():
                if not _nome_valido(nome):
                    raise ValueError(f"entrada inesperada no backup: {nome}")
            # O CRC de cada entrada, e não só o do manifesto: um byte trocado
            # numa capa passaria daqui e só estouraria no meio da restauração.
            if (corrompida := arquivo.testzip()) is not None:
                raise ValueError(f"entrada corrompida no backup: {corrompida}")
            manifesto = json.loads(arquivo.read(_MANIFESTO).decode("utf-8"))
    except ValueError:
        raise
    except Exception as erro:  # pylint: disable=broad-exception-caught
        raise ValueError(str(erro)) from erro

    if not isinstance(manifesto, dict) or manifesto.get("version") != VERSAO:
        raise ValueError("o arquivo não é um backup desta versão")
    if not isinstance(manifesto.get("jogos"), dict):
        raise ValueError("backup sem o bloco de jogos")
    return manifesto


def agendar(caminho: Path) -> None:
    """Deixa ``caminho`` para ser aplicado na próxima abertura do app."""
    destino = _pendente()
    temporario = destino.with_name(destino.name + ".tmp")
    try:
        shared.app_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(caminho, temporario)
        temporario.replace(destino)
    finally:
        temporario.unlink(missing_ok=True)


def aplicar_pendente() -> Optional[bool]:
    """Aplica o backup que `agendar` deixou, se houver.

    Chamar na abertura, antes de qualquer coisa ler os dados do app. ``None``:
    nada agendado. ``True``: restaurado. ``False``: não deu (detalhes no log).
    """
    pendente = _pendente()
    if not pendente.is_file():
        return None

    extraido = shared.app_dir / "restaurar.tmp"
    antigo = shared.app_dir / "restaurar.old"
    # Sobras de uma abertura que caiu depois da troca: o que está no lugar já
    # é o backup, e o zip ainda aqui vai refazer tudo do zero.
    shutil.rmtree(extraido, ignore_errors=True)
    shutil.rmtree(antigo, ignore_errors=True)
    try:
        manifesto = validar(pendente)
        with zipfile.ZipFile(pendente) as arquivo:
            arquivo.extractall(extraido)
    except Exception as erro:  # pylint: disable=broad-exception-caught
        # Nada foi tocado ainda: a biblioteca atual fica, e o zip ruim sai
        # para não ser tentado de novo a cada abertura.
        logging.error("Backup agendado inválido: %s", erro)
        _limpar(extraido, pendente)
        return False

    try:
        _trocar(extraido, antigo)
    except OSError:
        logging.exception("Não foi possível trocar a biblioteca pela do backup")
        if antigo.is_dir() and not any(antigo.iterdir()):
            # Tudo voltou ao lugar: a biblioteca atual fica, como se o backup
            # nunca tivesse sido agendado.
            _limpar(extraido, antigo, pendente)
        # ponytail: se nem desfazer deu, o zip fica e a próxima abertura
        # termina a restauração; nesta, o app abre com o que estiver no lugar.
        return False

    # As configurações antes de o zip sair: aplicá-las de novo não muda nada,
    # e assim uma queda em qualquer ponto até aqui refaz tudo do zero.
    aplicar_configuracoes(manifesto)
    _limpar(extraido, antigo, pendente)
    logging.info("Backup restaurado")
    return True


def _trocar(extraido: Path, antigo: Path) -> None:
    """Põe o extraído no lugar do atual, que vai para ``antigo``.

    Só com `os.replace`, que no mesmo disco move ou falha inteiro — ao
    contrário de `rmtree`, que com um arquivo em uso apaga metade da pasta e
    para. Nada é apagado aqui; uma falha no meio desfaz o que já foi movido e
    levanta o erro.
    """
    itens = [*_pastas().items(), *_arquivos().items()]
    antigo.mkdir(exist_ok=True)
    feitos: list[tuple[Path, Path]] = []
    try:
        for nome, destino in itens:
            if destino.exists():
                destino.replace(antigo / nome)
                feitos.append((antigo / nome, destino))
        for nome, destino in itens:
            origem = extraido / nome
            if origem.exists():
                origem.replace(destino)
                feitos.append((destino, origem))
    except OSError:
        for de, para in reversed(feitos):
            de.replace(para)
        raise


def _limpar(*caminhos: Path) -> None:
    for caminho in caminhos:
        if caminho.is_dir():
            shutil.rmtree(caminho, ignore_errors=True)
            continue
        try:
            caminho.unlink(missing_ok=True)
        except OSError:
            logging.exception("Não foi possível apagar %s", caminho)
