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
        # O mtime de cada arquivo na última leitura que foi guardada com sucesso.
        self._mtimes: dict[str, Optional[int]] = {}
        # Arquivos cuja base ainda não foi lida: lidos em silêncio até dar certo.
        self._pendentes: set[str] = set()
        self._fonte = 0
        self._olhadas = 0

    @property
    def ativo(self) -> bool:
        return bool(self._fonte)

    def iniciar(self) -> None:
        if self._fonte or not acompanha(self.game):
            return
        try:
            self._arquivos = self._achar()
            self._base()
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao preparar o vigia de %s", self.game.name, exc_info=True)
            # O que não chegou a entrar na base não pode virar aviso depois.
            self._pendentes.update(
                str(a.caminho) for a in self._arquivos if str(a.caminho) not in self._mtimes
            )
        self._fonte = GLib.timeout_add_seconds(INTERVALO, self._olhar)

    def parar(self) -> None:
        if self._fonte:
            GLib.source_remove(self._fonte)
            self._fonte = 0

    def _achar(self) -> list[ArquivoDeConquista]:
        return arquivos.arquivos_do_jogo(str(self.game.steam_appid), self.game.executable)

    def _gravados(self, lidos: list[formatos.Desbloqueio]) -> bool:
        """Se tudo o que foi lido já está no histórico (ele só soma)."""
        guardado = historico.ler(self.game.game_id)
        if guardado is None:
            return not lidos
        return all(d.nome.strip().upper() in guardado for d in lidos)

    def _base(self) -> None:
        """O que já está nos arquivos entra no histórico em silêncio.

        Arquivo que não pôde ser lido agora fica pendente: continua em silêncio
        até uma leitura dar certo, para o que ele já tinha não virar aviso.
        """
        lidos_por_arquivo: list[tuple[ArquivoDeConquista, Optional[int], list]] = []
        for achado in self._arquivos:
            atual = _mtime(achado.caminho)
            lidos = formatos.ler_ou_none(achado.caminho, achado.formato)
            if lidos is None:
                self._pendentes.add(str(achado.caminho))
            else:
                lidos_por_arquivo.append((achado, atual, lidos))
        historico.registrar(
            self.game.game_id, [d for _a, _m, lidos in lidos_por_arquivo for d in lidos]
        )
        for achado, atual, lidos in lidos_por_arquivo:
            if self._gravados(lidos):
                self._mtimes[str(achado.caminho)] = atual
            else:
                self._pendentes.add(str(achado.caminho))

    def _retomar_base(self, achado: ArquivoDeConquista, atual: Optional[int]) -> None:
        """Nova tentativa de ler, em silêncio, um arquivo que ficou sem base."""
        chave = str(achado.caminho)
        if atual is None:
            self._pendentes.discard(chave)
            self._mtimes[chave] = None
            return
        lidos = formatos.ler_ou_none(achado.caminho, achado.formato)
        if lidos is None:
            return
        historico.registrar(self.game.game_id, lidos)
        if self._gravados(lidos):
            self._pendentes.discard(chave)
            self._mtimes[chave] = atual

    def _olhar(self) -> bool:
        """Um tique. Sempre devolve True: o timer só para em `parar`."""
        try:
            self._olhadas += 1
            if self._olhadas % REBUSCA == 0:
                conhecidos = {str(a.caminho) for a in self._arquivos}
                # Arquivo novo: sem mtime guardado, tudo o que ele traz é desta partida.
                self._arquivos.extend(
                    a for a in self._achar() if str(a.caminho) not in conhecidos
                )
            mudaram: list[tuple[ArquivoDeConquista, int, list]] = []
            for achado in self._arquivos:
                chave = str(achado.caminho)
                atual = _mtime(achado.caminho)
                if chave in self._pendentes:
                    self._retomar_base(achado, atual)
                elif atual is None:
                    self._mtimes[chave] = None
                elif atual != self._mtimes.get(chave):
                    lidos = formatos.ler_ou_none(achado.caminho, achado.formato)
                    # Leitura que falhou: o mtime antigo fica, e o próximo tique tenta de novo.
                    if lidos is not None:
                        mudaram.append((achado, atual, lidos))
            if mudaram:
                self._processar(mudaram)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning(
                "Falha ao acompanhar as conquistas de %s", self.game.name, exc_info=True
            )
        return True

    def _processar(self, mudaram: list[tuple[ArquivoDeConquista, int, list]]) -> None:
        lidos = [d for _a, _m, lidos_do_arquivo in mudaram for d in lidos_do_arquivo]
        antes = progresso.do_jogo(self.game)
        entraram, primeira = historico.registrar(self.game.game_id, lidos)
        # Só vale como visto o arquivo cujo conteúdo foi mesmo guardado; o resto
        # volta no próximo tique.
        for achado, atual, lidos_do_arquivo in mudaram:
            if self._gravados(lidos_do_arquivo):
                self._mtimes[str(achado.caminho)] = atual
        if primeira or not entraram:
            return
        cat = catalogo.em_cache(str(self.game.steam_appid))
        por_nome = cat.por_nome() if cat is not None else {}
        depois = progresso.do_jogo(self.game)
        completou = bool(
            depois is not None
            and depois.completo
            and not (antes is not None and antes.completo)
        )
        horas = {d.nome.strip().upper(): d.quando for d in lidos}
        ordem = sorted(entraram, key=lambda nome: horas.get(nome, 0))
        # O 100% é da última conquista do catálogo, nunca de um nome que ele não conhece.
        ultima = next((nome for nome in reversed(ordem) if nome in por_nome), None)
        self._avisar(
            [Desbloqueada(nome, por_nome.get(nome), completou and nome == ultima) for nome in ordem]
        )
