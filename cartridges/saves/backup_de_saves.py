"""O backup e a restauração dos saves, jogo a jogo, em segundo plano.

É o que a interface chama: o fim de uma sessão dispara o backup, o menu do jogo
lista as versões e restaura uma, as Preferências restauram todas e trocam a pasta.
Cada operação roda numa thread, aparece como tarefa na janela de tarefas e só
fala com o usuário quando falha (um aviso); sucesso é silencioso.

Uma trava única cobre gravar o `config.yaml` e rodar o Ludusavi: duas sessões que
terminam em sequência esperam uma pela outra, e a troca da pasta dos saves nunca
acontece no meio de um backup. O config de cada chamada leva todos os jogos da
biblioteca que já têm nome no Ludusavi, para que o `restore` de qualquer um ache a
sua entrada.
"""

import logging
import subprocess
import threading
from pathlib import Path
from typing import Optional

from gi.repository import Adw

from cartridges import shared
from cartridges.game import Game
from cartridges.saves import config, ludusavi, pasta
from cartridges.saves.ludusavi import LudusaviFalhou, Versao
from cartridges.utils import tarefas
from cartridges.utils.na_tela import entregar_na_tela

# Os testes trocam por um executor falso; é o que `ludusavi.rodar` recebe.
executor = subprocess.run

_trava = threading.Lock()
# Nome no Ludusavi -> versões, da mais nova para a mais velha. Lido pela tela
# (`tem_backup`) sem esperar a trava: a tela nunca fica parada atrás de um backup.
_cache: dict[str, list[Versao]] = {}


def disponivel() -> bool:
    return ludusavi.executavel() is not None


def _pasta_config() -> Path:
    return shared.app_dir / "ludusavi"


def _biblioteca() -> list[Game]:
    """Os jogos da biblioteca. Quem chama na thread da tela tira o instantâneo antes de
    abrir a thread de trabalho, que então só lê atributos; o store itera sobre uma
    cópia protegida por trava, então chamar de outra thread também é seguro."""
    return [jogo for jogo in shared.store if not jogo.removed and not jogo.blacklisted]


def _em_segundo_plano(alvo, *argumentos) -> None:
    threading.Thread(target=alvo, args=argumentos, daemon=True).start()


def _no_config(game: Game, no_manifesto: bool = True) -> config.JogoNoConfig:
    # Todo nome guardado vai como "extend". O Ludusavi 0.31 trata "extend" de um nome
    # que o manifesto não conhece como uma entrada própria (conferido), e se o manifesto
    # ganhar esse nome mais tarde, juntar os caminhos dele é o desejado. Por isso o
    # config não precisa lembrar se o nome veio do manifesto ou foi criado aqui.
    return config.JogoNoConfig(game.ludusavi_nome, game.steam_appid, game.executable, no_manifesto)


def _preparar(biblioteca: list[Game], atual: Optional[config.JogoNoConfig] = None) -> None:
    """Grava o `config.yaml` desta chamada. Sempre sob a trava."""
    escolhida = pasta.atual()
    # Uma pasta configurada que sumiu (disco externo, OneDrive desconectado) não
    # pode virar uma pasta nova e vazia: os backups antigos ficariam para trás sem aviso.
    if escolhida != pasta.padrao() and not escolhida.is_dir():
        raise LudusaviFalhou(f"a pasta dos saves não existe: {escolhida}")
    # Por nome: o mesmo jogo em duas lojas tem um nome só no Ludusavi.
    jogos = {jogo.ludusavi_nome: _no_config(jogo) for jogo in biblioteca if jogo.ludusavi_nome}
    if atual is not None:
        jogos[atual.nome] = atual
    lista = list(jogos.values())
    config.gravar(config.montar(lista, escolhida, config.raizes(lista)), _pasta_config())


def _ler_versoes(biblioteca: list[Game]) -> bool:
    """Relê as versões de todos os jogos. Sob a trava. Diz se conseguiu; falhar deixa
    o cache como estava."""
    global _cache  # noqa: PLW0603
    try:
        _preparar(biblioteca)
        _cache = ludusavi.versoes(_pasta_config(), executor)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.exception("Não foi possível ler os backups dos saves")
        return False
    return True


def _mostrar_aviso(texto: str) -> bool:
    toast = Adw.Toast.new(texto)
    # O nome do jogo está no texto, e o Adw.Toast lê o título como markup por padrão.
    toast.set_use_markup(False)
    if shared.win is not None:
        shared.win.toast_queue.add(toast)
    return False


def _avisar(texto: str) -> None:
    entregar_na_tela(_mostrar_aviso, texto)


def _salvar(game: Game) -> bool:
    game.save()
    return False


