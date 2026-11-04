# fita_wizard.py
#
# Copyright 2026 joaomgabaldi
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Onde as fitas de LED são configuradas, uma vez.

O Access Secret fica salvo (DPAPI, amarrado à conta do Windows) só para pré-preencher a tela, e só depois de uma busca
que prova os dois códigos. Quem acende uma fita é a chave local, gravada em claro no `fitas.json`.
"""

import logging
import threading
import weakref
from typing import Any, Optional

import shiboken6
from PySide6.QtCore import Property, QObject, Signal, Slot

from cartridges.utils import open_uri, session_fita, tuya_conta
from cartridges.utils.session_fita import Fita, devolver_removidas, fitas, gravar_fitas
from cartridges.utils.thread_principal import na_thread_principal

PAINEL_DA_TUYA = "https://auth.tuya.com/?from=https%3A%2F%2Fdeveloper.tuya.com%3Fredirect%3Dhttps%3A%2F%2Fplatform.tuya.com"

# As regiões da Tuya, na ordem da lista da tela: o índice escolhido lá é o índice daqui.
REGIOES = ("us", "eu", "cn", "in")


def credencial_valida(nuvem: Any, resposta: Any) -> bool:
    """A busca provou que os dois códigos funcionam? A tinytuya devolve lista vazia também com o token recusado (erro em `nuvem.error`)."""
    return bool(getattr(nuvem, "token", None)) and not getattr(
        nuvem, "error", None
    ) and isinstance(resposta, list)


# Categorias da nuvem da Tuya que falam cor pelos pontos 20/21/24: fita de LED (dd) e lâmpada (dj).
CATEGORIAS = ("dd", "dj")


def fitas_da_nuvem(resposta: Any) -> list[Fita]:
    """Converte a lista que a nuvem devolve em fitas: só fita de LED e lâmpada (``CATEGORIAS``, ou sem categoria), com chave local.

    Sem IP entra com o campo vazio (a nuvem dá o IP público do roteador; ``com_enderecos`` acha o da fita). Aceita qualquer
    entrada: com a busca falhando a ``tinytuya`` devolve um dicionário de erro, que não pode virar exceção na thread.
    """
    if not isinstance(resposta, list):
        return []

    encontradas = []
    for item in resposta:
        if not isinstance(item, dict):
            continue
        categoria = item.get("category")
        if categoria and categoria not in CATEGORIAS:
            continue
        chave = str(item.get("key") or "")
        identificador = str(item.get("id") or "")
        if not chave or not identificador:
            continue
        encontradas.append(
            Fita(
                str(item.get("name") or identificador),
                identificador,
                str(item.get("ip") or ""),
                chave,
                str(item.get("version") or "3.3"),
            )
        )
    return encontradas


def com_enderecos(
    encontradas: list[Fita],
    mapa: dict[str, str],
    versoes: Optional[dict[str, str]] = None,
) -> list[Fita]:
    """Põe em cada fita o endereço na rede local e a versão do protocolo anunciados na varredura por broadcast.

    A nuvem não sabe o IP local. A fita não achada mantém o que tinha; um módulo 3.4 ou 3.5 falado como 3.3 nunca responde.
    """
    configuradas = {fita.id: fita for fita in fitas()}
    versoes = versoes or {}
    return [
        fita._replace(
            ip=mapa.get(fita.id)
            or fita.ip
            or getattr(configuradas.get(fita.id), "ip", ""),
            versao=versoes.get(fita.id) or fita.versao,
            # O brilho por dispositivo e a calibração são daqui, não da nuvem.
            brilho=getattr(configuradas.get(fita.id), "brilho", fita.brilho),
            calibracao=getattr(configuradas.get(fita.id), "calibracao", fita.calibracao),
        )
        for fita in encontradas
    ]


def _nuvem(regiao: str, chave: str, segredo: str) -> Any:
    """A fábrica da nuvem da Tuya: o único ponto que fala com ela (os testes trocam este)."""
    import tinytuya  # noqa: PLC0415

    return tinytuya.Cloud(apiRegion=regiao, apiKey=chave, apiSecret=segredo)


def _buscar(eu: "weakref.ref[FitaWizard]", busca: int, chave: str, segredo: str, regiao: str) -> None:
    """A busca, numa thread: não toca no assistente, só devolve o resultado à principal por referência fraca."""
    try:
        # Dentro do try: sem a biblioteca instalada, um ImportError aqui deixaria a tela presa no "Buscando…".
        nuvem = _nuvem(regiao, chave, segredo)
        resposta = nuvem.getdevices()
        if credencial_valida(nuvem, resposta):
            tuya_conta.salvar(tuya_conta.Conta(chave, segredo, regiao))
        encontrados = fitas_da_nuvem(resposta)
    except Exception as erro:  # a tinytuya levanta de tudo aqui também
        # O texto do erro pode trazer a requisição inteira: os dois códigos nunca vão ao log.
        texto = str(erro).replace(segredo, "***").replace(chave, "***")
        logging.warning("Busca na nuvem da Tuya falhou: %s", texto)
        encontrados = []
    na_thread_principal(_entregar, eu, busca, com_enderecos(encontrados, *session_fita.enderecos_na_rede()))


def _entregar(eu: "weakref.ref[FitaWizard]", busca: int, encontrados: list[Fita]) -> None:
    assistente = eu()
    if assistente is not None and shiboken6.isValid(assistente) and assistente._busca == busca:  # noqa: SLF001
        assistente._mostrar(encontrados)  # noqa: SLF001


class FitaWizard(QObject):
    """O assistente das fitas, sem tela: a `ConfiguracaoDasFitas.qml` lê e grava estas propriedades.

    Só na thread principal; o resultado de uma busca já deixada para trás é descartado.
    """

    alterado = Signal()
    fechado = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._pagina = "credenciais"
        self._chave = ""
        self._segredo = ""
        self._regiao = 0
        self._sem_resultado = False
        self._encontradas: list[Fita] = []
        self._marcadas: set[str] = set()
        self._busca = 0
        self._fechado = False
        self._preencher_credenciais()

    def _preencher_credenciais(self) -> None:
        conta = tuya_conta.carregar()
        if conta is None:
            return
        self._chave = conta.chave
        self._segredo = conta.segredo
        try:
            self._regiao = REGIOES.index(conta.regiao)
        except ValueError:
            self._regiao = 0

    @Property(str, notify=alterado)
    def pagina(self) -> str:
        return self._pagina

    @Property(str, notify=alterado)
    def chave(self) -> str:
        return self._chave

    @chave.setter
    def chave(self, valor: str) -> None:
        self._chave = valor
        self.alterado.emit()

    @Property(str, notify=alterado)
    def segredo(self) -> str:
        return self._segredo

    @segredo.setter
    def segredo(self, valor: str) -> None:
        self._segredo = valor
        self.alterado.emit()

    @Property(int, notify=alterado)
    def regiao(self) -> int:
        return self._regiao

    @regiao.setter
    def regiao(self, valor: int) -> None:
        self._regiao = max(0, min(len(REGIOES) - 1, int(valor)))
        self.alterado.emit()

    @Property(bool, notify=alterado)
    def semResultado(self) -> bool:  # noqa: N802
        return self._sem_resultado

    @Property("QVariantList", notify=alterado)
    def dispositivos(self) -> list[dict[str, Any]]:
        return [
            {
                "id": fita.id,
                "nome": fita.nome,
                "subtitulo": fita.ip or _("Não encontrado na rede. Verifique se o dispositivo está ligado."),
                "ativo": bool(fita.ip),
                "marcado": fita.id in self._marcadas,
            }
            for fita in self._encontradas
        ]

    @Slot()
    def buscar(self) -> None:
        """Vai à nuvem numa thread; a Secret não sai desta chamada."""
        chave = self._chave.strip()
        segredo = self._segredo.strip()
        regiao = REGIOES[self._regiao] if self._regiao < len(REGIOES) else REGIOES[0]
        if self._fechado or not chave or not segredo:
            return

        self._busca += 1
        self._pagina = "buscando"
        self.alterado.emit()
        threading.Thread(
            target=_buscar, args=(weakref.ref(self), self._busca, chave, segredo, regiao), daemon=True
        ).start()

    def _mostrar(self, encontrados: list[Fita]) -> None:
        if self._fechado:
            return

        # Busca vazia fica nas credenciais: aplicar uma lista vazia apagaria as fitas já configuradas.
        if not encontrados:
            self._encontradas, self._marcadas = [], set()
            self._sem_resultado = True
            self._pagina = "credenciais"
            self.alterado.emit()
            return

        self._sem_resultado = False
        ja_configuradas = {fita.id for fita in fitas()}
        self._encontradas = encontrados
        # Sem endereço não há como falar com a fita: marcá-la seria gravar uma fita que nunca acende.
        self._marcadas = {fita.id for fita in encontrados if fita.ip and fita.id in ja_configuradas}
        self._pagina = "dispositivos"
        self.alterado.emit()

    @Slot(str, bool)
    def marcar(self, id_: str, marcado: bool) -> None:
        fita = next((f for f in self._encontradas if f.id == id_), None)
        if fita is None or not fita.ip:
            return
        (self._marcadas.add if marcado else self._marcadas.discard)(id_)
        self.alterado.emit()

    @Slot()
    def salvar(self) -> None:
        escolhidas = [fita for fita in self._encontradas if fita.id in self._marcadas]
        # Quem sai da configuração sai antes de o arquivo mudar: depois o app não conhece mais a fita e não a devolveria ao estado anterior.
        saindo = [fita for fita in fitas() if fita.id not in self._marcadas]
        gravar_fitas(escolhidas)
        if saindo:
            threading.Thread(target=devolver_removidas, args=(saindo,), daemon=True).start()
        self.fechar()

    @Slot()
    def fechar(self) -> None:
        if self._fechado:
            return
        self._fechado = True
        self.fechado.emit()

    @Slot()
    def abrirPainel(self) -> None:  # noqa: N802
        open_uri.abrir_url(PAINEL_DA_TUYA)
