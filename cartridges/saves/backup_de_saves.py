"""O backup e a restauração dos saves, jogo a jogo, em segundo plano.

É o que a interface chama: o fim de uma sessão dispara o backup, o menu do jogo
lista as versões e restaura uma, as Preferências restauram todas e trocam a pasta.
Cada operação roda numa thread, aparece como tarefa na janela de tarefas desde o
pedido e só fala com o usuário quando falha (um aviso) ou quando "Restaurar todos"
não acha nada a restaurar; sucesso é silencioso.

Uma trava única cobre gravar o `config.yaml` e rodar o Ludusavi: duas sessões que
terminam em sequência esperam uma pela outra, e a troca da pasta dos saves nunca
acontece no meio de um backup. O config de cada chamada leva todos os jogos da
biblioteca que já têm nome no Ludusavi, para que o `restore` de qualquer um ache a
sua entrada.
"""

import logging
import subprocess
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from gi.repository import Adw

from cartridges import shared
from cartridges.conquistas import arquivos
from cartridges.game import Game
from cartridges.saves import conferencia, config, ludusavi, pasta
from cartridges.saves.ludusavi import LudusaviFalhou, Versao
from cartridges.utils import tarefas
from cartridges.utils.create_dialog import create_dialog
from cartridges.utils.na_tela import entregar_na_tela

# Os testes trocam por um executor falso; é o que `ludusavi.rodar` recebe.
executor = subprocess.run

# As marcas que o app grava nas versões (comentários do Ludusavi): a versão que um
# backup com falha deixou pela metade, e a cópia dos saves feita antes de uma restauração.
INCOMPLETA = "cartridges:incompleta"
ANTES_DE_RESTAURAR = "cartridges:antes-de-restaurar"

_trava = threading.Lock()
# Nome no Ludusavi -> versões, da mais nova para a mais velha. Lido pela tela
# (`tem_backup`) sem esperar a trava: a tela nunca fica parada atrás de um backup.
_cache: dict[str, list[Versao]] = {}
# Quantas restaurações pendentes cada jogo tem (nome no Ludusavi, e também o objeto `Game`,
# para o caso de o nome mudar no meio) e quantas de "Restaurar todos", para o jogo não
# abrir no meio. Contadores, e não um conjunto e uma marca: com dois pedidos seguidos, o
# fim do primeiro não pode soltar o jogo enquanto o segundo, na fila da trava, ainda vai
# gravar. Só a thread da tela os muda: a restauração soma logo depois de abrir a thread de
# trabalho, e o fim subtrai com `entregar_na_tela` (que só roda depois, quando a tela está
# livre). Por isso não precisam de trava, a tela os lê sem esperar um backup, e um pedido
# que não chega a abrir a thread não deixa marca.
_restaurando: Counter[str] = Counter()
_jogos_restaurando: Counter[int] = Counter()  # id do `Game`; vivo enquanto a thread o segura
_restaurando_todos = 0  # pylint: disable=invalid-name
# Quantas tarefas visíveis de backup ou restauração estão de pé. Ao contrário dos de cima,
# sobe na thread da tela e desce nas threads de trabalho, por isso a trava própria.
_tarefas_abertas = 0  # pylint: disable=invalid-name
_trava_tarefas = threading.Lock()


def trava_dos_saves() -> threading.Lock:
    """A trava que cobre o Ludusavi e a pasta dos saves, para quem precisa de uma
    pasta dos saves estável (o backup do app): ``with trava_dos_saves(): ...``."""
    return _trava


def disponivel() -> bool:
    return ludusavi.executavel() is not None


def em_andamento() -> bool:
    """Há um backup ou uma restauração pedidos e ainda não terminados. Conta desde o
    pedido, quando a tarefa visível nasce: fechar o app na busca do nome ou na espera pela
    trava perderia a operação sem aviso, e no meio dela deixaria o `ludusavi.exe` órfão."""
    with _trava_tarefas:
        return _tarefas_abertas > 0


def _somar_tarefa(passo: int) -> None:
    global _tarefas_abertas  # pylint: disable=global-statement
    with _trava_tarefas:
        _tarefas_abertas += passo


