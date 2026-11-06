# copias_animadas.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cópias reduzidas das capas animadas, no tamanho em que são exibidas.

Tocar o original decodificaria e redimensionaria centenas de quadros grandes a cada volta: a cópia já sai
no tamanho da tela e com os quadros curtos fundidos.
"""

import contextlib
import io
import logging
import shutil
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

from kyron import shared
from kyron.utils.na_tela import entregar_na_tela
from kyron.utils.thread_principal import eh_thread_principal

# ``ilegivel`` é a origem que não abre; ``falhou`` é a cópia que não pôde ser gravada (disco cheio, permissão): a capa segue animada.
Resultado = Literal["pronta", "estatica", "ilegivel", "falhou"]

# Abaixo disto o quadro é fundido ao anterior: nenhuma tela mostra mais de ~30 quadros por segundo.
QUADRO_MINIMO_MS = 30


class GravacaoFalhou(Exception):
    """Não foi possível gravar a cópia em ``destino``.

    Não herda de ``OSError`` de propósito: a origem ilegível sobe como
    ``OSError``, e quem chama precisa distinguir as duas falhas.
    """


def tamanhos() -> tuple[tuple[int, int], tuple[int, int]]:
    return (
        (int(shared.display_size[0]), int(shared.display_size[1])),
        (int(shared.details_size[0]), int(shared.details_size[1])),
    )


def caminho_para(origem: Path, tamanho: tuple[int, int]) -> Path:
    """Onde fica a cópia de ``origem`` no ``tamanho`` pedido.

    As da biblioteca vão para o cache do app; as prévias dos seletores ficam ao lado delas, numa pasta temporária
    que o seletor limpa. O tamanho no nome faz uma mudança de escala gerar cópias novas.
    """
    nome = f"{origem.stem}_{tamanho[0]}x{tamanho[1]}.webp"
    if origem.parent == shared.covers_dir:
        return shared.capas_animadas_dir / nome
    return origem.with_name(nome)


class _CodificadorIndisponivel(Exception):
    """O ``_webp.WebPAnimEncoder`` do Pillow sumiu ou mudou de assinatura."""


# Vira True na primeira falha do codificador quadro a quadro: daí em diante vai pelo caminho da lista, e o aviso sai uma vez.
_sem_codificador = False


class _PorQuadro:
    """Codifica cada quadro assim que chega, sem guardar a animação.

    Usa a API privada do Pillow (``_webp.WebPAnimEncoder``), na ordem do ``WebPImagePlugin._save_all``: o ``save``
    público só aceita a lista inteira, que chegava a 600 MB na cópia de detalhes. ``AttributeError``/``TypeError``
    viram ``_CodificadorIndisponivel``, e ``gerar`` refaz pela lista.
    """

    def __init__(self, tamanho: tuple[int, int]) -> None:
        self._instante = 0
        try:
            # tamanho, fundo, loop, minimize_size, kmin, kmax, allow_mixed, verbose (kmin/kmax: padrões do Pillow com perda).
            self._enc = _webp.WebPAnimEncoder(tamanho, 0, 0, False, 3, 5, False, False)
        except (AttributeError, TypeError) as erro:
            raise _CodificadorIndisponivel(erro) from erro

    def add(self, quadro: Image.Image, duracao: int) -> None:
        # lossless, quality, alpha_quality, method: os mesmos quality=90 e method=4 do caminho da lista.
        try:
            self._enc.add(quadro.getim(), self._instante, False, 90.0, 100.0, 4)
        except (AttributeError, TypeError) as erro:
            raise _CodificadorIndisponivel(erro) from erro
        self._instante += duracao

    def dados(self) -> bytes:
        try:
            # O quadro vazio fecha a animação: o instante dele dá a duração do último.
            self._enc.add(None, self._instante, False, 90.0, 100.0, 0)
            dados = self._enc.assemble(b"", b"", b"")  # ICC, EXIF, XMP
        except (AttributeError, TypeError) as erro:
            raise _CodificadorIndisponivel(erro) from erro
        if dados is None:
            raise OSError("o codificador WebP não devolveu nada")
        return dados


class _EmLista:
    """O caminho público do Pillow: todos os quadros na memória até o fim.

    shortcut: só para o caso de a API privada do ``_PorQuadro`` mudar; o pico é a animação inteira (até ~600 MB).
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
    # A duração do quadro pendente só é final quando o seguinte chega (um curto absorve o seguinte).
    pendente: Image.Image | None = None
    duracao_pendente = 0
    entregues = 0
    with Image.open(io.BytesIO(dados)) as imagem:
        for quadro in ImageSequence.Iterator(imagem):
            # Centenas de quadros levam segundos: se a capa mudou ou o app fecha, para já (vale também para a codificação).
            if not vigente():
                return None
            # No WebP o Pillow só preenche info["duration"] ao decodificar o quadro; antes disso todo quadro valeria 100 ms.
            quadro.load()
            duracao = int(quadro.info.get("duration", 100)) or 100
            reduzido = quadro.convert("RGBA").resize(tamanho, Image.LANCZOS)
            if pendente is not None and duracao_pendente < QUADRO_MINIMO_MS:
                # O curto cede o tempo ao seguinte, que é o que aparece.
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

    False, sem gravar, se a origem não é animada (menos de 2 quadros após a fusão) ou se ``vigente()`` (a cada quadro e antes da troca final) diz que a capa mudou ou o app fechou. Origem que não abre sobe como ``OSError``/``ValueError``/``Image.DecompressionBombError``; falha de codificação ou gravação, ``GravacaoFalhou``, sem deixar ``.tmp``.
    O libwebp funde quadros quase iguais ao gravar e, com perda, isso depende do tamanho: a contagem de quadros da grade e dos detalhes pode divergir (a duração não), então quem troca de cópia continua pelo tempo.
    A origem é lida inteira antes de abrir: aberta, o Windows não deixaria apagá-la (pasta do seletor) nem substituí-la (``save_cover``).
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

    # Grava ao lado e troca de nome no fim, para ninguém pegar uma cópia pela metade; sufixo único porque o trabalho velho e o novo podem gravar o mesmo destino.
    temporario = destino.with_name(f"{destino.name}.{uuid4().hex}.tmp")
    try:
        if destino.parent == shared.capas_animadas_dir:
            destino.parent.mkdir(parents=True, exist_ok=True)
        temporario.write_bytes(webp)
        # Checagem e troca são um passo só em relação ao ``apagar`` (mesma trava): o rename cai antes da invalidação
        # (e o glob do ``apagar`` o remove) ou depois (e é pulado). ``vigente`` não pode pegar a trava, ou travaria aqui.
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
    # Vira True quando a capa muda ou o pedido é cancelado; o trabalho em curso vê em ``vigente`` e descarta.
    invalido: bool = False


