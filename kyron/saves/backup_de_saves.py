"""O backup e a restauração dos saves, jogo a jogo, em segundo plano.

Cada operação roda numa thread, aparece como tarefa desde o pedido e só fala com o usuário quando falha (ou quando
"Restaurar todos" não acha nada). Uma trava única cobre gravar o `config.yaml` e rodar o Ludusavi: sessões em sequência
esperam uma pela outra e a troca da pasta dos saves nunca cai no meio de um backup. O config de cada chamada leva todos
os jogos com nome no Ludusavi, para o `restore` de qualquer um achar a sua entrada.
"""

import logging
import subprocess
import threading
import time
import weakref
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from kyron import shared
from kyron.conquistas import arquivos
from kyron.jogo import Jogo
from kyron.saves import conferencia, config, ludusavi, pasta
from kyron.saves.ludusavi import LudusaviFalhou, Versao
from kyron.modelos import tarefas
from kyron.utils.thread_principal import na_thread_principal

# Os testes trocam por um executor falso; é o que `ludusavi.rodar` recebe.
executor = subprocess.run

# Espera depois de uma tentativa falha de baixar o manifesto; curta, para cobrir o resto de um "Restaurar todos" sem segurar quem tenta de novo.
PAUSA_DO_MANIFESTO = 60
_manifesto_falhou_em: float | None = None  # `time.monotonic()` da última falha

# As marcas que o app grava nas versões (comentários do Ludusavi): a versão que um
# backup com falha deixou pela metade, e a cópia dos saves feita antes de uma restauração.
INCOMPLETA = "cartridges:incompleta"
ANTES_DE_RESTAURAR = "cartridges:antes-de-restaurar"

_trava = threading.Lock()
# Nome no Ludusavi -> versões, da mais nova para a mais velha. Lido pela tela
# (`tem_backup`) sem esperar a trava: a tela nunca fica parada atrás de um backup.
_cache: dict[str, list[Versao]] = {}
# Restaurações pendentes por jogo (nome no Ludusavi e objeto `Jogo`, caso o nome mude no meio) e de "Restaurar todos", para o jogo não abrir no meio. Contadores e não conjunto: o fim do primeiro pedido não pode soltar o jogo enquanto o segundo, na fila da trava, ainda vai gravar. Só a thread da tela os muda (soma ao abrir a thread de trabalho; subtrai em `na_thread_principal`), por isso dispensam trava.
_restaurando: Counter[str] = Counter()
_jogos_restaurando: Counter[int] = Counter()  # id do `Jogo`; vivo enquanto a thread o segura
_restaurando_todos = 0  # pylint: disable=invalid-name
# Quantas tarefas visíveis de backup ou restauração estão de pé. Ao contrário dos de cima,
# sobe na thread da tela e desce nas threads de trabalho, por isso a trava própria.
_tarefas_abertas = 0  # pylint: disable=invalid-name
_trava_tarefas = threading.Lock()


def trava_dos_saves() -> threading.Lock:
    """A trava que cobre o Ludusavi e a pasta dos saves: ``with trava_dos_saves(): ...`` para quem precisa dela estável (o backup do app)."""
    return _trava


def disponivel() -> bool:
    return ludusavi.executavel() is not None


def em_andamento() -> bool:
    """Há backup ou restauração pedido e não terminado. Conta desde o pedido: fechar o app na busca do nome ou na espera pela trava perderia a operação e deixaria o `ludusavi.exe` órfão."""
    with _trava_tarefas:
        return _tarefas_abertas > 0


def _somar_tarefa(passo: int) -> None:
    global _tarefas_abertas  # pylint: disable=global-statement
    with _trava_tarefas:
        _tarefas_abertas += passo


def comecar_tarefa(nome: str, total: int) -> tarefas.Tarefa:
    """`tarefas.comecar`, contada em `em_andamento`; soma antes, para a tarefa nunca ficar à vista sem a contagem."""
    _somar_tarefa(1)
    try:
        return tarefas.comecar(nome, total)
    except BaseException:
        _somar_tarefa(-1)
        raise


def terminar_tarefa(tarefa: tarefas.Tarefa) -> None:
    try:
        tarefa.terminar()
    finally:
        _somar_tarefa(-1)


def _pasta_config() -> Path:
    return shared.app_dir / "ludusavi"


