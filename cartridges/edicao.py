# edicao.py
#
# Copyright 2022-2024 kramo
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A regra da edição de um jogo, sem tela (D41).

O que o `DetailsDialog.apply_preferences` da `main` fazia, separado dos widgets:
o `Formulario` é o que a tela edita, `validar` dá a primeira mensagem de erro e
`aplicar` grava o formulário no `Jogo`, na mesma ordem e com os mesmos guardas.
Quem desenha (o `ModeloDaEdicao` e o `DialogoDeEdicao.qml`) só preenche o
formulário e mostra o resultado. Tudo aqui roda na thread principal.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from time import time
from typing import Any, Literal, Optional

from cartridges import shared
from cartridges.conquistas import historico
from cartridges.errors.friendly_error import FriendlyError
from cartridges.jogo import STATUS_LABELS, Jogo
from cartridges.store.managers.sgdb_manager import SgdbManager
from cartridges.utils import copias_animadas, game_logo, session_wallpaper
from cartridges.utils.ligacao_zerado import ligar_zerado
from cartridges.utils.process_monitor import install_dir_from_command
from cartridges.utils.run_executable import aumid_from_command
from cartridges.utils.save_cover import save_cover
from cartridges.utils.steam import STEAM_METADATA_VERSION, format_release_date
from cartridges.utils.thread_principal import na_thread_principal

# Os valores gravados do seletor de status: "" ("Sem status") e as chaves de STATUS_LABELS.
STATUS_VALUES = ("", *STATUS_LABELS)
# Os do suporte a controle: None é "não informado".
CONTROLLER_VALUES = (None, "full", "partial")

# As fontes de conquistas em que o appID não é a fonte (`conquistas.fontes`).
_FONTES_DE_CONTA = frozenset({"xbox", "epic", "ubisoft", "ea"})


@dataclass
class Escolha:
    """Uma decisão de logo ou papel de parede tomada na tela, gravada só no Aplicar.

    ``modo``: ``"auto"`` (voltar ao automático), ``"manual"`` (o ``arquivo``),
    ``"title"`` (logo: mostrar o título) ou ``"none"`` (parede: não trocar).
    ``temporario``: o arquivo é uma cópia que a tela recebeu de um seletor; sai
    depois de gravado. Um arquivo escolhido do disco é da pessoa e fica.
    """

    modo: Literal["auto", "manual", "title", "none"]
    arquivo: Optional[Path] = None
    posicoes: session_wallpaper.Posicoes = field(default_factory=session_wallpaper.Posicoes)
    temporario: bool = False


@dataclass
class Formulario:
    nome: str = ""
    desenvolvedora: str = ""
    publicadora: str = ""
    lancamento: str = ""
    genero: str = ""
    controle: Optional[str] = None
    status: str = ""
    nota: int = 0
    executavel: str = ""
    admin: bool = False
    rastrear_processo: bool = False
    executavel_do_processo: str = ""
    notificar_atualizacoes: bool = False
    # O "Adicionar" já vem com as conquistas ligadas.
    conquistas: bool = True
    appid: str = ""
    # None = não mexeu; "" = "Nenhum" (desliga o backup dos saves).
    ludusavi_escolhido: Optional[str] = None
    # O que a última busca trouxe (`metacritic`, `gamepad_recommended`,
    # `description`, `steam_review`, `steam_appid`, `hltb`). Só entra no jogo o
    # que chegou: uma chave ausente (ou None) deixa o valor gravado.
    buscado: dict = field(default_factory=dict)
    # A capa que a tela mostra: a do jogo ao abrir; com ``capa_mudou``, a
    # provisória (um temporário, que passa a ser do `aplicar`) ou None (excluída).
    capa: Optional[Path] = None
    capa_mudou: bool = False
    # None = não mexeu.
    logo: Optional[Escolha] = None
    papel_de_parede: Optional[Escolha] = None

    @classmethod
    def do_jogo(cls, jogo: Optional[Jogo]) -> "Formulario":
        """O que a abertura do diálogo preenche. ``None`` é o "Adicionar"."""
        if jogo is None:
            return cls()
        return cls(
            nome=jogo.name,
            desenvolvedora=jogo.developer or "",
            publicadora=jogo.publisher or "",
            lancamento=jogo.release_date or "",
            genero=jogo.genre or "",
            # Um valor que ninguém reconhece (ficha editada à mão) abre como
            # "não informado" / "Sem status", como a página de detalhes o mostra.
            controle=jogo.controller_support if jogo.controller_support in CONTROLLER_VALUES else None,
            status=jogo.status if jogo.status in STATUS_VALUES else "",
            nota=jogo.stars,
            executavel=jogo.executable,
            admin=jogo.run_as_admin,
            rastrear_processo=jogo.track_process,
            # O nome gravado, ou o do .exe que o comando aponta (vazio se nenhum).
            executavel_do_processo=jogo.process_executable or exe_name_from_command(jogo.executable),
            notificar_atualizacoes=jogo.track_updates,
            conquistas=jogo.conquistas,
            appid=str(jogo.steam_appid or ""),
            capa=jogo.get_cover_path(),
        )


