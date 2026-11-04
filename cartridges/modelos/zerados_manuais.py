# zerados_manuais.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O "Adicionar a Jogos Zerados": marcar como zerado um jogo já desinstalado ou adicionar um que nunca passou pelo
app. Sem tela: o `SeletorDeZerados.qml` só desenha as `linhas`.

A tela de detalhes só abre para o que está em alguma grade, e um desinstalado sem a marca não está em nenhuma. O campo
do topo busca na Steam (só com Enter, que a loja limita as requisições) e a última linha cria o jogo só pelo nome; a
regra de quem pode entrar fica em `zerado_manual`. Tudo na thread principal; a busca roda numa thread e entrega por
`na_thread_principal`, e o que chega a uma geração velha, ou com o diálogo fechado, é descartado.
"""

import logging
import threading
import weakref
from typing import Any, Optional

import requests
from PySide6.QtCore import Property, QObject, Signal, Slot

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.utils import zerado_manual
from cartridges.utils.format_playtime import format_playtime
from cartridges.utils.name_cleaner import clean_for_search
from cartridges.utils.relative_date import relative_date
from cartridges.utils.steam import SteamError, SteamGameNotFoundError
from cartridges.utils.thread_principal import na_thread_principal

MOTIVO = {
    "zerado": "Já está em Jogos Zerados",
    "biblioteca": "Já está na biblioteca",
}


def candidatos() -> list[Jogo]:
    """Os desinstalados que ainda não são zerados, em ordem de nome."""
    return sorted(
        (jogo for jogo in shared.store if jogo.removed and not jogo.blacklisted and not jogo.zerado),
        key=lambda jogo: jogo.name.casefold(),
    )


def descricao(jogo: Jogo) -> str:
    """Tempo e última vez jogado: o que separa duas fichas de mesmo nome."""
    if not jogo.last_played:
        return "Nunca jogado"
    # As variáveis são o tempo de jogo e a data da última vez jogado
    return "{} · Jogado por último: {}".format(format_playtime(jogo.playtime), relative_date(jogo.last_played))


def _buscar_na_steam(seletor_fraco: "weakref.ref[SeletorDeZerados]", texto: str, geracao: int) -> None:
    """O corpo da thread da busca. Referência fraca: a thread não prende o seletor."""
    aviso = ""
    achados: list[tuple[dict, Any]] = []
    try:
        achados = zerado_manual.helper_da_steam().find_candidates(clean_for_search(texto))
    except SteamGameNotFoundError:
        aviso = "Nenhum jogo encontrado na Steam."
    except (SteamError, requests.RequestException) as erro:
        logging.warning("Busca de zerado na Steam falhou: %s", erro)
        aviso = "Não foi possível concluir a busca na Steam."
    except Exception:  # noqa: BLE001  (uma thread que morre deixaria o indicador girando para sempre)
        logging.exception("Busca de zerado na Steam falhou")
        aviso = "Não foi possível concluir a busca na Steam."
    na_thread_principal(_entregar, seletor_fraco, texto, achados, aviso, geracao)


def _entregar(seletor_fraco: "weakref.ref[SeletorDeZerados]", texto: str, achados: list, aviso: str, geracao: int) -> None:
    if (seletor := seletor_fraco()) is not None:
        seletor._mostrar_resultados(texto, achados, aviso, geracao)  # noqa: SLF001


class SeletorDeZerados(QObject):
    """O estado do `SeletorDeZerados.qml` (contexto `zeradosManuais`): os desinstalados para marcar e, com a busca, os
    jogos para adicionar. Chaves das linhas: `jogo:<game_id>`, `steam:<appid>` e `nome`."""

    alterado = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._aberto = False
        self._estado = "vazio"
        self._aviso = ""
        self._linhas: list[dict[str, Any]] = []
        # Chave → o que a linha cria: ("jogo", Jogo), ("steam", nome, appid) ou ("nome", texto).
        self._destinos: dict[str, tuple] = {}
        # Resposta de uma busca antiga (ou do diálogo já fechado) não pinta a lista.
        self._geracao = 0
        self._ultima: Optional[tuple[str, list, str]] = None

    @Property(bool, notify=alterado)
    def aberto(self) -> bool:
        return self._aberto

    @Property(str, notify=alterado)
    def estado(self) -> str:
        return self._estado

    @Property(str, notify=alterado)
    def aviso(self) -> str:
        return self._aviso

    @Property("QVariantList", notify=alterado)  # type: ignore[arg-type]
    def linhas(self) -> list[dict[str, Any]]:
        return self._linhas

    @Slot()
    def abrir(self) -> None:
        self._geracao += 1
        self._aberto = True
        self._mostrar_desinstalados()

    @Slot()
    def fechar(self) -> None:
        self._geracao += 1
        self._aberto = False
        self._ultima = None
        self._destinos = {}
        self._linhas = []
        self._aviso = ""
        self._estado = "vazio"
        self.alterado.emit()

    @Slot(str)
    def mudouBusca(self, texto: str) -> None:  # noqa: N802
        """Só o campo vazio age sozinho; a busca na Steam espera o Enter."""
        if self._aberto and not texto.strip():
            self._geracao += 1
            self._mostrar_desinstalados()

    @Slot(str)
    def buscar(self, texto: str) -> None:
        texto = texto.strip()
        if not texto or not self._aberto:
            return
        self._geracao += 1
        self._estado = "carregando"
        self._aviso = ""
        self.alterado.emit()
        threading.Thread(
            target=_buscar_na_steam, args=(weakref.ref(self), texto, self._geracao), daemon=True
        ).start()

    @Slot(str)
    def escolher(self, chave: str) -> None:
        """Só uma linha da lista atual e ativa; o resto é ignorado."""
        linha = next((item for item in self._linhas if item["chave"] == chave), None)
        destino = self._destinos.get(chave)
        if linha is None or not linha["ativa"] or destino is None:
            return
        if destino[0] == "jogo":
            # Fica aberto: quem veio marcar os jogos antigos costuma ter vários. Linha velha (o jogo foi reinstalado,
            # ou a ficha trocada na store desde que a lista abriu): só sai da lista, sem mexer no jogo.
            jogo = destino[1]
            if shared.store.get(jogo.game_id) is jogo and jogo.removed:
                jogo.definir_status("beaten")
                jogo.save()
                jogo.update()
            self._linhas = [item for item in self._linhas if item["chave"] != chave]
            self._destinos.pop(chave, None)
            self._estado = "lista" if self._linhas else "vazio"
            self.alterado.emit()
            return
        zerado_manual.adicionar(destino[1], destino[2])
        # Redesenha em vez de tirar a linha: o jogo recém-adicionado volta desativado, e a linha do nome com ele.
        if self._ultima is not None:
            self._mostrar_resultados(*self._ultima, self._geracao)

    def _mostrar_desinstalados(self) -> None:
        self._ultima = None
        self._aviso = ""
        self._destinos = {}
        self._linhas = []
        for jogo in candidatos():
            chave = f"jogo:{jogo.game_id}"
            self._destinos[chave] = ("jogo", jogo)
            self._linhas.append({"chave": chave, "titulo": jogo.name, "subtitulo": descricao(jogo), "ativa": True})
        self._estado = "lista" if self._linhas else "vazio"
        self.alterado.emit()

    def _mostrar_resultados(self, texto: str, achados: list, aviso: str, geracao: int) -> bool:
        if geracao != self._geracao or not self._aberto:
            return False
        self._ultima = (texto, achados, aviso)
        self._aviso = aviso
        self._destinos = {}
        self._linhas = []
        # Um índice por desenho: cada linha pergunta se o jogo já existe.
        jogos = zerado_manual.indice()
        for achado, _pontuacao in achados:
            appid = str(achado.get("id", ""))
            if not appid:
                continue
            nome = str(achado.get("name", ""))
            self._linha(f"steam:{appid}", ("steam", nome, appid), nome, f"ID na Steam: {appid}", jogos)
        self._linha("nome", ("nome", texto, None), f"Adicionar “{texto}” sem dados da Steam", "", jogos)
        self._estado = "lista"
        self.alterado.emit()
        return True

    def _linha(self, chave: str, destino: tuple, titulo: str, subtitulo: str, jogos: zerado_manual.Indice) -> None:
        situacao, _existente = zerado_manual.situacao(destino[1], destino[2], jogos)
        self._destinos[chave] = destino
        self._linhas.append(
            {"chave": chave, "titulo": titulo, "subtitulo": MOTIVO.get(situacao, subtitulo), "ativa": situacao not in MOTIVO}
        )
