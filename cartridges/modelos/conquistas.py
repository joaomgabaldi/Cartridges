# conquistas.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O que a página do jogo, o diálogo das conquistas e a tela da sessão mostram (`conquistasDoJogo`).

As funções puras montam os dicionários que o QML lê; `ConquistasDoJogo` segue o jogo da página de detalhes, o do diálogo e o
da sessão, refaz cada vista quando o domínio avisa (`mudou`) e pede os ícones fora da tela. O QML nunca recebe um `Jogo`.
Só na thread principal.
"""

import logging
import time
import weakref
from functools import partial
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from cartridges import shared
from cartridges.conquistas import icones, progresso
from cartridges.conquistas.progresso import Linha, Progresso
from cartridges.modelos.ordem import _url_da_capa  # noqa: PLC2701
from cartridges.utils import game_logo
from cartridges.utils.relative_date import relative_date
from cartridges.utils.thread_principal import eh_thread_principal, na_thread_principal

ICONES_NO_CARTAO = 4
# A largura útil do diálogo (520 menos as margens) e uma altura que não empurra a lista para baixo da dobra.
LARGURA_DO_LOGO = 472
ALTURA_DO_LOGO = 96
ATRASO_DOS_ICONES = 100
# O `icones.carregar` não avisa quando o download falha (o limite dele é 10 s): passada a espera, o pedido se repete.
ESPERA_DO_ICONE = 30.0


def _agora() -> float:
    return time.monotonic()


def data_por_extenso(quando: int) -> Optional[str]:
    """A data por extenso; ``None`` se o carimbo não couber num calendário: o histórico aceita qualquer inteiro de 64 bits, e
    ``datetime.fromtimestamp`` levanta OverflowError, OSError ou ValueError para os absurdos (no Windows, qualquer negativo).
    """
    try:
        texto = str(relative_date(quando))
    except (OverflowError, OSError, ValueError):
        logging.getLogger(__name__).debug("Carimbo fora do calendário: %r", quando)
        return None
    # `relative_date` devolve minúsculas, para seguir um rótulo com dois-pontos; aqui a data aparece sozinha.
    return texto[:1].upper() + texto[1:]


def icone(linha: Linha, mostrar_ocultas: bool, urls: dict[str, str]) -> dict[str, Any]:
    """O ícone de uma conquista: a URL já baixada ("" até chegar), o cinza, a interrogação e a dica."""
    visual = progresso.aparencia(linha, mostrar_ocultas)
    return {
        "url": urls.get(visual.origem, ""),
        "cinza": visual.cinza,
        "oculta": visual.oculta,
        # A dica do QML é StyledText: o `<br>` quebra a linha.
        "dica": progresso.dica(linha, mostrar_ocultas).replace("\n", "<br>"),
    }


def cartao_da_pagina(atual: Optional[Progresso], urls: dict[str, str]) -> dict[str, Any]:
    if atual is None:
        return {"visivel": False, "contagem": "", "porcentagem": "", "fracao": 0.0, "icones": [], "resto": ""}
    resto = atual.feitas - ICONES_NO_CARTAO
    return {
        "visivel": True,
        "contagem": _("{} de {}").format(atual.feitas, atual.total),
        "porcentagem": f"{atual.porcentagem}%",
        "fracao": atual.fracao,
        # Desbloqueada nunca é oculta: a preferência não muda nada aqui.
        "icones": [icone(linha, False, urls) for linha in atual.desbloqueadas[:ICONES_NO_CARTAO]],
        "resto": f"+{resto}" if resto > 0 else "",
    }


def cartao_da_sessao(atual: Optional[Progresso], mostrar_ocultas: bool, urls: dict[str, str]) -> dict[str, Any]:
    """O cartão da tela da sessão: o progresso e todas as conquistas, desbloqueadas e depois bloqueadas."""
    if atual is None:
        return {"visivel": False, "contagem": "", "porcentagem": "", "fracao": 0.0, "icones": []}
    return {
        "visivel": True,
        "contagem": _("{} de {}").format(atual.feitas, atual.total),
        "porcentagem": f"{atual.porcentagem}%",
        "fracao": atual.fracao,
        "icones": [icone(linha, mostrar_ocultas, urls) for linha in atual.desbloqueadas + atual.bloqueadas],
    }


def fileira(linha: Linha, mostrar_ocultas: bool, urls: dict[str, str]) -> dict[str, Any]:
    info = linha.info
    oculta = progresso.aparencia(linha, mostrar_ocultas).oculta
    porcentagem = ""
    if info.porcentagem is not None:
        texto = progresso.porcentagem_em_texto(info.porcentagem)
        porcentagem = f"★ {texto}" if info.rara else texto
    return {
        "titulo": _("Conquista oculta") if oculta else info.titulo,
        "subtitulo": _("Os detalhes aparecem depois do desbloqueio.") if oculta else info.descricao,
        "icone": icone(linha, mostrar_ocultas, urls),
        "data": (data_por_extenso(linha.quando) or "") if linha.quando else "",
        "porcentagem": porcentagem,
        "rara": info.rara,
        "desbloqueada": linha.desbloqueada,
    }


def _origens(linhas: Any, mostrar_ocultas: bool) -> set[str]:
    return {visual.origem for linha in linhas if (visual := progresso.aparencia(linha, mostrar_ocultas)).origem}


_PAGINA_VAZIA = cartao_da_pagina(None, {})
_SESSAO_VAZIA = cartao_da_sessao(None, False, {})
_DIALOGO_FECHADO: dict[str, Any] = {
    "aberto": False, "nome": "", "logo": "", "larguraDoLogo": 0, "resumo": "", "fracao": 0.0,
    "desbloqueadas": [], "bloqueadas": [],
}  # fmt: skip
# O que cada vista mostra quando falha ou perde o jogo.
_VAZIAS = {"pagina": {"pagina": _PAGINA_VAZIA}, "dialogo": _DIALOGO_FECHADO, "sessao": {"sessao": _SESSAO_VAZIA}}
_VISTAS = ("pagina", "dialogo", "sessao")


def _prop(tipo: Any, nome: str, notify: Any) -> Property:
    return Property(tipo, lambda self: self._v[nome], notify=notify)


class ConquistasDoJogo(QObject):
    alterado = Signal()

    _p = partial(_prop, notify=alterado)
    pagina = _p("QVariantMap", "pagina")
    sessao = _p("QVariantMap", "sessao")
    aberto = _p(bool, "aberto")
    nome = _p(str, "nome")
    logo = _p(str, "logo")
    larguraDoLogo = _p(int, "larguraDoLogo")  # noqa: N815
    resumo = _p(str, "resumo")
    fracao = _p(float, "fracao")
    desbloqueadas = _p("QVariantList", "desbloqueadas")
    bloqueadas = _p("QVariantList", "bloqueadas")
    del _p

    def __init__(self, detalhes: Any, sessao: Any = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._detalhes = detalhes
        self._loja = detalhes.loja
        self._sessao = sessao
        self._jogo_da_sessao = ""  # o jogo que a vista da sessão mostra ("" sem sessão)
        self._v: dict[str, Any] = {"pagina": _PAGINA_VAZIA, "sessao": _SESSAO_VAZIA, **_DIALOGO_FECHADO}
        # O jogo do diálogo; o da página é o dos detalhes. Só o id: o `Jogo` vem da loja na abertura.
        self._dialogo = ""
        # A lista é um retrato do momento em que o diálogo abriu: (progresso, ocultas, nome); só os ícones, que chegam depois, mudam.
        self._retrato: Optional[tuple[Progresso, bool, str]] = None
        self._logo: tuple[str, int] = ("", 0)
        # Ícones: origem → URL `file:` já baixada; as pedidas e ainda a caminho; e as que cada vista usa.
        self._urls: dict[str, str] = {}
        self._a_caminho: dict[str, float] = {}
        self._origens: dict[str, set[str]] = {vista: set() for vista in _VISTAS}
        # Os ícones chegam às dezenas: as vistas que eles pedem são refeitas de uma vez, no máximo a cada ATRASO ms.
        self._a_refazer: set[str] = set()
        self._atraso = QTimer(self)
        self._atraso.setSingleShot(True)
        self._atraso.setInterval(ATRASO_DOS_ICONES)
        self._atraso.timeout.connect(self._refazer_dos_icones)
        # Referência fraca: a configuração é global e o modelo pode morrer antes.
        eu = weakref.ref(self)
        shared.schema.connect("changed::conquistas-mostrar-ocultas", lambda *_: (c := eu()) and c._refazer(("sessao",)))
        detalhes.alterado.connect(self._detalhes_mudou)
        if sessao is not None:
            sessao.alterado.connect(self._sessao_mudou)

    def _alvo(self, vista: str) -> str:
        if vista == "sessao":
            return self._jogo_da_sessao
        return self._detalhes.jogoId if vista == "pagina" else self._dialogo

    def _atual(self, game_id: str) -> Optional[Progresso]:
        jogo = self._loja.get(game_id)
        return progresso.do_jogo(jogo) if jogo is not None else None

    def _refazer(self, vistas: tuple[str, ...] = _VISTAS, game_id: Optional[str] = None) -> None:
        """Refaz as vistas cujo jogo é ``game_id`` (ou todas). Cada uma no seu `try`: a falha de uma não cala a outra."""
        mudou = False
        for vista in vistas:
            alvo = self._alvo(vista)
            if not alvo or (game_id is not None and alvo != game_id):
                continue
            try:
                mudou |= getattr(self, f"_montar_{vista}")(alvo)
            except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                # A da sessão nunca trava o "Já terminei de jogar": some, e a camada segue.
                logging.warning("Falha ao montar as conquistas (%s)", vista, exc_info=True)
                self._origens[vista] = set()
                if vista == "dialogo":
                    self._dialogo = ""
                    self._retrato = None
                mudou |= self._guardar(_VAZIAS[vista])
        if mudou:
            self.alterado.emit()

    def _guardar(self, campos: dict[str, Any]) -> bool:
        if all(self._v[chave] == valor for chave, valor in campos.items()):
            return False
        self._v.update(campos)
        return True

    def _montar_pagina(self, game_id: str) -> bool:
        atual = self._atual(game_id)
        self._pedir("pagina", _origens(atual.desbloqueadas[:ICONES_NO_CARTAO] if atual else (), False))
        return self._guardar({"pagina": cartao_da_pagina(atual, self._urls)})

    def _montar_dialogo(self, game_id: str) -> bool:
        if self._retrato is None:
            atual, jogo = self._atual(game_id), self._loja.get(game_id)
            if atual is None or jogo is None:
                # Sem catálogo, sem fonte ou com a conta desconectada não há o que listar: o diálogo nem abre.
                self._dialogo = ""
                self._origens["dialogo"] = set()
                return self._guardar(_DIALOGO_FECHADO)
            self._retrato = (atual, shared.schema.get_boolean("conquistas-mostrar-ocultas"), jogo.name)
        atual, mostrar, nome = self._retrato
        self._pedir("dialogo", _origens(atual.desbloqueadas + atual.bloqueadas, mostrar))
        return self._guardar({
            "aberto": True, "nome": nome, "logo": self._logo[0], "larguraDoLogo": self._logo[1],
            "resumo": _("{} de {} conquistas desbloqueadas").format(atual.feitas, atual.total),
            "fracao": atual.fracao,
            "desbloqueadas": [fileira(linha, mostrar, self._urls) for linha in atual.desbloqueadas],
            "bloqueadas": [fileira(linha, mostrar, self._urls) for linha in atual.bloqueadas],
        })  # fmt: skip

    def _montar_sessao(self, game_id: str) -> bool:
        atual = self._atual(game_id)
        mostrar = shared.schema.get_boolean("conquistas-mostrar-ocultas")
        self._pedir("sessao", _origens(atual.desbloqueadas + atual.bloqueadas, mostrar) if atual else set())
        return self._guardar({"sessao": cartao_da_sessao(atual, mostrar, self._urls)})

    def _pedir(self, vista: str, origens: set[str]) -> None:
        """Um `icones.carregar` por origem sem URL e que não está a caminho."""
        self._origens[vista] = origens
        eu = weakref.ref(self)
        agora = _agora()
        for origem in origens - self._urls.keys():
            if agora - self._a_caminho.get(origem, -ESPERA_DO_ICONE - 1) <= ESPERA_DO_ICONE:
                continue
            self._a_caminho[origem] = agora

            def entregar(caminho: Path, origem: str = origem) -> None:
                if (modelo := eu()) is not None:
                    modelo._icone_chegou(origem, caminho)  # noqa: SLF001

            icones.carregar(origem, entregar)

    def _icone_chegou(self, origem: str, caminho: Path) -> None:
        self._a_caminho.pop(origem, None)
        self._urls[origem] = QUrl.fromLocalFile(str(caminho)).toString()
        # Só as vistas que usam este ícone; jogo trocado no meio: a URL fica guardada e mais nada.
        self._a_refazer.update(vista for vista, usadas in self._origens.items() if origem in usadas)
        if self._a_refazer and not self._atraso.isActive():
            self._atraso.start()

    def _refazer_dos_icones(self) -> None:
        vistas, self._a_refazer = tuple(v for v in _VISTAS if v in self._a_refazer), set()
        self._refazer(vistas)

    def _detalhes_mudou(self) -> None:
        self._refazer(("pagina",))

    def _sessao_mudou(self) -> None:
        """Só um jogo novo (ou o fim) refaz o cartão: o `alterado` também sai com outros campos da sessão."""
        jogo = self._sessao.jogoId
        if jogo == self._jogo_da_sessao:
            return
        self._jogo_da_sessao = jogo
        if jogo:
            self._refazer(("sessao",))
            return
        self._origens["sessao"] = set()
        if self._guardar(_VAZIAS["sessao"]):
            self.alterado.emit()

    def mudou(self, game_id: Optional[str]) -> None:
        """O histórico, o catálogo ou uma conta mudou: refaz a página e a sessão do jogo (``None`` = todas); a lista do diálogo aberto não muda."""
        if not eh_thread_principal():
            na_thread_principal(self.mudou, game_id)
            return
        self._refazer(("pagina", "sessao"), game_id=game_id)

    @Slot(str)
    def abrir(self, game_id: str) -> None:
        """Abre a lista do jogo; ignora um jogo que a loja não tem ou que não tem cartão."""
        jogo = self._loja.get(game_id)
        if jogo is None:
            return
        self._dialogo = game_id
        self._retrato = None
        logo, largura = "", 0
        # Só o que já está em disco: a busca no SteamGridDB é da página de detalhes, de onde isto é aberto.
        if (caminho := game_logo.cached_logo_path(jogo)) and (
            carregado := game_logo.load_logo(caminho, LARGURA_DO_LOGO, ALTURA_DO_LOGO)
        ):
            logo, largura = _url_da_capa(carregado[0]), carregado[1]
        self._logo = (logo, largura)
        self._refazer(("dialogo",))

    @Slot()
    def fechar(self) -> None:
        self._dialogo = ""
        self._retrato = None
        self._logo = ("", 0)
        self._origens["dialogo"] = set()
        # Só `aberto` cai: o diálogo sai com o conteúdo intacto (120 ms); `abrir` sobrescreve tudo na vez seguinte.
        if self._guardar({"aberto": False}):
            self.alterado.emit()

