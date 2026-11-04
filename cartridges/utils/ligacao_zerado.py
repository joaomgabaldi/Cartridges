# ligacao_zerado.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Liga um jogo de Jogos Zerados ao jogo da biblioteca que tem o mesmo appID.

Um zerado recriado pelo backup (ou reinstalado de outra pasta) não casa com o atalho novo, e a página
ficaria com as duas versões. Quando o jogo da biblioteca ganha o appID da Steam, os dados do zerado passam
para ele e o zerado sai.

Liga só sem dúvida: exatamente um zerado e um jogo da biblioteca com aquele appID; o resto fica como está,
com uma linha no log.
"""

import logging

from cartridges import shared
from cartridges.conquistas import historico
from cartridges.jogo import Jogo
from cartridges.utils.thread_principal import eh_thread_principal, na_thread_principal
from cartridges.utils import game_logo, session_fita, session_log, session_wallpaper
from cartridges.utils.save_cover import save_cover


def agendar(jogo: Jogo) -> None:
    """Pede a ligação na thread principal; seguro de qualquer thread."""
    na_thread_principal(ligar_zerado, jogo)


def _vazio(valor) -> bool:
    return valor in (None, "", 0) or (isinstance(valor, str) and not valor.strip())


def _mover_capa(zerado: Jogo, jogo: Jogo) -> None:
    # Pela troca de capa normal: invalida as cópias animadas da capa anterior (o nome delas é só o id).
    origem = zerado.get_cover_path()
    if origem is not None:
        save_cover(jogo.game_id, origem)


def _mover_escolhas(zerado: Jogo, jogo: Jogo) -> None:
    """Leva a escolha manual do zerado, só se o jogo não tiver uma própria.

    Escolha própria é qualquer decisão travada, não só um arquivo (logo "title", parede "none");
    só ``"auto"`` conta como vazio.
    """
    if game_logo.logo_choice(zerado) == "manual" and game_logo.logo_choice(jogo) == "auto":
        if (logo := game_logo.cached_logo_path(zerado)) is not None:
            game_logo.save_manual_logo(jogo.game_id, jogo.name, logo)
    if (
        session_wallpaper.escolha(zerado) == "manual"
        and session_wallpaper.escolha(jogo) == "auto"
        and (parede := session_wallpaper.imagem_escolhida(zerado.game_id)) is not None
    ):
        session_wallpaper.salvar_escolha(
            jogo.game_id, jogo.name, parede,
            session_wallpaper.posicoes_escolhidas(zerado.game_id),
        )
    if (cor := session_fita.cor_escolhida(zerado.game_id)) is not None and not (
        session_fita.escolhida(jogo.game_id)
    ):
        session_fita.salvar_cor(jogo.game_id, jogo.name, cor)
    elif (
        (brilho := session_fita.brilho_escolhido(zerado.game_id)) is not None
        and session_fita.brilho_gravado(jogo.game_id) is None
    ):
        # O brilho próprio também é escolha do zerado, e o arquivo dele vai embora com a ligação.
        session_fita.salvar_brilho(jogo.game_id, jogo.name, brilho)


def ligar_zerado(jogo: Jogo) -> bool:
    """Liga ``jogo`` ao zerado de mesmo appID. True: ligou."""
    assert eh_thread_principal(), "ligar_zerado toca a store e a fila de avisos"
    appid = getattr(jogo, "steam_appid", None)
    if not appid or jogo.removed or jogo.blacklisted:
        return False

    zerados = [g for g in shared.store if g.zerado and g.steam_appid == appid]
    vivos = [
        g for g in shared.store
        if not g.removed and not g.blacklisted and g.steam_appid == appid
    ]
    if len(zerados) != 1 or vivos != [jogo]:
        logging.info(
            "Sem ligação de zerado para o appID %s: %d zerado(s), %d jogo(s) na biblioteca",
            appid, len(zerados), len(vivos),
        )
        return False
    zerado = zerados[0]

    jogo.playtime = (jogo.playtime or 0) + (zerado.playtime or 0)
    jogo.last_played = max(jogo.last_played or 0, zerado.last_played or 0)
    for campo in ("status", "rating", "notes"):
        if _vazio(getattr(jogo, campo, None)) and not _vazio(getattr(zerado, campo, None)):
            setattr(jogo, campo, getattr(zerado, campo))

    session_log.mover_jogo(zerado.game_id, jogo.game_id)
    # As conquistas são do mesmo jogo (mesmo appID); o arquivo do zerado vai embora com o Excluir abaixo.
    historico.transferir(zerado.game_id, jogo.game_id)
    try:
        _mover_capa(zerado, jogo)
        _mover_escolhas(zerado, jogo)
    except OSError as erro:
        # Capa e escolhas se refazem; o tempo e as sessões não.
        logging.warning("Ligação de %s: arquivos não copiados: %s", jogo.name, erro)

    # Salva antes de excluir: se `cleanup_game` falhar (PermissionError no Windows), só o zerado fica para trás.
    jogo.save()
    jogo.update()

    # O `jogo_excluido` da store fecha a página de detalhes do zerado; aberta, uma ação ali reviveria o arquivo apagado.
    shared.store.excluir(zerado, apagar_sessoes=False)

    if shared.aplicativo is not None:
        # Texto puro: a fila de avisos não interpreta markup.
        shared.aplicativo.avisos.adicionar(
            _("Os dados de {} em Jogos Zerados foram transferidos para a biblioteca").format(
                jogo.name
            )
        )
    return True