@dataclass
class Resultado:
    jogo: Optional[Jogo]
    # O zerado saiu da store com a tela aberta: fechar sem gravar nada.
    fechar_sem_gravar: bool = False
    # Era zerado e virou um desinstalado comum: não há mais página de detalhes dele.
    sair_dos_detalhes: bool = False


def exe_name_from_command(command: str) -> str:
    """O nome do .exe do jogo num comando, ou "" quando não há (Steam/Epic/UWP).

    Prefere um .exe entre aspas (o atalho clássico e o "Adicionar"), depois um
    .exe solto, ignorando os lançadores em que o comando vem embrulhado.
    """
    if not command:
        return ""

    candidates = re.findall(r'"([^"]*\.exe)"', command, re.IGNORECASE)
    if not candidates:
        ignored = {"explorer.exe", "cmd.exe", "start.exe"}
        candidates = [
            token
            for token in re.findall(r"\S+\.exe", command, re.IGNORECASE)
            if Path(token.strip('"')).name.casefold() not in ignored
        ]
    if not candidates:
        return ""
    return Path(candidates[-1].strip('"')).name


def empacotado(executavel: str) -> bool:
    """Jogo da Microsoft Store / Game Pass, pelo comando do campo."""
    return bool(aumid_from_command(executavel))


def acompanha_sem_nome(executavel: str) -> bool:
    """O jogo já é acompanhado sem o nome do executável?

    Pela identidade do pacote ou pela pasta de instalação que o comando revela:
    nos dois casos a sessão já é automática e o rastreio pelo nome não muda
    nada. Lê o disco (a subida até a raiz do jogo).
    """
    return empacotado(executavel) or bool(install_dir_from_command(executavel))


def _appid_aceito(texto: str) -> bool:
    return texto == "" or (texto.isascii() and texto.isdigit())


def _rastrear(form: Formulario) -> bool:
    # Desligado sempre que as linhas estão escondidas: um valor antigo não pode
    # barrar a validação por um switch que a pessoa não vê mais.
    return form.rastrear_processo and not acompanha_sem_nome(form.executavel)


def titulo_do_erro(adicionando: bool) -> str:
    return _("Não foi possível adicionar o jogo") if adicionando else _("Não foi possível aplicar as alterações")


def validar(form: Formulario, jogo: Optional[Jogo]) -> Optional[str]:
    """A primeira mensagem de erro, na ordem do Aplicar; None se o formulário vale."""
    if form.nome == "":
        return _("O título do jogo não pode ficar vazio.")
    # Um zerado não tem linha de executável na tela.
    if form.executavel == "" and (jogo is None or not jogo.removed):
        return _("O executável não pode ficar vazio.")
    lancamento = form.lancamento.strip()
    if lancamento and not format_release_date(lancamento):
        return _("A data de lançamento informada é inválida. Utilize o formato 2/set./2026.")
    if not _appid_aceito(form.appid.strip()):
        return _("O AppID da Steam deve conter apenas números.")
    if _rastrear(form) and not form.executavel_do_processo.strip():
        return _("Informe o nome do executável para rastrear o tempo de jogo.")
    return None


def _descartar(caminho: Path) -> None:
    try:
        caminho.unlink(missing_ok=True)
    except OSError as error:
        logging.info("Could not remove the staged file %s: %s", caminho, error)


def _descartar_provisoria(caminho: Path) -> None:
    # Abandona antes: uma provisória presa (antivírus) não pode deixar a
    # geração das cópias dela na fila.
    copias_animadas.abandonar(caminho)
    _descartar(caminho)