def _biblioteca() -> list[Jogo]:
    """Os jogos da biblioteca. Na thread da tela, tire o instantâneo antes de abrir a thread de trabalho; o store itera sobre cópia protegida, então outra thread também é segura."""
    return [jogo for jogo in shared.store if not jogo.removed and not jogo.blacklisted]


def _em_segundo_plano(alvo, *argumentos) -> None:
    threading.Thread(target=alvo, args=argumentos, daemon=True).start()


def _no_config(
    game: Jogo, no_manifesto: bool = True, nome: str | None = None
) -> config.JogoNoConfig:
    # Todo nome guardado vai como "extend": o Ludusavi 0.31 trata "extend" de nome desconhecido como entrada própria, e se o manifesto o ganhar depois juntar os caminhos é o desejado. ``nome``: o de quando o pedido foi feito (o diálogo de detalhes pode tê-lo limpado).
    return config.JogoNoConfig(
        nome or game.ludusavi_nome, game.steam_appid, game.executable, no_manifesto
    )


def _preparar(
    biblioteca: list[Jogo],
    atual: config.JogoNoConfig | None = None,
    redirecionamentos: list[tuple[str, str]] | None = None,
) -> None:
    """Grava o `config.yaml` desta chamada, sempre sob a trava; `redirecionamentos` são os da restauração seguinte."""
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


def _ler_versoes(biblioteca: list[Jogo]) -> bool:
    """Relê as versões de todos os jogos, sob a trava; diz se conseguiu (falhar deixa o cache como estava)."""
    global _cache  # noqa: PLW0603
    try:
        _preparar(biblioteca)
        _cache = ludusavi.versoes(_pasta_config(), executor)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.exception("Não foi possível ler os backups dos saves")
        return False
    return True


def _mostrar_aviso(texto: str) -> None:
    # A `FilaDeAvisos` mostra sempre texto puro: o nome do jogo no texto não é marcação.
    aplicativo = shared.aplicativo
    if aplicativo is None:
        logging.warning("Aviso sem janela: %s", texto)
    else:
        aplicativo.avisos.adicionar(texto)


def _avisar(texto: str) -> None:
    na_thread_principal(_mostrar_aviso, texto)


def _nao_abriu(tarefa: tarefas.Tarefa | None, aviso: str) -> None:
    """O pedido não chegou a abrir a thread de trabalho: desfaz a tarefa e avisa. Quem chama registra a exceção."""
    if tarefa is not None:
        terminar_tarefa(tarefa)
    _avisar(aviso)


def _dialogo(titulo: str, corpo: str) -> None:
    """Um aviso com o botão "Dispensar", pela fila de diálogos do app; sem app, só o log."""
    aplicativo = shared.aplicativo
    if aplicativo is None:
        logging.warning("%s: %s", titulo, corpo)
    else:
        aplicativo.pedir_dialogo(titulo, corpo, [], lambda: None)


def _nada_para_restaurar() -> None:
    _dialogo(_("Nada para restaurar"), _("Nenhum jogo tem cópias dos saves para restaurar."))


def _restauracao_incompleta(falhas: list[tuple[str, str]]) -> None:
    """Fim de "Restaurar todos" com falhas (``falhas``: nome do jogo e aviso). Diálogo e não aviso: o pedido vem das Preferências, que esconderiam um aviso. Uma falha mostra o aviso dela; várias, os nomes."""
    if len(falhas) == 1:
        corpo = falhas[0][1]
    else:
        nomes = list(dict.fromkeys(nome for nome, _aviso in falhas))
        juntos = ", ".join(nomes[:-1]) + _(" e ") + nomes[-1] if len(nomes) > 1 else nomes[0]
        corpo = _("Não foi possível restaurar os saves dos seguintes jogos: {}.").format(juntos)
    _dialogo(_("Restauração incompleta"), corpo)


def _marcar_nova(nome: str, inicio: datetime, comentario: str) -> None:
    """Grava ``comentario`` na versão mais nova só se criada depois de ``inicio`` (um backup sem mudança não cria versão). Sob a trava; nunca levanta."""
    try:
        lista = ludusavi.versoes(_pasta_config(), executor).get(nome)
        if lista and lista[0].quando >= inicio:
            ludusavi.marcar(nome, lista[0].id, comentario, _pasta_config(), executor)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.exception("Não foi possível marcar a versão nova dos saves de %s", nome)


