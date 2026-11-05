# edicao.py
#
# Copyright 2022-2024 kramo
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A regra da edição de um jogo, sem tela: `Formulario`, `validar` e `aplicar`. Roda na thread principal."""

import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from time import time
from typing import Any, Literal, Optional

from PIL import Image, UnidentifiedImageError

from cartridges import shared
from cartridges.conquistas import fontes, historico
from cartridges.emuladores import aplicacao, idiomas, ini
from cartridges.emuladores import varredura as varredura_dos_inis
from cartridges.errors.friendly_error import FriendlyError
from cartridges.jogo import STATUS_LABELS, Jogo
from cartridges.store.managers.sgdb_manager import SgdbManager
from cartridges.utils import capa_video, copias_animadas, game_logo, session_fita, session_wallpaper
from cartridges.utils.ligacao_zerado import ligar_zerado
from cartridges.utils.process_monitor import install_dir_from_command
from cartridges.utils.run_executable import aumid_from_command
from cartridges.utils.save_cover import _temporario, composite_cover, convert_cover, save_cover  # noqa: PLC2701
from cartridges.utils.steam import STEAM_METADATA_VERSION, format_release_date
from cartridges.utils.thread_principal import na_thread_principal

# Os valores gravados do seletor de status: "" ("Sem status") e as chaves de STATUS_LABELS.
STATUS_VALUES = ("", *STATUS_LABELS)
# Os do suporte a controle: None é "não informado".
CONTROLLER_VALUES = (None, "full", "partial")
CONTROLLER_LABELS = {None: _("Não informada"), "full": _("Total"), "partial": _("Parcial")}


@dataclass
class Escolha:
    """Uma decisão de logo ou papel de parede tomada na tela, gravada só no Aplicar.

    ``modo``: ``"auto"`` (voltar ao automático), ``"manual"`` (o ``arquivo``), ``"title"`` (logo: mostrar o título) ou
    ``"none"`` (parede: não trocar). ``temporario``: cópia recebida de um seletor, apagada depois de gravada.
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
    # Idioma (código da Steam) e nome do jogador só deste jogo; "" = o padrão do Kyron.
    idioma_proprio: str = ""
    nome_proprio: str = ""
    # None = não mexeu; "" = "Nenhum" (desliga o backup dos saves).
    ludusavi_escolhido: Optional[str] = None
    # O que a última busca trouxe; chave ausente (ou None) deixa o valor gravado.
    buscado: dict = field(default_factory=dict)
    # A capa que a tela mostra: a do jogo ao abrir; com ``capa_mudou``, a provisória ou None (excluída).
    capa: Optional[Path] = None
    capa_mudou: bool = False
    logo: Optional[Escolha] = None
    papel_de_parede: Optional[Escolha] = None
    # A cor da fita (`session_fita.Cor`): a que a linha mostrou ao abrir e a que está na tela; ``None`` em ``fita_mostrada``: sem fita.
    fita_mostrada: Optional[session_fita.Cor] = None
    fita_na_tela: Optional[session_fita.Cor] = None
    # "Voltar ao automático" pedido: só o Aplicar apaga a escolha gravada.
    fita_redefinir: bool = False

    @classmethod
    def do_jogo(cls, jogo: Optional[Jogo]) -> "Formulario":
        if jogo is None:
            return cls()
        return cls(
            nome=jogo.name,
            desenvolvedora=jogo.developer or "",
            publicadora=jogo.publisher or "",
            lancamento=jogo.release_date or "",
            genero=jogo.genre or "",
            # Um valor que ninguém reconhece (arquivo editado à mão) abre como "não informado" / "Sem status".
            controle=jogo.controller_support if jogo.controller_support in CONTROLLER_VALUES else None,
            status=jogo.status if jogo.status in STATUS_VALUES else "",
            nota=jogo.stars,
            executavel=jogo.executable,
            admin=jogo.run_as_admin,
            rastrear_processo=jogo.track_process,
            executavel_do_processo=jogo.process_executable or exe_name_from_command(jogo.executable),
            notificar_atualizacoes=jogo.track_updates,
            conquistas=jogo.conquistas,
            appid=str(jogo.steam_appid or ""),
            idioma_proprio=jogo.idioma_proprio,
            nome_proprio=jogo.nome_proprio,
            capa=jogo.get_cover_path(),
        )