def _aplicar_logo(jogo: Jogo, escolha: Optional[Escolha]) -> None:
    """Grava a decisão do logo, presa ao nome final (o desta mesma gravação)."""
    if escolha is None:
        return
    if escolha.modo == "manual" and escolha.arquivo:
        game_logo.save_manual_logo(jogo.game_id, jogo.name, escolha.arquivo)
    elif escolha.modo == "title":
        game_logo.use_title_instead(jogo.game_id, jogo.name)
    else:
        game_logo.reset_logo(jogo.game_id)
    if escolha.temporario and escolha.arquivo:
        _descartar(escolha.arquivo)


def _aplicar_papel_de_parede(jogo: Jogo, escolha: Optional[Escolha]) -> None:
    """Como a do logo: a escolha automática é reaberta quando o jogo é renomeado."""
    if escolha is None:
        return
    if escolha.modo == "manual" and escolha.arquivo:
        session_wallpaper.salvar_escolha(jogo.game_id, jogo.name, escolha.arquivo, escolha.posicoes)
    elif escolha.modo == "none":
        session_wallpaper.nao_trocar(jogo.game_id, jogo.name)
    else:
        session_wallpaper.redefinir(jogo.game_id)
    if escolha.temporario and escolha.arquivo:
        _descartar(escolha.arquivo)


def _appid_era_a_fonte(game_id: str) -> bool:
    """As conquistas guardadas vieram do appID (Steam, ou fonte nenhuma)?

    Nas lojas com conta e na Ubisoft elas são da conta ou dos arquivos do launcher.
    """
    # shortcut: lê só o tipo da fonte, sem `fontes.gravada` (que ainda puxa o gi); uma fonte de
    # conta com id inválido é mantida em vez de apagada. O plano 6 volta a usar `fontes.gravada`.
    texto = historico.fonte(game_id)
    if not isinstance(texto, str) or texto.count(":") != 1:
        return True
    return texto.split(":")[0] not in _FONTES_DE_CONTA


def _capa_do_sgdb_chegou(jogo: Jogo, manager: Any) -> None:
    jogo.set_loading(-1)
    jogo.update()
    for error in manager.collect_errors():
        # Só o erro amigável (a chave do SteamGridDB recusada) é dito à pessoa.
        if isinstance(error, FriendlyError) and shared.aplicativo is not None:
            # shortcut: sem o botão "Preferências" (página do SteamGridDB), plano 7.
            shared.aplicativo.pedir_dialogo(error.title, error.subtitle, [], lambda: None)


