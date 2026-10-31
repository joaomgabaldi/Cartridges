# restauracao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A continuação da restauração de um backup (D81), sem tela: a pasta de atalhos, os jogos sem atalho, a escolha do
atalho e o conflito de dados. As regras são do `utils/restauracao.py`; este modelo só guia o fluxo dos quatro modais
da janela (o QML recebe dicionários e ids, nunca um `Jogo`). Só na thread principal."""

import logging
import weakref
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from cartridges import shared
from cartridges.modelos.ordem import _url_da_capa  # noqa: PLC2701
from cartridges.utils import restauracao
from cartridges.utils.format_playtime import format_playtime

_DECISOES = ("backup", "mesclar", "este_pc")


def _sessoes(numero: int) -> str:
    return ngettext("{} sessão", "{} sessões", numero).format(numero)


def _cartao(jogo: Any) -> dict[str, str]:
    segundos, sessoes, ultima = restauracao.resumo(jogo)
    data = datetime.fromtimestamp(ultima).strftime("%d/%m/%Y") if ultima else ""
    return {
        "tempo": format_playtime(segundos),
        "sessoes": _sessoes(sessoes),
        "ultima": _("Última: {}").format(data) if data else "",
    }


class ContinuacaoDaRestauracao(QObject):
    alterado = Signal()
    # O QML abre o seletor de arquivos dos atalhos.
    procurarPedido = Signal()  # noqa: N815

    def __init__(self, aplicativo: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._aplicativo = aplicativo
        self._pedindo_pasta = False
        self._texto_da_pasta = ""
        self._pendentes: list[dict[str, str]] = []
        self._pendentes_abertos = False
        self._travada = False
        self._escolha: dict[str, Any] = {}
        self._alvo = ""  # o jogo cujo atalho se escolhe (também sem lista, quando só o seletor abre)
        self._candidatos: list[Path] = []
        self._conflito: dict[str, Any] = {}
        self._decisao: tuple[str, Path, str] | None = None  # (restaurado, atalho, novo) à espera da escolha

    # region Estado

    @Property(bool, notify=alterado)
    def aberta(self) -> bool:
        return self._pedindo_pasta or self._pendentes_abertos or bool(self._escolha) or bool(self._conflito)

    @Property(bool, notify=alterado)
    def pedindoPasta(self) -> bool:  # noqa: N802
        return self._pedindo_pasta

    @Property(str, notify=alterado)
    def textoDaPasta(self) -> str:  # noqa: N802
        return self._texto_da_pasta

    @Property("QVariantList", notify=alterado)
    def pendentes(self) -> list:
        return self._pendentes

    @Property(bool, notify=alterado)
    def pendentesAbertos(self) -> bool:  # noqa: N802
        return self._pendentes_abertos

    @Property(bool, notify=alterado)
    def listaTravada(self) -> bool:  # noqa: N802
        return self._travada

    @Property("QVariantMap", notify=alterado)
    def escolha(self) -> dict:
        return self._escolha

    @Property(bool, notify=alterado)
    def escolhaAberta(self) -> bool:  # noqa: N802
        return bool(self._escolha)

    @Property("QVariantMap", notify=alterado)
    def conflito(self) -> dict:
        return self._conflito

    @Property(bool, notify=alterado)
    def conflitoAberto(self) -> bool:  # noqa: N802
        return bool(self._conflito)

    # endregion
    # region A pasta de atalhos

    @Slot()
    def continuar(self) -> None:
        """A cada abertura enquanto houver pendências: a pasta de atalhos é obrigatória, a importação roda mesmo com
        "Importar jogos automaticamente" desligado, e a janela dos jogos sem atalho abre no fim dela."""
        local = shared.schema.get_string("shortcuts-location")
        if not local or not Path(local).expanduser().is_dir():
            self._texto_da_pasta = (
                _("A pasta de atalhos usada anteriormente não foi encontrada. Selecione a pasta onde estão os atalhos dos jogos.")
                if local
                else _("Selecione a pasta onde estão os atalhos dos jogos.")
            )
            self._pedindo_pasta = True
            self.alterado.emit()
            return
        self._aplicativo.importar(ao_terminar=self.mostrarPendentes, varrer_atalhos=True, silenciosa=True)

    @Slot(QUrl)
    def escolherPasta(self, url: QUrl) -> None:  # noqa: N802
        if url.isEmpty() or not url.toLocalFile():
            return  # seletor cancelado: a janela continua
        shared.schema.set_string("shortcuts-location", str(Path(url.toLocalFile())))
        self._pedindo_pasta = False
        self.alterado.emit()
        self.continuar()

    # endregion
    # region Os jogos sem atalho

    def _ler_pendentes(self) -> list[dict[str, str]]:
        return [
            {
                "id": jogo.game_id,
                "nome": jogo.name,
                "tempo": format_playtime(jogo.playtime or 0),
                "capa": _url_da_capa(jogo.get_cover_path()),
            }
            for jogo in restauracao.pendentes()
        ]

    @Slot()
    def mostrarPendentes(self) -> None:  # noqa: N802
        """Abre (ou relê) a lista, destravada; sem pendências a restauração acabou ali mesmo."""
        self._pendentes = self._ler_pendentes()
        self._travada = False
        if self._pendentes:
            self._pendentes_abertos = True
            self.alterado.emit()
            return
        self._pendentes_abertos = False
        self.alterado.emit()
        self._aplicativo.avisos.adicionar(_("Restauração concluída"))

    @Slot()
    def lembrarDepois(self) -> None:  # noqa: N802
        """Só fecha: a restauração continua pendente e o aviso de concluída não aparece."""
        self._pendentes_abertos = False
        self.alterado.emit()

    @Slot(str)
    def excluir(self, jogo_id: str) -> None:
        jogo = shared.store.get(jogo_id)
        if jogo is None:
            return
        eu = weakref.ref(self)

        def responder(confirmou: bool) -> None:
            if confirmou and (modelo := eu()) is not None:
                modelo._excluir_de_vez(jogo_id)  # noqa: SLF001

        self._aplicativo.pedir_confirmacao(
            # A variável é o nome do jogo
            _("Excluir {}?").format(jogo.name),
            _("Tem certeza que deseja excluir este jogo? Esta ação é irreversível."),
            _("Excluir"),
            responder,
            destrutivo=True,
        )

    def _excluir_de_vez(self, jogo_id: str) -> None:
        if (jogo := shared.store.get(jogo_id)) is not None:
            restauracao.excluir(jogo)
        self.mostrarPendentes()

    # endregion
    # region A escolha do atalho

    @Slot(str)
    def escolherAtalho(self, jogo_id: str) -> None:  # noqa: N802
        jogo = shared.store.get(jogo_id)
        if jogo is None:
            return
        self._alvo = jogo_id
        candidatos = restauracao.candidatos(jogo)
        if not candidatos:
            # Sem atalho para sugerir, a janela teria só o botão de procurar: abre direto o seletor.
            self.procurarPedido.emit()
            return
        self._candidatos = candidatos
        self._escolha = {
            "id": jogo_id,
            "nome": jogo.name,
            "candidatos": [{"caminho": str(c), "titulo": c.stem, "subtitulo": c.name} for c in candidatos],
        }
        self.alterado.emit()

    @Slot()
    def procurar(self) -> None:
        self.procurarPedido.emit()

    @Slot()
    def fecharEscolha(self) -> None:  # noqa: N802
        self._alvo = ""
        self._candidatos = []
        self._escolha = {}
        self.alterado.emit()

    @Slot(str)
    def usarAtalho(self, caminho: str) -> None:  # noqa: N802
        """Só um caminho da lista de candidatos atual (o QML é a fronteira)."""
        escolhido = next((c for c in self._candidatos if str(c) == caminho), None)
        if escolhido is not None:
            self._usar(escolhido)

    @Slot(QUrl)
    def procurado(self, url: QUrl) -> None:
        if not self._alvo or url.isEmpty() or not url.toLocalFile():
            return
        try:
            caminho = restauracao.copiar_para_a_pasta(Path(url.toLocalFile()))
        except restauracao.AtalhoJaExiste:
            # Sem candidatos, o atalho de mesmo nome é de outro jogo e não há lista onde selecioná-lo.
            if self._candidatos:
                self._aplicativo.pedir_dialogo(
                    _("Já existe um atalho com este nome. Selecione-o na lista."), "", [], lambda: None
                )
            else:
                self._aplicativo.pedir_dialogo(
                    _("Já existe um atalho com este nome na pasta de atalhos."), "", [], lambda: None
                )
            return
        except OSError:
            # shortcut: a cópia que falha só vai ao log (a `main` deixava a exceção subir) e não há texto aprovado para o aviso; sai quando houver (o diálogo de erro inesperado do plano 8b, ou um texto aprovado).
            logging.exception("Não foi possível copiar o atalho %s", url.toLocalFile())
            return
        self._usar(caminho)

    def _usar(self, caminho: Path) -> None:
        jogo = shared.store.get(self._alvo)
        self.fecharEscolha()
        if jogo is None:
            self.mostrarPendentes()
            return
        novo = restauracao.jogo_do_atalho(caminho)
        if novo is not None and restauracao.tem_historico(novo):
            self._decisao = (jogo.game_id, caminho, novo.game_id)
            segundos_a, sessoes_a, _ultima = restauracao.resumo(jogo)
            segundos_b, sessoes_b, _ultima = restauracao.resumo(novo)
            self._conflito = {
                "nome": jogo.name,
                "capa": _url_da_capa(jogo.get_cover_path()),
                "backup": _cartao(jogo),
                "estePc": _cartao(novo),
                "dica": _("Mesclar dados: {} em {}").format(
                    format_playtime(segundos_a + segundos_b), _sessoes(sessoes_a + sessoes_b)
                ),
            }
            self.alterado.emit()
        else:
            self._concluir(jogo, caminho, novo, "backup")

    def _concluir(self, jogo: Any, caminho: Path, novo: Any, decisao: str) -> None:
        restauracao.decidir(jogo, caminho, novo, decisao)
        if decisao == "este_pc":
            self.mostrarPendentes()
            return
        # A varredura adota o jogo pelo atalho novo e o tira das pendências. A lista fica travada até lá: duas
        # importações ao mesmo tempo zerariam as listas de jogos achados uma da outra.
        self._travada = True
        self.alterado.emit()
        self._aplicativo.importar(ao_terminar=self.mostrarPendentes, varrer_atalhos=True, silenciosa=True)

    # endregion
    # region O conflito de dados

    @Slot()
    def cancelarConflito(self) -> None:  # noqa: N802
        self._decisao = None
        self._conflito = {}
        self.alterado.emit()

    @Slot(str)
    def decidir(self, decisao: str) -> None:
        if decisao not in _DECISOES or self._decisao is None:
            return
        jogo_id, caminho, novo_id = self._decisao
        self.cancelarConflito()
        jogo = shared.store.get(jogo_id)
        if jogo is None:
            self.mostrarPendentes()
            return
        self._concluir(jogo, caminho, shared.store.get(novo_id), decisao)

    # endregion
