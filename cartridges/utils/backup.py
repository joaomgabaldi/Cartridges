# backup.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O backup: os dados que cada jogo tem de você, e as configurações, num .zip.

Leva, por jogo, nota, status, tempo, anotação, sessões e as escolhas feitas à
mão (capa, logo, papel de parede, cor da fita), além da lista de fitas e das
configurações. Fica fora o que vale só nesta máquina: a conta da Tuya (um blob
DPAPI não decifra em outra conta do Windows), a pasta de atalhos, o monitor da
sessão, os logs e o caminho de volta de uma sessão em andamento.

`restaurar()` casa cada jogo do backup com um jogo local pela identidade
portátil (ver `identidade`) e sobrescreve os dados dele. Nunca apaga e nunca
cria jogo, exceto um zerado que só existe no backup. Faz isso ao vivo, sem
fechar o app.
"""

import json
import logging
import re
import threading
import zipfile
from hashlib import sha256
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from time import time
from typing import Any, Callable, Iterable, NamedTuple, Optional

from gi.repository import Gio, GLib

from cartridges import shared
from cartridges.game import STATUS_LABELS, Game
from cartridges.store.managers.display_manager import is_main_thread
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.utils import game_logo, save_cover, session_fita, session_log, session_wallpaper
from cartridges.utils.name_cleaner import clean_for_search

VERSAO = 4

_MANIFESTO = "backup.json"

# Ligado do começo ao fim de `restaurar()` (try/finally). `ligacao_zerado`
# confere isto antes de fundir um zerado: o restore já casa zerados com jogos
# vivos por identidade, por conta própria, e uma fusão concorrente no meio
# dele apagaria uma tumba que a thread do restore ainda ia tocar.
RESTAURANDO = threading.Event()

# O caminho de volta de uma sessão em andamento nesta máquina: as telas e as
# fitas como estavam antes do jogo. Restaurado noutra máquina, ou depois de a
# sessão acabar, "desfaria" uma troca que nunca aconteceu.
_CHAVES_DE_SESSAO = frozenset({"session-wallpaper-saved", "fita-estado-anterior"})

# Do schema de estado, só a ordenação é escolha de alguém. Tamanho e posição da
# janela, o balde do limitador da Steam e a última novidade vista são da máquina.
_CHAVES_DE_ESTADO = ("sort-mode",)

# Valem só nesta máquina: a pasta de atalhos (outra letra de disco em outro PC)
# e o monitor escolhido para a sessão. Restauradas noutro PC, a pasta sumiria e
# a importação passaria a pular a fonte em silêncio.
_CHAVES_DA_MAQUINA = frozenset({"shortcuts-location", "session-monitor"})

# Campos que representam a opinião do usuário sobre um jogo — os únicos que o
# backup por jogo leva. Tudo que é identidade (executable, game_id, source,
# shortcut_*) ou metadado online (developer, steam_appid como dado, hltb_*)
# fica de fora: identidade nunca viaja, e metadado online o próprio pipeline
# de import recarrega sozinho assim que o jogo existir.
CAMPOS_OPINIAO = (
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

# O que a tela de um zerado mostra e ninguém mais recarrega. Um jogo vivo busca
# isto de novo pelo pipeline assim que existir; um zerado nunca passa por ele,
# então o backup leva junto para poder recriá-lo num PC onde ele não existe.
CAMPOS_FICHA = (
    "name",
    "developer",
    "publisher",
    "release_date",
    "genre",
    "description",
    "metacritic",
    "steam_review",
    "controller_support",
    "gamepad_recommended",
    "steam_appid",
    "hltb_id",
    "hltb_main",
    "hltb_main_extra",
    "hltb_completionist",
    "hltb_chapters",
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


def _agrupar_por_nome(jogos: Iterable[Any]) -> dict[str, list[Any]]:
    """Os jogos pelo hash da identidade por nome, tenham appID ou não — a
    identidade de reserva do B9, usada quando a identidade principal (por
    appID) de uma entrada não casa com nenhum jogo local."""
    grupos: dict[str, list[Any]] = {}
    for jogo in jogos:
        chave = _hash_identidade(f"nome:{clean_for_search(jogo.name).casefold()}")
        grupos.setdefault(chave, []).append(jogo)
    return grupos


def _salvar_e_atualizar(jogo: Game) -> bool:
    """``jogo.save()``/``jogo.update()`` emitem sinais GObject que managers
    como o ``DisplayManager`` respondem tocando widgets diretamente — só é
    seguro chamar na thread principal. Marshallado com ``GLib.idle_add`` por
    quem roda em thread de fundo (a varredura de appID, o casamento do
    restore). Devolve ``False`` porque é isso que ``GLib.idle_add`` espera
    para não repetir a chamada.

    Confere a identidade antes de gravar: entre o agendamento na thread de
    fundo e a execução aqui, a thread principal pode ter excluído, ligado
    (Q2) ou substituído esse registro. Gravar um jogo que não é mais o da
    store ressuscitaria um arquivo apagado ou pisaria um id reciclado.
    """
    if shared.store.get(jogo.game_id) is not jogo:
        logging.info("Restore: %s não é mais o jogo da store, gravação ignorada", jogo.game_id)
        return False
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
        # `only_missing`: um jogo que já tem opinião do usuário sobre outro
        # campo não deve levar por cima o que a Steam devolver. `sem_ligacao`:
        # o casamento de zerado por identidade já roda logo depois, no mesmo
        # `restaurar` — deixar o `SteamAPIManager` ligar por conta própria
        # criaria uma segunda fusão concorrente com a de `restaurar`.
        gerente.run(jogo, {"only_missing": True, "sem_ligacao": True})
        GLib.idle_add(_salvar_e_atualizar, jogo)
        if progresso is not None:
            GLib.idle_add(progresso, indice, total)
    return True


class ResultadoRestauracao(NamedTuple):
    casados: int
    total: int
    ambiguos: list[str]


def _extrair_asset(
    arquivo: zipfile.ZipFile, tmp_dir: Path, hash_id: str, base: str
) -> Optional[Path]:
    prefixo = f"jogos/{hash_id}/{base}."
    for nome in arquivo.namelist():
        if nome.startswith(prefixo):
            destino = tmp_dir / nome.replace("/", "_")
            destino.write_bytes(arquivo.read(nome))
            return destino
    return None


def _aplicar_sessoes(game_id: str, sessoes: list[dict[str, Any]]) -> None:
    existentes = {
        (sessao["game_id"], sessao["end"], sessao["seconds"])
        for sessao in session_log.load(game_id)
    }
    for sessao in sessoes:
        try:
            fim = int(sessao["end"])
            segundos = int(sessao["seconds"])
        except (KeyError, TypeError, ValueError):
            continue
        if (game_id, fim, segundos) not in existentes:
            session_log.record(game_id, segundos, fim)


_CAMPOS_BOOLEANOS = frozenset({"run_as_admin", "track_process", "track_updates"})
_CAMPOS_TEXTO = frozenset({"notes", "process_executable"})


def _para_inteiro_finito(valor: Any) -> Optional[int]:
    """``valor`` como ``int``, ou ``None`` se a conversão não for possível ou
    exata. ``int(float("inf"))`` já levanta ``OverflowError`` e
    ``int(float("nan"))`` já levanta ``ValueError`` — o mesmo ``try`` cobre os
    dois sem checagem extra."""
    try:
        return int(valor)
    except (OverflowError, TypeError, ValueError):
        return None


def _sanitizar_campos(entrada: dict[str, Any]) -> dict[str, Any]:
    """Valida cada campo de ``CAMPOS_OPINIAO`` presente em ``entrada`` e
    descarta (nunca aplica, nunca derruba a restauração) o que for inválido —
    mesma filosofia de ``_aplicar_sessoes``.

    ``Game.update_values`` só filtra a CHAVE (contra ``PERSISTED_ATTRS``),
    nunca o VALOR. Sem isto, um backup com ``"playtime": Infinity`` (JSON
    válido: ``json.loads`` aceita ``Infinity``/``NaN`` como float) passava
    direto e o ``FileManager`` gravava esse valor de volta em disco — quebrando
    ordenação, ``format_playtime`` e a soma de sessão rio abaixo.
    """
    campos: dict[str, Any] = {}
    for campo in CAMPOS_OPINIAO:
        if campo not in entrada:
            continue
        valor = entrada[campo]

        if campo in _CAMPOS_BOOLEANOS:
            if isinstance(valor, bool):
                campos[campo] = valor
        elif campo == "last_played":
            convertido = _para_inteiro_finito(valor)
            if convertido is not None:
                campos[campo] = convertido
        elif campo == "playtime":
            convertido = _para_inteiro_finito(valor)
            if convertido is not None and convertido >= 0:
                campos[campo] = convertido
        elif campo == "status":
            if isinstance(valor, str) and (valor == "" or valor in STATUS_LABELS):
                campos[campo] = valor
        elif campo == "rating":
            convertido = _para_inteiro_finito(valor)
            if convertido is not None and 0 <= convertido <= 5:
                campos[campo] = convertido
        elif campo in _CAMPOS_TEXTO:
            if isinstance(valor, str):
                campos[campo] = valor
    return campos


def _posicao_valida(valor: Any) -> Optional[float]:
    """``valor`` como posição de recorte (0.0–1.0), ou ``None`` se inválido."""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    if numero != numero or numero in (float("inf"), float("-inf")):  # NaN/infinito
        return None
    return numero if 0.0 <= numero <= 1.0 else None


def _componente_de_cor_valido(valor: Any, maximo: int) -> Optional[int]:
    """``valor`` como componente de ``Cor`` (0–``maximo``), ou ``None`` se
    inválido — mesma faixa que ``session_fita.Cor`` documenta."""
    convertido = _para_inteiro_finito(valor)
    if convertido is None or not (0 <= convertido <= maximo):
        return None
    return convertido


def _aplicar_jogo(
    jogo: Game, entrada: dict[str, Any], hash_id: str, arquivo: zipfile.ZipFile, tmp_dir: Path
) -> None:
    campos = _sanitizar_campos(entrada)
    jogo.update_values(campos)
    GLib.idle_add(_salvar_e_atualizar, jogo)

    try:
        capa = _extrair_asset(arquivo, tmp_dir, hash_id, "capa")
        if capa is not None:
            save_cover.save_cover(jogo.game_id, capa)

        logo = _extrair_asset(arquivo, tmp_dir, hash_id, "logo")
        if logo is not None:
            game_logo.save_manual_logo(jogo.game_id, jogo.name, logo)
        if entrada.get("logo_escolha") == "title":
            game_logo.use_title_instead(jogo.game_id, jogo.name)

        parede = _extrair_asset(arquivo, tmp_dir, hash_id, "wallpaper")
        if parede is not None:
            retrato = _posicao_valida(entrada.get("wallpaper_posicao_retrato"))
            paisagem = _posicao_valida(entrada.get("wallpaper_posicao_paisagem"))
            posicoes = session_wallpaper.Posicoes(
                retrato if retrato is not None else 0.5,
                paisagem if paisagem is not None else 0.5,
            )
            session_wallpaper.salvar_escolha(jogo.game_id, jogo.name, parede, posicoes)
        if entrada.get("wallpaper_escolha") == "none":
            session_wallpaper.nao_trocar(jogo.game_id, jogo.name)

        matiz = _componente_de_cor_valido(entrada.get("fita_matiz"), 359)
        saturacao = _componente_de_cor_valido(entrada.get("fita_saturacao"), 1000)
        brilho = _componente_de_cor_valido(entrada.get("fita_brilho"), 1000)
        if matiz is not None and saturacao is not None and brilho is not None:
            session_fita.salvar_cor(
                jogo.game_id, jogo.name, session_fita.Cor(matiz, saturacao, brilho)
            )

        _aplicar_sessoes(jogo.game_id, entrada.get("sessoes") or [])
    except OSError as erro:
        # Um arquivo travado (antivírus, disco cheio) custa só este jogo — o
        # restore segue para o resto da biblioteca.
        logging.warning("Backup: arquivos de %s não restaurados: %s", jogo.name, erro)


_FICHA_INTEIROS = ("metacritic", "hltb_id", "hltb_main", "hltb_main_extra", "hltb_completionist")


def _sanitizar_capitulo(capitulo: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Um item de ``hltb_chapters`` com os números convertidos para inteiros
    finitos, ou ``None`` se algum campo não for conversível.

    ``name`` fica como texto; ``None`` num campo numérico (um capítulo sem
    tempo de completista, por exemplo) é legítimo e passa direto — só um
    valor presente e inconversível (``"x"``, ``inf``, ``nan``) derruba o
    capítulo inteiro.
    """
    limpo: dict[str, Any] = {}
    for chave, valor in capitulo.items():
        if chave == "name":
            if not isinstance(valor, str):
                return None
            limpo[chave] = valor
            continue
        if valor is None:
            limpo[chave] = None
            continue
        convertido = _para_inteiro_finito(valor)
        if convertido is None or isinstance(valor, bool):
            return None
        limpo[chave] = convertido
    return limpo