def _comecar_tarefa(nome: str, total: int) -> tarefas.Tarefa:
    """`tarefas.comecar`, contada em `em_andamento`. Soma antes: a tarefa nunca fica
    à vista sem a contagem."""
    _somar_tarefa(1)
    try:
        return tarefas.comecar(nome, total)
    except BaseException:
        _somar_tarefa(-1)
        raise


def _terminar_tarefa(tarefa: tarefas.Tarefa) -> None:
    try:
        tarefa.terminar()
    finally:
        _somar_tarefa(-1)


def _pasta_config() -> Path:
    return shared.app_dir / "ludusavi"


def _biblioteca() -> list[Game]:
    """Os jogos da biblioteca. Quem chama na thread da tela tira o instantâneo antes de
    abrir a thread de trabalho, que então só lê atributos; o store itera sobre uma
    cópia protegida por trava, então chamar de outra thread também é seguro."""
    return [jogo for jogo in shared.store if not jogo.removed and not jogo.blacklisted]


def _em_segundo_plano(alvo, *argumentos) -> None:
    threading.Thread(target=alvo, args=argumentos, daemon=True).start()


def _no_config(
    game: Game, no_manifesto: bool = True, nome: str | None = None
) -> config.JogoNoConfig:
    # Todo nome guardado vai como "extend". O Ludusavi 0.31 trata "extend" de um nome
    # que o manifesto não conhece como uma entrada própria (conferido), e se o manifesto
    # ganhar esse nome mais tarde, juntar os caminhos dele é o desejado. Por isso o
    # config não precisa lembrar se o nome veio do manifesto ou foi criado aqui.
    # ``nome``: o de quando a operação foi pedida, que o diálogo de detalhes pode ter limpado.
    return config.JogoNoConfig(
        nome or game.ludusavi_nome, game.steam_appid, game.executable, no_manifesto
    )


def _preparar(
    biblioteca: list[Game],
    atual: config.JogoNoConfig | None = None,
    redirecionamentos: list[tuple[str, str]] | None = None,
) -> None:
    """Grava o `config.yaml` desta chamada. Sempre sob a trava. Os `redirecionamentos`
    são os da restauração que vem a seguir."""
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
    config.gravar(
        config.montar(lista, escolhida, config.raizes(lista), redirecionamentos or ()),
        _pasta_config(),
    )


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


def _nao_abriu(tarefa: tarefas.Tarefa | None, aviso: str) -> None:
    """O pedido não chegou a abrir a thread de trabalho: desfaz a tarefa e avisa o usuário.
    Quem chama registra a exceção; nada sobe para a tela que pediu."""
    if tarefa is not None:
        _terminar_tarefa(tarefa)
    _avisar(aviso)


def _nada_para_restaurar() -> bool:
    if shared.win is not None:
        create_dialog(
            shared.win,
            _("Nada para restaurar"),
            _("Nenhum jogo tem cópias dos saves para restaurar."),
        )
    return False


def _restauracao_incompleta(falhas: list[tuple[str, str]]) -> bool:
    """O fim de "Restaurar todos" com falhas; ``falhas``: (nome do jogo, aviso) de cada
    jogo que não foi restaurado. Diálogo, e não aviso: o pedido vem das Preferências, e um
    aviso ficaria escondido atrás delas. Uma falha mostra o aviso dela, que diz o que
    fazer; várias, os nomes dos jogos."""
    if shared.win is None:
        return False
    if len(falhas) == 1:
        corpo = falhas[0][1]
    else:
        # O mesmo jogo em duas lojas aparece uma vez.
        nomes = list(dict.fromkeys(nome for nome, _aviso in falhas))
        juntos = ", ".join(nomes[:-1]) + _(" e ") + nomes[-1] if len(nomes) > 1 else nomes[0]
        corpo = _("Não foi possível restaurar os saves dos seguintes jogos: {}.").format(juntos)
    create_dialog(shared.win, _("Restauração incompleta"), corpo)
    return False


