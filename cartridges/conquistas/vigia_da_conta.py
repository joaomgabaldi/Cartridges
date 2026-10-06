"""O vigia da sessão para os jogos cujas conquistas vêm de uma conta (Xbox, Epic).

Não há arquivo local: a cada `INTERVALO` segundos, uma consulta às conquistas
desbloqueadas da conta (`loja.desbloqueadas`), numa thread, com o resultado
aplicado na thread principal. O primeiro resultado é a base (silêncio); depois,
o que entra no histórico é novidade — salvo o que tem hora anterior ao início
da sessão, que veio de outro aparelho e entra em silêncio, com a mesma margem
da Steam. Só pulso: a Xbox Game Bar e o overlay da Epic já mostram o aviso deles.

Não há leitura final aqui: o fim da sessão já chama a varredura do jogo, que lê
a conta de novo (`varredura.varrer_jogo`).

A loja é um dos módulos de `contas.lojas()`; sem loja passada, vale a da fonte
gravada do jogo.
"""

import logging
import threading
import time
from typing import Any, Callable, Optional

from gi.repository import GLib

from cartridges.conquistas import catalogo, contas, fontes, historico, progresso
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.conquistas.vigia import MARGEM_DA_STEAM, Desbloqueada

INTERVALO = 15


def _em_thread(trabalho: Callable[[], Any], entregar: Callable[[Any], None]) -> None:
    """Roda ``trabalho`` numa thread e ``entregar`` com o resultado, na thread principal."""

    def devolver(resultado: Any) -> bool:
        entregar(resultado)
        return False  # uma vez só

    def rodar() -> None:
        try:
            resultado = trabalho()
        except Exception as erro:  # pylint: disable=broad-exception-caught
            # Só o tipo: a mensagem de uma falha de rede pode trazer endereços.
            logging.warning("Falha numa tarefa da conta em segundo plano (%s)", type(erro).__name__)
            resultado = None
        try:
            GLib.idle_add(devolver, resultado)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao entregar o resultado de uma tarefa da conta", exc_info=True)

    threading.Thread(target=rodar, daemon=True).start()


class Vigia:
    def __init__(
        self,
        game: Any,
        avisar: Callable[[list[Desbloqueada]], None],
        relogio: Callable[[], float] = time.time,
        em_thread: Callable[..., None] = _em_thread,
        loja: Optional[Any] = None,
    ) -> None:
        self.game = game
        self._avisar = avisar
        self._relogio = relogio
        self._em_thread = em_thread
        self._loja = loja
        # A hora em que a sessão começou; None antes de `iniciar`.
        self._inicio: Optional[float] = None
        self._fonte_glib = 0
        # O titleId (Xbox) ou namespace (Epic) da fonte gravada.
        self._id = ""
        # Enquanto a base não foi gravada, o que chega entra em silêncio.
        self._base_feita = False
        self._pedindo = False
        # Muda a cada iniciar/parar: a resposta de um pedido de antes é descartada.
        self._geracao = 0

    @property
    def ativo(self) -> bool:
        return bool(self._fonte_glib)

    def iniciar(self) -> None:
        try:
            fonte = fontes.gravada(self.game)
            loja = self._loja if self._loja is not None else contas.da_fonte(fonte)
            if (
                self._fonte_glib
                or fonte is None
                or loja is None
                or fonte.tipo != loja.TIPO
                or not fontes.ativa(fonte)
            ):
                return
            self._loja = loja
            self._id = fonte.id
            self._inicio = self._relogio()
            self._base_feita = False
            self._pedindo = False
            self._geracao += 1
            self._fonte_glib = GLib.timeout_add_seconds(INTERVALO, self._tique)
            self._olhar()
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao preparar o vigia da conta de %s", self.game.name, exc_info=True)

    def parar(self) -> None:
        if self._fonte_glib:
            GLib.source_remove(self._fonte_glib)
            self._fonte_glib = 0
        self._geracao += 1
        self._pedindo = False

    def _tique(self) -> bool:
        """Callback do timer: nunca levanta, e devolve True para continuar."""
        self._olhar()
        return True

    def _olhar(self) -> None:
        """Pede a lista da conta, se não há um pedido em andamento. Nunca levanta."""
        if not self.ativo or self._pedindo:
            return
        self._pedindo = True
        geracao = self._geracao
        loja, id_ = self._loja, self._id
        try:
            self._em_thread(lambda: self._pedir(loja, id_), lambda lidos: self._receber(geracao, lidos))
        except Exception:  # pylint: disable=broad-exception-caught
            self._pedindo = False
            logging.warning("Falha ao consultar as conquistas da conta de %s", self.game.name, exc_info=True)

    @staticmethod
    def _pedir(loja: Any, id_: str) -> Optional[list[Desbloqueio]]:
        """Roda na thread: faz rede e renova o token, então nunca na principal."""
        try:
            return loja.desbloqueadas(id_)
        except loja.FalhaDeRede:
            logging.info("Sem rede para as conquistas da conta nesta consulta")
            return None
        except Exception as erro:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao consultar as conquistas da conta (%s)", type(erro).__name__)
            return None

    def _receber(self, geracao: int, lidos: Optional[list[Desbloqueio]]) -> None:
        """Roda na thread principal, com o resultado do pedido. Nunca levanta."""
        try:
            if geracao != self._geracao or not self.ativo:
                return
            self._pedindo = False
            if lidos is None:
                # Sem resposta: rede fora (tenta no próximo tique) ou conta desconectada (fim).
                if self._loja is None or not self._loja.conectada():
                    self.parar()
                return
            if not self._base_feita:
                historico.registrar(self.game.game_id, lidos)
                # Histórico indisponível: a base continua pendente, em silêncio.
                self._base_feita = self._gravados(lidos)
                return
            self._processar(lidos)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning(
                "Falha ao acompanhar as conquistas da conta de %s", self.game.name, exc_info=True
            )

    def _gravados(self, lidos: list[Desbloqueio]) -> bool:
        """Se tudo o que foi lido já está no histórico (ele só soma)."""
        guardado = historico.ler(self.game.game_id)
        if guardado is None:
            return not lidos
        return all(d.nome.strip().upper() in guardado for d in lidos)

    def _processar(self, lidos: list[Desbloqueio]) -> None:
        antes = progresso.do_jogo(self.game)
        entraram, primeira = historico.registrar(self.game.game_id, lidos)
        if primeira or not entraram:
            return
        depois = progresso.do_jogo(self.game)
        completou = bool(
            depois is not None and depois.completo and not (antes is not None and antes.completo)
        )
        horas = {d.nome.strip().upper(): d.quando for d in lidos}
        limite = (self._inicio or 0) - MARGEM_DA_STEAM
        # Conquista com hora anterior ao início da sessão veio de outro aparelho: não é aviso.
        avisaveis = [
            nome
            for nome in sorted(entraram, key=lambda nome: horas.get(nome, 0))
            if not 0 < horas.get(nome, 0) < limite
        ]
        if not avisaveis:
            return
        cat = catalogo.em_cache(self._loja.chave_do_catalogo(self._id))
        por_nome = cat.por_nome() if cat is not None else {}
        # O 100% é da última conquista do catálogo, nunca de um nome que ele não conhece.
        ultima = next((nome for nome in reversed(avisaveis) if nome in por_nome), None)
        self._avisar(
            [Desbloqueada(nome, por_nome.get(nome), completou and nome == ultima) for nome in avisaveis]
        )