# Trocado pelos testes. Dois trabalhos por vez: a geração é quase toda CPU.
_executor = ThreadPoolExecutor(max_workers=2)
# Guarda ``_trabalhos`` e os campos de cada ``_Trabalho``; ``gerar`` a pega só na checagem final e no rename.
_trava = threading.Lock()
_trabalhos: dict[Path, _Trabalho] = {}  # destino -> trabalho pendente ou rodando


def pedir(
    origem: Path,
    destino: Path,
    tamanho: tuple[int, int],
    pronto: Callable[[Resultado], None],
) -> None:
    """Gera a cópia em segundo plano e avisa ``pronto`` na thread principal.

    Pedido repetido para o mesmo ``destino`` só acrescenta o ``pronto``. Se a capa muda (``apagar``) ou o pedido é
    cancelado, ``pronto`` não é chamado: quem trocou a capa pede de novo.
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
        # Um erro imprevisto não pode deixar o pedido sem resposta: a tarefa "Capas animadas" esperaria para sempre.
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
    for pronto in prontos:
        entregar_na_tela(_entregar, pronto, resultado)


def _entregar(pronto: Callable[[Resultado], None], resultado: Resultado) -> bool:
    pronto(resultado)
    return False


# Larga os arquivos de cópia que a tela segura: o ``AnimatedImage`` mantém o ``.webp`` aberto sem compartilhar a exclusão,
# e o Windows não deixa apagar nem regravar assim (WinError 32). Chamado com o id do jogo, na thread principal.
soltar_do_jogo: Callable[[str], None] | None = None
soltar_da_pagina: Callable[[str], None] | None = None


def soltar(game_id: str) -> None:
    """Pede à tela que largue as cópias do jogo, antes de apagá-las ou regravá-las.

    Só a thread principal toca a tela; de outra thread não faz nada (a cópia presa fica para a limpeza da próxima abertura).
    """
    if eh_thread_principal():
        for gancho in (soltar_do_jogo, soltar_da_pagina):
            if gancho is not None:
                gancho(game_id)


def apagar(game_id: str) -> None:
    """Apaga as cópias do jogo e invalida os trabalhos dele, pendentes ou não."""
    soltar(game_id)
    # Os trabalhos invalidados nunca avisam: a tarefa precisa deixar de esperá-los. Na principal o descarte é imediato
    # (enfileirado, rodaria depois do ``preparar`` da capa nova e a levaria junto). De outra thread, a entrega mantém
    # a ordem; ler ``_lote`` aqui, sem trava, podia ver None antes de um ``preparar`` criar o lote.
    if eh_thread_principal():
        _descartar_do_lote(game_id)
    else:
        entregar_na_tela(_descartar_do_lote, game_id)
    with _trava:
        for destino, trabalho in list(_trabalhos.items()):
            if trabalho.chave == game_id:
                trabalho.invalido = True
                # Fora do dicionário: um pedido novo para este destino não herda um trabalho que vai descartar o resultado.
                del _trabalhos[destino]
    for arquivo in _copias_de(game_id):
        try:
            arquivo.unlink(missing_ok=True)
        except OSError:
            logging.warning("Não foi possível apagar a cópia animada %s", arquivo.name)
            continue


def abandonar(origem: Path) -> None:
    """Cancela e apaga as cópias de uma capa fora da biblioteca (prévias do seletor, capa provisória da edição).

    ``apagar`` só acha as da biblioteca, pelo id; as destas ficariam na fila (minutos de CPU) e em %TEMP%. Na thread principal.
    """
    destinos = [caminho_para(origem, tamanho) for tamanho in tamanhos()]
    with _trava:
        for destino in destinos:
            if (trabalho := _trabalhos.pop(destino, None)) is not None:
                trabalho.invalido = True
    _descartar_do_lote(origem.stem)
    for destino in destinos:
        try:
            destino.unlink(missing_ok=True)
        except OSError:
            logging.warning("Não foi possível apagar a cópia animada %s", destino.name)
            continue


def adotar(origem: Path, capa: Path) -> None:
    """Copia para ``capa`` as cópias prontas de ``origem`` (a capa provisória da edição que vira a do jogo), para o ``preparar`` não as gerar de novo.

    Vem depois do ``apagar`` da capa velha e antes do ``preparar``. Uma cópia que falha é só gerada de novo.
    """
    soltar(capa.stem)
    for tamanho in tamanhos():
        fonte, destino = caminho_para(origem, tamanho), caminho_para(capa, tamanho)
        # ``gerar`` só põe a cópia no lugar inteira: existindo, está pronta.
        if fonte == destino or not fonte.is_file():
            continue
        temporario = destino.with_name(f"{destino.name}.{uuid4().hex}.tmp")
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(fonte, temporario)
            temporario.replace(destino)
        except OSError as erro:
            logging.warning("Não foi possível aproveitar a cópia animada %s: %s", fonte.name, erro)
            continue
        finally:
            with contextlib.suppress(OSError):
                temporario.unlink(missing_ok=True)


def _dono_e_tamanho(arquivo: Path) -> tuple[str, str]:
    """(id, ``{L}x{A}``) do nome ``{id}_{L}x{A}.webp``; o id pode ter ``_``."""
    dono, _, tamanho = arquivo.stem.rpartition("_")
    return dono, tamanho


def _copias_de(game_id: str) -> list[Path]:
    """As cópias do jogo ``game_id``, de todos os tamanhos (o id é o que vem antes do último ``_``: o glob ``{id}_*`` pegaria ``x_y`` junto com ``x``)."""
    return [
        arquivo
        for arquivo in shared.capas_animadas_dir.glob("*.webp")
        if _dono_e_tamanho(arquivo)[0] == game_id
    ]


def pares_de_migracao(antigo: str, novo: str) -> list[tuple[Path, Path]]:
    return [
        (arquivo, arquivo.with_name(f"{novo}_{_dono_e_tamanho(arquivo)[1]}.webp"))
        for arquivo in _copias_de(antigo)
    ]


def limpar(ids: set[str]) -> None:
    """Apaga o que sobrou na pasta das cópias: de jogo inexistente, de tamanho que nenhuma tela usa e temporários de gravação interrompida.

    Roda numa thread de segundo plano na abertura; um arquivo que sumiu ou está preso fica para a próxima.
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
    """Invalida todos os trabalhos, pendentes e em andamento, para fechar o app.

    O executor não é daemon: sem isto o interpretador esperaria a geração em curso e toda a fila. Os pendentes
    saem sem gerar e os em andamento param no próximo quadro.
    """
    with _trava:
        for trabalho in _trabalhos.values():
            trabalho.invalido = True
        _trabalhos.clear()
    _encerrar_lote()



