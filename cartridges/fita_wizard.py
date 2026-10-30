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

O módulo Tuya só aceita comandos de quem tem a chave local dele, e essa chave
não está no app Smart Life — ela sai da conta de desenvolvedor da Tuya, pela
nuvem. Este assistente faz essa viagem uma vez: pede as credenciais da conta,
lista os dispositivos e grava a chave dos que o usuário apontar como fitas.

O Access Secret fica salvo — criptografado pelo DPAPI do Windows, amarrado à
conta do Windows de quem roda o app — só para pré-preencher esta tela na
próxima vez, e só depois de uma busca que prova que os dois códigos são
válidos. O dia a dia das fitas nunca usa isso: quem acende uma fita é a chave
local, achada aqui e gravada à parte, em claro, no `fitas.json`.
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

# O painel de desenvolvedor da Tuya, de onde saem o Access ID e o Access Secret.
PAINEL_DA_TUYA = "https://auth.tuya.com/?from=https%3A%2F%2Fdeveloper.tuya.com%3Fredirect%3Dhttps%3A%2F%2Fplatform.tuya.com"

# As regiões que a Tuya oferece, na mesma ordem da lista do `.blp`. As duas
# listas precisam andar juntas: o índice escolhido na tela é o índice aqui.
REGIOES = ("us", "eu", "cn", "in")


def credencial_valida(nuvem: Any, resposta: Any) -> bool:
    """A busca provou que os dois códigos funcionam?

    A tinytuya devolve lista vazia também quando o token é recusado (o erro
    fica em `nuvem.error`), então a lista sozinha não prova nada.
    """
    return bool(getattr(nuvem, "token", None)) and not getattr(
        nuvem, "error", None
    ) and isinstance(resposta, list)


# Categorias da nuvem da Tuya que falam cor pelos pontos 20/21/24: fita de LED
# (dd) e lâmpada (dj). O resto da conta — interruptor, tomada, sensor, controle
# IR — não tem o que fazer aqui.
CATEGORIAS = ("dd", "dj")


def fitas_da_nuvem(resposta: Any) -> list[Fita]:
    """Converte a lista que a nuvem devolve em fitas.

    Só fita de LED e lâmpada entram (``CATEGORIAS``); dispositivo sem categoria
    na resposta entra também. Dispositivo sem chave local fica de fora: sem ela
    não há conversa possível.
    Sem IP, entra com o campo vazio — a nuvem devolve o IP público do roteador,
    que não serve para nada aqui. Quem acha o IP da fita é a varredura que este
    assistente roda logo depois (``com_enderecos``), uma vez só; o app nunca
    varre sozinho.

    Aceita qualquer coisa como entrada de propósito: quando a busca falha, a
    ``tinytuya`` devolve um dicionário de erro no lugar da lista, e isso não
    pode virar exceção dentro da thread.
    """
    if not isinstance(resposta, list):
        return []

    encontradas = []
    for item in resposta:
        if not isinstance(item, dict):
            continue
        # Sem categoria entra: resposta que não traz o campo não é prova de
        # que o dispositivo não fala cor.
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
    """Põe em cada fita o endereço que ela tem na rede de casa, e a versão do
    protocolo que ela anunciou.

    A nuvem não sabe o IP local das fitas; quem sabe é a varredura por
    broadcast, que roda uma única vez, aqui. O endereço achado fica gravado e o
    app não procura mais: o IP das fitas é fixo, e se um dia mudar é só rodar
    este assistente de novo. A fita que a varredura não achou mantém o endereço
    que já tinha na configuração, se tinha um.

    A versão vem da mesma varredura: a nuvem costuma não dizê-la, e um módulo
    3.4 ou 3.5 falado como 3.3 nunca responde.
    """
    configuradas = {fita.id: fita for fita in fitas()}
    versoes = versoes or {}
    return [
        fita._replace(
            ip=mapa.get(fita.id)
            or fita.ip
            or getattr(configuradas.get(fita.id), "ip", ""),
            versao=versoes.get(fita.id) or fita.versao,
            # A nuvem não sabe do brilho por dispositivo nem da calibração:
            # eles são daqui.
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
        # A tinytuya devolve lista vazia também quando o token é recusado (o erro fica em `nuvem.error`), então só a
        # lista não prova que a credencial funcionou, e uma credencial que não funcionou não merece ficar salva.
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
    """O assistente das fitas, sem tela: a tela (`ConfiguracaoDasFitas.qml`) lê e grava estas propriedades.

    Só na thread principal. A busca vai à nuvem numa thread e volta por `na_thread_principal`; o resultado de uma
    busca que o usuário já deixou para trás (fechou o assistente, ou pediu outra) é descartado.
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
        """Pré-preenche com a conta salva da vez anterior, se houver."""
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

        # Busca vazia fica nas credenciais, com o aviso ali. A página dos dispositivos só tem o botão "Aplicar", e
        # aplicar uma lista vazia apagaria as fitas já configuradas: num clique, e sem caminho de volta para corrigir
        # a credencial errada.
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
        # Quem sai da configuração sai antes de o arquivo mudar: depois da gravação o app não conhece mais essa fita,
        # não tem como devolvê-la ao estado de antes, e ela ficaria na cor do Cartridges para sempre.
        saindo = [fita for fita in fitas() if fita.id not in self._marcadas]
        gravar_fitas(escolhidas)
        if saindo:
            # Rede: fora da thread de UI, como todo o resto da conversa.
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
