# soltar_atalhos.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Atalhos arrastados para a janela: quais entram na pasta de atalhos.

Os arquivos vêm de qualquer programa que arraste para cá, então só passam
``.lnk`` e ``.url`` locais, de tamanho de atalho, e nunca por cima de um que
já esteja na pasta. O conteúdo deles é julgado depois, pela varredura, como o
de qualquer outro atalho da pasta.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cartridges import shared
from cartridges.utils import restauracao

MAX_ARQUIVOS = 100
MAX_BYTES = 1_048_576
_EXTENSOES = (".lnk", ".url")


@dataclass
class Resultado:
    copiados: int
    ja_existiam: int
    ignorados: int


def filtrar(caminhos: list[Optional[Path]]) -> tuple[list[Path], int]:
    """Os atalhos aceitos, na ordem em que vieram, e quantos ficaram de fora.

    ``None`` é um arquivo sem caminho local (de rede, de um celular): fica de
    fora como os demais.
    """
    aceitos: list[Path] = []
    ignorados = 0
    for caminho in caminhos:
        try:
            aceito = (
                caminho is not None
                and caminho.suffix.casefold() in _EXTENSOES
                and caminho.is_file()
                and caminho.stat().st_size <= MAX_BYTES
            )
        except OSError:
            aceito = False
        if aceito and len(aceitos) < MAX_ARQUIVOS:
            aceitos.append(caminho)
        else:
            ignorados += 1
    return aceitos, ignorados


def copiar(caminhos: list[Optional[Path]]) -> Resultado:
    """Copia os atalhos aceitos para a pasta de atalhos, sem sobrescrever."""
    aceitos, ignorados = filtrar(caminhos)
    copiados = ja_existiam = 0
    for caminho in aceitos:
        try:
            restauracao.copiar_para_a_pasta(caminho)
            copiados += 1
        except restauracao.AtalhoJaExiste:
            ja_existiam += 1
        except OSError:
            logging.warning("Não foi possível copiar o atalho %s", caminho, exc_info=True)
            ignorados += 1
    return Resultado(copiados, ja_existiam, ignorados)


def pasta_configurada() -> bool:
    local = shared.schema.get_string("shortcuts-location")
    return bool(local) and Path(local).expanduser().is_dir()


def ao_soltar(
    caminhos: list[Optional[Path]], importando: bool
) -> tuple[list[str], bool]:
    """Os avisos a mostrar, em ordem, e se a importação deve rodar."""
    # A varredura em andamento pode já ter passado pela pasta, e não veria
    # os atalhos copiados agora.
    if importando:
        return [_("Aguarde o fim da importação em andamento.")], False
    if not pasta_configurada():
        return [
            _("Escolha uma pasta de atalhos em Preferências para importar atalhos.")
        ], False

    resultado = copiar(caminhos)
    if resultado.copiados + resultado.ja_existiam == 0:
        return [_("Nenhum atalho para importar.")], False

    avisos = []
    if resultado.ja_existiam:
        avisos.append(
            ngettext(
                "{} atalho já estava na pasta de atalhos.",
                "{} atalhos já estavam na pasta de atalhos.",
                resultado.ja_existiam,
            ).format(resultado.ja_existiam)
        )
    if resultado.ignorados:
        avisos.append(
            ngettext(
                "{} arquivo foi ignorado.",
                "{} arquivos foram ignorados.",
                resultado.ignorados,
            ).format(resultado.ignorados)
        )
    return avisos, True