def aplicar(form: Formulario, jogo: Optional[Jogo], appid_inicial: str) -> Resultado:
    """Grava o formulário no jogo (ou cria o jogo, com ``jogo=None``).

    ``appid_inicial`` é o AppID que o campo mostrava ao abrir. Quem chama já
    validou; um formulário inválido levanta `ValueError` sem gravar nada.
    """
    # Um jogo REMOVIDO (zerado) pode ter saído da store enquanto a tela estava
    # aberta: uma ligação de zerado por appID rodando por baixo, ou uma
    # importação que apagou a ficha. Aplicar a gravaria de novo e o tempo
    # contaria em dobro numa fusão futura. Um jogo vivo nunca é apagado da store
    # por baixo assim, e um jogo novo não está nela por design: o guarda é só do zerado.
    if jogo is not None and jogo.removed and shared.store.get(jogo.game_id) is not jogo:
        return Resultado(jogo, fechar_sem_gravar=True)
    if (erro := validar(form, jogo)) is not None:
        raise ValueError(erro)

    era_zerado = bool(jogo and jogo.zerado)
    appid_digitado = form.appid.strip()
    buscado = form.buscado

    # Só depois de todas as validações: uma que falhasse com o jogo novo já criado
    # o deixaria pela metade, e o clique seguinte o trataria como edição.
    if jogo is None:
        jogo = Jogo(
            {
                "game_id": shared.store.proximo_id_importado(),
                "source": "imported",
                "added": int(time()),
                # Campo de identidade, sem padrão na classe.
                "executable": "",
            }
        )

    jogo.name = form.nome
    jogo.developer = form.desenvolvedora or None
    jogo.publisher = form.publicadora or None
    jogo.release_date = format_release_date(form.lancamento.strip())
    jogo.genre = form.genero.strip() or None
    jogo.controller_support = form.controle
    jogo.definir_status(form.status)
    jogo.rating = form.nota
    # Só o que a busca trouxe: uma edição sem busca mantém o que já havia.
    for chave in ("metacritic", "gamepad_recommended", "description", "steam_review"):
        if buscado.get(chave) is not None:
            setattr(jogo, chave, buscado[chave])

    appid_anterior = jogo.steam_appid
    appid_buscado = buscado.get("steam_appid")
    # O campo manda: a busca sempre o preenche, então depois dela o que está nele
    # (inclusive de volta ao antigo, ou vazio) é a palavra final.
    appid_final = appid_digitado if appid_digitado != appid_inicial or appid_buscado is not None else None
    if appid_final is not None:
        jogo.steam_appid = appid_final or None
        if appid_buscado == appid_final:
            # A busca é a mesma da importação: o jogo fica tão em dia quanto
            # numa atualização, e o "só o que falta" não volta a ele.
            jogo.steam_checked = STEAM_METADATA_VERSION
        if str(jogo.steam_appid or "") != str(appid_anterior or ""):
            # O nome no Ludusavi foi achado pelo appID antigo: o próximo backup o
            # procura de novo. Com o appID novo o jogo pode ser achado: se o local
            # voltar a ser desconhecido, o aviso merece aparecer de novo.
            jogo.ludusavi_nome = ""
            jogo.saves_local_desconhecido_avisado = False
    # Depois do appID: o jogo escolhido à mão ganha do zeramento causado por ele.
    if form.ludusavi_escolhido is not None:
        jogo.ludusavi_nome = form.ludusavi_escolhido
        jogo.backup_dos_saves_desligado = not form.ludusavi_escolhido
    if hltb := buscado.get("hltb"):
        # Só as chaves que a busca devolveu: um jogo só com a história principal
        # mantém as outras duas estimativas.
        jogo.update_values(dict(hltb))
    jogo.executable = form.executavel
    jogo.run_as_admin = form.admin
    jogo.track_process = _rastrear(form)
    jogo.process_executable = form.executavel_do_processo.strip()

    # Desligar o aviso apaga o pendente: religado depois, começa limpo, sem
    # ressuscitar um patch de um feed que já seguiu em frente. Acabar de ligar
    # decide se o feed é lido agora, em vez de esperar o próximo ciclo.
    acabou_de_ligar = form.notificar_atualizacoes and not jogo.track_updates
    if not form.notificar_atualizacoes:
        jogo.update_available_ts = 0
        jogo.update_url = ""
    jogo.track_updates = form.notificar_atualizacoes
    jogo.conquistas = form.conquistas

    if form.capa_mudou:
        try:
            save_cover(jogo.game_id, form.capa)
        except OSError as error:
            # Uma capa animada antiga presa pelo Windows recusa o `replace`
            # (WinError 5). O resto da edição é salvo, em vez de o Aplicar
            # abortar no meio; a provisória fica, é a capa nova desta sessão.
            logging.warning("Could not save the cover: %s", error)
        else:
            if form.capa is not None:
                # Depois da recarga que o `save_cover` agenda (a mesma fila, que
                # roda na ordem): até lá a capa ainda é lida da provisória.
                na_thread_principal(_descartar_provisoria, form.capa)

    _aplicar_logo(jogo, form.logo)
    _aplicar_papel_de_parede(jogo, form.papel_de_parede)
    # shortcut: a cor e o brilho da fita (`aplicar_fita`) não são gravados, plano 5 com o
    # grupo "Iluminação inteligente"; o que já está gravado fica como está.

    shared.store.add_game(jogo, {}, run_pipeline=False)
    jogo.save()
    jogo.update()

    appid_mudou = str(jogo.steam_appid or "") != str(appid_anterior or "")
    if appid_anterior and appid_mudou and _appid_era_a_fonte(jogo.game_id):
        # O appID antigo estava errado: as conquistas guardadas eram de outro jogo.
        historico.apagar(jogo.game_id)

    if jogo.steam_appid and str(jogo.steam_appid) != str(appid_anterior):
        ligar_zerado(jogo)

    # shortcut: a varredura de conquistas depois do Aplicar não roda (a `main` varre com as
    # conquistas ligadas e o appID ou o executável mudado, ou as conquistas recém-ligadas), plano 6.

    if acabou_de_ligar and shared.aplicativo is not None:
        if (verificador := getattr(shared.aplicativo, "verificador_de_atualizacoes", None)) is not None:
            verificador.check_async()

    # Sem capa, o SteamGridDB procura uma.
    if form.capa is None and (sgdb := shared.store.managers.get(SgdbManager)) is not None:
        jogo.set_loading(1)
        sgdb.reset_cancellable()
        sgdb.process_game(jogo, {}, lambda manager: _capa_do_sgdb_chegou(jogo, manager))

    return Resultado(jogo, sair_dos_detalhes=era_zerado and jogo.removed and not jogo.zerado)