def _exigir_manifesto() -> None:
    """Antes de todo `ludusavi.fazer_backup`: sem o manifesto o Ludusavi copia só os caminhos do config e sai com 0, deixando a versão sem o save do manifesto e sem marca de incompleta."""
    if not _garantir_manifesto(_pasta_config()):
        raise LudusaviFalhou("o manifesto do Ludusavi não foi baixado")


def _garantir_manifesto(pasta_config: Path) -> bool:
    """O manifesto está baixado, baixando-o se falta (instalação nova, ou pasta do Ludusavi perdida: fica fora do backup do app). Sob a trava."""
    global _manifesto_falhou_em  # pylint: disable=global-statement
    if ludusavi.manifesto_baixado(pasta_config):
        return True
    # Logo depois de uma falha, não tenta de novo: "Restaurar todos" pede o manifesto uma
    # vez por jogo, e cada tentativa sem rede pode esperar o limite inteiro.
    if _manifesto_falhou_em is not None and time.monotonic() - _manifesto_falhou_em < PAUSA_DO_MANIFESTO:
        return False
    try:
        ludusavi.baixar_manifesto(pasta_config, executor)
    except LudusaviFalhou as erro:
        logging.warning("Não foi possível baixar o manifesto do Ludusavi: %s", erro)
    if ludusavi.manifesto_baixado(pasta_config):
        return True
    _manifesto_falhou_em = time.monotonic()
    return False


def _salvar(game: Jogo) -> None:
    game.save()


def _resolver(game: Jogo) -> Optional[config.JogoNoConfig]:
    """O jogo como o Ludusavi o conhece, ou None se não há como backupear. Sob a trava.

    A primeira vez só liga o jogo sozinho se o manifesto tem o appID dele (guardando o nome); sem appID, ou com appID fora do manifesto, fica sem backup até o usuário indicar o jogo nas opções avançadas, sem palpite pelo título. Sem o manifesto baixado, "não achado" não significa nada: levanta e nada é guardado.
    """
    if game.backup_dos_saves_desligado:
        logging.info("O backup dos saves de %s está desligado", game.name)
        return None
    if game.ludusavi_nome:
        return _no_config(game)
    pasta_config = _pasta_config()
    if not _garantir_manifesto(pasta_config):
        # Sem o manifesto o `find` também não acha nada, e o jogo ficaria sem backup em silêncio.
        raise LudusaviFalhou("o manifesto do Ludusavi ainda não foi baixado")
    nome = ludusavi.nome_por_appid(game.steam_appid, pasta_config, executor) if game.steam_appid else None
    if nome is None:
        return None  # ver `_local_desconhecido`
    jogo = config.JogoNoConfig(nome, game.steam_appid, game.executable, True)
    game.ludusavi_nome = nome
    na_thread_principal(_salvar, game)
    return jogo


def _local_desconhecido(game: Jogo) -> None:
    """Jogo sem appID no manifesto e sem jogo escolhido nas opções avançadas fica sem backup. O diálogo avisa até o usuário responder (a marca é gravada no jogo); depois, só o log. Sob a trava."""
    logging.info("O local dos saves de %s é desconhecido: sem backup", game.name)
    if not game.saves_local_desconhecido_avisado:
        na_thread_principal(_avisar_local_desconhecido, game)


# Os jogos (`game_id`) com o diálogo de `_avisar_local_desconhecido` na tela: duas
# sessões seguidas não abrem dois. Só a thread da tela o usa.
_local_desconhecido_na_tela: set[str] = set()


def _avisar_local_desconhecido(game: Jogo) -> None:
    """Pergunta, e não aviso: o jogo fica sem backup até ser identificado, e um aviso despercebido não voltaria. A marca só é gravada na resposta; fechado o app antes, a pergunta volta na próxima sessão."""
    aplicativo = shared.aplicativo
    if aplicativo is None or game.saves_local_desconhecido_avisado or game.game_id in _local_desconhecido_na_tela:
        return
    chave = game.game_id
    _local_desconhecido_na_tela.add(chave)
    fraco = weakref.ref(game)  # a pergunta vive na fila do app, que não segura o jogo
    aplicativo.pedir_confirmacao(
        _("Saves sem backup"),
        _(
            "Não foi possível identificar os saves de {}. Indique o jogo nas opções "
            "avançadas para que o backup seja feito."
        ).format(game.name),
        _("Editar jogo"),
        lambda confirmou: _ao_responder_local_desconhecido(chave, fraco(), confirmou),
    )


