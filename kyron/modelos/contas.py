# contas.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As contas das lojas (Microsoft, Epic e EA) e as janelas de login.

`LoginDaLoja` é a janela de login da EA e da Epic: a página da loja abre no navegador e a pessoa cola o que copiou. As duas
só diferem nos textos, no campo, no botão e no endereço (uma `Loja`, em `conquistas/*/janela.py`). A troca vai à rede numa
thread e o resultado volta na principal; com a janela já fechada, só a conta conectada conta. O texto colado (traz cookies)
nunca vai para o log.

`ContasDasLojas` é o grupo "Contas" (`GrupoDasContas.qml`): três linhas, o login pendente da Microsoft e as duas janelas.
Quem hospeda o grupo o cria e chama `fechar()` ao fechar a tela. Só na thread principal.
"""

import logging
import os
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from types import SimpleNamespace
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from kyron import shared
from kyron.conquistas import fontes, vigia_da_conta
from kyron.conquistas.ea import conta as ea_conta
from kyron.conquistas.epic import conta as epic_conta
from kyron.conquistas.xbox import conta as xbox_conta
from kyron.conquistas.xbox import login as xbox_login

_OK, _RECUSADO, _FALHOU = "ok", "recusado", "falhou"
# Os logins com a troca na rede: a thread só tem referência fraca (o QObject nunca é largado por ela); esta é a forte, da thread
# principal: o login conecta e lê os jogos mesmo que a tela que o hospedava já tenha fechado.
_em_voo: set["LoginDaLoja"] = set()


@dataclass(frozen=True)
class Loja:
    """Tudo o que muda entre a janela de login da EA e a da Epic."""

    titulo: str
    passos: tuple[str, ...]
    rotulo_do_campo: str
    multilinha: bool
    botao_da_pagina: str
    url_do_botao: str
    aviso_sem_navegador: str
    mostra_endereco: bool
    texto_recusado: str
    texto_falhou: str
    log: str  # o nome da loja nas mensagens de log
    conta: Any  # o módulo da conta: `conectar`, `PAGINA_DE_LOGIN`
    extrair: Callable[[str], Any]  # None = o texto não serve (o "Conectar" fica apagado)
    recusa: type[Exception]  # o que `conta.conectar` levanta quando a loja recusa o login
    argumento: Callable[[str, Any], Any]  # o que vai a `conta.conectar`: o texto colado ou o que se extraiu dele


def _abrir_navegador(url: str) -> None:
    os.startfile(url)  # type: ignore[attr-defined]  # pylint: disable=no-member


def _fraco(metodo: Callable[..., Any]) -> Callable[..., Any]:
    """O método sem prender o objeto: o QObject não pode ser largado por uma thread de trabalho."""
    ref = weakref.WeakMethod(metodo)

    def chamar(*args: Any) -> Any:
        if (vivo := ref()) is not None:
            return vivo(*args)
        return None

    return chamar


class LoginDaLoja(QObject):
    mudou = Signal()
    fechou = Signal()

    def __init__(
        self,
        loja: Loja,
        ao_conectar: Callable[[], None],
        abrir: Callable[[str], None] | None = None,
        em_thread: Callable[..., None] = vigia_da_conta._em_thread,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._loja = loja
        self._ao_conectar = ao_conectar
        # `None` = o navegador do Windows, buscado a cada uso (é o que o `conftest.py` troca).
        self._abrir = abrir
        self._em_thread = em_thread
        self._aberto = False
        self._fechada = False
        self._texto = ""
        self._ocupada = False
        self._erro = ""
        self._endereco_visivel = False

    titulo = Property(str, lambda self: self._loja.titulo, constant=True)
    passos = Property("QStringList", lambda self: list(self._loja.passos), constant=True)
    rotuloDoCampo = Property(str, lambda self: self._loja.rotulo_do_campo, constant=True)  # noqa: N815
    multilinha = Property(bool, lambda self: self._loja.multilinha, constant=True)
    botaoDaPagina = Property(str, lambda self: self._loja.botao_da_pagina, constant=True)  # noqa: N815
    endereco = Property(str, lambda self: self._loja.conta.PAGINA_DE_LOGIN if self._loja.mostra_endereco else "", constant=True)

    @Property(bool, notify=mudou)
    def aberto(self) -> bool:
        return self._aberto

    def _ler_texto(self) -> str:
        return self._texto

    def _gravar_texto(self, texto: str) -> None:
        if texto != self._texto:
            self._texto = texto
            self.mudou.emit()

    texto = Property(str, _ler_texto, _gravar_texto, notify=mudou)

    @Property(bool, notify=mudou)
    def podeConectar(self) -> bool:  # noqa: N802
        return not self._ocupada and self._loja.extrair(self._texto) is not None

    @Property(bool, notify=mudou)
    def ocupada(self) -> bool:
        return self._ocupada

    @Property(str, notify=mudou)
    def erro(self) -> str:
        """Vazio = o erro fica escondido."""
        return self._erro

    @Property(bool, notify=mudou)
    def enderecoVisivel(self) -> bool:  # noqa: N802
        return self._endereco_visivel

    def _mostrar(self, **campos: Any) -> None:
        for nome, valor in campos.items():
            setattr(self, f"_{nome}", valor)
        self.mudou.emit()

    @Slot()
    def abrir(self) -> None:
        self._fechada = False
        self._mostrar(aberto=True)
        self._abrir_url(self._loja.conta.PAGINA_DE_LOGIN)

    @Slot()
    def abrirPagina(self) -> None:  # noqa: N802
        self._abrir_url(self._loja.url_do_botao)

    def _abrir_url(self, url: str) -> None:
        aviso = self._loja.aviso_sem_navegador
        try:
            (self._abrir or _abrir_navegador)(url)
        except Exception as erro:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao abrir a página da %s: %s", self._loja.log, type(erro).__name__)
            self._mostrar(erro=aviso, endereco_visivel=self._loja.mostra_endereco)
        else:
            # Só o aviso do navegador some; um erro de login anterior continua.
            self._mostrar(erro="" if self._erro == aviso else self._erro, endereco_visivel=False)

    @Slot()
    def fechar(self) -> None:
        if self._fechada:
            return
        self._fechada = True
        self._mostrar(aberto=False)
        self.fechou.emit()

    @Slot()
    def conectar(self) -> None:
        loja, texto = self._loja, self._texto
        extraido = loja.extrair(texto)
        if extraido is None or self._ocupada:
            return
        self._mostrar(erro="", endereco_visivel=False, ocupada=True)
        _em_voo.add(self)

        def trabalho() -> str:
            try:
                loja.conta.conectar(loja.argumento(texto, extraido))
                return _OK
            except loja.recusa:
                return _RECUSADO
            except Exception as erro:  # pylint: disable=broad-exception-caught
                logging.info("Conta %s: o login falhou (%s)", loja.log, type(erro).__name__)
                return _FALHOU

        try:
            self._em_thread(trabalho, _fraco(self._receber))
        except Exception as erro:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao iniciar o login da %s: %s", loja.log, type(erro).__name__)
            self._receber(_FALHOU)

    def _receber(self, resultado: str | None) -> None:
        # None só chega se o trabalho levantar fora de `Exception` (o `_em_thread` entrega None): falha genérica.
        loja = self._loja
        _em_voo.discard(self)
        self._mostrar(ocupada=False)
        if resultado == _OK:
            # A conta já conectou, com a janela aberta ou não (Cancelar, Esc, tela fechada durante a troca): a leitura dos jogos tem de acontecer.
            try:
                self.fechar()
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao fechar a janela de login da %s", loja.log, exc_info=True)
            try:
                self._ao_conectar()
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao avisar que a conta %s conectou", loja.log, exc_info=True)
            return
        if self._fechada:
            return
        if resultado == _RECUSADO:
            self._mostrar(texto="", erro=loja.texto_recusado)
        else:
            self._mostrar(erro=loja.texto_falhou)


def _varrer_jogos_da_loja(filtro: Callable[[Any], bool], loja: str) -> None:
    """Depois do login: lê na hora as conquistas dos jogos da loja, sem aviso de novas."""
    try:
        varredura = getattr(shared.aplicativo, "varredura_conquistas", None)
        if varredura is not None:
            # O filtro lê o disco do jogo: quem o aplica é a thread da varredura.
            varredura.varrer_jogos(list(shared.store), filtro=filtro)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao ler as conquistas da conta %s depois do login", loja, exc_info=True)


def _ao_entrar_xbox(
    grupo: "weakref.ref[ContasDasLojas]", avisos: Any, quem: object, resultado: "xbox_login.Resultado"
) -> None:
    """O fim do login da conta Microsoft. Sem o grupo (a tela fechou), sobra só a leitura dos jogos."""
    vivo = grupo()
    if vivo is not None:
        # Só esquece o pedido que terminou: o OK tardio de um cancelado não apaga o pedido novo.
        if vivo._quem_pediu is quem:  # noqa: SLF001
            vivo._pedido = None  # noqa: SLF001
        vivo._atualizar()  # noqa: SLF001
    # Cancelar durante a troca de código pode deixar a conta conectada: vale o estado da conta, não o resultado que chegou.
    if resultado is xbox_login.Resultado.CANCELADO and xbox_conta.conectada():
        resultado = xbox_login.Resultado.OK
    textos = {
        xbox_login.Resultado.SEM_PERFIL_XBOX: _("Esta conta Microsoft não tem um perfil Xbox."),
        xbox_login.Resultado.CONTA_INFANTIL: _("Esta conta precisa de permissão de um responsável para usar o Xbox."),
        xbox_login.Resultado.FALHOU: _("Não foi possível entrar na conta Microsoft."),
        xbox_login.Resultado.SEM_NAVEGADOR: _("Não foi possível abrir o navegador. Verifique o navegador padrão do Windows."),
        xbox_login.Resultado.PRAZO_ESGOTADO: _("O login da conta Microsoft expirou. Tente novamente."),
    }
    if resultado in textos:
        if vivo is not None and not vivo._fechado:  # noqa: SLF001
            avisos.adicionar(textos[resultado])
    elif resultado is xbox_login.Resultado.OK:
        _varrer_jogos_da_loja(fontes.eh_do_xbox, "Xbox")


def _dados_da_loja(chave: str) -> SimpleNamespace:
    """O que o grupo precisa de cada loja de colar-e-conectar. As janelas são importadas aqui (elas importam `Loja`)."""
    if chave == "epic":
        from kyron.conquistas.epic import janela  # noqa: PLC0415

        return SimpleNamespace(
            conta=epic_conta,
            loja=janela.LOJA,
            ao_conectar=lambda: _varrer_jogos_da_loja(fontes.eh_da_epic, "Epic"),
            erro_ao_sair=_("Não foi possível sair da conta Epic."),
            erro_ao_abrir=_("Não foi possível abrir a janela de login da Epic."),
        )
    from kyron.conquistas.ea import janela  # noqa: PLC0415

    return SimpleNamespace(
        conta=ea_conta,
        loja=janela.LOJA,
        ao_conectar=lambda: _varrer_jogos_da_loja(fontes.eh_da_ea, "EA"),
        erro_ao_sair=_("Não foi possível sair da conta EA."),
        erro_ao_abrir=_("Não foi possível abrir a janela de login da EA."),
    )


def _login_fechou(grupo: "weakref.ref[ContasDasLojas]", chave: str, login: "weakref.ref[LoginDaLoja]") -> None:
    if (vivo := grupo()) is not None:
        vivo._soltar_login(chave, login())  # noqa: SLF001


class ContasDasLojas(QObject):
    mudou = Signal()
    loginsMudaram = Signal()  # noqa: N815

    titulo = Property(str, lambda _self: _("Contas"), constant=True)
    descricao = Property(
        str,
        lambda _self: _(
            "Entre com as contas das lojas para acompanhar as conquistas dos jogos do Xbox, do Game Pass, da Epic "
            "Games Store e do EA app."
        ),
        constant=True,
    )

    def __init__(
        self,
        avisos: Any,
        abrir: Callable[[str], None] | None = None,
        em_thread: Callable[..., None] = vigia_da_conta._em_thread,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._avisos = avisos
        self._abrir = abrir
        self._em_thread = em_thread
        self._fechado = False
        self._pedido: Any = None
        self._quem_pediu: object = None
        self._logins: dict[str, LoginDaLoja] = {}
        self._linhas = self._montar()
        # Os ouvintes das contas são globais: com referência fraca, não seguram o grupo.
        eu = weakref.ref(self)

        def ouvinte() -> None:
            if (grupo := eu()) is not None:
                grupo._atualizar()  # noqa: SLF001

        self._remover = [modulo.ao_mudar(ouvinte) for modulo in (xbox_conta, epic_conta, ea_conta)]

    microsoft = Property("QVariantMap", lambda self: self._linhas["microsoft"], notify=mudou)
    epic = Property("QVariantMap", lambda self: self._linhas["epic"], notify=mudou)
    ea = Property("QVariantMap", lambda self: self._linhas["ea"], notify=mudou)

    @Property(QObject, notify=loginsMudaram)
    def loginEpic(self) -> QObject | None:  # noqa: N802
        return self._logins.get("epic")

    @Property(QObject, notify=loginsMudaram)
    def loginEa(self) -> QObject | None:  # noqa: N802
        return self._logins.get("ea")

    def _montar(self) -> dict[str, dict[str, str]]:
        if self._pedido is not None:
            microsoft = _("Aguardando o login no navegador…"), _("Cancelar")
        elif xbox_conta.conectada():
            microsoft = xbox_conta.gamertag() or _("Conta Microsoft"), _("Sair")
        else:
            microsoft = _("Não conectada"), _("Entrar")
        epic = (epic_conta.nome() or _("Conta Epic"), _("Sair")) if epic_conta.conectada() else (_("Não conectada"), _("Entrar"))
        ea = (ea_conta.nome() or _("Conta EA"), _("Sair")) if ea_conta.conectada() else (_("Não conectada"), _("Entrar"))
        return {
            chave: {"titulo": titulo, "subtitulo": subtitulo, "botao": botao}
            for chave, titulo, (subtitulo, botao) in (
                ("microsoft", _("Conta Microsoft"), microsoft),
                ("epic", _("Conta Epic"), epic),
                ("ea", _("Conta EA"), ea),
            )
        }

    def _atualizar(self) -> None:
        if not self._fechado and (linhas := self._montar()) != self._linhas:
            self._linhas = linhas
            self.mudou.emit()

    def _avisar(self, texto: str) -> None:
        self._avisos.adicionar(texto)

    @Slot()
    def clicarMicrosoft(self) -> None:  # noqa: N802
        if self._pedido is not None:
            self._pedido.cancelar()
            return
        if xbox_conta.conectada():
            xbox_conta.sair()
            self._atualizar()
            return
        try:
            quem = self._quem_pediu = object()
            self._pedido = xbox_login.entrar(partial(_ao_entrar_xbox, weakref.ref(self), self._avisos, quem))
        except Exception as erro:  # pylint: disable=broad-exception-caught
            # Porta local bloqueada, limite de handles, falha ao criar a thread: o clique não levanta e a pessoa vê o aviso.
            logging.warning("Falha ao iniciar o login da conta Microsoft: %s", type(erro).__name__)
            self._ao_entrar(xbox_login.Resultado.FALHOU)
            return
        self._atualizar()

    def _ao_entrar(self, resultado: "xbox_login.Resultado") -> None:
        _ao_entrar_xbox(weakref.ref(self), self._avisos, self._quem_pediu, resultado)

    @Slot()
    def clicarEpic(self) -> None:  # noqa: N802
        self._clicar_loja("epic")

    @Slot()
    def clicarEa(self) -> None:  # noqa: N802
        self._clicar_loja("ea")

    def _clicar_loja(self, chave: str) -> None:
        dados = _dados_da_loja(chave)
        if dados.conta.conectada():
            try:
                dados.conta.sair()
            except Exception as erro:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao sair da conta %s: %s", dados.loja.log, type(erro).__name__)
                self._avisar(dados.erro_ao_sair)
            self._atualizar()
            return
        if chave in self._logins:
            return
        login = None
        try:
            login = LoginDaLoja(dados.loja, dados.ao_conectar, self._abrir, self._em_thread)
            self._logins[chave] = login
            login.fechou.connect(partial(_login_fechou, weakref.ref(self), chave, weakref.ref(login)))
            self.loginsMudaram.emit()
            login.abrir()
        except Exception as erro:  # pylint: disable=broad-exception-caught
            # Sem soltar a janela, "Entrar" ficaria morto.
            logging.warning("Falha ao abrir o login da conta %s: %s", dados.loja.log, type(erro).__name__)
            self._soltar_login(chave, login)
            self._avisar(dados.erro_ao_abrir)

    def _soltar_login(self, chave: str, login: LoginDaLoja | None) -> None:
        """A janela fechou (ou nem abriu): sai da vista e a linha da conta volta a ser lida."""
        if login is not None and self._logins.get(chave) is login:
            del self._logins[chave]
            self.loginsMudaram.emit()
        self._atualizar()

    @Slot()
    def fechar(self) -> None:
        """Cancela o login pendente, fecha as janelas de login e solta os ouvintes das contas. Pode ser chamado mais de uma vez."""
        self._fechado = True
        xbox_login.cancelar_pendente()
        for login in list(self._logins.values()):
            try:
                login.fechar()
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao fechar a janela de login da conta", exc_info=True)
        remover, self._remover = self._remover, []
        for fn in remover:
            fn()
