"""O vigia da sessão: percebe, durante a partida, as conquistas que acabaram de sair.

O jeito é o do Hydra (`achievement-watcher-manager.ts`): de tempos em tempos,
olhar o `mtime` de cada arquivo de conquista e reler só o que mudou. Aqui o
vigia só existe enquanto a sessão de um jogo aberto pelo Cartridges está
aberta, e o que já estava nos arquivos quando a sessão começou entra no
histórico em silêncio — é a base, não novidade.

Roda na thread principal (`GLib.timeout_add_seconds`), como manda o histórico:
cada olhada é um punhado de `stat`, e a releitura é de arquivos pequenos. Um
arquivo pode aparecer no meio da partida (a primeira conquista de um jogo
novo), então a lista de arquivos é refeita a cada `REBUSCA` olhadas.

Fase 2: só jogos que não são da Steam. Os da Steam ficam para a fase 3.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

from gi.repository import GLib

from cartridges.conquistas import arquivos, catalogo, formatos, historico, progresso
from cartridges.conquistas.arquivos import ArquivoDeConquista
from cartridges.conquistas.catalogo import ConquistaInfo

INTERVALO = 2
REBUSCA = 15


@dataclass(frozen=True)
class Desbloqueada:
    """Uma conquista que acabou de sair, pronta para o aviso."""

    nome: str
    # None quando o jogo não tem catálogo: sem nome nem ícone para mostrar.
    info: Optional[ConquistaInfo]
    # Se foi a que fechou 100% do jogo.
    completou: bool


def acompanha(game: Any) -> bool:
    """Se o vigia acompanha este jogo nesta fase."""
    return (
        arquivos.appid_valido(getattr(game, "steam_appid", None))
        and bool(getattr(game, "conquistas", True))
        and not arquivos.eh_jogo_da_steam(getattr(game, "executable", "") or "")
    )


def _mtime(caminho: Any) -> Optional[int]:
    try:
        return os.stat(caminho).st_mtime_ns
    except OSError:
        return None


class Vigia:
    def __init__(self, game: Any, avisar: Callable[[list[Desbloqueada]], None]) -> None:
        self.game = game
        self._avisar = avisar
        self._arquivos: list[ArquivoDeConquista] = []
        self._mtimes: dict[str, Optional[int]] = {}
        self._fonte = 0
        self._olhadas = 0

    @property
    def ativo(self) -> bool:
        return bool(self._fonte)

    def iniciar(self) -> None:
        if self._fonte or not acompanha(self.game):
            return
        try:
            achados = self._achar()
            for achado in achados:
                self._mtimes[str(achado.caminho)] = _mtime(achado.caminho)
            self._arquivos = achados
            # A base: o que já está nos arquivos entra em silêncio.
            historico.registrar(self.game.game_id, self._ler(achados))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao preparar o vigia de %s", self.game.name, exc_info=True)
        self._fonte = GLib.timeout_add_seconds(INTERVALO, self._olhar)

    def parar(self) -> None:
        if self._fonte:
            GLib.source_remove(self._fonte)
            self._fonte = 0

    def _achar(self) -> list[ArquivoDeConquista]:
        return arquivos.arquivos_do_jogo(str(self.game.steam_appid), self.game.executable)

    @staticmethod
    def _ler(lista: list[ArquivoDeConquista]) -> list[formatos.Desbloqueio]:
        return [d for achado in lista for d in formatos.ler(achado.caminho, achado.formato)]

    def _olhar(self) -> bool:
        """Um tique. Sempre devolve True: o timer só para em `parar`."""
        try:
            self._olhadas += 1
            mudaram: list[ArquivoDeConquista] = []
            if self._olhadas % REBUSCA == 0:
                conhecidos = {str(a.caminho) for a in self._arquivos}
                for achado in self._achar():
                    if str(achado.caminho) not in conhecidos:
                        # Arquivo novo: tudo o que ele traz é desta partida.
                        self._arquivos.append(achado)
                        self._mtimes[str(achado.caminho)] = _mtime(achado.caminho)
                        mudaram.append(achado)
            for achado in self._arquivos:
                chave = str(achado.caminho)
                atual = _mtime(achado.caminho)
                if atual is not None and atual != self._mtimes.get(chave) and achado not in mudaram:
                    mudaram.append(achado)
                self._mtimes[chave] = atual
            if mudaram:
                self._processar(mudaram)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning(
                "Falha ao acompanhar as conquistas de %s", self.game.name, exc_info=True
            )
        return True

    def _processar(self, mudaram: list[ArquivoDeConquista]) -> None:
        lidos = self._ler(mudaram)
        entraram, primeira = historico.registrar(self.game.game_id, lidos)
        if primeira or not entraram:
            return
        cat = catalogo.em_cache(str(self.game.steam_appid))
        por_nome = cat.por_nome() if cat is not None else {}
        atual = progresso.do_jogo(self.game)
        completo = bool(atual is not None and atual.completo)
        horas = {d.nome.strip().upper(): d.quando for d in lidos}
        ordem = sorted(entraram, key=lambda nome: horas.get(nome, 0))
        self._avisar(
            [
                Desbloqueada(nome, por_nome.get(nome), completo and indice == len(ordem) - 1)
                for indice, nome in enumerate(ordem)
            ]
        )