@dataclass
class Resultado:
    jogo: Optional[Jogo]
    fechar_sem_gravar: bool = False
    sair_dos_detalhes: bool = False
    # A capa nova não foi gravada (arquivo preso): a provisória é a capa desta sessão e não pode ser apagada.
    capa_presa: bool = False


def exe_name_from_command(command: str) -> str:
    """O nome do .exe do jogo num comando, ou "" quando não há (Steam/Epic/UWP); prefere um .exe entre aspas, depois um solto."""
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
    return bool(aumid_from_command(executavel))


def acompanha_sem_nome(executavel: str) -> bool:
    """O jogo já é acompanhado sem o nome do executável (pela identidade do pacote ou pela pasta de instalação)? Lê o disco."""
    return empacotado(executavel) or bool(install_dir_from_command(executavel))


def appid_aceito(texto: str) -> bool:
    return texto == "" or (texto.isascii() and texto.isdigit())


def _rastrear(form: Formulario) -> bool:
    # Desligado com as linhas escondidas: um valor antigo não pode barrar a validação por um switch que não se vê.
    return form.rastrear_processo and not acompanha_sem_nome(form.executavel)


def titulo_do_erro(adicionando: bool) -> str:
    return _("Não foi possível adicionar o jogo") if adicionando else _("Não foi possível aplicar as alterações")


def validar(form: Formulario, jogo: Optional[Jogo]) -> Optional[str]:
    """A primeira mensagem de erro, na ordem do Aplicar; None se o formulário vale."""
    if form.nome == "":
        return _("O título do jogo não pode ficar vazio.")
    if form.executavel == "" and (jogo is None or not jogo.removed):
        return _("O executável não pode ficar vazio.")
    lancamento = form.lancamento.strip()
    if lancamento and not format_release_date(lancamento):
        return _("A data de lançamento informada é inválida. Utilize o formato 2/set./2026.")
    if not appid_aceito(form.appid.strip()):
        return _("O AppID da Steam deve conter apenas números.")
    if _rastrear(form) and not form.executavel_do_processo.strip():
        return _("Informe o nome do executável para rastrear o tempo de jogo.")
    return None


def _descartar(caminho: Path) -> None:
    try:
        caminho.unlink(missing_ok=True)
    except OSError as error:
        logging.info("Could not remove the staged file %s: %s", caminho, error)


def descartar_provisoria(caminho: Path) -> None:
    # Abandona antes: uma provisória presa (antivírus) não pode deixar a geração das cópias dela na fila.
    copias_animadas.abandonar(caminho)
    _descartar(caminho)


def preparar_capa(arquivo: Path) -> Optional[Path]:
    """Uma imagem escolhida vira a provisória da capa (temporário em %TEMP%), ou None se ilegível. Fora da thread principal."""
    try:
        with Image.open(arquivo) as imagem:
            if getattr(imagem, "is_animated", False):
                return convert_cover(arquivo)
    except UnidentifiedImageError:
        pass
    except Exception:  # noqa: BLE001  # um arquivo truncado ou grande demais cai no `composite_cover` abaixo
        logging.info("Could not probe the chosen cover", exc_info=True)
    intermediaria = _temporario(".png")
    try:
        composite_cover(arquivo).save(intermediaria, "PNG")
        return convert_cover(intermediaria)
    except Exception:  # noqa: BLE001  # só esta thread devolve o contador de ocupado: não pode morrer
        logging.exception("Could not prepare the chosen cover")
        return None
    finally:
        intermediaria.unlink(missing_ok=True)