def _sanitizar_ficha(dados: dict[str, Any]) -> dict[str, Any]:
    """Números da ficha como inteiros finitos; capítulos só com números válidos.

    O ``sanitize_game_fields`` da carga aceita float (inclusive ``inf``/``nan``),
    e um backup editado à mão chegaria à tela como "Metacritic: inf".
    """
    limpos = dict(dados)
    for campo in _FICHA_INTEIROS:
        if campo in limpos and limpos[campo] is not None:
            convertido = _para_inteiro_finito(limpos[campo])
            if convertido is None or isinstance(limpos[campo], bool):
                limpos.pop(campo)
            else:
                limpos[campo] = convertido

    capitulos = limpos.get("hltb_chapters")
    if capitulos is not None:
        limpos["hltb_chapters"] = [
            capitulo_limpo
            for capitulo in (capitulos if isinstance(capitulos, list) else [])
            if isinstance(capitulo, dict)
            and (capitulo_limpo := _sanitizar_capitulo(capitulo)) is not None
        ]
    return limpos


def _criar_zerado(
    entrada: dict[str, Any], hash_id: str, arquivo: zipfile.ZipFile, tmp_dir: Path
) -> bool:
    """Recria no PC um zerado que só existe no backup. False: ficha ilegível,
    id ocupado bem na hora do registro, ou o registro na thread principal não
    aconteceu (ver `_rodar_na_main`).

    A única exceção a "restaurar nunca cria jogo", e só para zerados, que
    nunca são jogos ativos: nasce como tumba, sem atalho e sem executável,
    exatamente como ficou no PC de origem. O id é escolhido e registrado na
    thread principal primeiro — capa, logo e sessões só vão para o disco
    depois, na thread do restore, com o id já reservado; se a gravação
    falhar, o zerado fica sem capa (aceitável, ela pode ser baixada de novo).
    """
    # Local: main importa (via preferences) este módulo.
    from cartridges.main import sanitize_game_fields  # noqa: PLC0415

    ficha = entrada.get("ficha")
    if not isinstance(ficha, dict):
        return False
    dados = _sanitizar_ficha(
        sanitize_game_fields(
            {campo: ficha[campo] for campo in CAMPOS_FICHA if campo in ficha},
            f"backup:{hash_id}",
        )
    )
    if not isinstance(dados.get("name"), str) or not dados["name"].strip():
        return False

    dados.update(_sanitizar_campos(entrada))
    dados.update(
        source="imported", executable="", added=int(time()), removed=True, status="beaten"
    )

    registrado: dict[str, str] = {}

    def registrar() -> None:
        game_id = shared.store.proximo_id_importado()
        if shared.store.get(game_id) is not None:
            # Corrida: outra coisa ocupou este id entre a escolha e aqui.
            return
        dados.update(game_id=game_id)
        _registrar_zerado(dados)
        registrado["id"] = game_id

    if not _rodar_na_main(registrar) or "id" not in registrado:
        return False
    game_id = registrado["id"]

    try:
        capa = _extrair_asset(arquivo, tmp_dir, hash_id, "capa")
        if capa is not None:
            save_cover.save_cover(game_id, capa)
        logo = _extrair_asset(arquivo, tmp_dir, hash_id, "logo")
        if logo is not None:
            game_logo.save_manual_logo(game_id, dados["name"], logo)
        _aplicar_sessoes(game_id, entrada.get("sessoes") or [])
    except OSError as erro:
        logging.warning("Backup: arquivos do zerado %s não restaurados: %s", dados["name"], erro)
    GLib.idle_add(_recarregar_capa, game_id)
    return True


