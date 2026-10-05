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

Nos jogos da Steam, o estado vem do `UserGameStats` que a própria Steam grava
no instante do desbloqueio. Ela cria esse arquivo ao abrir o jogo, já com as
conquistas antigas: por isso ele é conhecido desde o início da sessão, e
quando aparece entra em silêncio, como a base.

Tudo o que o vigia lê vem de arquivos de emulador ou da Steam, então quando lê
algo num jogo sem fonte gravada ele grava a fonte `steam:<appid>`: um emulador
que aparece no meio da partida dá fonte ao jogo sem esperar a varredura. Uma
fonte já gravada nunca é trocada por ele.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from gi.repository import GLib

from cartridges.conquistas import arquivos, catalogo, formatos, fontes, historico, progresso
from cartridges.conquistas.arquivos import ArquivoDeConquista
from cartridges.conquistas.catalogo import ConquistaInfo

INTERVALO = 2
REBUSCA = 15
# Falhas seguidas de um arquivo antes de ele passar a ser tentado só a cada rebusca.
TENTATIVAS = 3
# Nos jogos da Steam, conquista com hora anterior ao início da sessão por mais
# que isto (o relógio do PC e o da Steam podem diferir) veio de outro aparelho.
MARGEM_DA_STEAM = 5 * 60


@dataclass(frozen=True)
class Desbloqueada:
    """Uma conquista que acabou de sair, pronta para o aviso."""

    nome: str
    # None quando o jogo não tem catálogo: sem nome nem ícone para mostrar.
    info: Optional[ConquistaInfo]
    # Se foi a que fechou 100% do jogo.
    completou: bool


def acompanha(game: Any) -> bool:
    """Se o vigia de arquivos acompanha este jogo: appID válido e conquistas ligadas.

    Jogo do Xbox/Game Pass (o executável é um AUMID) fica de fora: ele é do vigia
    da conta, e um arquivo velho de emulador com o mesmo appID não o faz da Steam.
    Só o texto do executável é olhado, nunca o disco.
    """
    return (
        arquivos.appid_valido(getattr(game, "steam_appid", None))
        and bool(getattr(game, "conquistas", True))
        and fontes.pfn(game) is None
    )


def _mtime(caminho: Any) -> Optional[int]:
    try:
        return os.stat(caminho).st_mtime_ns
    except OSError:
        return None


