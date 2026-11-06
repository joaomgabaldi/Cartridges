"""A passada de abertura: lê as conquistas de cada jogo e guarda no histórico.

Adaptada do `preSearchAchievements` do Hydra Launcher (hydralauncher/hydra, MIT, `src/main/services/achievements/`): uma vez por execução, em segundo plano, em "Tarefas em andamento". Entram os jogos da biblioteca e os de Jogos Zerados (as pastas do AppData sobrevivem à desinstalação).

Duas passadas. A primeira decide a fonte de cada jogo (`fontes.do_jogo`) e lê o disco (emuladores, `.spool` e catálogo da Ubisoft); a gravação volta à thread principal, que confere se o jogo ainda está na store (senão um jogo excluído no meio ganharia de volta o arquivo recém-apagado). A segunda vai à rede: renova o catálogo da Steam e lê as contas das lojas (Xbox, Epic, EA). Quando um pedido falha por rede, os jogos seguintes ficam só com cache e arquivo; jogo sem fonte não vai à rede.

A fonte de uma loja com conta só é gravada na segunda passada. A primeira leitura de uma fonte (conta recém-conectada, por exemplo) não conta no aviso, senão as conquistas antigas da conta apareceriam como novas.

Ao fim da primeira passada sai um aviso só com o que entrou desde a abertura anterior (jogado fora do app); as novas das contas, que só chegam pela rede, saem num aviso próprio no fim da segunda. A primeira varredura de um jogo não conta. Na Steam e na Ubisoft (hora confiável), conquista com data anterior à varredura anterior também não: foi ganha em outro aparelho e só chegou porque o arquivo nasceu quando o jogo rodou aqui (mesmo critério e margem do vigia).
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from kyron import shared
from kyron.conquistas import arquivos, catalogo, contas, fontes, formatos, historico, sessao
from kyron.conquistas.fontes import Fonte
from kyron.conquistas.ubisoft import locais as ubisoft_locais, pacote as ubisoft_pacote, spool as ubisoft_spool
from kyron.conquistas.vigia import MARGEM_DA_STEAM
from kyron.modelos import tarefas
from kyron.utils.thread_principal import na_thread_principal
from kyron.utils.passada_agendada import PassadaAgendada

_ULTIMA_VARREDURA = "conquistas-ultima-varredura"

_ATRASO_INICIAL = 10
_ESPERA_IMPORTACAO = 30


def participa(game: Any) -> bool:
    if not getattr(game, "conquistas", True):
        return False
    if game.blacklisted:
        return False
    return not game.removed or game.zerado


def _filtrar(games: list[Any], filtro: Callable[[Any], bool]) -> list[Any]:
    passaram = []
    for game in games:
        try:
            if filtro(game):
                passaram.append(game)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao filtrar %s para a varredura de conquistas", game.name, exc_info=True)
    return passaram


@dataclass
class Leitura:
    """O que os arquivos de um jogo trazem (primeira passada)."""

    game: Any
    # O appID que a leitura usou (vazio fora da Steam): o jogo pode ter o appID corrigido durante a leitura, e a leitura velha não vale para o novo.
    appid: str
    desbloqueios: list[formatos.Desbloqueio] = field(default_factory=list)
    # Falso na varredura de um jogo só: não entra no aviso final.
    avisar: bool = True
    fonte: Optional[Fonte] = None
    # O executável que gerou a fonte: se for editado até a entrega, a leitura é descartada.
    executavel: str = ""
    # Ubisoft: a conta do `.spool` lido (None = nenhum `.spool` agora).
    conta: Optional[str] = None
    catalogo_mudou: bool = False
    # Falso quando o arquivo existia mas não pôde ser lido agora: nada é gravado.
    valida: bool = True


@dataclass
class LeituraDaConta:
    """O que a conta de uma loja trouxe para um jogo (segunda passada)."""

    game: Any
    fonte: Fonte
    desbloqueios: list[formatos.Desbloqueio] = field(default_factory=list)
    # Falso na varredura de um jogo só: não entra no aviso das contas.
    avisar: bool = True
    # O executável que gerou a fonte: se editado até a entrega, a leitura é descartada.
    executavel: str = ""


@dataclass
class Catalogacao:
    """O que a renovação do catálogo de um jogo trouxe (segunda passada)."""

    game: Any
    appid: str
    chave_recusada: bool = False
    # Veio um catálogo (novo ou do cache): o cartão do jogo aberto pode ter de aparecer mesmo sem conquista nova.
    mudou: bool = False
    # A Steam não respondeu: o resto da passada não vai à rede.
    rede_falhou: bool = False
    # Falso na varredura de um jogo só: não avisa da chave.
    avisar: bool = True


def _ler_da_ubisoft(game: Any, fonte: Fonte, executavel: str) -> Leitura:
    """Trabalho de thread: o catálogo do ZIP (refeito se mudou) e o `.spool`. Só disco."""
    _catalogo, refeito = ubisoft_pacote.obter(fonte.id)
    achado = ubisoft_locais.spool(fonte.id)
    if achado is None:
        return Leitura(game, "", [], fonte=fonte, executavel=executavel, catalogo_mudou=refeito)
    caminho, conta = achado
    lidos = ubisoft_spool.ler_ou_none(caminho)
    if lidos is None:
        # O launcher gravando no mesmo instante, por exemplo: a próxima varredura lê.
        return Leitura(game, "", [], fonte=fonte, executavel=executavel, catalogo_mudou=refeito, valida=False)
    return Leitura(
        game, "", lidos, fonte=fonte, executavel=executavel, conta=conta, catalogo_mudou=refeito
    )


def ler_jogo(game: Any) -> Leitura:
    """Trabalho de thread: decide a fonte e lê o que está no disco (Steam/emulador, Ubisoft). Só disco."""
    executavel = getattr(game, "executable", "") or ""
    fonte = fontes.do_jogo(game)
    if fonte is not None and fonte.tipo == fontes.UBISOFT:
        return _ler_da_ubisoft(game, fonte, executavel)
    if fonte is None or fonte.tipo != fontes.STEAM:
        return Leitura(game, "", [], fonte=fonte, executavel=executavel)
    desbloqueios = [
        desbloqueio
        for achado in arquivos.arquivos_do_jogo(fonte.id, game.executable)
        for desbloqueio in formatos.ler(achado.caminho, achado.formato)
    ]
    return Leitura(game, fonte.id, desbloqueios, fonte=fonte, executavel=executavel)


def ler_da_conta(
    game: Any, fonte: Fonte, executavel: Optional[str] = None
) -> tuple[Optional[LeituraDaConta], bool]:
    """Trabalho de thread, com rede: o id da fonte (se faltar) e a leitura da conta; ``executavel`` é o da primeira passada. Devolve ``(leitura, rede_falhou)``."""
    if executavel is None:
        executavel = getattr(game, "executable", "") or ""
    loja = contas.da_fonte(fonte)
    if loja is None:
        return None, False
    try:
        id_ = fonte.id or loja.resolver(game, fonte)
        if not id_:
            return None, False
        leitura = loja.ler(id_)
    except loja.FalhaDeRede:
        logging.info("Sem rede para as conquistas da conta; o resto da passada fica sem rede")
        return None, True
    if leitura is None:
        return None, False
    return LeituraDaConta(game, Fonte(fonte.tipo, id_), leitura.desbloqueios, executavel=executavel), False


def renovar_catalogo(game: Any, rede: bool = True, usar_chave: bool = True) -> Catalogacao:
    """Trabalho de thread: renova o catálogo, que pode ir à rede. Não grava."""
    appid = str(game.steam_appid)
    renovacao = catalogo.obter(appid, game.executable, rede=rede, usar_chave=usar_chave)
    return Catalogacao(
        game,
        appid,
        renovacao.chave_recusada,
        mudou=renovacao.catalogo is not None,
        rede_falhou=renovacao.rede_falhou,
    )


def mensagem(novas_por_jogo: list[tuple[str, int]]) -> Optional[str]:
    com_novas = [(nome, novas) for nome, novas in novas_por_jogo if novas > 0]
    if not com_novas:
        return None
    total = sum(novas for _nome, novas in com_novas)
    if len(com_novas) == 1:
        return ngettext("{} nova conquista em {}", "{} novas conquistas em {}", total).format(
            total, com_novas[0][0]
        )
    return _("{} novas conquistas em {} jogos").format(total, len(com_novas))


def _aviso(texto: str) -> None:
    if shared.aplicativo is not None:
        shared.aplicativo.avisos.adicionar(texto)


class VarreduraConquistas(PassadaAgendada):

    atraso_inicial = _ATRASO_INICIAL
    espera_da_importacao = _ESPERA_IMPORTACAO

    def __init__(self) -> None:
        super().__init__()
        # Um aviso de chave recusada por execução, não um por jogo.
        self._avisou_chave = False
        self._novas: list[tuple[str, int]] = []
        self._novas_da_conta: list[tuple[str, int]] = []
        # Quando começou a varredura anterior que foi até o fim (0 = nenhuma), lido no começo de cada passada com aviso.
        self._desde = 0

    def run_async(self) -> None:
        if self._stopped:
            return
        # Retrato tirado na thread principal: a store muda durante importações.
        games = [game for game in shared.store if participa(game)]
        if not games:
            return
        if not self._reservar():
            return
        threading.Thread(
            target=self._worker, args=(games, self._generation), daemon=True
        ).start()

    def varrer_jogo(self, game: Any) -> None:
        """Um jogo só, sem aviso (appID corrigido, interruptor religado, fim de sessão)."""
        self.varrer_jogos([game])

    def varrer_jogos(self, games: Any, filtro: Optional[Callable[[Any], bool]] = None) -> None:
        """Alguns jogos, numa thread só e sem aviso (jogos recém-importados).

        Não grava a data da varredura nem conta como a passada da abertura. ``filtro``: critério extra que pode ler o disco do jogo, por isso aplicado na thread da varredura.
        """
        jogos = [game for game in games if participa(game)]
        if not jogos:
            return
        threading.Thread(
            target=self._worker, args=(jogos, self._generation, False, filtro), daemon=True
        ).start()


    def _worker(
        self,
        games: list[Any],
        geracao: int,
        avisar: bool = True,
        filtro: Optional[Callable[[Any], bool]] = None,
    ) -> None:
        """Duas passadas. A dos arquivos vem primeiro e só toca o disco: grava o histórico e avisa sem esperar a Steam. A da rede (catálogo da Steam, contas Xbox, Epic, EA) vem depois."""
        tarefa = None
        concluiu = False
        try:
            if filtro is not None:
                games = _filtrar(games, filtro)
            if avisar:
                inicio = int(time.time())
                # Na fila antes de qualquer `_entregar` desta passada (a fila serve na ordem de entrada).
                na_thread_principal(self._comecar_aviso)
                tarefa = tarefas.comecar(_("Conquistas"), 2 * len(games))
            lidas: dict[str, tuple[Optional[Fonte], str]] = {}
            leu_tudo = self._passada_dos_arquivos(games, geracao, avisar, tarefa, lidas)
            if avisar:
                concluiu = True
                na_thread_principal(self._concluir, inicio if leu_tudo else None)
            self._passada_da_rede(games, geracao, avisar, tarefa, lidas)
        finally:
            if tarefa is not None:
                tarefa.terminar()
            if avisar:
                self._liberar()
                if not concluiu:
                    na_thread_principal(self._concluir)
                # Depois de todo `_entregar_da_conta` desta passada (ordem da fila).
                na_thread_principal(self._concluir_da_conta)

    def _passada_dos_arquivos(
        self,
        games: list[Any],
        geracao: int,
        avisar: bool,
        tarefa: Optional[Any],
        lidas: dict[str, tuple[Optional[Fonte], str]],
    ) -> bool:
        """Lê os arquivos de cada jogo e anota em ``lidas`` a fonte (e o executável); devolve se foi até o fim sem ser parada."""
        for feitos, game in enumerate(games):
            if tarefa is not None:
                tarefa.atualizar(feitos)
            if self._deve_parar(geracao):
                return False
            try:
                leitura = ler_jogo(game)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao ler as conquistas de %s", game.name, exc_info=True)
                continue
            leitura.avisar = avisar
            lidas[game.game_id] = (leitura.fonte, leitura.executavel)
            na_thread_principal(self._entregar, leitura)
        return True

    def _passada_da_rede(
        self,
        games: list[Any],
        geracao: int,
        avisar: bool,
        tarefa: Optional[Any],
        lidas: dict[str, tuple[Optional[Fonte], str]],
    ) -> None:
        rede = True
        usar_chave = True
        for feitos, game in enumerate(games, start=len(games)):
            if tarefa is not None:
                tarefa.atualizar(feitos)
            if self._deve_parar(geracao):
                break
            fonte, executavel = lidas.get(game.game_id, (None, ""))
            if fonte is None:
                continue
            if contas.da_fonte(fonte) is not None:
                rede = self._ler_da_conta(game, fonte, executavel, rede, avisar)
                continue
            if fonte.tipo != fontes.STEAM:
                # Ubisoft: tudo vem do disco e já foi lido na primeira passada.
                continue
            try:
                catalogacao = renovar_catalogo(game, rede, usar_chave)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao renovar o catálogo de %s", game.name, exc_info=True)
                continue
            if catalogacao.rede_falhou and rede:
                # Sem rede para um jogo, sem rede para os outros: o resto fica com o cache e o arquivo.
                rede = False
                logging.info("Sem rede para o catálogo de conquistas; seguindo só com o disco")
            if catalogacao.chave_recusada and usar_chave:
                # A mesma chave seria recusada em cada jogo: os seguintes não a mandam à Steam (o aviso segue sendo um só).
                usar_chave = False
                logging.info("Chave da Steam recusada; os demais jogos seguem sem ela")
            catalogacao.avisar = avisar
            na_thread_principal(self._entregar_catalogo, catalogacao)

    def _ler_da_conta(self, game: Any, fonte: Fonte, executavel: str, rede: bool, avisar: bool) -> bool:
        """Lê a conta da loja de um jogo. Devolve se a rede segue valendo."""
        loja = contas.da_fonte(fonte)
        if not rede or loja is None or not loja.conectada():
            return rede
        try:
            leitura, falhou = ler_da_conta(game, fonte, executavel)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao ler as conquistas da conta de %s", game.name, exc_info=True)
            return rede
        if falhou:
            return False
        if leitura is not None:
            leitura.avisar = avisar
            na_thread_principal(self._entregar_da_conta, leitura)
        return rede


    def _comecar_aviso(self) -> bool:
        # Chamada da fila: nada pode escapar daqui.
        try:
            self._desde = int(shared.state_schema.get_int64(_ULTIMA_VARREDURA))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Data da varredura anterior de conquistas ilegível", exc_info=True)
            self._desde = 0
        return False

    def _contam(self, entraram: list[str], lidos: list[formatos.Desbloqueio], hora_confiavel: bool) -> int:
        """Quantas das que entraram contam como novas no aviso.

        Com hora confiável (Steam, Ubisoft), a conquista anterior à varredura anterior (menos a margem do relógio) é de outro aparelho ou veio da conta: entra no histórico, mas não é novidade. Sem data, conta.
        """
        if not self._desde or not hora_confiavel:
            return len(entraram)
        horas: dict[str, int] = {}
        for lido in lidos:
            nome = lido.nome.strip().upper()
            if lido.quando > 0 and (nome not in horas or lido.quando < horas[nome]):
                horas[nome] = lido.quando
        limite = self._desde - MARGEM_DA_STEAM
        return sum(1 for nome in entraram if not 0 < horas.get(nome, 0) < limite)

    def _entregar(self, leitura: Leitura) -> bool:
        try:
            if not self._stopped:
                novas = self._gravar(leitura)
                if novas and leitura.avisar:
                    self._novas.append((leitura.game.name, novas))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao guardar as conquistas de um jogo", exc_info=True)
        return False

    def _entregar_catalogo(self, catalogacao: Catalogacao) -> bool:
        try:
            if self._stopped:
                return False
            game = catalogacao.game
            if catalogacao.mudou and shared.conquistas is not None:
                shared.conquistas.mudou(game.game_id)
            if catalogacao.avisar and catalogacao.chave_recusada and not self._avisou_chave:
                self._avisou_chave = True
                _aviso(_("A chave da Steam Web API foi recusada. Verifique-a nas Preferências."))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao entregar o catálogo de conquistas", exc_info=True)
        return False

    def _gravar(self, leitura: Leitura) -> int:
        """Grava o histórico e a fonte. Devolve quantas contam para o aviso."""
        game = leitura.game
        if shared.store.get(game.game_id) is not game or not participa(game):
            return 0
        fonte = leitura.fonte
        # O appID foi corrigido durante a leitura (e o Aplicar já apagou o histórico antigo): são conquistas do jogo errado, e o histórico só cresce.
        if (
            fonte is not None
            and fonte.tipo == fontes.STEAM
            and str(game.steam_appid or "") != leitura.appid
        ):
            return 0
        # Sessão aberta com o vigia ativo: o histórico do jogo é dele agora.
        if sessao.acompanhando(game):
            return 0
        antes = historico.fonte(game.game_id)
        if fonte is None:
            historico.esquecer_fonte(game.game_id)
            self._atualizar_pagina(game, antes is not None)
            return 0
        if fonte.tipo == fontes.UBISOFT:
            return self._gravar_da_ubisoft(leitura, antes)
        if fonte.tipo != fontes.STEAM:
            # A de uma loja com conta é gravada na segunda passada, junto com as conquistas.
            return 0
        entraram, primeira = historico.registrar(
            game.game_id, leitura.desbloqueios, fonte=fonte.texto
        )
        self._atualizar_pagina(game, bool(entraram) or antes != fonte.texto)
        executavel = getattr(game, "executable", "") or ""
        return 0 if primeira else self._contam(entraram, leitura.desbloqueios, arquivos.eh_jogo_da_steam(executavel))

    def _gravar_da_ubisoft(self, leitura: Leitura, antes: Optional[str]) -> int:
        """Grava o histórico, a fonte e a conta da Ubisoft; devolve quantas contam para o aviso.

        A primeira leitura (histórico novo, ou fonte ou conta diferente) não avisa: o `.spool` nasce com o que a conta já tinha.
        """
        game = leitura.game
        fonte = leitura.fonte
        if fonte is None or not leitura.valida:
            return 0
        # O executável foi editado depois da leitura: o productId pode ser outro, e o histórico só cresce.
        if (getattr(game, "executable", "") or "") != leitura.executavel:
            return 0
        conta_antes = historico.conta(game.game_id)
        conta = leitura.conta
        if conta is None and antes == fonte.texto:
            # Sem `.spool` agora (o launcher desinstalado, por exemplo): a conta gravada fica.
            conta = conta_antes
        entraram, primeira = historico.registrar(
            game.game_id, leitura.desbloqueios, fonte=fonte.texto, conta=conta
        )
        primeira_da_conta = antes != fonte.texto or conta_antes != conta
        self._atualizar_pagina(game, bool(entraram) or primeira_da_conta or leitura.catalogo_mudou)
        if primeira or primeira_da_conta:
            return 0
        return self._contam(entraram, leitura.desbloqueios, hora_confiavel=True)

    def _atualizar_pagina(self, game: Any, mudou: bool) -> None:
        if mudou and shared.conquistas is not None:
            shared.conquistas.mudou(game.game_id)

    def _entregar_da_conta(self, leitura: LeituraDaConta) -> bool:
        try:
            game = leitura.game
            if (
                self._stopped
                or shared.store.get(game.game_id) is not game
                or not participa(game)
                or sessao.acompanhando(game)
                or (loja := contas.da_fonte(leitura.fonte)) is None
                or not loja.conectada()
            ):
                return False
            # Executável editado depois da leitura: o jogo pode ser outro (ou de outra loja) e o histórico só cresce; a próxima varredura refaz.
            if (getattr(game, "executable", "") or "") != leitura.executavel:
                return False
            texto = leitura.fonte.texto
            id_conta = loja.id_da_conta()
            if id_conta is None:
                return False
            antes = historico.fonte(game.game_id)
            conta_antes = historico.conta(game.game_id)
            entraram, primeira = historico.registrar(
                game.game_id, leitura.desbloqueios, fonte=texto, conta=id_conta
            )
            # A primeira leitura da fonte (conta recém-conectada, por exemplo), ou de uma conta diferente da que o histórico conhecia, traz o que a conta já tinha: não é novidade.
            primeira_da_conta = antes != texto or conta_antes != id_conta
            novas = 0 if (primeira or primeira_da_conta) else len(entraram)
            self._atualizar_pagina(game, bool(entraram) or primeira_da_conta)
            if novas and leitura.avisar:
                self._novas_da_conta.append((game.name, novas))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao guardar as conquistas da conta de um jogo", exc_info=True)
        return False

    def _concluir_da_conta(self) -> bool:
        """Chamada da fila: não levanta, e a lista sempre zera."""
        try:
            if not self._stopped and (texto := mensagem(self._novas_da_conta)):
                _aviso(texto)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao avisar das conquistas novas das contas", exc_info=True)
        finally:
            self._novas_da_conta = []
        return False

    def _concluir(self, inicio: Optional[int] = None) -> bool:
        """Também chamada da fila: não levanta, e a lista sempre zera. ``inicio``: quando começou esta passada, se leu os arquivos de todos os jogos; vira a "varredura anterior" da próxima abertura."""
        try:
            if not self._stopped and (texto := mensagem(self._novas)):
                _aviso(texto)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao avisar das conquistas novas", exc_info=True)
        finally:
            self._novas = []
        if inicio is not None and not self._stopped:
            try:
                shared.state_schema.set_int64(_ULTIMA_VARREDURA, inicio)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao guardar a data da varredura de conquistas", exc_info=True)
        return False