def _registrar_zerado(dados: dict[str, Any]) -> None:
    jogo = Game(dados)
    shared.store.add_game(jogo, {})
    jogo.save()


def _recarregar_capa(game_id: str) -> bool:
    """A capa gravada depois do registro precisa chegar ao card já na grade."""
    jogo = shared.store.get(game_id)
    if jogo is not None:
        jogo.update()
    return False


def _aplicar_fitas(arquivo: zipfile.ZipFile) -> None:
    """Se o `.zip` tiver `fitas.json`, sobrescreve `shared.fitas_arquivo` com
    ele — depois de devolver ao estado de antes as fitas que saem da lista
    nova (ver `session_fita.devolver_removidas`), senão elas ficariam presas
    na cor do Cartridges sem ninguém para desligá-las. Configuração global (a
    lista de fitas de LED, sem a conta Tuya) — diferente da opinião por jogo,
    não depende de nenhum casamento de identidade: aplica sempre que a
    entrada existir no backup. Por isso `restaurar()` chama isto (e
    `_aplicar_configuracoes_fora_da_main`) antes da varredura cancelável de
    appID — não depois, como um dado de jogo: cancelar a varredura não pode
    deixar essa configuração pela metade, restaurada só se der tempo."""
    if "fitas.json" not in arquivo.namelist():
        return
    dados = arquivo.read("fitas.json")
    try:
        novas = {item.get("id") for item in json.loads(dados).get("fitas", [])}
    except (ValueError, AttributeError, TypeError):
        novas = set()
    saem = [fita for fita in session_fita.fitas() if fita.id not in novas]
    if saem:
        # As que saem da lista perderiam a única referência que o fechamento
        # tem para devolvê-las ao estado de antes (mesmo caminho do assistente).
        session_fita.devolver_removidas(saem)

    temporario = shared.fitas_arquivo.with_name(shared.fitas_arquivo.name + ".tmp")
    try:
        shared.fitas_arquivo.parent.mkdir(parents=True, exist_ok=True)
        temporario.write_bytes(dados)
        temporario.replace(shared.fitas_arquivo)
    except OSError as erro:
        logging.warning("Não foi possível restaurar fitas.json: %s", erro)