def preparar_capa_de_video(arquivo: Path) -> tuple[Optional[Path], str]:
    """O vídeo escolhido vira a provisória (WebP animado) e as cópias dela, ou ``(None, erro)``.

    Fora da thread principal. O ffmpeg só existe no instalador (ou no PATH).
    """
    if capa_video.executavel() is None:
        return None, _("O arquivo não pôde ser lido como vídeo.")
    try:
        # As cópias da grade e dos detalhes saem junto: a prévia toca assim que a capa aparece.
        capa = capa_video.converter(
            arquivo,
            lambda destino: [
                (copias_animadas.caminho_para(destino, tamanho), tamanho) for tamanho in copias_animadas.tamanhos()
            ],
        )
    except capa_video.VideoFalhou as erro:
        return None, str(erro)
    except Exception:  # noqa: BLE001
        logging.exception("Could not convert the chosen video")
        return None, _("O arquivo não pôde ser lido como vídeo.")
    return capa, ""


def estado_do_logo(form: Formulario, jogo: Optional[Jogo]) -> str:
    """``auto``, ``manual`` ou ``title``: a escolha da tela, ou a gravada."""
    if form.logo is not None:
        return form.logo.modo
    return game_logo.logo_choice(jogo) if jogo else "auto"


def estado_do_papel(form: Formulario, jogo: Optional[Jogo]) -> str:
    """``auto``, ``manual`` ou ``none``: a escolha da tela, ou a gravada."""
    if form.papel_de_parede is not None:
        return form.papel_de_parede.modo
    return session_wallpaper.escolha(jogo) if jogo else "auto"


# O seletor arredonda a cor: diferenças menores que isto são a mesma cor, e `aplicar_fita` não pode ler a deriva como escolha.
FOLGA_MATIZ = 2
FOLGA_SATURACAO = 10


def mesmo_tom(uma: session_fita.Cor, outra: session_fita.Cor) -> bool:
    """Matiz e saturação, sem o brilho. A distância de matiz é circular: 359 e 0 são vizinhos."""
    distancia = abs(uma.matiz - outra.matiz) % 360
    return min(distancia, 360 - distancia) <= FOLGA_MATIZ and abs(uma.saturacao - outra.saturacao) <= FOLGA_SATURACAO


def aplicar_fita(form: Formulario, jogo: Jogo) -> None:
    """Grava a cor da fita só quando ela é escolha de verdade: quem abriu a tela só para renomear não pediu cor, e gravar
    a marcaria como "escolhida à mão" para sempre.
    """
    # Sem fita configurada a linha nem é preenchida: apagar a cor que o jogo já tem seria perdê-la; a redefinição pedida passa.
    mostrada, na_tela = form.fita_mostrada, form.fita_na_tela
    if mostrada is None or na_tela is None:
        if form.fita_redefinir:
            session_fita.redefinir(jogo.game_id)
        return
    # Contra o que a linha mostrou, não contra o automático de agora (um jogo novo ganha a capa neste Aplicar); cor e brilho separados.
    escolha_nova = not mesmo_tom(na_tela, mostrada)
    brilho_novo = na_tela.brilho != mostrada.brilho
    if escolha_nova:
        # Uma cor escolhida depois do "voltar ao automático" cancela a redefinição: vale a que está na tela.
        session_fita.salvar_cor(jogo.game_id, jogo.name, na_tela)
    elif form.fita_redefinir:
        session_fita.redefinir(jogo.game_id)
        if brilho_novo:
            session_fita.salvar_brilho(jogo.game_id, jogo.name, na_tela.brilho)
    elif session_fita.escolhida(jogo.game_id):
        # Nada mudou, mas a escolha é regravada: ela guarda o nome do jogo, e o que vale é o deste Aplicar.
        session_fita.salvar_cor(jogo.game_id, jogo.name, na_tela)
    elif brilho_novo:
        session_fita.salvar_brilho(jogo.game_id, jogo.name, na_tela.brilho)


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


def _appid_era_a_fonte(jogo: Jogo) -> bool:
    """As conquistas guardadas vieram do appID (Steam, ou fonte nenhuma)? Nas lojas com conta e na Ubisoft vêm da conta ou do launcher."""
    fonte = fontes.gravada(jogo)
    return fonte is None or fonte.tipo == fontes.STEAM