def _marcar_nova(nome: str, inicio: datetime, comentario: str) -> None:
    """Grava ``comentario`` na versão mais nova do jogo, só se ela foi criada depois de
    ``inicio``: um backup sem mudança não cria versão, e uma versão antiga nunca leva a
    marca de outra operação. Sob a trava. Nunca levanta: a falha vai para o log."""
    try:
        lista = ludusavi.versoes(_pasta_config(), executor).get(nome)
        if lista and lista[0].quando >= inicio:
            ludusavi.marcar(nome, lista[0].id, comentario, _pasta_config(), executor)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.exception("Não foi possível marcar a versão nova dos saves de %s", nome)


def _exigir_manifesto() -> None:
    """Antes de todo `ludusavi.fazer_backup`. Sem o manifesto, o Ludusavi copia só os
    caminhos do config (emulador, pasta do jogo) e sai com 0: a versão ficaria sem o save
    que o manifesto aponta, e sem marca de incompleta."""
    if not ludusavi.manifesto_baixado(_pasta_config()):
        raise LudusaviFalhou("o manifesto do Ludusavi não foi baixado")


def _salvar(game: Game) -> bool:
    game.save()
    return False


def _resolver(game: Game) -> Optional[config.JogoNoConfig]:
    """O jogo como o Ludusavi o conhece, ou None se não há como backupear. Sob a trava.

    A primeira vez só liga o jogo sozinho se o manifesto tem o appID dele (e guarda o
    nome); as seguintes usam o guardado. Qualquer outro caso (sem appID, ou appID fora
    do manifesto) fica sem backup até o usuário indicar o jogo nas opções avançadas:
    nada de palpite pelo título nem de entrada própria. Sem o manifesto baixado, "não
    achado" não quer dizer nada: levanta e nada é guardado.
    """
    if game.backup_dos_saves_desligado:
        logging.info("O backup dos saves de %s está desligado", game.name)
        return None
    if game.ludusavi_nome:
        return _no_config(game)
    pasta_config = _pasta_config()
    if not ludusavi.manifesto_baixado(pasta_config):
        # Sem o manifesto o `find` também não acha nada, e o jogo ficaria sem backup em silêncio.
        raise LudusaviFalhou("o manifesto do Ludusavi ainda não foi baixado")
    nome = ludusavi.nome_por_appid(game.steam_appid, pasta_config, executor) if game.steam_appid else None
    if nome is None:
        return None  # ver `_local_desconhecido`
    jogo = config.JogoNoConfig(nome, game.steam_appid, game.executable, True)
    game.ludusavi_nome = nome
    entregar_na_tela(_salvar, game)
    return jogo


def _local_desconhecido(game: Game) -> None:
    """Sem o appID no manifesto e sem jogo escolhido nas opções avançadas, o jogo não
    tem backup. O usuário é avisado num diálogo até responder a ele (e então a marca é
    gravada no jogo); nas sessões seguintes, só o log. Sob a trava."""
    logging.info("O local dos saves de %s é desconhecido: sem backup", game.name)
    if not game.saves_local_desconhecido_avisado:
        entregar_na_tela(_avisar_local_desconhecido, game)


# Os jogos (`id` do objeto) com o diálogo de `_avisar_local_desconhecido` na tela: duas
# sessões seguidas não abrem dois. Só a thread da tela o usa.
_local_desconhecido_na_tela: set[int] = set()


def _avisar_local_desconhecido(game: Game) -> bool:
    """Diálogo, e não aviso: o jogo fica sem backup dos saves até ser identificado, e um
    aviso que passasse despercebido (ou que o app fechasse antes de mostrar) não voltaria.
    A marca só é gravada quando o usuário responde: fechado o app antes disso, o diálogo
    volta no fim da próxima sessão."""
    if (
        shared.win is None
        or game.saves_local_desconhecido_avisado
        or id(game) in _local_desconhecido_na_tela
    ):
        return False
    _local_desconhecido_na_tela.add(id(game))
    create_dialog(
        shared.win,
        _("Saves sem backup"),
        _(
            "Não foi possível identificar os saves de {}. Indique o jogo nas opções "
            "avançadas para que o backup seja feito."
        ).format(game.name),
        "editar",
        _("Editar jogo"),
    ).connect("response", _ao_responder_local_desconhecido, game)
    return False