def _ao_responder_local_desconhecido(chave: str, game: Jogo | None, confirmou: bool) -> None:
    _local_desconhecido_na_tela.discard(chave)
    if game is None:  # o jogo já não existe: não há marca a gravar
        return
    game.saves_local_desconhecido_avisado = True
    game.save()
    edicao = shared.edicao
    if confirmou and not game.removed and edicao is not None and not edicao.aberto:
        edicao.abrir(game.game_id, avancadas=True)


def no_fim_da_sessao(game: Jogo) -> None:
    """Dispara o backup do jogo e volta na hora; a tarefa nasce aqui (ver `em_andamento`) e a thread de trabalho a termina."""
    if not disponivel():
        return
    tarefa = None
    try:
        biblioteca = _biblioteca()
        tarefa = comecar_tarefa(_("Backup dos saves de {}").format(game.name), 1)
        _em_segundo_plano(_backup, game, biblioteca, tarefa)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.exception("O backup dos saves de %s não chegou a começar", game.name)
        _nao_abriu(tarefa, _("Não foi possível fazer o backup dos saves de {}.").format(game.name))


def _limite_do_backup(nome: str) -> int | None:
    """O ``limite`` do backup normal: as cópias guardadas mais as incompletas do jogo. A retenção do Ludusavi conta as incompletas como completas; sem a folga, falhas seguidas empurrariam as versões boas para fora. None quando não há incompleta."""
    incompletas = sum(1 for v in _cache.get(nome, []) if v.comentario == INCOMPLETA)
    if not incompletas:
        return None
    return min(config.COPIAS_GUARDADAS + incompletas, 255)


def _backup(game: Jogo, biblioteca: list[Jogo], tarefa: tarefas.Tarefa) -> None:
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
                # O Ludusavi cria a versão mesmo quando um arquivo falha; só a falha do próprio backup deixa versão nova, então só ela é marcada. Relê as versões para a lista mostrar a incompleta e não oferecer o que a retenção apagou.
                _marcar_nova(jogo.nome, inicio, INCOMPLETA)
                _ler_versoes(biblioteca)
                raise
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Backup dos saves de %s falhou", game.name)
            _avisar(_("Não foi possível fazer o backup dos saves de {}.").format(game.name))
        else:
            _ler_versoes(biblioteca)
        finally:
            terminar_tarefa(tarefa)


def tem_backup(game: Jogo) -> bool:
    return bool(_cache.get(game.ludusavi_nome))


def versoes_do_jogo(game: Jogo) -> list[Versao]:
    return list(_cache.get(game.ludusavi_nome, []))


def atualizar_cache() -> None:
    if disponivel():
        _em_segundo_plano(_atualizar_cache, _biblioteca())


def _atualizar_cache(biblioteca: list[Jogo]) -> None:
    with _trava:
        _ler_versoes(biblioteca)


def _restaurar_um(
    game: Jogo, nome: str, versao: Versao, biblioteca: list[Jogo]
) -> str | None:
    """Restaura ``versao`` (do jogo ``nome`` no Ludusavi) sem arriscar o save atual, sob a trava. None se restaurou; senão, o aviso.

    Qualquer falha interrompe antes do `restore`, nesta ordem: o zip da versão tem de estar inteiro (o Ludusavi grava uma versão danificada por cima do save e só depois acusa o erro); os saves atuais viram uma versão nova; os caminhos do zip vão ao usuário e à pasta do jogo de hoje; a prévia só grava em pastas de save, por cima do que a cópia dos saves atuais guardou.
    """
    if game.ludusavi_nome != nome:
        # O nome mudou depois do pedido (o diálogo de detalhes o limpa ao corrigir o appID): o config de agora não leva o que `nome` precisava e a cópia dos saves sairia incompleta. Nada é copiado nem gravado.
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
            # Uma cópia a mais: no limite normal a cópia apagaria a mais antiga, que pode ser a escolhida.
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
    game: Jogo, previa: ludusavi.Previa, limites: conferencia.Raizes, copiados: tuple[str, ...]
) -> str | None:
    """O aviso se a prévia não pode virar restauração, senão None: destino fora das pastas de save, ou save de hoje que a cópia dos saves atuais não guardou (a restauração o perderia)."""
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


def restaurando(game: Jogo) -> bool:
    """Os saves do jogo estão sendo restaurados (sozinhos ou em "Restaurar todos"). Só na thread da tela."""
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
    """O mesmo para "Restaurar todos": a marca geral e a de cada objeto ``jogos``."""
    global _restaurando_todos  # pylint: disable=global-statement
    _restaurando_todos += passo
    for jogo in jogos:
        _marcar_jogo(jogo, passo)