def _capa_do_sgdb_chegou(jogo: Jogo, manager: Any) -> None:
    jogo.set_loading(-1)
    jogo.update()
    for error in manager.collect_errors():
        # Só o erro amigável (a chave do SteamGridDB recusada) é dito à pessoa.
        if isinstance(error, FriendlyError) and shared.aplicativo is not None:
            shared.aplicativo.pedir_dialogo(error.title, error.subtitle, [], lambda: None, preferencias="sgdb")


def saiu_da_store(jogo: Optional[Jogo]) -> bool:
    """Um zerado que a store soltou com a tela aberta: aplicar não pode gravá-lo de novo. Vale antes da validação."""
    return jogo is not None and jogo.removed and shared.store.get(jogo.game_id) is not jogo


def _aplicar_inis_em_thread(jogo: Jogo) -> None:
    """O idioma e o nome do jogo valem já: a gravação nos .ini toca o disco, então sai da thread principal.

    Com os .ini por procurar (jogo novo, executável trocado), procura antes e adota o AppID deles.
    """
    procurar = jogo.inis is None

    def tarefa() -> None:
        try:
            if procurar:
                varredura_dos_inis.procurar_jogo(jogo)
            else:
                aplicacao.aplicar_no_jogo(jogo)
        except Exception:  # noqa: BLE001
            logging.exception("Falha ao aplicar o idioma e o nome em %s", jogo.name)

    threading.Thread(target=tarefa, name="aplicar-inis-da-edicao", daemon=True).start()