class _Lote:
    """O que a tarefa "Capas animadas" em andamento ainda espera."""

    def __init__(self, tarefa: "tarefas.Tarefa", total: int) -> None:
        self.tarefa = tarefa
        self.total = total
        self.feitos = 0
        self.pendentes: dict[Path, str] = {}  # destino -> game_id


# Só a thread principal troca isto. No máximo uma tarefa: um pedido novo durante ela entra no mesmo lote.
_lote: _Lote | None = None


def _em_dia(origem: Path, destino: Path, game_id: str) -> bool:
    """A cópia existe e não é mais velha que a capa; uma velha é largada pela tela para ser refeita (senão a animação velha ficaria na grade)."""
    try:
        if not destino.exists():
            return False
        if destino.stat().st_mtime_ns >= origem.stat().st_mtime_ns:
            return True
    except OSError:
        return True  # a capa sumiu ou a cópia está ilegível: não há o que refazer aqui
    soltar(game_id)
    return False


def preparar(capas: list[tuple[str, Path]]) -> None:
    """Gera, em segundo plano, as cópias que faltam das capas (na ordem dada). Na thread principal.

    Mostra uma só tarefa "Capas animadas", que termina quando todo pedido voltou (``estatica``, ``ilegivel`` e
    ``falhou`` contam) ou o app fecha; sem nada a gerar, nenhuma. Durante uma tarefa, acrescenta as cópias novas a ela.
    """
    global _lote  # pylint: disable=global-statement
    novos: dict[Path, tuple[str, Path, tuple[int, int]]] = {}
    for game_id, origem in capas:
        for tamanho in tamanhos():
            destino = caminho_para(origem, tamanho)
            if (_lote and destino in _lote.pendentes) or _em_dia(origem, destino, game_id):
                continue
            novos.setdefault(destino, (game_id, origem, tamanho))
    if not novos:
        return

    # O lote e as pendências ficam prontos antes do primeiro ``pedir``: um aviso nunca chega a um lote que acha que terminou.
    if _lote is None:
        # Aqui e não no topo: a lista de `tarefas` é um QObject e nasce na thread que importa o módulo; a store importa este só para apagar e migrar.
        from kyron.modelos import tarefas  # pylint: disable=import-outside-toplevel

        _lote = _Lote(tarefas.comecar(_("Capas animadas"), len(novos)), len(novos))
    else:
        _lote.total += len(novos)
        _lote.tarefa.atualizar(_lote.feitos, _lote.total)
    lote = _lote
    for destino, (game_id, _origem, _tamanho) in novos.items():
        lote.pendentes[destino] = game_id
    for destino, (_game_id, origem, tamanho) in novos.items():
        pedir(origem, destino, tamanho, partial(_voltou, lote, destino))


