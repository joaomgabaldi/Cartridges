# tocador_capas.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Um único tocador, a 30 Hz, para todas as capas animadas à vista.

Um timer por capa na thread principal decodificava os quadros no mesmo lugar
que desenha a tela. Aqui uma só thread decodifica o próximo quadro de cada capa
cujo prazo venceu e entrega o lote inteiro à thread principal de uma vez: a
tela só precisa trocar as texturas.

Este módulo não conhece o GTK. Quem chama recebe os bytes RGBA no
``ao_quadro`` (já na thread principal) e monta a textura.
"""

import io
import logging
import threading
import time
from bisect import bisect_right
from dataclasses import dataclass, field
from itertools import accumulate
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from cartridges.utils.na_tela import entregar_na_tela

TICK = 1 / 30

# Parada há mais que isto, a capa fecha a cópia: quem sai da tela e volta logo
# retoma do mesmo quadro; quem sumiu de vez não ocupa memória.
FECHAR_APOS = 30.0

# Mais paradas que isto com a cópia aberta, as paradas há mais tempo fecham
# antes dos 30 s. Cada uma custa ~10 MB (grade) a ~30 MB (detalhes), e rolar
# uma biblioteca grande pausa dezenas delas; 8 ainda cobre ir e voltar do
# mouse e da rolagem por perto, que é o que a retomada do mesmo quadro serve.
MAX_PAUSADAS_ABERTAS = 8

FALHAS_ATE_CORROMPIDA = 3


@dataclass(eq=False)
class _Estado:
    """O que o tocador guarda de cada dono.

    ``imagem`` e as listas de durações só são tocadas pela thread do tocador
    (dentro de ``passo``). ``tocar`` nunca mexe nelas: troca de cópia criando
    um estado novo. Assim a decodificação roda fora da trava sem disputar a
    imagem com a thread principal.
    """

    copia: Path
    ao_quadro: Callable[[bytes, int, int], None]
    ao_falhar: Callable[[], None]
    # Instante do loop em que a cópia deve ser posicionada ao (re)abrir.
    inicial_ms: int
    prazo: float
    # Início do quadro mostrado (ou do que vai ser mostrado primeiro).
    posicao: int = 0
    imagem: Image.Image | None = None
    inicios: list[int] = field(default_factory=list)
    duracoes: list[int] = field(default_factory=list)
    proximo: int = 0
    falhas: int = 0
    pausado_em: float | None = None
    # O próximo quadro é o primeiro depois de abrir, posicionar ou retomar: o
    # prazo dele conta de agora, não do prazo do quadro anterior.
    recomecou: bool = True
    # Sobe a cada ``esquecer``: uma abertura que estava em andamento na thread
    # do tocador sabe, ao terminar, que leu o arquivo antigo.
    versao: int = 0


def _duracoes_do_container(dados: bytes) -> list[int] | None:
    """Durações dos quadros lidas do contêiner RIFF/WebP, sem decodificar.

    Cada quadro de um WebP animado é um bloco ``ANMF``; a duração (24 bits,
    little-endian) fica no deslocamento 12 do conteúdo. Devolve ``None`` se o
    contêiner não for o esperado, para quem chama cair na leitura quadro a
    quadro.
    """
    if dados[:4] != b"RIFF" or dados[8:12] != b"WEBP":
        return None
    duracoes = []
    pos = 12
    while pos + 8 <= len(dados):
        tamanho = int.from_bytes(dados[pos + 4 : pos + 8], "little")
        fim = pos + 8 + tamanho
        if fim > len(dados):
            return None
        if dados[pos : pos + 4] == b"ANMF":
            if tamanho < 16:
                return None
            duracoes.append(
                int.from_bytes(dados[pos + 20 : pos + 23], "little")
            )
        pos = fim + (tamanho & 1)
    return duracoes or None


def _abrir(estado: _Estado) -> None:
    """Abre a cópia e posiciona no quadro que cobre ``inicial_ms``.

    Lê os bytes do arquivo e abre a imagem sobre a memória: no Windows um
    arquivo aberto não pode ser apagado nem substituído, e o app apaga e
    regenera cópias enquanto elas tocam. A duração total e o início de cada
    quadro saem do contêiner, sem decodificar: uma cópia tem centenas de
    quadros, e decodificar todos só para somar durações parava as outras capas
    a cada abertura.
    """
    dados = estado.copia.read_bytes()
    imagem = Image.open(io.BytesIO(dados))
    n_frames = getattr(imagem, "n_frames", 1)
    duracoes = _duracoes_do_container(dados)
    if duracoes is None or len(duracoes) != n_frames:
        # Contêiner fora do esperado: lê quadro a quadro. No WebP,
        # ``info["duration"]`` só é preenchido depois do ``load``.
        duracoes = []
        for n in range(n_frames):
            imagem.seek(n)
            imagem.load()
            duracoes.append(int(imagem.info.get("duration") or 1))
    duracoes = [max(1, d) for d in duracoes]
    inicios = list(accumulate(duracoes[:-1], initial=0))
    estado.imagem = imagem
    estado.duracoes = duracoes
    estado.inicios = inicios
    # Contagens diferentes de quadros (grade x detalhes) têm a mesma duração
    # total: a continuidade entre cópias é pelo tempo, não pelo índice.
    p = estado.inicial_ms % sum(duracoes)
    estado.proximo = bisect_right(inicios, p) - 1


class Tocador:
    def __init__(
        self,
        agora: Callable[[], float] = time.monotonic,
        entregar: Callable[..., Any] = entregar_na_tela,
        iniciar_thread: bool = True,
    ) -> None:
        self._agora = agora
        self._entregar = entregar
        self._iniciar_thread = iniciar_thread
        # Um dono é uma capa; fica no dicionário até ``parar`` + 30 s (ou até
        # sair das ``MAX_PAUSADAS_ABERTAS`` mais recentes) ou até a cópia
        # falhar de vez. Quem chama deve parar o dono ao destruí-lo.
        self._estados: dict[object, _Estado] = {}
        self._trava = threading.Lock()
        self._acordar = threading.Event()
        self._thread: threading.Thread | None = None
        # Janela fora da tela (minimizada, escondida, coberta pela sessão de
        # jogo): nenhuma capa decodifica, por qualquer motivo. Ver `suspender`.
        self._suspenso = False
        # Quadros que a thread principal ainda não aplicou, o mais novo de cada
        # dono: (estado, versão, ao_quadro, (dados, largura, altura)). Guardado
        # pela `_trava`. Não vazio = há exatamente um `_aplicar` agendado: com
        # a tela travada, o quadro novo substitui o velho em vez de empilhar
        # um lote RGBA por tick na fila do GLib.
        self._pendentes: dict[object, tuple] = {}

    def tocar(
        self,
        dono: object,
        copia: Path,
        ao_quadro: Callable[[bytes, int, int], None],
        ao_falhar: Callable[[], None],
        posicao_inicial_ms: int = 0,
    ) -> None:
        """Começa (ou retoma) a capa ``dono``; o 1º quadro sai no próximo passo.

        Não abre o arquivo aqui: a leitura e a decodificação das durações
        ficam na thread do tocador, e uma cópia que sumiu vira falha no
        degrau normal em vez de estourar na thread principal.
        """
        agora = self._agora()
        with self._trava:
            estado = self._estados.get(dono)
            if estado is not None and estado.copia == copia:
                # Mesma cópia ainda aberta: segue de onde parou.
                estado.ao_quadro = ao_quadro
                estado.ao_falhar = ao_falhar
                if estado.pausado_em is not None:
                    estado.pausado_em = None
                    estado.prazo = agora
                    estado.recomecou = True
            else:
                self._estados[dono] = _Estado(
                    copia=copia,
                    ao_quadro=ao_quadro,
                    ao_falhar=ao_falhar,
                    inicial_ms=posicao_inicial_ms,
                    posicao=posicao_inicial_ms,
                    prazo=agora,
                )
            if self._iniciar_thread and self._thread is None:
                self._thread = threading.Thread(
                    target=self._rodar, name="tocador-capas", daemon=True
                )
                self._thread.start()
        self._acordar.set()

    def parar(self, dono: object) -> None:
        """Pausa a capa mantendo a cópia aberta, para retomar do mesmo quadro."""
        agora = self._agora()
        with self._trava:
            estado = self._estados.get(dono)
            if estado is not None and estado.pausado_em is None:
                estado.pausado_em = agora

    def esquecer(self, copia: Path) -> None:
        """A cópia em ``copia`` foi apagada ou regravada: larga o que tem dela.

        O caminho de uma cópia é estável, então a regravada tem o mesmo nome da
        anterior; sem isto, quem ainda a tem registrada seguiria tocando a
        antiga. Quem toca reabre o arquivo no próximo passo, do quadro 0; quem
        está pausado é fechado. Não chama callbacks.
        """
        with self._trava:
            for dono, estado in list(self._estados.items()):
                if estado.copia != copia:
                    continue
                if estado.pausado_em is not None:
                    del self._estados[dono]
                    continue
                estado.imagem = None
                estado.inicial_ms = 0
                estado.posicao = 0
                estado.falhas = 0
                estado.recomecou = True
                estado.versao += 1

    def suspender(self, suspenso: bool) -> None:
        """Suspende (True) ou retoma (False) todas as capas de uma vez.

        Para quando nada do app está à vista: vale para todo motivo de tocar
        (hover, detalhes, edição, prévias), que segue ligado em cada capa.
        Suspensas, as que tocam fecham a cópia no próximo passo; ao retomar,
        reabrem no instante em que pararam. As pausadas seguem pausadas.
        """
        agora = self._agora()
        with self._trava:
            if suspenso == self._suspenso:
                return
            self._suspenso = suspenso
            if not suspenso:
                for estado in self._estados.values():
                    if estado.pausado_em is None:
                        estado.prazo = agora
                        estado.recomecou = True
        self._acordar.set()

    def posicao_ms(self, dono: object) -> int:
        """Instante do loop em que começa o quadro mostrado agora."""
        with self._trava:
            estado = self._estados.get(dono)
            return estado.posicao if estado is not None else 0

    def passo(self) -> None:
        """Um tick: fecha as pausadas há muito (ou além das
        ``MAX_PAUSADAS_ABERTAS`` com a cópia aberta) e avança as vencidas.

        A decodificação roda fora da trava, para ``tocar``/``parar`` da thread
        principal nunca esperarem por ela. O estado é copiado antes (os
        devidos) e conferido depois: se o dono foi parado ou trocado no meio,
        o quadro é descartado e nada avança.
        """
        agora = self._agora()
        with self._trava:
            pausadas = sorted(
                (d for d, e in self._estados.items() if e.pausado_em is not None),
                key=lambda d: self._estados[d].pausado_em,
            )
            abertas = [d for d in pausadas if self._estados[d].imagem is not None]
            excesso = set(abertas[: max(0, len(abertas) - MAX_PAUSADAS_ABERTAS)])
            for dono in pausadas:
                parada_ha = agora - self._estados[dono].pausado_em
                if dono in excesso or parada_ha > FECHAR_APOS:
                    del self._estados[dono]
            if self._suspenso:
                # Uma sessão de jogo dura horas: a cópia fecha e, ao retomar,
                # reabre no quadro que estava na tela. A versão nova descarta
                # o que um passo anterior ainda estivesse lendo dela.
                for estado in self._estados.values():
                    if estado.pausado_em is None and estado.imagem is not None:
                        estado.imagem = None
                        estado.inicial_ms = estado.posicao
                        estado.versao += 1
                devidos = []
            else:
                devidos = [
                    (dono, estado, estado.versao)
                    for dono, estado in self._estados.items()
                    if estado.pausado_em is None and estado.prazo <= agora
                ]

        lido = []
        for dono, estado, versao in devidos:
            try:
                if estado.imagem is None:
                    _abrir(estado)
                n = estado.proximo
                estado.imagem.seek(n)
                rgba = estado.imagem.convert("RGBA")
                lido.append((dono, estado, versao, n, (rgba.tobytes(), *rgba.size)))
            except Exception as erro:  # noqa: BLE001 - a thread não pode morrer
                logging.warning("Capa animada ilegível (%s): %s", estado.copia, erro)
                lido.append((dono, estado, versao, -1, None))

        agendar = False
        avisos = []
        with self._trava:
            for dono, estado, versao, n, quadro in lido:
                if self._estados.get(dono) is not estado:
                    continue
                if estado.versao != versao:
                    # ``esquecer`` chegou no meio: o que foi lido é do arquivo
                    # antigo. Descarta e reabre no próximo passo. Antes da
                    # checagem de pausa: uma parada logo depois do ``esquecer``
                    # guardaria a imagem velha para a retomada.
                    estado.imagem = None
                    continue
                if estado.pausado_em is not None:
                    continue
                if quadro is not None:
                    estado.falhas = 0
                    estado.posicao = estado.inicios[n]
                    estado.proximo = (n + 1) % len(estado.duracoes)
                    # O prazo avança pela duração do quadro, não a partir do
                    # tick: com ticks de 33 ms, contar do tick faria todo
                    # quadro durar um número inteiro de ticks (um de 34 ms
                    # tocaria na metade da velocidade). Se já passou do prazo
                    # (a tela travou), recomeça de agora, sem rajada para
                    # alcançar o atraso.
                    duracao = estado.duracoes[n] / 1000
                    base = agora if estado.recomecou else estado.prazo
                    estado.recomecou = False
                    estado.prazo = base + duracao
                    if estado.prazo <= agora:
                        estado.prazo = agora + duracao
                    agendar = agendar or not self._pendentes
                    self._pendentes[dono] = (estado, versao, estado.ao_quadro, quadro)
                    continue
                # Degrau 1: fecha e reabre no próximo tick, do quadro 0.
                estado.imagem = None
                estado.inicial_ms = 0
                estado.recomecou = True
                estado.falhas += 1
                if estado.falhas >= FALHAS_ATE_CORROMPIDA:
                    del self._estados[dono]
                    avisos.append(estado.ao_falhar)

        # Fora da trava: os callbacks podem voltar a chamar o tocador. Nunca
        # espera a thread principal: com um ``_aplicar`` já na fila, o quadro
        # novo só substitui o pendente.
        if agendar:
            self._entregar(self._aplicar)
        for ao_falhar in avisos:
            self._entregar(ao_falhar)

    def _aplicar(self) -> bool:
        """Aplica o quadro mais novo de cada dono. Thread principal.

        Descarta o de quem o tocador largou ou esqueceu depois de o ler (capa
        parada de vez, cópia regravada): ele seria do estado antigo.
        """
        with self._trava:
            pendentes, self._pendentes = self._pendentes, {}
            vigentes = [
                (ao_quadro, quadro)
                for dono, (estado, versao, ao_quadro, quadro) in pendentes.items()
                if self._estados.get(dono) is estado and estado.versao == versao
            ]
        for ao_quadro, quadro in vigentes:
            try:
                ao_quadro(*quadro)
            except Exception:  # noqa: BLE001 - uma capa não derruba as outras
                logging.exception("Erro ao aplicar o quadro da capa")
        return False  # o GLib repetiria o callback que devolvesse um valor verdadeiro

    def _ocioso(self) -> bool:
        """Se o próximo passo não teria nada a fazer. Chamar com a trava.

        Suspenso, só as pausadas (que ainda fecham) e as cópias por fechar
        dão trabalho; o resto espera o ``suspender(False)``.
        """
        if self._suspenso:
            return all(
                e.pausado_em is None and e.imagem is None
                for e in self._estados.values()
            )
        return not self._estados

    def _rodar(self) -> None:
        while True:
            # Limpa antes de conferir: um ``tocar`` que chegue depois do
            # ``clear`` deixa o evento ligado e o ``wait`` não dorme.
            self._acordar.clear()
            with self._trava:
                ocioso = self._ocioso()
            if ocioso:
                self._acordar.wait()
            inicio = time.monotonic()
            try:
                self.passo()
            except Exception:  # noqa: BLE001
                logging.exception("Erro no tocador de capas")
            time.sleep(max(0.0, TICK - (time.monotonic() - inicio)))


tocador = Tocador()