def _desmarcar(nome: str, jogo: int) -> bool:
    """Fim de uma restauração (callback da tela): o jogo só abre de novo quando o último pedido acaba."""
    _marcar(nome, jogo, -1)
    return False


def _desmarcar_todos(jogos: list[int]) -> bool:
    _marcar_todos(-1, jogos)
    return False


def restaurar(game: Jogo, versao: str) -> None:
    """Devolve os saves do jogo aos da versão ``versao`` (o `id`), guardando os atuais antes."""
    nome = game.ludusavi_nome
    if not (disponivel() and nome):
        return
    tarefa = None
    try:
        biblioteca = _biblioteca()
        tarefa = comecar_tarefa(_("Restaurando o save de {}").format(game.name), 1)
        _em_segundo_plano(_restaurar, game, nome, versao, biblioteca, tarefa)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.exception("A restauração do save de %s não chegou a começar", game.name)
        _nao_abriu(tarefa, _("Não foi possível restaurar o save de {}.").format(game.name))
        return
    _marcar(nome, id(game), 1)  # depois da thread aberta (ver `_restaurando`)


def _restaurar(
    game: Jogo, nome: str, versao: str, biblioteca: list[Jogo], tarefa: tarefas.Tarefa
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
        terminar_tarefa(tarefa)
        na_thread_principal(_desmarcar, nome, id(game))


def restaurar_todos() -> None:
    """Restaura a versão completa mais recente de cada jogo da biblioteca que tem backup."""
    if not disponivel():
        return
    tarefa = None
    try:
        biblioteca = _biblioteca()
        pedidos = [(jogo, jogo.ludusavi_nome) for jogo in biblioteca if jogo.ludusavi_nome]
        if not pedidos:  # sem nome no Ludusavi, nenhum jogo tem backup
            na_thread_principal(_nada_para_restaurar)
            return
        # Total provisório (nunca 0): os nomes com cópias no cache, ou todos se o cache está vazio; a thread de trabalho o acerta.
        nomes = {nome for _jogo, nome in pedidos}
        provisorio = sum(1 for nome in nomes if _cache.get(nome)) or len(nomes)
        tarefa = comecar_tarefa(_("Restaurando os saves"), provisorio)
        _em_segundo_plano(_restaurar_todos, biblioteca, pedidos, tarefa)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.exception("A restauração dos saves não chegou a começar")
        _nao_abriu(tarefa, _("Não foi possível restaurar os saves."))
        return
    # Depois da thread aberta (ver `_restaurando`).
    _marcar_todos(1, [id(jogo) for jogo, _nome in pedidos])


def _restaurar_todos(
    biblioteca: list[Jogo], pedidos: list[tuple[Jogo, str]], tarefa: tarefas.Tarefa
) -> None:
    """``pedidos``: cada jogo com o nome do pedido. Os alvos saem deles, não dos nomes de agora: um jogo com nome limpo na fila continua com cópias e, sem poder ser restaurado, entra no aviso de falha."""
    try:
        with _trava:
            # O cache pode estar vazio ou velho: relê. Sem conseguir ler, não há o que restaurar e o usuário precisa saber.
            if not _ler_versoes(biblioteca):
                _avisar(_("Não foi possível restaurar os saves."))
                return
            # Por nome, como no config: o mesmo jogo em duas lojas tem um nome só no Ludusavi.
            jogos: dict[str, list[Jogo]] = {}
            for jogo, nome in pedidos:
                jogos.setdefault(nome, []).append(jogo)
            alvos = [nome for nome in jogos if _cache.get(nome)]
            if not alvos:
                na_thread_principal(_nada_para_restaurar)
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
                na_thread_principal(_restauracao_incompleta, falhas)
            _ler_versoes(biblioteca)
    finally:
        terminar_tarefa(tarefa)
        na_thread_principal(_desmarcar_todos, [id(jogo) for jogo, _nome in pedidos])


def trocar_pasta(nova: Path) -> None:
    """Troca a pasta dos saves sem backup ou restauração rodando. Espera a trava (chamar fora da thread da tela); levanta `pasta.TrocaRecusada` sem mexer em nada se a troca não vale."""
    with _trava:
        pasta.trocar(nova)
    atualizar_cache()