def _rodar_na_main(funcao: Callable[[], None]) -> bool:
    """Roda ``funcao`` na thread principal e espera terminar.

    `restaurar()` roda fora dela, e o que chama daqui toca GTK: os sinais
    `changed::<chave>` do Gio.Settings, a construção de um `Game`.

    True: ``funcao`` rodou até o fim. False: o teto de espera estourou, ou
    ``funcao`` levantou exceção dentro do ``idle_add`` (que fica no log do
    GLib). Já na thread principal, a exceção sobe direto para quem chamou.
    """
    if is_main_thread():
        funcao()
        return True

    concluido = threading.Event()
    rodou = False

    def rodar() -> bool:
        nonlocal rodou
        try:
            funcao()
            rodou = True
        finally:
            concluido.set()
        return False

    GLib.idle_add(rodar)
    if not concluido.wait(timeout=30):
        # Nada aqui pode travar a thread de fundo para sempre — mesmo espírito
        # de main.py: um app fechando no momento errado nunca processa o
        # idle_add, e a thread precisa poder seguir (ou morrer) mesmo assim.
        logging.warning("Tempo esgotado esperando a thread principal no restore do backup")
        return False
    return rodou


def _aplicar_configuracoes_fora_da_main(manifesto: dict[str, Any]) -> None:
    """`aplicar_configuracoes` grava no Gio.Settings de verdade, que dispara
    sinais `changed::<chave>` — e handlers já conectados a eles
    (CartridgesWindow, GamepadManager) tocam GTK direto na resposta. Só
    seguro na thread principal. `restaurar()` roda fora dela, então isto
    marshalla e espera terminar: o resto da função depende do valor já
    restaurado de `steam-metadata`."""
    _rodar_na_main(lambda: aplicar_configuracoes(manifesto))