def _resolver(game: Game) -> Optional[config.JogoNoConfig]:
    """O jogo como o Ludusavi o conhece, ou None se não há como backupear. Sob a trava.

    A primeira vez procura o nome no manifesto (pelo appID, depois pelo título) e
    guarda; as seguintes usam o guardado. Com appID e sem entrada no manifesto, o
    jogo ganha uma entrada própria com o nome dele.
    """
    if game.ludusavi_nome:
        return _no_config(game)
    pasta_config = _pasta_config()
    nome = None
    if game.steam_appid:
        nome = ludusavi.nome_por_appid(game.steam_appid, pasta_config, executor)
    if nome is None:
        nome = ludusavi.nome_por_titulo(game.name, pasta_config, executor)
    if nome is not None:
        jogo = config.JogoNoConfig(nome, game.steam_appid, game.executable, True)
    elif game.steam_appid:
        jogo = config.JogoNoConfig(game.name, game.steam_appid, game.executable, False)
    else:
        return None  # sem appID e fora do manifesto não há o que copiar
    game.ludusavi_nome = jogo.nome
    entregar_na_tela(_salvar, game)
    return jogo


# -- backup ------------------------------------------------------------------


def no_fim_da_sessao(game: Game) -> None:
    """Dispara o backup do jogo e volta na hora."""
    if disponivel():
        _em_segundo_plano(_backup, game, _biblioteca())


def _backup(game: Game, biblioteca: list[Game]) -> None:
    tarefa = None
    with _trava:
        try:
            jogo = _resolver(game)
            if jogo is None:
                return
            tarefa = tarefas.comecar(_("Backup dos saves de {}").format(game.name), 1)
            _preparar(biblioteca, jogo)
            ludusavi.fazer_backup(jogo.nome, _pasta_config(), executor)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Backup dos saves de %s falhou", game.name)
            _avisar(_("Não foi possível fazer o backup dos saves de {}.").format(game.name))
        else:
            _ler_versoes(biblioteca)
        finally:
            if tarefa is not None:
                tarefa.terminar()


# -- versões -----------------------------------------------------------------


def tem_backup(game: Game) -> bool:
    return bool(_cache.get(game.ludusavi_nome))


def versoes_do_jogo(game: Game) -> list[Versao]:
    return list(_cache.get(game.ludusavi_nome, []))


def atualizar_cache() -> None:
    if disponivel():
        _em_segundo_plano(_atualizar_cache, _biblioteca())


def _atualizar_cache(biblioteca: list[Game]) -> None:
    with _trava:
        _ler_versoes(biblioteca)


# -- restauração -------------------------------------------------------------


def restaurar(game: Game, versao: Optional[str]) -> None:
    """Devolve os saves do jogo; sem ``versao``, os da mais recente."""
    if disponivel() and game.ludusavi_nome:
        _em_segundo_plano(_restaurar, game, versao, _biblioteca())


def _restaurar(game: Game, versao: Optional[str], biblioteca: list[Game]) -> None:
    with _trava:
        tarefa = tarefas.comecar(_("Restaurando o save de {}").format(game.name), 1)
        try:
            _preparar(biblioteca, _no_config(game))
            ludusavi.restaurar(game.ludusavi_nome, _pasta_config(), versao, executor)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Restauração do save de %s falhou", game.name)
            _avisar(_("Não foi possível restaurar o save de {}.").format(game.name))
        else:
            _ler_versoes(biblioteca)
        finally:
            tarefa.terminar()


def restaurar_todos() -> None:
    """Restaura a versão mais recente de cada jogo da biblioteca que tem backup."""
    if disponivel():
        _em_segundo_plano(_restaurar_todos, _biblioteca())


def _restaurar_todos(biblioteca: list[Game]) -> None:
    with _trava:
        # O cache pode estar vazio (nada o encheu ainda) ou velho: relê antes. Sem
        # conseguir ler, não há como saber o que restaurar, e o usuário precisa saber.
        if not _ler_versoes(biblioteca):
            _avisar(_("Não foi possível restaurar os saves."))
            return
        jogos = {jogo.ludusavi_nome: jogo for jogo in biblioteca if jogo.ludusavi_nome}
        alvos = [nome for nome in jogos if _cache.get(nome)]
        if not alvos:
            return
        tarefa = tarefas.comecar(_("Restaurando os saves"), len(alvos))
        try:
            _preparar(biblioteca)
            for feitos, nome in enumerate(alvos):
                tarefa.atualizar(feitos)
                try:
                    ludusavi.restaurar(nome, _pasta_config(), None, executor)
                except Exception:  # pylint: disable=broad-exception-caught
                    logging.exception("Restauração do save de %s falhou", jogos[nome].name)
                    _avisar(_("Não foi possível restaurar o save de {}.").format(jogos[nome].name))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Restauração dos saves falhou")
            _avisar(_("Não foi possível restaurar os saves."))
        finally:
            tarefa.terminar()
        _ler_versoes(biblioteca)


# -- pasta dos saves ---------------------------------------------------------


def trocar_pasta(nova: Path) -> None:
    """Troca a pasta dos saves sem que um backup ou restauração esteja rodando.

    Espera a trava, então quem chama (as Preferências) deve fazê-lo fora da thread
    da tela. Levanta `pasta.TrocaRecusada`, sem mexer em nada, se a troca não vale.
    """
    with _trava:
        pasta.trocar(nova)
    atualizar_cache()