def _ao_responder_local_desconhecido(_dialogo, resposta: str, game: Game) -> None:
    _local_desconhecido_na_tela.discard(id(game))
    game.saves_local_desconhecido_avisado = True
    game.save()
    if resposta != "editar" or game.removed:
        return
    # Aqui, e não no topo: o diálogo de detalhes puxa a interface inteira (seletores,
    # Pillow), que o backup em si não usa.
    from cartridges.details_dialog import (  # pylint: disable=import-outside-toplevel
        DetailsDialog,
    )

    if not DetailsDialog.is_open:
        DetailsDialog(game, avancadas_abertas=True).present(shared.win)


# -- backup ------------------------------------------------------------------


def no_fim_da_sessao(game: Game) -> None:
    """Dispara o backup do jogo e volta na hora. A tarefa nasce aqui (ver `em_andamento`)
    e a thread de trabalho a termina."""
    if not disponivel():
        return
    tarefa = None
    try:
        biblioteca = _biblioteca()
        tarefa = _comecar_tarefa(_("Backup dos saves de {}").format(game.name), 1)
        _em_segundo_plano(_backup, game, biblioteca, tarefa)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.exception("O backup dos saves de %s não chegou a começar", game.name)
        _nao_abriu(tarefa, _("Não foi possível fazer o backup dos saves de {}.").format(game.name))


def _limite_do_backup(nome: str) -> int | None:
    """O ``limite`` do backup normal: as cópias guardadas mais as incompletas do jogo. A
    retenção do Ludusavi conta as incompletas como versões completas; sem esta folga,
    cada backup que falha empurraria para fora uma versão boa, e uma sequência de falhas
    deixaria só incompletas. None (a retenção do config) quando não há incompleta."""
    incompletas = sum(1 for v in _cache.get(nome, []) if v.comentario == INCOMPLETA)
    if not incompletas:
        return None
    return min(config.COPIAS_GUARDADAS + incompletas, 255)


def _backup(game: Game, biblioteca: list[Game], tarefa: tarefas.Tarefa) -> None:
    with _trava:
        try:
            jogo = _resolver(game)
            if jogo is None:
                if not game.backup_dos_saves_desligado:
                    _local_desconhecido(game)
                return  # sem o que copiar: o `finally` desfaz a tarefa
            _preparar(biblioteca, jogo)
            _exigir_manifesto()
            inicio = datetime.now(timezone.utc)
            try:
                limite = _limite_do_backup(jogo.nome)
                ludusavi.fazer_backup(jogo.nome, _pasta_config(), executor, limite)
            except LudusaviFalhou:
                # O Ludusavi cria a versão mesmo quando um arquivo falha; só a falha do
                # próprio backup deixa uma versão nova, então só ela é marcada. Relê as
                # versões: a lista mostra a incompleta e não oferece o que a retenção
                # do Ludusavi apagou nessa rodada.
                _marcar_nova(jogo.nome, inicio, INCOMPLETA)
                _ler_versoes(biblioteca)
                raise
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Backup dos saves de %s falhou", game.name)
            _avisar(_("Não foi possível fazer o backup dos saves de {}.").format(game.name))
        else:
            _ler_versoes(biblioteca)
        finally:
            _terminar_tarefa(tarefa)


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