def aplicar(form: Formulario, jogo: Optional[Jogo], appid_inicial: str) -> Resultado:
    """Grava o formulário no jogo (ou cria o jogo, com ``jogo=None``); ``appid_inicial`` é o AppID que o campo mostrava ao abrir.

    Formulário inválido levanta `ValueError` sem gravar nada.
    """
    if saiu_da_store(jogo):
        return Resultado(jogo, fechar_sem_gravar=True)
    if (erro := validar(form, jogo)) is not None:
        raise ValueError(erro)

    era_zerado = bool(jogo and jogo.zerado)
    appid_digitado = form.appid.strip()
    buscado = form.buscado

    # Só depois de todas as validações: uma falha com o jogo novo já criado o deixaria pela metade.
    if jogo is None:
        jogo = Jogo(
            {
                "game_id": shared.store.proximo_id_importado(),
                "source": "imported",
                "added": int(time()),
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
    for chave in ("metacritic", "gamepad_recommended", "description", "steam_review"):
        if buscado.get(chave) is not None:
            setattr(jogo, chave, buscado[chave])

    appid_anterior = jogo.steam_appid
    appid_buscado = buscado.get("steam_appid")
    # O campo manda: depois da busca o que está nele (inclusive de volta ao antigo, ou vazio) é a palavra final.
    appid_final = appid_digitado if appid_digitado != appid_inicial or appid_buscado is not None else None
    if appid_final is not None:
        jogo.steam_appid = appid_final or None
        if appid_digitado != appid_inicial:
            jogo.appid_manual = bool(appid_final)  # escrito à mão: os .ini não o trocam mais
        if appid_buscado == appid_final:
            # A busca é a mesma da importação: o jogo fica em dia e o "só o que falta" não volta a ele.
            jogo.steam_checked = STEAM_METADATA_VERSION
        if str(jogo.steam_appid or "") != str(appid_anterior or ""):
            # O nome no Ludusavi veio do appID antigo: o próximo backup o procura de novo, e o aviso de local desconhecido pode reaparecer.
            jogo.ludusavi_nome = ""
            jogo.saves_local_desconhecido_avisado = False
            jogo.idiomas_steam = buscado.get("idiomas_steam")  # os do AppID anterior não valem
    # Depois do appID: o jogo escolhido à mão ganha do zeramento causado por ele.
    if form.ludusavi_escolhido is not None:
        jogo.ludusavi_nome = form.ludusavi_escolhido
        jogo.backup_dos_saves_desligado = not form.ludusavi_escolhido
    if hltb := buscado.get("hltb"):
        # Só as chaves que a busca devolveu: um jogo só com a história principal mantém as outras duas estimativas.
        jogo.update_values(dict(hltb))
    executavel_mudou = form.executavel != (jogo.executable or "")
    jogo.executable = form.executavel
    if executavel_mudou:
        jogo.inis = None  # os da pasta antiga não valem: procurados de novo no fim
    jogo.run_as_admin = form.admin
    jogo.track_process = _rastrear(form)
    jogo.process_executable = form.executavel_do_processo.strip()

    # Desligar o aviso apaga o pendente (religado, começa limpo); acabar de ligar decide se o feed é lido agora.
    acabou_de_ligar = form.notificar_atualizacoes and not jogo.track_updates
    if not form.notificar_atualizacoes:
        jogo.update_available_ts = 0
        jogo.update_url = ""
    jogo.track_updates = form.notificar_atualizacoes
    conquistas_antes = jogo.conquistas
    jogo.conquistas = form.conquistas
    proprios_antes = (jogo.idioma_proprio, jogo.nome_proprio)
    if form.idioma_proprio == "" or form.idioma_proprio in idiomas.IDIOMAS:
        jogo.idioma_proprio = form.idioma_proprio
    # Nome fora da regra não é gravado; o resto da edição segue.
    if ini.nome_aceito(form.nome_proprio):
        jogo.nome_proprio = form.nome_proprio.strip()

    capa_presa = False
    if form.capa_mudou:
        # As cópias animadas que a tela segura abertas (grade e página de detalhes) travariam o `replace`.
        copias_animadas.soltar(jogo.game_id)
        try:
            save_cover(jogo.game_id, form.capa)
        except OSError as error:
            # Uma capa animada antiga presa pelo Windows recusa o `replace` (WinError 5): o resto da edição é salvo; a provisória fica.
            logging.warning("Could not save the cover: %s", error)
            capa_presa = form.capa is not None
            jogo.capa_da_sessao = form.capa
        else:
            # O `save_cover` também a limpa (na principal, para toda gravação); aqui já, para o `update` logo abaixo.
            jogo.capa_da_sessao = None
            if form.capa is not None:
                # Depois da recarga que o `save_cover` agenda (mesma fila): até lá a capa ainda é lida da provisória.
                na_thread_principal(descartar_provisoria, form.capa)

    _aplicar_logo(jogo, form.logo)
    _aplicar_papel_de_parede(jogo, form.papel_de_parede)
    aplicar_fita(form, jogo)

    shared.store.add_game(jogo, {}, run_pipeline=False)
    # À mão, durante uma importação: o "Desfazer" dela não pode levá-lo embora.
    shared.store.new_game_ids.discard(jogo.game_id)
    jogo.save()
    jogo.update()

    appid_mudou = str(jogo.steam_appid or "") != str(appid_anterior or "")
    if appid_anterior and appid_mudou and _appid_era_a_fonte(jogo):
        # O appID antigo estava errado: as conquistas guardadas eram de outro jogo.
        historico.apagar(jogo.game_id)

    if jogo.steam_appid and str(jogo.steam_appid) != str(appid_anterior):
        ligar_zerado(jogo)

    # O cartão de conquistas da página não segue o `update`: o interruptor e o histórico apagado pedem a refeita.
    if shared.conquistas is not None:
        shared.conquistas.mudou(jogo.game_id)

    if jogo.conquistas and (appid_mudou or executavel_mudou or not conquistas_antes):
        if (varredura := getattr(shared.aplicativo, "varredura_conquistas", None)) is not None:
            varredura.varrer_jogo(jogo)

    if acabou_de_ligar and shared.aplicativo is not None:
        if (verificador := getattr(shared.aplicativo, "verificador_de_atualizacoes", None)) is not None:
            verificador.check_async()

    if jogo.inis is None or proprios_antes != (jogo.idioma_proprio, jogo.nome_proprio):
        _aplicar_inis_em_thread(jogo)

    if form.capa is None and (sgdb := shared.store.managers.get(SgdbManager)) is not None:
        jogo.set_loading(1)
        sgdb.reset_cancellable()
        sgdb.process_game(jogo, {}, lambda manager: _capa_do_sgdb_chegou(jogo, manager))

    return Resultado(jogo, sair_dos_detalhes=era_zerado and jogo.removed and not jogo.zerado, capa_presa=capa_presa)