class Vigia:
    def __init__(
        self,
        game: Any,
        avisar: Callable[[list[Desbloqueada]], None],
        relogio: Callable[[], float] = time.time,
    ) -> None:
        self.game = game
        self._avisar = avisar
        self._relogio = relogio
        # A hora em que a sessão começou; None antes de `iniciar`.
        self._inicio: Optional[float] = None
        self._arquivos: list[ArquivoDeConquista] = []
        # O mtime de cada arquivo na última leitura que foi guardada com sucesso.
        self._mtimes: dict[str, Optional[int]] = {}
        # Arquivos cuja base ainda não foi lida: lidos em silêncio até dar certo.
        self._pendentes: set[str] = set()
        # Arquivos da Steam conhecidos antes de existirem (`arquivos.da_steam_esperados`):
        # quando aparecem, entram em silêncio.
        self._esperados: set[str] = set()
        # Falhas seguidas por arquivo (leitura ou gravação). Passando de
        # `TENTATIVAS`, o arquivo só é tentado de novo a cada rebusca.
        self._falhas: dict[str, int] = {}
        self._fonte = 0
        self._olhadas = 0

    @property
    def ativo(self) -> bool:
        return bool(self._fonte)

    def iniciar(self) -> None:
        if self._fonte or not acompanha(self.game):
            return
        self._inicio = self._relogio()
        try:
            self._arquivos = self._achar()
            esperados = arquivos.da_steam_esperados(
                str(self.game.steam_appid), self.game.executable
            )
            self._esperados = {str(a.caminho) for a in esperados}
            conhecidos = {str(a.caminho) for a in self._arquivos}
            self._arquivos.extend(a for a in esperados if str(a.caminho) not in conhecidos)
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

    def _desistiu(self, chave: str, rebusca: bool) -> bool:
        """Se o arquivo falhou vezes demais para ser tentado neste tique."""
        return self._falhas.get(chave, 0) >= TENTATIVAS and not rebusca

    def _resultado(self, chave: str, deu_certo: bool) -> None:
        if deu_certo:
            self._falhas.pop(chave, None)
        else:
            self._falhas[chave] = self._falhas.get(chave, 0) + 1

    def _registrar(self, lidos: list[formatos.Desbloqueio]) -> tuple[list[str], bool]:
        """Grava ``lidos`` no histórico; com algo lido e o jogo sem fonte, grava a Steam."""
        fonte = None
        if lidos and historico.fonte(self.game.game_id) is None:
            fonte = f"steam:{self.game.steam_appid}"
        return historico.registrar(self.game.game_id, lidos, fonte=fonte)

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
            if atual is None and str(achado.caminho) in self._esperados:
                # Ainda não existe: quando a Steam o criar, entra em silêncio.
                self._pendentes.add(str(achado.caminho))
                continue
            lidos = formatos.ler_ou_none(achado.caminho, achado.formato)
            if lidos is None:
                self._pendentes.add(str(achado.caminho))
            else:
                lidos_por_arquivo.append((achado, atual, lidos))
        self._registrar([d for _a, _m, lidos in lidos_por_arquivo for d in lidos])
        for achado, atual, lidos in lidos_por_arquivo:
            if self._gravados(lidos):
                self._mtimes[str(achado.caminho)] = atual
            else:
                self._pendentes.add(str(achado.caminho))

    def _retomar_base(self, achado: ArquivoDeConquista, atual: Optional[int]) -> None:
        """Nova tentativa de ler, em silêncio, um arquivo que ficou sem base."""
        chave = str(achado.caminho)
        if atual is None:
            if chave in self._esperados:
                self._falhas.pop(chave, None)
                return  # a Steam ainda não criou o arquivo; continua pendente
            self._pendentes.discard(chave)
            self._falhas.pop(chave, None)
            self._mtimes[chave] = None
            return
        lidos = formatos.ler_ou_none(achado.caminho, achado.formato)
        if lidos is None:
            self._resultado(chave, False)
            return
        self._registrar(lidos)
        gravados = self._gravados(lidos)
        self._resultado(chave, gravados)
        if gravados:
            self._pendentes.discard(chave)
            self._mtimes[chave] = atual

    def _olhar(self) -> bool:
        """Um tique. Sempre devolve True: o timer só para em `parar`."""
        try:
            self._olhadas += 1
            rebusca = self._olhadas % REBUSCA == 0
            if rebusca:
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
                    # Ausente não faz E/S: `_retomar_base` zera as falhas já neste
                    # tique, em vez de esperar a rebusca (30 s) para o arquivo que
                    # volta ser lido.
                    if atual is None or not self._desistiu(chave, rebusca):
                        self._retomar_base(achado, atual)
                elif atual is None:
                    self._falhas.pop(chave, None)
                    self._mtimes[chave] = None
                elif atual != self._mtimes.get(chave) and not self._desistiu(chave, rebusca):
                    lidos = formatos.ler_ou_none(achado.caminho, achado.formato)
                    # Leitura que falhou: o mtime antigo fica, e o próximo tique tenta de novo.
                    if lidos is None:
                        self._resultado(chave, False)
                    else:
                        # O sucesso só vale quando a gravação também der certo (`_processar`).
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
        try:
            entraram, primeira = self._registrar(lidos)
        except Exception:
            for achado, _atual, _lidos in mudaram:
                self._resultado(str(achado.caminho), False)
            raise
        # Só vale como visto o arquivo cujo conteúdo foi mesmo guardado; o resto
        # volta no próximo tique.
        for achado, atual, lidos_do_arquivo in mudaram:
            chave = str(achado.caminho)
            gravados = self._gravados(lidos_do_arquivo)
            self._resultado(chave, gravados)
            if gravados:
                self._mtimes[chave] = atual
        if primeira or not entraram:
            return
        cat = catalogo.em_cache(self._chave_do_catalogo())
        por_nome = cat.por_nome() if cat is not None else {}
        depois = progresso.do_jogo(self.game)
        completou = bool(
            depois is not None
            and depois.completo
            and not (antes is not None and antes.completo)
        )
        horas = {d.nome.strip().upper(): d.quando for d in lidos}
        ordem = sorted(entraram, key=lambda nome: horas.get(nome, 0))
        limite = self._limite_da_steam()
        # Conquista antiga que a Steam acabou de sincronizar entra no histórico, mas não é aviso.
        avisaveis = [
            nome for nome in ordem if limite is None or not 0 < horas.get(nome, 0) < limite
        ]
        if not avisaveis:
            return
        # O 100% é da última conquista do catálogo, nunca de um nome que ele não conhece.
        ultima = next((nome for nome in reversed(avisaveis) if nome in por_nome), None)
        self._avisar(
            [
                Desbloqueada(nome, por_nome.get(nome), completou and nome == ultima)
                for nome in avisaveis
            ]
        )

    def _chave_do_catalogo(self) -> str:
        """A chave do catálogo da fonte gravada, a mesma que `progresso.do_jogo` usa.

        Assim os títulos e o `completou` saem do mesmo catálogo. Sem fonte
        gravada, o appID do jogo.
        """
        fonte = fontes.gravada(self.game)
        return fontes.chave_do_catalogo(fonte) if fonte is not None else str(self.game.steam_appid)

    def _limite_da_steam(self) -> Optional[float]:
        """A hora abaixo da qual uma conquista da Steam não é desta sessão.

        Ao abrir o jogo a Steam baixa do servidor o que foi ganho em outro
        aparelho e regrava o arquivo: essas conquistas têm horas antigas. Só vale
        para jogos da Steam; a hora dos emuladores é menos confiável.
        """
        if self._inicio is None or not arquivos.eh_jogo_da_steam(self.game.executable):
            return None
        return self._inicio - MARGEM_DA_STEAM