def _restaurar_um(
    game: Game, nome: str, versao: Versao, biblioteca: list[Game]
) -> str | None:
    """Restaura ``versao`` (do jogo ``nome`` no Ludusavi) sem arriscar o save atual. Sob a
    trava. None se restaurou; senão, o aviso para o usuário.

    Nesta ordem, e qualquer falha interrompe tudo antes do `restore`: o zip da versão
    tem de estar inteiro (o Ludusavi grava uma versão danificada por cima do save e só
    depois acusa o erro); os saves atuais viram uma versão nova; os caminhos do zip são
    levados ao usuário e à pasta do jogo de hoje; a prévia só pode gravar em pastas
    de save, e só por cima do que a cópia dos saves atuais guardou.
    """
    if game.ludusavi_nome != nome:
        # O nome mudou depois do pedido (o diálogo de detalhes limpa o nome ao corrigir o
        # appID): o config de agora já não leva o que `nome` precisava (emulador, pasta do
        # jogo), e a cópia dos saves atuais sairia incompleta. Nada é copiado nem gravado.
        logging.warning(
            "O nome de %s no Ludusavi mudou de %r para %r durante a restauração: abortada",
            game.name,
            nome,
            game.ludusavi_nome,
        )
        return _("Não foi possível restaurar o save de {}.").format(game.name)
    jogo = _no_config(game, nome=nome)
    try:
        arquivo = versao.arquivo
        if arquivo is None or not conferencia.integra(arquivo):
            logging.warning(
                "O zip da versão %s dos saves de %s está danificado ou sumiu", versao.id, game.name
            )
            return _(
                "A versão escolhida dos saves de {} está danificada e não foi restaurada."
            ).format(game.name)
        _exigir_manifesto()  # fora do `try` de baixo: não é o jogo aberto
        inicio = datetime.now(timezone.utc)
        try:
            # Uma cópia a mais que as guardadas: no limite normal, a cópia apagaria a
            # mais antiga, que pode ser a escolhida.
            limite = min(len(_cache.get(nome, [])) + 1, 255)
            copiados = ludusavi.fazer_backup(nome, _pasta_config(), executor, limite)
        except LudusaviFalhou:
            logging.exception("A cópia dos saves atuais de %s falhou", game.name)
            _marcar_nova(nome, inicio, INCOMPLETA)
            return _(
                "Não foi possível guardar os saves atuais de {} antes da restauração. "
                "Verifique se o jogo está fechado e tente novamente."
            ).format(game.name)
        _marcar_nova(nome, inicio, ANTES_DE_RESTAURAR)
        bases = arquivos.bases_do_jogo(game.executable)
        caminhos = conferencia.caminhos_no_zip(arquivo)
        pastas = arquivos.pastas_do_sistema()
        # O mesmo config na prévia e no `restore`: o que foi conferido é o que se grava.
        _preparar(
            biblioteca,
            jogo,
            conferencia.redirecionamentos(caminhos, Path.home(), bases, _do_sistema(pastas)),
        )
        previa = ludusavi.previa(nome, _pasta_config(), versao.id, executor)
        limites = conferencia.raizes(
            pastas, Path.home(), [raiz for _loja, raiz in config.raizes([jogo])] + bases
        )
        if (aviso := _conferir_previa(game, previa, limites, copiados)) is not None:
            return aviso
        ludusavi.restaurar(nome, _pasta_config(), versao.id, executor)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.exception("Restauração do save de %s falhou", game.name)
        return _("Não foi possível restaurar o save de {}.").format(game.name)
    return None


def _do_sistema(pastas: arquivos.Pastas) -> tuple[Path, ...]:
    """As pastas do Windows onde um save comum mora (nunca a pasta de um jogo)."""
    return (
        pastas.appdata,
        pastas.localappdata,
        pastas.documentos,
        pastas.documentos_publicos.parent,
        pastas.programdata,
    )


def _conferir_previa(
    game: Game, previa: ludusavi.Previa, limites: conferencia.Raizes, copiados: tuple[str, ...]
) -> str | None:
    """O aviso para o usuário se a prévia não pode virar restauração, senão None: um destino
    fora das pastas de save, ou um save de hoje que a cópia dos saves atuais não guardou (o
    config de agora não cobre o caminho dele), que a restauração perderia de vez."""
    if (recusado := conferencia.recusado(previa, limites)) is not None:
        logging.warning(
            "A restauração dos saves de %s gravaria em %r: recusada", game.name, recusado
        )
        return _(
            "O backup dos saves de {} contém arquivos fora das pastas de save "
            "e não foi restaurado."
        ).format(game.name)
    if (perdido := conferencia.fora_da_copia(previa, copiados)) is not None:
        logging.warning(
            "A restauração dos saves de %s gravaria por cima de %r, que a cópia dos saves "
            "atuais não guardou: recusada",
            game.name,
            perdido,
        )
        return _("Não foi possível restaurar o save de {}.").format(game.name)
    return None