def restaurar(
    caminho: Path,
    progresso: Optional[Callable[[int, int], None]] = None,
    cancelado: Optional[Callable[[], bool]] = None,
    fim_da_varredura: Optional[Callable[[], None]] = None,
) -> Optional[ResultadoRestauracao]:
    """Aplica um backup ``.zip`` à biblioteca e às configurações atuais, ao
    vivo — sem fechar o app, sem criar jogo (exceto um zerado que só existe
    no backup — ver `_criar_zerado`), sem participar de import ou
    remoção. ``None``: a restauração foi cancelada antes de aplicar os jogos.
    As configurações e as fitas do backup já estão aplicadas nesse ponto; os
    jogos não.

    ``fim_da_varredura``, se passado, é chamado via ``GLib.idle_add`` assim
    que a fase cancelável (a varredura forçada de appID) termina — para quem
    chama tirar de tela um botão de cancelar que não faz mais nada depois
    disso.

    Pode (e deve, para uma biblioteca grande ou com jogos sem appID)  rodar
    fora da thread principal: cada `jogo.save()`/`jogo.update()` já vai
    marshallado (ver `_salvar_e_atualizar`), e aplicar as configurações
    também (ver `_aplicar_configuracoes_fora_da_main`) — os sinais
    `changed::<chave>` do `Gio.Settings` de verdade têm handler que toca GTK
    direto.
    """
    # Ligado durante toda a restauração: uma ligação de zerado por appID
    # (`ligacao_zerado`) rodando por baixo (import em andamento, edição
    # salva por outra janela) não pode fundir um zerado que o casamento por
    # identidade abaixo ainda vai tocar — apagaria uma tumba no meio do
    # trabalho dele.
    RESTAURANDO.set()
    try:
        manifesto = validar(caminho)

        with zipfile.ZipFile(caminho) as arquivo:
            _aplicar_fitas(arquivo)

        _aplicar_configuracoes_fora_da_main(manifesto)

        jogos_ativos = [jogo for jogo in shared.store if not jogo.removed]
        pendentes = [jogo for jogo in jogos_ativos if not jogo.steam_appid]
        if pendentes and shared.schema.get_boolean("steam-metadata"):
            if not _forcar_appids(pendentes, progresso, cancelado):
                return None
        if fim_da_varredura is not None:
            GLib.idle_add(lambda: (fim_da_varredura(), False)[1])
        # Última chance: um "Cancelar" clicado sem varredura (ou depois dela) ainda
        # chega antes de qualquer jogo ser tocado.
        if cancelado is not None and cancelado():
            return None

        grupos = _agrupar_por_identidade(jogos_ativos)
        # Tumbas entram só para as entradas de zerado, e só depois dos jogos vivos:
        # uma tumba velha com o nome de um jogo instalado não pode tornar ambíguo
        # o casamento que já funcionava. Em duas camadas, espelho do `exportar`:
        # a entrada de zerado casa primeiro com uma tumba zerada da mesma
        # identidade; uma tumba comum só entra se for a única do grupo (nunca às
        # cegas, nunca todas de uma vez).
        grupos_tumbas_zeradas = _agrupar_por_identidade(
            [jogo for jogo in shared.store if jogo.zerado]
        )
        grupos_tumbas_comuns = _agrupar_por_identidade(
            [jogo for jogo in shared.store if jogo.removed and not jogo.blacklisted and not jogo.zerado]
        )
        jogos_no_backup = manifesto.get("jogos", {})
        # Identidade de reserva: uma entrada `steam:` sem casamento tenta o nome do
        # mesmo jogo (`identidade_nome`, gravado pelo export), e uma entrada
        # `nome:` sem casamento tenta os jogos vivos cujo appID resolveu depois —
        # o inverso, pela própria chave do hash. Um jogo com entrada própria no
        # backup (a identidade real dele é uma chave de `jogos_no_backup`) nunca
        # entra nesse grupo: ele já tem para onde ir, e a entrada dele já teria
        # casado direto — um jogo assim virar reserva de OUTRA entrada roubaria o
        # dado certo (o da entrada dele) e aplicaria por cima o de uma entrada
        # órfã.
        hashes_no_backup = set(jogos_no_backup)
        grupos_por_nome = _agrupar_por_nome(
            jogo for jogo in jogos_ativos
            if _hash_identidade(identidade(jogo)) not in hashes_no_backup
        )
        casados = 0
        ambiguos: list[str] = []
        # Um jogo só recebe uma entrada por restore, mesmo vindo de duas entradas
        # de reserva diferentes que (por coincidência ou backup corrompido)
        # resolvem para o mesmo alvo.
        aplicados: set[str] = set()

        with zipfile.ZipFile(caminho) as arquivo, TemporaryDirectory() as pasta_tmp:
            tmp_dir = Path(pasta_tmp)
            for hash_id, entrada in jogos_no_backup.items():
                grupo = grupos.get(hash_id)
                if grupo is None and entrada.get("zerado") is True:
                    # Espelho do export: a entrada é feita dos zerados, então casa
                    # primeiro com os zerados. Uma tumba comum só entra se for a
                    # única daquela identidade — nunca todas, nunca às cegas.
                    grupo = grupos_tumbas_zeradas.get(hash_id)
                    if grupo is None:
                        comuns = grupos_tumbas_comuns.get(hash_id)
                        if comuns is not None and len(comuns[1]) == 1:
                            grupo = comuns
                        elif comuns is not None:
                            ambiguos.append(str(entrada.get("identidade_exibicao", hash_id)))
                            continue
                    if grupo is None:
                        if _criar_zerado(entrada, hash_id, arquivo, tmp_dir):
                            casados += 1
                        continue
                    # Vários zerados da mesma identidade recebem uma entrada só: a
                    # do mais recente, como o export fez.
                    grupo = (grupo[0], [max(grupo[1], key=lambda jogo: jogo.last_played or 0)])
                if grupo is None and (reserva := entrada.get("identidade_nome")):
                    por_nome = [j for j in grupos_por_nome.get(reserva, []) if j.game_id not in aplicados]
                    if len(por_nome) == 1:
                        grupo = ("nome", por_nome)
                    elif len(por_nome) > 1:
                        ambiguos.append(str(entrada.get("identidade_exibicao", hash_id)))
                        continue
                if grupo is None:
                    # O inverso: backup feito sem appID, jogo que ganhou appID depois.
                    por_nome = [j for j in grupos_por_nome.get(hash_id, []) if j.game_id not in aplicados]
                    if len(por_nome) == 1:
                        grupo = ("nome", por_nome)
                    elif len(por_nome) > 1:
                        ambiguos.append(str(entrada.get("identidade_exibicao", hash_id)))
                        continue
                if grupo is None:
                    continue
                tipo, alvos = grupo
                if len(alvos) > 1 and tipo == "nome":
                    ambiguos.append(str(entrada.get("identidade_exibicao", hash_id)))
                    continue
                for jogo in alvos:
                    _aplicar_jogo(jogo, entrada, hash_id, arquivo, tmp_dir)
                    aplicados.add(jogo.game_id)
                casados += 1

        if casados:
            # `status`/`rating` mudando pode mover um jogo entre a
            # biblioteca e os zerados, ou tirá-lo de um filtro ativo — as listas
            # precisam invalidar sort/filter para refletir isso. GTK, então na
            # thread principal.
            GLib.idle_add(_invalidar_listas)

        return ResultadoRestauracao(casados, len(jogos_no_backup), ambiguos)
    finally:
        RESTAURANDO.clear()


