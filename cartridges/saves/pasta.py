"""Onde os backups dos saves moram, e a troca dessa pasta.

A escolha fica na chave `pasta-dos-saves` (vazia = a pasta padrão). Trocar não
joga os backups fora: se a pasta nova não tem saves eles vão junto; se ela já tem,
é ela que vale e a antiga fica como estava.

"Save" aqui é só a pasta de jogo que o Ludusavi grava, com o `mapping.yaml` dentro.
A pasta escolhida pode ser a raiz do OneDrive ou dos Documentos: o resto do que
há nela não é do app, não decide nada e nunca sai do lugar.
"""

import logging
import os
import shutil
import threading
from pathlib import Path

from cartridges import shared
from cartridges.utils.na_tela import entregar_na_tela

_CHAVE = "pasta-dos-saves"

# O que o Ludusavi grava em cada pasta de jogo, e só nela.
MAPA = "mapping.yaml"


class TrocaRecusada(ValueError):
    """A troca não vale. A mensagem (`str(erro)`) já é o aviso que o usuário lê."""


def padrao() -> Path:
    return shared.app_dir / "saves"


def atual() -> Path:
    escolhida = shared.schema.get_string(_CHAVE)
    return Path(escolhida) if escolhida else padrao()


def saves_em(raiz: Path) -> list[Path]:
    """As pastas de jogo do Ludusavi dentro de `raiz`, em ordem; o resto fica de fora."""
    if not raiz.is_dir():
        return []
    return sorted(item for item in raiz.iterdir() if (item / MAPA).is_file())


def _chave(caminho: Path) -> str:
    """Forma comparável do caminho: absoluto e sem diferença de maiúsculas."""
    return os.path.normcase(os.path.abspath(caminho))


def _dentro(caminho: Path, pasta: Path) -> bool:
    """Se `caminho` é `pasta` ou está dentro dela. `commonpath` e não prefixo de
    texto: a raiz de um disco já termina no separador."""
    try:
        return os.path.commonpath([_chave(caminho), _chave(pasta)]) == _chave(pasta)
    except ValueError:  # discos diferentes
        return False


def _levar(antiga: Path, nova: Path) -> list[Path]:
    """Copia os saves de `antiga` para `nova` e devolve os que foram copiados.

    Se qualquer cópia falhar, apaga só o que esta chamada já copiou para `nova`
    (os originais nunca foram tocados) e relança o erro.
    """
    saves = saves_em(antiga)
    if any((nova / save.name).exists() for save in saves):
        raise TrocaRecusada(
            _("A pasta escolhida já tem arquivos com os mesmos nomes dos saves. Escolha outra pasta.")
        )
    nova.mkdir(parents=True, exist_ok=True)
    copiados: list[Path] = []
    try:
        for save in saves:
            copiados.append(nova / save.name)  # antes, para limpar uma cópia pela metade
            shutil.copytree(save, nova / save.name)
    except BaseException:
        for copiado in copiados:
            shutil.rmtree(copiado, ignore_errors=True)
        raise
    return saves


def _gravar_escolha(valor: str) -> None:
    """Grava a chave na thread da tela (GSettings avisa quem o observa na thread em
    que é escrito) e só volta depois de gravada.

    Esperar é o que mantém a ordem: os originais só saem, e a trava dos saves só é
    solta, com a pasta nova já valendo — senão um backup logo em seguida, ou a
    releitura do cache, ainda veria a antiga. Não trava: nada na thread da tela
    espera a trava dos saves.
    """
    if threading.current_thread() is threading.main_thread():
        shared.schema.set_string(_CHAVE, valor)
        return
    gravada = threading.Event()

    def gravar() -> bool:
        try:
            shared.schema.set_string(_CHAVE, valor)
        finally:
            gravada.set()
        return False

    entregar_na_tela(gravar)
    gravada.wait()


def trocar(nova: Path) -> None:
    """Passa a guardar os saves em `nova`.

    Levanta `TrocaRecusada`, sem mexer em nada, se `nova` é a pasta atual, está
    dentro dela, é uma pasta que a contém, está dentro da pasta de dados do app
    (fora a padrão) ou a contém, ou já tem algo com o nome de um save que
    precisaria receber.
    """
    antiga = atual()
    if _dentro(nova, antiga):
        raise TrocaRecusada(_("Escolha uma pasta fora da pasta atual dos saves."))
    if _dentro(antiga, nova):
        raise TrocaRecusada(_("Escolha uma pasta que não contenha a pasta atual dos saves."))
    # A restauração de um backup do app troca a pasta de dados inteira (o que há
    # nela vai para `.anterior` e é apagado): só a padrão sobrevive a isso.
    e_padrao = _chave(nova) == _chave(padrao())
    if not e_padrao and (_dentro(nova, shared.app_dir) or _dentro(shared.app_dir, nova)):
        raise TrocaRecusada(_("Escolha uma pasta fora da pasta de dados do Cartridges."))

    originais: list[Path] = []
    if not saves_em(nova):
        originais = _levar(antiga, nova)
    nova.mkdir(parents=True, exist_ok=True)
    # A escolha só muda com tudo copiado; uma falha antes deixa a antiga valendo.
    _gravar_escolha("" if e_padrao else str(nova))
    for original in originais:
        try:
            shutil.rmtree(original)
        except OSError:
            logging.warning("Save antigo não removido de %s", original, exc_info=True)