def restaurando(game: Game) -> bool:
    """Os saves do jogo estão sendo restaurados (sozinhos ou em "Restaurar todos"). Só
    na thread da tela."""
    nome = game.ludusavi_nome
    # Pelo objeto também: o nome pode ter sido limpado no meio da restauração.
    return id(game) in _jogos_restaurando or (
        bool(nome) and (_restaurando_todos > 0 or nome in _restaurando)
    )


def _marcar_jogo(jogo: int, passo: int) -> None:
    _jogos_restaurando[jogo] += passo
    if _jogos_restaurando[jogo] <= 0:
        del _jogos_restaurando[jogo]


def _marcar(nome: str, jogo: int, passo: int) -> None:
    """Soma ``passo`` (1 ou -1) à marca de um pedido de restauração: a de ``nome`` e a do
    objeto ``jogo``. Zerada, a chave sai. Só na thread da tela."""
    _restaurando[nome] += passo
    if _restaurando[nome] <= 0:
        del _restaurando[nome]
    _marcar_jogo(jogo, passo)


def _marcar_todos(passo: int, jogos: list[int]) -> None:
    """O mesmo para "Restaurar todos": a marca geral e a de cada objeto ``jogos`` (os que
    tinham nome ao pedir; o nome de um deles pode ser limpo durante a execução)."""
    global _restaurando_todos  # pylint: disable=global-statement
    _restaurando_todos += passo
    for jogo in jogos:
        _marcar_jogo(jogo, passo)


def _desmarcar(nome: str, jogo: int) -> bool:
    """Fim de uma restauração (callback da tela). O jogo só volta a poder abrir quando o
    último pedido acaba."""
    _marcar(nome, jogo, -1)
    return False


def _desmarcar_todos(jogos: list[int]) -> bool:
    _marcar_todos(-1, jogos)
    return False


def restaurar(game: Game, versao: str) -> None:
    """Devolve os saves do jogo aos da versão ``versao`` (o `id`), guardando os atuais antes."""
    nome = game.ludusavi_nome
    if not (disponivel() and nome):
        return
    tarefa = None
    try:
        biblioteca = _biblioteca()
        tarefa = _comecar_tarefa(_("Restaurando o save de {}").format(game.name), 1)
        _em_segundo_plano(_restaurar, game, nome, versao, biblioteca, tarefa)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.exception("A restauração do save de %s não chegou a começar", game.name)
        _nao_abriu(tarefa, _("Não foi possível restaurar o save de {}.").format(game.name))
        return
    _marcar(nome, id(game), 1)  # depois da thread aberta (ver `_restaurando`)


def _restaurar(
    game: Game, nome: str, versao: str, biblioteca: list[Game], tarefa: tarefas.Tarefa
) -> None:
    try:
        with _trava:
            # Relidas agora: o zip e o número de versões (o limite da cópia) são os de hoje.
            achada = None
            if _ler_versoes(biblioteca):
                versoes = _cache.get(nome, [])
                achada = next((v for v in versoes if v.id == versao), None)
            if achada is None:
                logging.warning("A versão %s dos saves de %s não foi encontrada", versao, game.name)
                aviso = _("Não foi possível restaurar o save de {}.").format(game.name)
            else:
                aviso = _restaurar_um(game, nome, achada, biblioteca)
            if aviso is not None:
                _avisar(aviso)
            _ler_versoes(biblioteca)
    finally:
        _terminar_tarefa(tarefa)
        entregar_na_tela(_desmarcar, nome, id(game))