def _invalidar_listas() -> bool:
    shared.win.library.invalidate_sort()
    shared.win.zerados_library.invalidate_sort()
    shared.win.library.invalidate_filter()
    shared.win.zerados_library.invalidate_filter()
    return False


def _filtrar_chaves(chaves: Iterable[str]) -> list[str]:
    """``chaves`` sem as de sessão nem as da máquina. Extraída à parte de
    `_chaves_do_app` para poder ser testada sem um `Gio.Settings` de verdade."""
    return [
        chave
        for chave in chaves
        if chave not in _CHAVES_DE_SESSAO and chave not in _CHAVES_DA_MAQUINA
    ]


def _chaves_do_app() -> list[str]:
    return _filtrar_chaves(shared.schema.props.settings_schema.list_keys())


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


def _jogos_exportaveis(
    jogos: Iterable[Any],
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """(hash -> jogo exportado, game_id -> hash que leva as sessões dele,
    identidades vivas excluídas por colisão).

    Os da biblioteca e os zerados — o desinstalado comum não é levado. Em
    duas camadas, como no restore. Os vivos primeiro: duas cópias locais do
    mesmo jogo (mesmo appID, ou mesmo nome sem appID) não têm como decidir de
    qual delas vem a opinião — a identidade sai do backup inteira, em vez de
    chutar uma. Depois os zerados, só numa identidade que nenhum vivo ocupa,
    para nunca tornar ambíguo o jogo reinstalado que tem o mesmo appID.
    Zerados de mesma identidade (fichas duplicadas do mesmo jogo) viram uma
    entrada só: a ficha do jogado por último, as sessões de todos.
    """
    jogos = list(jogos)
    vivos = _agrupar_por_identidade(j for j in jogos if not j.removed)
    exportaveis = {chave: alvos[0] for chave, (_tipo, alvos) in vivos.items() if len(alvos) == 1}
    game_id_para_hash = {jogo.game_id: chave for chave, jogo in exportaveis.items()}

    colisoes = [
        alvos[0].name
        for _chave, (_tipo, alvos) in vivos.items()
        if len(alvos) > 1
    ]
    for nome in colisoes:
        logging.warning("%s ficou fora do backup: há mais de um jogo com essa identidade", nome)

    for chave, (_tipo, zerados) in _agrupar_por_identidade(j for j in jogos if j.zerado).items():
        if chave in vivos:
            for zerado in zerados:
                logging.warning(
                    "Zerado %r (%s) ficou fora do backup: um jogo instalado tem a mesma identidade",
                    zerado.name,
                    zerado.game_id,
                )
            continue
        # max devolve o primeiro no empate.
        exportaveis[chave] = max(zerados, key=lambda jogo: jogo.last_played)
        game_id_para_hash.update((zerado.game_id, chave) for zerado in zerados)

    return exportaveis, game_id_para_hash, colisoes


def _entrada_do_jogo(jogo: Any, sessoes: list[dict[str, int]]) -> dict[str, Any]:
    entrada: dict[str, Any] = {campo: getattr(jogo, campo) for campo in CAMPOS_OPINIAO}
    entrada["identidade_exibicao"] = jogo.steam_appid or jogo.name
    entrada["sessoes"] = sessoes

    escolha_parede = session_wallpaper.escolha(jogo)
    if escolha_parede == "manual":
        posicoes = session_wallpaper.posicoes_escolhidas(jogo.game_id)
        entrada["wallpaper_posicao_retrato"] = posicoes.retrato
        entrada["wallpaper_posicao_paisagem"] = posicoes.paisagem
    elif escolha_parede == "none":
        entrada["wallpaper_escolha"] = "none"

    if game_logo.logo_choice(jogo) == "title":
        entrada["logo_escolha"] = "title"

    if jogo.steam_appid:
        entrada["identidade_nome"] = _hash_identidade(
            f"nome:{clean_for_search(jogo.name).casefold()}"
        )

    cor = session_fita.cor_escolhida(jogo.game_id)
    if cor is not None:
        entrada["fita_matiz"] = cor.matiz
        entrada["fita_saturacao"] = cor.saturacao
        entrada["fita_brilho"] = cor.brilho

    if jogo.zerado:
        entrada["zerado"] = True
        entrada["ficha"] = {campo: getattr(jogo, campo, None) for campo in CAMPOS_FICHA}

    return entrada


def _assets_do_jogo(jogo: Any) -> list[tuple[Path, str]]:
    """Lista (caminho_no_disco, nome_no_zip) dos arquivos deste jogo.

    A capa sempre entra se existir — ao contrário de logo e papel de parede,
    ela não tem uma versão "automática" que algum processo em segundo plano
    rebusque sozinho, então não existe "escolha manual" para ela: uma vez
    definida, nada troca por conta própria. Logo e papel de parede só entram
    quando travados à mão (`logo_choice`/`escolha` == "manual") — a versão
    automática é recarregada sozinha pelo pipeline normal, não vale o espaço
    no backup. O de um zerado entra sempre: ele não passa pelo pipeline, e o
    automático não seria rebuscado."""
    assets: list[tuple[Path, str]] = []

    capa = jogo.get_cover_path()
    if capa is not None:
        assets.append((capa, f"capa{capa.suffix.lower()}"))

    if jogo.zerado or game_logo.logo_choice(jogo) == "manual":
        logo = game_logo.cached_logo_path(jogo)
        if logo is not None:
            assets.append((logo, f"logo{logo.suffix.lower()}"))

    if session_wallpaper.escolha(jogo) == "manual":
        parede = session_wallpaper.imagem_escolhida(jogo.game_id)
        if parede is not None:
            assets.append((parede, f"wallpaper{parede.suffix.lower()}"))

    return assets


def exportar(destino: Path, configuracoes: dict[str, Any]) -> list[str]:
    """Grava o backup em ``destino``. Pode rodar fora da thread principal.

    Devolve as identidades vivas excluídas por colisão (ver
    ``_jogos_exportaveis``) — lista vazia quando nenhuma ficou de fora.
    """
    exportaveis, game_id_para_hash, colisoes = _jogos_exportaveis(shared.store)

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

    return colisoes


_HASH_RE = re.compile(r"^[0-9a-f]{16}$")

# Nome base -> extensões aceitas para cada tipo de asset por jogo. Reaproveita
# as listas que cada módulo já mantém, em vez de duplicar — uma extensão nova
# aceita por `game_logo`/`save_cover`/`session_wallpaper` entra aqui sozinha,
# sem precisar lembrar de sincronizar duas listas manualmente.
_EXTENSOES_ASSET = {
    "capa": (*save_cover.ANIMATED_SUFFIXES, ".tiff"),
    "logo": game_logo.IMAGE_SUFFIXES,
    "wallpaper": session_wallpaper.IMAGE_SUFFIXES,
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


# Nenhum asset por jogo (capa/logo/parede) chega perto disso; acima disso é
# sinal de zip malicioso/corrompido, não de um backup de verdade.
_TAMANHO_MAXIMO_POR_ENTRADA = 500 * 1024 * 1024

# Soma das entradas descomprimidas. Um backup de verdade com centenas de capas
# e papéis de parede fica bem abaixo; acima disto é zip-bomba.
_TAMANHO_MAXIMO_TOTAL = 2 * 1024 * 1024 * 1024


class BackupInvalido(ValueError):
    """O arquivo não é um backup válido do Cartridges (ou está corrompido).

    Subclasse de ``ValueError`` para não quebrar quem já captura o tipo mais
    genérico; existe para que ``restaurar()`` possa distinguir "o arquivo é
    ruim" de um ``ValueError`` vindo de outro lugar do processo de
    restauração (já com configurações aplicadas), que não deve virar o
    diálogo de "Backup inválido".
    """


def validar(caminho: Path) -> dict[str, Any]:
    """O manifesto de um backup por jogo. ``BackupInvalido`` se não for um."""
    try:
        with zipfile.ZipFile(caminho) as arquivo:
            total = 0
            for info in arquivo.infolist():
                if not _nome_valido(info.filename):
                    raise BackupInvalido(f"entrada inesperada no backup: {info.filename}")
                if info.file_size > _TAMANHO_MAXIMO_POR_ENTRADA:
                    raise BackupInvalido(f"entrada grande demais no backup: {info.filename}")
                total += info.file_size
                if total > _TAMANHO_MAXIMO_TOTAL:
                    raise BackupInvalido("backup grande demais")
            # O CRC de cada entrada, e não só o do manifesto: um byte trocado
            # numa capa passaria daqui e só estouraria no meio da restauração.
            if (corrompida := arquivo.testzip()) is not None:
                raise BackupInvalido(f"entrada corrompida no backup: {corrompida}")
            manifesto = json.loads(arquivo.read(_MANIFESTO).decode("utf-8"))
    except BackupInvalido:
        raise
    except Exception as erro:  # pylint: disable=broad-exception-caught
        raise BackupInvalido(str(erro)) from erro

    if not isinstance(manifesto, dict) or manifesto.get("version") != VERSAO:
        raise BackupInvalido("o arquivo não é um backup desta versão")
    if not isinstance(manifesto.get("jogos"), dict):
        raise BackupInvalido("backup sem o bloco de jogos")
    if not isinstance(manifesto.get("settings"), dict):
        raise BackupInvalido("backup sem o bloco de configurações")

    for entrada in manifesto["jogos"].values():
        if not isinstance(entrada, dict):
            raise BackupInvalido("entrada de jogo inválida no backup")
        if "sessoes" in entrada and not isinstance(entrada["sessoes"], list):
            raise BackupInvalido("sessões inválidas no backup")

    return manifesto