# Quem quer saber de cada cópia que termina (o modelo da biblioteca): (game_id, resultado), na thread principal. Global: o pedido pode vir de ``save_cover``.
ao_terminar_copia: Callable[[str, Resultado], None] | None = None
ao_terminar_da_pagina: Callable[[str, Resultado], None] | None = None


def _voltou(lote: _Lote, destino: Path, resultado: Resultado) -> None:
    # Aviso tardio de lote terminado ou cancelado, ou de cópia que a tarefa já não espera, não conta.
    if lote is not _lote or destino not in lote.pendentes:
        return
    game_id = lote.pendentes.pop(destino)
    # Um gancho que levanta não pode deixar o lote sem encerrar.
    for gancho in (ao_terminar_copia, ao_terminar_da_pagina):
        if gancho is not None:
            try:
                gancho(game_id, resultado)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao avisar o fim da cópia de %s", game_id, exc_info=True)
    lote.feitos += 1
    lote.tarefa.atualizar(lote.feitos)
    if not lote.pendentes:
        _encerrar_lote()


def _descartar_do_lote(game_id: str) -> bool:
    if _lote is not None:
        descartadas = [d for d, dono in _lote.pendentes.items() if dono == game_id]
        for destino in descartadas:
            del _lote.pendentes[destino]
        if descartadas and not _lote.pendentes:
            _encerrar_lote()
        elif descartadas:
            _lote.total -= len(descartadas)
            _lote.tarefa.atualizar(_lote.feitos, _lote.total)
    return False


def _encerrar_lote() -> None:
    global _lote  # pylint: disable=global-statement
    if _lote is not None:
        _lote.tarefa.terminar()
        _lote = None