def restaurar_todos() -> None:
    """Restaura a versão completa mais recente de cada jogo da biblioteca que tem backup."""
    if not disponivel():
        return
    tarefa = None
    try:
        biblioteca = _biblioteca()
        pedidos = [(jogo, jogo.ludusavi_nome) for jogo in biblioteca if jogo.ludusavi_nome]
        if not pedidos:  # sem nome no Ludusavi, nenhum jogo tem backup
            entregar_na_tela(_nada_para_restaurar)
            return
        # Total provisório (nunca 0): os nomes com cópias no cache, ou todos os nomes se o
        # cache ainda está vazio. A thread de trabalho o acerta quando souber quem tem backup.
        nomes = {nome for _jogo, nome in pedidos}
        provisorio = sum(1 for nome in nomes if _cache.get(nome)) or len(nomes)
        tarefa = _comecar_tarefa(_("Restaurando os saves"), provisorio)
        _em_segundo_plano(_restaurar_todos, biblioteca, pedidos, tarefa)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.exception("A restauração dos saves não chegou a começar")
        _nao_abriu(tarefa, _("Não foi possível restaurar os saves."))
        return
    # Depois da thread aberta (ver `_restaurando`).
    _marcar_todos(1, [id(jogo) for jogo, _nome in pedidos])


def _restaurar_todos(
    biblioteca: list[Game], pedidos: list[tuple[Game, str]], tarefa: tarefas.Tarefa
) -> None:
    """``pedidos``: cada jogo com o nome que tinha no pedido. Os alvos saem deles, e não dos
    nomes de agora: um jogo cujo nome foi limpo na fila (o diálogo de detalhes, ao corrigir
    o appID) continua com cópias e, sem poder ser restaurado, entra no aviso de falha."""
    try:
        with _trava:
            # O cache pode estar vazio (nada o encheu ainda) ou velho: relê antes. Sem
            # conseguir ler, não há como saber o que restaurar, e o usuário precisa saber.
            if not _ler_versoes(biblioteca):
                _avisar(_("Não foi possível restaurar os saves."))
                return
            # Por nome, como no config: o mesmo jogo em duas lojas tem um nome só no Ludusavi.
            jogos: dict[str, list[Game]] = {}
            for jogo, nome in pedidos:
                jogos.setdefault(nome, []).append(jogo)
            alvos = [nome for nome in jogos if _cache.get(nome)]
            if not alvos:
                entregar_na_tela(_nada_para_restaurar)
                return
            falhas: list[tuple[str, str]] = []  # (nome do jogo, aviso)
            for feitos, nome in enumerate(alvos):
                tarefa.atualizar(feitos, len(alvos))
                # Um que ainda tenha o nome do pedido; sem nenhum, `_restaurar_um` aborta (falha).
                jogo = next((j for j in jogos[nome] if j.ludusavi_nome == nome), jogos[nome][0])
                # A completa: restaurar uma incompleta deixaria o save misturado.
                versao = next((v for v in _cache[nome] if v.comentario != INCOMPLETA), None)
                if versao is None:
                    logging.warning("Os saves de %s só têm versões incompletas", jogo.name)
                    aviso = _(
                        "Não foi possível restaurar os saves de {}: "
                        "todas as cópias deste jogo estão incompletas."
                    ).format(jogo.name)
                else:
                    aviso = _restaurar_um(jogo, nome, versao, biblioteca)
                if aviso is not None:
                    falhas.append((jogo.name, aviso))
            # Um aviso só, no fim: uma falha por jogo viraria uma fila de avisos.
            if falhas:
                entregar_na_tela(_restauracao_incompleta, falhas)
            _ler_versoes(biblioteca)
    finally:
        _terminar_tarefa(tarefa)
        entregar_na_tela(_desmarcar_todos, [id(jogo) for jogo, _nome in pedidos])


# -- pasta dos saves ---------------------------------------------------------


def trocar_pasta(nova: Path) -> None:
    """Troca a pasta dos saves sem que um backup ou restauração esteja rodando.

    Espera a trava, então quem chama (as Preferências) deve fazê-lo fora da thread
    da tela. Levanta `pasta.TrocaRecusada`, sem mexer em nada, se a troca não vale.
    """
    with _trava:
        pasta.trocar(nova)
    atualizar_cache()
