"""O vigia da sessão: percebe, durante a partida, as conquistas que acabaram de sair.

Como no Hydra (`achievement-watcher-manager.ts`): olha de tempos em tempos o `mtime` de cada arquivo de conquista e relê só o que mudou. Só existe enquanto a sessão de um jogo aberto pelo app está aberta, e o que já estava nos arquivos no começo entra no histórico em silêncio (é a base).

Roda na thread principal (`QTimer`): cada olhada é um punhado de `stat` e a releitura é de arquivos pequenos. A lista de arquivos é refeita a cada `REBUSCA` olhadas, pois um arquivo pode surgir no meio da partida (a primeira conquista de um jogo novo).

Nos jogos da Steam o estado vem do `UserGameStats`, gravado no desbloqueio; a Steam o cria ao abrir o jogo já com as conquistas antigas, então ao aparecer ele entra em silêncio. Tudo o que o vigia lê vem de emulador ou da Steam: ao ler algo num jogo sem fonte ele grava `steam:<appid>`, dando fonte ao emulador que aparece no meio da partida; uma fonte já gravada nunca é trocada.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from PySide6.QtCore import QTimer

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

    nome: str
    # None quando o jogo não tem catálogo: sem nome nem ícone para mostrar.
    info: Optional[ConquistaInfo]
    completou: bool


def acompanha(game: Any) -> bool:
    """Se o vigia de arquivos acompanha este jogo: appID válido e conquistas ligadas.

    Xbox/Game Pass (executável é AUMID) e jogos abertos pelo launcher da Epic ou da Ubisoft ficam de fora (vigia próprio). Só o texto do executável é olhado, nunca o disco.
    """
    return (
        arquivos.appid_valido(getattr(game, "steam_appid", None))
        and bool(getattr(game, "conquistas", True))
        and fontes.pfn(game) is None
        and not fontes.url_da_epic(game)
        and not fontes.url_da_ubisoft(game)
        and not _gravada_da_ea(game)
    )


def _gravada_da_ea(game: Any) -> bool:
    fonte = fontes.gravada(game)
    return fonte is not None and fonte.tipo == fontes.EA


def completou(antes: Optional[progresso.Progresso], depois: Optional[progresso.Progresso]) -> bool:
    return bool(depois is not None and depois.completo and not (antes is not None and antes.completo))


def para_avisar(
    entraram: list[str], lidos: list[formatos.Desbloqueio], limite: Optional[float]
) -> list[str]:
    """As que entraram, da mais antiga para a mais nova, sem as de antes de ``limite`` (de outro aparelho, ou que a Steam acabou de sincronizar: entram no histórico, mas não são aviso). Sem hora, avisa."""
    horas = {d.nome.strip().upper(): d.quando for d in lidos}
    return [
        nome
        for nome in sorted(entraram, key=lambda nome: horas.get(nome, 0))
        if limite is None or not 0 < horas.get(nome, 0) < limite
    ]


def desbloqueadas(
    avisaveis: list[str], por_nome: dict[str, ConquistaInfo], fechou_100: bool
) -> list[Desbloqueada]:
    """O aviso pronto. O 100% é da última conquista do catálogo, nunca de um nome
    que ele não conhece."""
    ultima = next((nome for nome in reversed(avisaveis) if nome in por_nome), None)
    return [Desbloqueada(nome, por_nome.get(nome), fechou_100 and nome == ultima) for nome in avisaveis]


def _mtime(caminho: Any) -> Optional[int]:
    try:
        return os.stat(caminho).st_mtime_ns
    except OSError:
        return None


def _repetir(segundos: int, funcao: Callable[[], Any]) -> QTimer:
    """Um QTimer sem pai que chama ``funcao`` a cada ``segundos``, já iniciado (ponto que os testes trocam)."""
    timer = QTimer()
    timer.setInterval(segundos * 1000)
    timer.timeout.connect(funcao)
    timer.start()
    return timer


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
        self._inicio: Optional[float] = None
        self._arquivos: list[ArquivoDeConquista] = []
        self._mtimes: dict[str, Optional[int]] = {}
        # Arquivos cuja base ainda não foi lida: lidos em silêncio até dar certo.
        self._pendentes: set[str] = set()
        # Arquivos da Steam conhecidos antes de existirem (`_esperados`):
        # quando aparecem, entram em silêncio.
        self._caminhos_esperados: set[str] = set()
        # Falhas seguidas por arquivo (leitura ou gravação). Passando de
        # `TENTATIVAS`, o arquivo só é tentado de novo a cada rebusca.
        self._falhas: dict[str, int] = {}
        self._fonte: Optional[QTimer] = None
        self._olhadas = 0

    @property
    def ativo(self) -> bool:
        return self._fonte is not None

    def iniciar(self) -> None:
        if self._fonte is not None or not self._acompanha():
            return
        self._inicio = self._relogio()
        try:
            self._arquivos = self._achar()
            esperados = self._esperados()
            self._caminhos_esperados = {str(a.caminho) for a in esperados}
            conhecidos = {str(a.caminho) for a in self._arquivos}
            self._arquivos.extend(a for a in esperados if str(a.caminho) not in conhecidos)
            self._base()
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao preparar o vigia de %s", self.game.name, exc_info=True)
            # O que não chegou a entrar na base não pode virar aviso depois.
            self._pendentes.update(
                str(a.caminho) for a in self._arquivos if str(a.caminho) not in self._mtimes
            )
        self._fonte = _repetir(INTERVALO, self._olhar)

    def parar(self) -> None:
        if self._fonte is not None:
            self._fonte.stop()
            self._fonte = None


    def _acompanha(self) -> bool:
        return acompanha(self.game)

    def _achar(self) -> list[ArquivoDeConquista]:
        return arquivos.arquivos_do_jogo(str(self.game.steam_appid), self.game.executable)

    def _esperados(self) -> list[ArquivoDeConquista]:
        return arquivos.da_steam_esperados(str(self.game.steam_appid), self.game.executable)

    def _ler(self, achado: ArquivoDeConquista) -> Optional[list[formatos.Desbloqueio]]:
        return formatos.ler_ou_none(achado.caminho, achado.formato)

    def _fonte_ao_registrar(self) -> str:
        return f"steam:{self.game.steam_appid}"

    def _novo_em_silencio(self) -> bool:
        """Se o arquivo que aparece no meio da partida entra em silêncio, como a base.

        Nos emuladores, não: o arquivo novo é a primeira conquista do jogo, desta partida.
        """
        return False

    def _desistiu(self, chave: str, rebusca: bool) -> bool:
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
            fonte = self._fonte_ao_registrar()
        return historico.registrar(self.game.game_id, lidos, fonte=fonte)

    def _gravados(self, lidos: list[formatos.Desbloqueio]) -> bool:
        return historico.contem(self.game.game_id, lidos)

    def _base(self) -> None:
        """O que já está nos arquivos entra no histórico em silêncio; o que não pôde ser lido fica pendente, também em silêncio, até uma leitura dar certo."""
        lidos_por_arquivo: list[tuple[ArquivoDeConquista, Optional[int], list]] = []
        for achado in self._arquivos:
            atual = _mtime(achado.caminho)
            if atual is None and str(achado.caminho) in self._caminhos_esperados:
                # Ainda não existe: quando a Steam o criar, entra em silêncio.
                self._pendentes.add(str(achado.caminho))
                continue
            lidos = self._ler(achado)
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
        chave = str(achado.caminho)
        if atual is None:
            if chave in self._caminhos_esperados:
                self._falhas.pop(chave, None)
                return  # a Steam ainda não criou o arquivo; continua pendente
            self._pendentes.discard(chave)
            self._falhas.pop(chave, None)
            self._mtimes[chave] = None
            return
        lidos = self._ler(achado)
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
        try:
            self._olhadas += 1
            rebusca = self._olhadas % REBUSCA == 0
            if rebusca:
                conhecidos = {str(a.caminho) for a in self._arquivos}
                # Arquivo novo: sem mtime guardado, tudo o que ele traz é desta partida
                # (salvo quando o tipo da fonte diz que ele nasce com o que já havia).
                novos = [a for a in self._achar() if str(a.caminho) not in conhecidos]
                self._arquivos.extend(novos)
                if self._novo_em_silencio():
                    self._pendentes.update(str(a.caminho) for a in novos)
            mudaram: list[tuple[ArquivoDeConquista, int, list]] = []
            for achado in self._arquivos:
                chave = str(achado.caminho)
                atual = _mtime(achado.caminho)
                if chave in self._pendentes:
                    # Ausente não faz E/S: `_retomar_base` zera as falhas já neste tique, sem esperar a rebusca (30 s).
                    if atual is None or not self._desistiu(chave, rebusca):
                        self._retomar_base(achado, atual)
                elif atual is None:
                    self._falhas.pop(chave, None)
                    self._mtimes[chave] = None
                elif atual != self._mtimes.get(chave) and not self._desistiu(chave, rebusca):
                    lidos = self._ler(achado)
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
        avisaveis = para_avisar(entraram, lidos, self._limite())
        if not avisaveis:
            return
        cat = catalogo.em_cache(self._chave_do_catalogo())
        por_nome = cat.por_nome() if cat is not None else {}
        self._avisar(desbloqueadas(avisaveis, por_nome, completou(antes, progresso.do_jogo(self.game))))

    def _chave_do_catalogo(self) -> str:
        """A chave do catálogo da fonte gravada, a mesma de `progresso.do_jogo` (títulos e `completou` saem do mesmo catálogo); sem fonte, o appID do jogo."""
        fonte = fontes.gravada(self.game)
        return fontes.chave_do_catalogo(fonte) if fonte is not None else str(self.game.steam_appid)

    def _limite(self) -> Optional[float]:
        """A hora abaixo da qual uma conquista da Steam não é desta sessão.

        Ao abrir o jogo a Steam baixa o que foi ganho em outro aparelho e regrava o arquivo, com horas antigas. Só vale para a Steam; a hora dos emuladores é menos confiável.
        """
        if self._inicio is None or not arquivos.eh_jogo_da_steam(self.game.executable):
            return None
        return self._inicio - MARGEM_DA_STEAM
