# copias_animadas.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cópias reduzidas das capas animadas, no tamanho em que são exibidas.

Tocar o GIF/WebP original na biblioteca decodificaria e redimensionaria
centenas de quadros grandes a cada volta. A cópia já sai no tamanho da tela e
com os quadros curtos fundidos, então o player só decodifica o que mostra.
"""

import contextlib
import io
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Callable, Literal
from uuid import uuid4

from PIL import Image, ImageSequence

try:
    from PIL import _webp
except ImportError:  # Pillow sem WebP: ``_PorQuadro`` cai no caminho da lista
    _webp = None  # pylint: disable=invalid-name

from cartridges import shared
from cartridges.utils import tarefas, tocador_capas
from cartridges.utils.na_tela import entregar_na_tela

# Como terminou um pedido. ``ilegivel`` é só a origem que não abre; ``falhou``
# é a cópia que não pôde ser gravada (disco cheio, permissão negada): nada foi
# gravado, a capa segue animada e o pedido pode ser repetido depois.
Resultado = Literal["pronta", "estatica", "ilegivel", "falhou"]

# Abaixo disto o quadro é fundido ao anterior: nenhuma tela mostra mais de
# ~30 quadros por segundo, e os quadros a mais só custariam decodificação.
QUADRO_MINIMO_MS = 30


class GravacaoFalhou(Exception):
    """Não foi possível gravar a cópia em ``destino``.

    Não herda de ``OSError`` de propósito: a origem ilegível sobe como
    ``OSError``, e quem chama precisa distinguir as duas falhas.
    """


def tamanhos() -> tuple[tuple[int, int], tuple[int, int]]:
    """(grade, detalhes): os dois tamanhos em que a capa é exibida."""
    return (
        (int(shared.display_size[0]), int(shared.display_size[1])),
        (int(shared.details_size[0]), int(shared.details_size[1])),
    )


def caminho_para(origem: Path, tamanho: tuple[int, int]) -> Path:
    """Onde fica a cópia de ``origem`` no ``tamanho`` pedido.

    As capas da biblioteca vão para o cache do app. As prévias dos seletores
    moram numa pasta temporária que o próprio seletor limpa: a cópia fica ao
    lado delas e some junto. O tamanho no nome faz uma mudança de escala gerar
    cópias novas, sem confundir com as do tamanho anterior.
    """
    nome = f"{origem.stem}_{tamanho[0]}x{tamanho[1]}.webp"
    if origem.parent == shared.covers_dir:
        return shared.capas_animadas_dir / nome
    return origem.with_name(nome)


class _CodificadorIndisponivel(Exception):
    """O ``_webp.WebPAnimEncoder`` do Pillow sumiu ou mudou de assinatura."""


# Vira True na primeira vez que o codificador quadro a quadro falha: daí em
# diante toda cópia vai direto pelo caminho da lista, e o aviso sai uma vez só.
_sem_codificador = False


class _PorQuadro:
    """Codifica cada quadro assim que ele chega, sem guardar a animação.

    Usa a API privada do Pillow (``_webp.WebPAnimEncoder``), na mesma ordem
    do ``WebPImagePlugin._save_all``: o ``save`` público só aceita a lista de
    todos os quadros, e uma cópia de detalhes inteira em RAM chegava a 600 MB.
    Qualquer ``AttributeError``/``TypeError`` vindo dela vira
    ``_CodificadorIndisponivel``, e ``gerar`` refaz pela lista.
    """

    def __init__(self, tamanho: tuple[int, int]) -> None:
        self._instante = 0
        try:
            # tamanho, fundo, loop, minimize_size, kmin, kmax, allow_mixed,
            # verbose; kmin/kmax são os padrões do Pillow para com perda.
            self._enc = _webp.WebPAnimEncoder(tamanho, 0, 0, False, 3, 5, False, False)
        except (AttributeError, TypeError) as erro:
            raise _CodificadorIndisponivel(erro) from erro

    def add(self, quadro: Image.Image, duracao: int) -> None:
        # lossless, quality, alpha_quality, method: os mesmos quality=90 e
        # method=4 do caminho da lista.
        try:
            self._enc.add(quadro.getim(), self._instante, False, 90.0, 100.0, 4)
        except (AttributeError, TypeError) as erro:
            raise _CodificadorIndisponivel(erro) from erro
        self._instante += duracao

    def dados(self) -> bytes:
        try:
            # O quadro vazio fecha a animação: o instante dele dá a duração do
            # último quadro.
            self._enc.add(None, self._instante, False, 90.0, 100.0, 0)
            dados = self._enc.assemble(b"", b"", b"")  # ICC, EXIF, XMP
        except (AttributeError, TypeError) as erro:
            raise _CodificadorIndisponivel(erro) from erro
        if dados is None:
            raise OSError("o codificador WebP não devolveu nada")
        return dados


class _EmLista:
    """O caminho público do Pillow: todos os quadros na memória até o fim.

    ponytail: só para o caso de a API privada do ``_PorQuadro`` mudar; o pico
    aqui é a animação inteira reduzida (até ~600 MB numa cópia de detalhes).
    """

    def __init__(self) -> None:
        self._quadros: list[Image.Image] = []
        self._duracoes: list[int] = []

    def add(self, quadro: Image.Image, duracao: int) -> None:
        self._quadros.append(quadro)
        self._duracoes.append(duracao)

    def dados(self) -> bytes:
        saida = io.BytesIO()
        self._quadros[0].save(
            saida, "WEBP", save_all=True, append_images=self._quadros[1:],
            duration=self._duracoes, loop=0, quality=90, method=4,
        )  # fmt: skip
        return saida.getvalue()


def _codificar(
    dados: bytes,
    tamanho: tuple[int, int],
    vigente: Callable[[], bool],
    saida: "_PorQuadro | _EmLista",
) -> bytes | None:
    """O WebP da cópia, ou None se não é animada ou deixou de ser vigente."""
    # O quadro reduzido que ainda espera: a duração dele só é final quando o
    # seguinte chega (um curto absorve o seguinte).
    pendente: Image.Image | None = None
    duracao_pendente = 0
    entregues = 0
    with Image.open(io.BytesIO(dados)) as imagem:
        for quadro in ImageSequence.Iterator(imagem):
            # Uma capa com centenas de quadros leva segundos: se a capa mudou
            # ou o app está fechando, para já. Como cada quadro é codificado
            # aqui mesmo, isto vale também para a codificação.
            if not vigente():
                return None
            # No WebP o Pillow só preenche info["duration"] ao decodificar o
            # quadro; lida antes, sai vazia e todo quadro valeria 100 ms.
            quadro.load()
            duracao = int(quadro.info.get("duration", 100)) or 100
            reduzido = quadro.convert("RGBA").resize(tamanho, Image.LANCZOS)
            if pendente is not None and duracao_pendente < QUADRO_MINIMO_MS:
                # O curto some e cede o tempo ao seguinte, que é o que aparece:
                # mostrar o relance curto pela duração do longo seria pior.
                pendente = reduzido
                duracao_pendente += duracao
                continue
            if pendente is not None:
                saida.add(pendente, duracao_pendente)
                entregues += 1
            pendente, duracao_pendente = reduzido, duracao
    if pendente is not None:
        if not vigente():
            return None
        saida.add(pendente, duracao_pendente)
        entregues += 1
    if entregues < 2:
        return None
    try:
        return saida.dados()
    except OSError as erro:
        # Falha de codificação não é origem ilegível.
        raise GravacaoFalhou() from erro


def gerar(
    origem: Path,
    destino: Path,
    tamanho: tuple[int, int],
    vigente: Callable[[], bool] = lambda: True,
) -> bool:
    """Grava em ``destino`` a cópia de ``origem`` reduzida a ``tamanho``.

    Devolve False, sem gravar nada, se a origem não é animada (menos de 2
    quadros, contados depois da fusão) ou se ``vigente()`` diz, no fim, que a
    capa mudou ou o app fechou no meio da geração (``vigente`` é consultada a
    cada quadro lido e antes da troca final). Se a origem não abre, o erro de leitura
    (``OSError``, ``ValueError``, ``Image.DecompressionBombError``) sobe para
    quem chamou decidir o que mostrar. Se é a codificação ou a gravação que
    falha, sobe ``GravacaoFalhou``, sem deixar ``.tmp`` para trás.

    A fusão acima depende só da origem, mas o libwebp também funde quadros
    repetidos ou quase iguais ao gravar, e com perda isso depende dos pixels,
    ou seja, do tamanho. A contagem de quadros das cópias da grade e dos
    detalhes pode divergir; a duração total, que a fusão preserva, não. Quem
    troca de uma cópia para a outra continua pelo tempo, não pelo quadro.

    A origem é lida inteira para a memória antes de abrir: nenhum trabalho
    segura o arquivo, que no Windows não poderia ser apagado (a pasta do
    seletor) nem substituído (``save_cover``) enquanto estivesse aberto. Só a
    pasta das cópias da biblioteca é criada aqui; a de uma prévia que já sumiu
    não é recriada, e a gravação falha com ``GravacaoFalhou``.
    """
    global _sem_codificador  # pylint: disable=global-statement
    dados = origem.read_bytes()
    webp: bytes | None = None
    if not _sem_codificador:
        try:
            webp = _codificar(dados, tamanho, vigente, _PorQuadro(tamanho))
        except _CodificadorIndisponivel as erro:
            _sem_codificador = True
            logging.debug("Cópias animadas sem o codificador quadro a quadro: %s", erro)
    if _sem_codificador:
        webp = _codificar(dados, tamanho, vigente, _EmLista())
    if webp is None:
        return False

    # Grava ao lado e troca de nome no fim: quem vê o destino nunca pega uma
    # cópia pela metade. O nome leva um sufixo único porque, quando a capa
    # troca, o trabalho velho e o novo podem gravar o mesmo destino juntos.
    temporario = destino.with_name(f"{destino.name}.{uuid4().hex}.tmp")
    try:
        if destino.parent == shared.capas_animadas_dir:
            destino.parent.mkdir(parents=True, exist_ok=True)
        temporario.write_bytes(webp)
        # A checagem e a troca formam um passo só em relação ao ``apagar``,
        # que invalida e apaga com a mesma trava: o rename cai antes da
        # invalidação (e o glob do ``apagar`` o remove) ou depois (e é pulado).
        # Sem isto a cópia da capa velha podia aparecer depois da troca.
        # ``vigente`` não pode pegar a trava, ou travaria aqui.
        with _trava:
            if not vigente():
                return False
            temporario.replace(destino)
        return True
    except OSError as erro:
        raise GravacaoFalhou(destino) from erro
    finally:
        with contextlib.suppress(OSError):
            temporario.unlink(missing_ok=True)


@dataclass
class _Trabalho:
    chave: str  # game_id: o que ``apagar`` usa para invalidar
    prontos: list[Callable[[Resultado], None]] = field(default_factory=list)
    iniciado: bool = False
    # Vira True quando a capa muda ou o pedido é cancelado; o trabalho que já
    # rodava vê isso em ``vigente`` e descarta o resultado.
    invalido: bool = False


# Trocado pelos testes. Dois trabalhos por vez: a geração é quase toda CPU, e
# cada trabalho segura só a origem e um ou dois quadros reduzidos.
_executor = ThreadPoolExecutor(max_workers=2)
# Guarda ``_trabalhos`` e os campos de cada ``_Trabalho``. ``gerar`` a pega só
# na checagem final e no rename; nunca durante a geração nem num ``pronto``.
_trava = threading.Lock()
_trabalhos: dict[Path, _Trabalho] = {}  # destino -> trabalho pendente ou rodando


def pedir(
    origem: Path,
    destino: Path,
    tamanho: tuple[int, int],
    pronto: Callable[[Resultado], None],
) -> None:
    """Gera a cópia em segundo plano e avisa ``pronto`` na thread principal.

    Pedido repetido para o mesmo ``destino``, com o trabalho ainda pendente ou
    rodando, só acrescenta o ``pronto``. Se a capa muda (``apagar``) ou o pedido
    é cancelado antes do fim, ``pronto`` não é chamado: quem trocou a capa
    pede de novo.
    """
    with _trava:
        trabalho = _trabalhos.get(destino)
        if trabalho is not None:
            trabalho.prontos.append(pronto)
            return
        trabalho = _trabalhos[destino] = _Trabalho(origem.stem, [pronto])
    _executor.submit(lambda: _rodar(trabalho, origem, destino, tamanho))


def _rodar(
    trabalho: _Trabalho, origem: Path, destino: Path, tamanho: tuple[int, int]
) -> None:
    with _trava:
        if trabalho.invalido:
            return
        trabalho.iniciado = True
    resultado: Resultado | None = None
    try:
        gravada = gerar(
            origem, destino, tamanho, vigente=lambda: not trabalho.invalido
        )
        resultado = "pronta" if gravada else "estatica"
    except GravacaoFalhou:
        logging.warning("Não foi possível gravar a cópia animada de %s", origem.name)
        resultado = "falhou"
    except (OSError, ValueError, Image.DecompressionBombError):
        logging.warning("Não foi possível ler a capa animada %s", origem.name)
        resultado = "ilegivel"
    except Exception:  # pylint: disable=broad-exception-caught
        # Um erro que ninguém previu não pode deixar o pedido sem resposta: a
        # tarefa "Capas animadas" esperaria por ele para sempre.
        logging.exception("Erro inesperado ao gerar a cópia animada de %s", origem.name)
        resultado = "falhou"
    finally:
        with _trava:
            if _trabalhos.get(destino) is trabalho:
                del _trabalhos[destino]
            prontos = list(trabalho.prontos)
            descartado = trabalho.invalido
    if resultado is None or descartado:
        return
    if resultado == "pronta":
        # O caminho da cópia é estável: quem já toca a anterior tem de largá-la
        # antes de receber o aviso. Fora da ``_trava``: o tocador tem a dele.
        tocador_capas.tocador.esquecer(destino)
    for pronto in prontos:
        entregar_na_tela(_entregar, pronto, resultado)


def _entregar(pronto: Callable[[Resultado], None], resultado: Resultado) -> bool:
    pronto(resultado)
    return False  # o GLib repetiria o callback que devolvesse um valor verdadeiro


def apagar(game_id: str) -> None:
    """Apaga as cópias do jogo e invalida os trabalhos dele, pendentes ou não."""
    # Os trabalhos invalidados abaixo nunca avisam: a tarefa precisa saber que
    # não deve mais esperá-los. Pode vir de uma thread de segundo plano, e a
    # tarefa é da thread principal. Quem pediu as cópias de novo (a capa nova)
    # o fez depois desta chamada, e a entrega mantém a ordem.
    if _lote is not None:
        entregar_na_tela(_descartar_do_lote, game_id)
    with _trava:
        for destino, trabalho in list(_trabalhos.items()):
            if trabalho.chave == game_id:
                trabalho.invalido = True
                # Fora do dicionário: um pedido novo para este destino (a capa
                # nova) não pode herdar um trabalho que vai descartar o resultado.
                del _trabalhos[destino]
    for arquivo in _copias_de(game_id):
        try:
            arquivo.unlink(missing_ok=True)
        except OSError:
            logging.warning("Não foi possível apagar a cópia animada %s", arquivo.name)
            continue
        # Fora da ``_trava``, pelo mesmo motivo do ``_rodar``.
        tocador_capas.tocador.esquecer(arquivo)


def abandonar(origem: Path) -> None:
    """Cancela e apaga as cópias de uma capa fora da biblioteca.

    Para as prévias do seletor e a capa provisória da edição: ``apagar`` só
    acha as da biblioteca, pelo id do jogo, e as destas ficariam na fila
    (minutos de CPU depois de o seletor fechar) e no disco (ao lado do
    temporário, em %TEMP%). Sempre na thread principal.
    """
    destinos = [caminho_para(origem, tamanho) for tamanho in tamanhos()]
    with _trava:
        for destino in destinos:
            if (trabalho := _trabalhos.pop(destino, None)) is not None:
                trabalho.invalido = True
    # O mesmo desconto do ``apagar``: a tarefa não espera trabalho invalidado.
    entregar_na_tela(_descartar_do_lote, origem.stem)
    for destino in destinos:
        try:
            destino.unlink(missing_ok=True)
        except OSError:
            logging.warning("Não foi possível apagar a cópia animada %s", destino.name)
            continue
        tocador_capas.tocador.esquecer(destino)


def _dono_e_tamanho(arquivo: Path) -> tuple[str, str]:
    """(id, ``{L}x{A}``) do nome ``{id}_{L}x{A}.webp``; o id pode ter ``_``."""
    dono, _, tamanho = arquivo.stem.rpartition("_")
    return dono, tamanho


def _copias_de(game_id: str) -> list[Path]:
    """As cópias do jogo ``game_id``, de todos os tamanhos.

    O id é o que vem antes do último ``_``: o glob ``{id}_*`` também pegaria as
    cópias de um jogo cujo id começa igual (``x`` e ``x_y``).
    """
    return [
        arquivo
        for arquivo in shared.capas_animadas_dir.glob("*.webp")
        if _dono_e_tamanho(arquivo)[0] == game_id
    ]


def pares_de_migracao(antigo: str, novo: str) -> list[tuple[Path, Path]]:
    """(cópia atual, cópia com o id novo) de cada cópia do jogo ``antigo``."""
    return [
        (arquivo, arquivo.with_name(f"{novo}_{_dono_e_tamanho(arquivo)[1]}.webp"))
        for arquivo in _copias_de(antigo)
    ]


def limpar(ids: set[str]) -> None:
    """Apaga o que sobrou na pasta das cópias: de jogo que não existe mais, de
    tamanho que nenhuma tela usa e todo temporário de gravação interrompida.

    Roda numa thread de segundo plano na abertura, sem tocar o GTK. Só olha os
    arquivos da própria pasta; um que sumiu ou está preso fica para a próxima.
    """
    validos = {f"{largura}x{altura}" for largura, altura in tamanhos()}
    for arquivo in list(shared.capas_animadas_dir.glob("*")):
        try:
            if not arquivo.is_file():
                continue
            if arquivo.suffix == ".webp":
                dono, tamanho = _dono_e_tamanho(arquivo)
                if dono in ids and tamanho in validos:
                    continue
            elif arquivo.suffix != ".tmp":
                continue
            arquivo.unlink()
        except OSError as erro:
            logging.debug("Cópia animada %s não apagada: %s", arquivo.name, erro)


def encerrar() -> None:
    """Invalida todos os trabalhos, pendentes e em andamento. Para fechar o app.

    O executor não é daemon: sem isto o interpretador esperaria a geração em
    curso (segundos numa capa grande) e todo trabalho ainda na fila. Os
    pendentes saem sem gerar e os em andamento param no próximo quadro.
    """
    with _trava:
        for trabalho in _trabalhos.values():
            trabalho.invalido = True
        _trabalhos.clear()
    _encerrar_lote()


def cancelar_pendentes() -> None:
    """Descarta o que ainda não começou; o que já roda segue até o fim.

    Quem cancela não vai receber o aviso dos pedidos descartados, então a tarefa
    "Capas animadas" também termina aqui. Sempre na thread principal.
    """
    with _trava:
        for destino, trabalho in list(_trabalhos.items()):
            if not trabalho.iniciado:
                trabalho.invalido = True
                del _trabalhos[destino]
    _encerrar_lote()


# --- A tarefa "Capas animadas" -------------------------------------------------


class _Lote:
    """O que a tarefa "Capas animadas" em andamento ainda espera."""

    def __init__(self, tarefa: tarefas.Tarefa, total: int) -> None:
        self.tarefa = tarefa
        self.total = total
        self.feitos = 0
        self.pendentes: dict[Path, str] = {}  # destino -> game_id


# Só a thread principal troca isto. Há no máximo uma tarefa: um pedido novo
# durante ela entra no mesmo lote em vez de abrir outro item na lista.
_lote: _Lote | None = None


def preparar(capas: list[tuple[str, Path]]) -> None:
    """Gera, em segundo plano, as cópias que faltam das capas (na ordem dada).

    Sempre na thread principal. Mostra uma só tarefa "Capas animadas" nas
    tarefas em andamento, que termina quando todo pedido voltou (``estatica``,
    ``ilegivel`` e ``falhou`` também contam) ou quando é cancelada. Sem nada a
    gerar, não mostra tarefa nenhuma. Chamada durante uma tarefa em andamento,
    acrescenta as cópias novas a ela; cópia já esperada não conta duas vezes.
    """
    global _lote  # pylint: disable=global-statement
    novos: dict[Path, tuple[str, Path, tuple[int, int]]] = {}
    for game_id, origem in capas:
        for tamanho in tamanhos():
            destino = caminho_para(origem, tamanho)
            if destino.exists() or (_lote and destino in _lote.pendentes):
                continue
            novos.setdefault(destino, (game_id, origem, tamanho))
    if not novos:
        return

    # O lote e as pendências ficam prontos antes do primeiro ``pedir``: um aviso
    # nunca chega a um lote que ainda acha que terminou.
    if _lote is None:
        _lote = _Lote(tarefas.comecar(_("Capas animadas"), len(novos)), len(novos))
    else:
        _lote.total += len(novos)
        _lote.tarefa.atualizar(_lote.feitos, _lote.total)
    lote = _lote
    for destino, (game_id, _origem, _tamanho) in novos.items():
        lote.pendentes[destino] = game_id
    for destino, (_game_id, origem, tamanho) in novos.items():
        pedir(origem, destino, tamanho, partial(_voltou, lote, destino))


def _voltou(lote: _Lote, destino: Path, _resultado: Resultado) -> None:
    # Um aviso tardio de lote que já terminou ou foi cancelado, ou de cópia que
    # a tarefa já deixou de esperar, não conta nem reabre nada.
    if lote is not _lote or destino not in lote.pendentes:
        return
    del lote.pendentes[destino]
    lote.feitos += 1
    lote.tarefa.atualizar(lote.feitos)
    if not lote.pendentes:
        _encerrar_lote()


def _descartar_do_lote(game_id: str) -> bool:
    """A capa do jogo mudou: a tarefa deixa de esperar as cópias antigas."""
    if _lote is not None:
        descartadas = [d for d, dono in _lote.pendentes.items() if dono == game_id]
        for destino in descartadas:
            del _lote.pendentes[destino]
        if descartadas and not _lote.pendentes:
            _encerrar_lote()
        elif descartadas:
            _lote.total -= len(descartadas)
            _lote.tarefa.atualizar(_lote.feitos, _lote.total)
    return False  # o GLib repetiria o callback que devolvesse um valor verdadeiro


def _encerrar_lote() -> None:
    global _lote  # pylint: disable=global-statement
    if _lote is not None:
        _lote.tarefa.terminar()
        _lote = None
