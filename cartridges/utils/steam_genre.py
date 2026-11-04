# steam_genre.py
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

"""Escolhe um único gênero para mostrar de um jogo.

O campo `genres` do appdetails é vago demais ("Action" para Call of Duty, Doom e Hades); as tags dos usuários dizem
o que o jogo é, mas misturam gêneros com cenário, humor, estilo e número de jogadores. Por isso as tags passam pela
tabela abaixo (uma lista de permissão, não um ranking) e vence a primeira *listada* por voto; sem nenhuma, o `genres` é o recurso.
"""

from typing import Iterable, Optional

# Faltam de propósito as tags amplas ("Ação", "RPG", "Indie"...): duplicam o `genres` e, sendo as mais votadas, enterrariam a tag específica logo abaixo.
GENRE_TAGS = {
    # Tiro
    1663: "Tiro em Primeira Pessoa (FPS)",
    3814: "Tiro em Terceira Pessoa",
    5547: "Tiro em Arena",
    620519: "Tiro de Heróis",
    1199779: "Tiro de Extração",
    353880: "Tiro com Saques",
    4637: "Shoot 'em up",
    4885: "Inferno de Balas",
    176981: "Battle Royale",
    1774: "Tiro",
    # Ação
    4106: "Ação / Aventura",
    1646: "Hack and Slash",
    4158: "Porradaria",
    323922: "Musou",
    1743: "Luta",
    4736: "Luta 2D",
    6506: "Luta 3D",
    1687: "Furtivo",
    1773: "Arcade",
    # Plataforma
    5379: "Plataforma 2D",
    5395: "Plataforma 3D",
    3877: "Plataforma de Precisão",
    5537: "Plataforma com Quebra-Cabeça",
    1628: "Metroidvania",
    1625: "Plataforma",
    # RPG
    4231: "RPG de Ação",
    4434: "JRPG",
    4474: "CRPG",
    21725: "RPG Tático",
    17305: "RPG de Estratégia",
    10695: "RPG de Grupos",
    1754: "MMORPG",
    29482: "Soulslike",
    # Roguelike
    1716: "Roguelike",
    3959: "Roguelite",
    42804: "Roguelike de Ação",
    1091588: "Montagem de Decks Roguelike",
    1720: "Explorador de Calabouços",
    198631: "Calabouço Misterioso",
    # Estratégia e tática
    1676: "Estratégia em Tempo Real (RTS)",
    1741: "Estratégia em Turnos",
    4364: "Grande Estratégia",
    1670: "4X",
    14139: "Tática por Turnos",
    3813: "Tática em Tempo Real",
    1645: "Defesa de Torres",
    4684: "Jogo de Guerra",
    1718: "MOBA",
    # Simulação e gestão
    1100687: "Simulador Automobilístico",
    16598: "Simulador Espacial",
    87918: "Simulador Rural",
    220585: "Simulador de Colônias",
    9204: "Simulador Imersivo",
    5900: "Simulador de Caminhada",
    35079: "Simulador de Emprego",
    9551: "Simulador de Encontros",
    10235: "Simulador de Vida Real",
    255534: "Automação",
    4328: "Construção de Cidades",
    5300: "Jogo de Divindade",
    12472: "Gerenciamento",
    # Corrida e veículos
    4102: "Corrida com Combate",
    11104: "Combate com Veículos",
    4994: "Combate Naval",
    15045: "Voo",
    # Terror e sobrevivência
    3978: "Terror de Sobrevivência",
    1721: "Terror Psicológico",
    1667: "Terror",
    1100689: "Sobrevivência em Mundo Aberto",
    1662: "Sobrevivência",
    # Raciocínio
    1664: "Quebra-Cabeça",
    1665: "Combinar 3",
    1730: "Sokoban",
    769306: "Fuja da Sala",
    6129: "Lógica",
    # Cartas e tabuleiro
    9271: "Jogo de Cartas",
    32322: "Montagem de Decks",
    791774: "Batalha com Cartas",
    1084988: "Batalha Automática",
    1770: "Jogo de Tabuleiro",
    4184: "Xadrez",
    6835: "Pôquer",
    13070: "Solitário",
    745697: "Dedução Social",
    # Narrativa
    3799: "Romance Visual",
    11014: "Ficção Interativa",
    1698: "Apontar e Clicar",
    31275: "Baseado em Texto",
    # Outros
    1752: "Ritmo",
    916648: "Coleção de Criaturas",
    379975: "Clicker",
    560542: "Incremental",
    1036: "Educativo",
}

# Tags de mecânica que o jogo *contém* (GTA V é "Simulador Automobilístico"): só valem quando as outras se esgotam.
VAGUE_GENRE_TAGS = frozenset(
    {
        1774,  # Tiro
        1662,  # Sobrevivência
        1687,  # Furtivo
        1625,  # Plataforma
        12472,  # Gerenciamento
        1773,  # Arcade
        15045,  # Voo
        1100687,  # Simulador Automobilístico
        11104,  # Combate com Veículos
        4994,  # Combate Naval
        6129,  # Lógica
        31275,  # Baseado em Texto
    }
)

# O `genres` mapeado por id, não pela string da Steam: os ids não mudam com o idioma, e a API é inconsistente com maiúsculas.
GENRE_NAMES = {
    "1": "Ação",
    "2": "Estratégia",
    "3": "RPG",
    "4": "Casual",
    "9": "Corrida",
    "18": "Esportes",
    "23": "Indie",
    "25": "Aventura",
    "28": "Simulação",
    "29": "Multijogador Massivo",
    "37": "Free to Play",
    "54": "Educativo",
    "70": "Acesso Antecipado",
}

# Dizem como o jogo é vendido, não o que é; último recurso.
WEAK_GENRES = frozenset({"4", "23", "37", "70"})


def pick_genre(genre_ids: Iterable[str], tag_ids: Iterable[int]) -> Optional[str]:
    """O gênero a mostrar, ou None. ``tag_ids`` deve vir na ordem da Steam (votos decrescentes): a escolha depende disso."""
    tag_ids = list(tag_ids)
    for wanted_vague in (False, True):
        for tag_id in tag_ids:
            if (tag_id in VAGUE_GENRE_TAGS) is wanted_vague:
                if name := GENRE_TAGS.get(tag_id):
                    return name

    genre_ids = list(genre_ids)
    for wanted_weak in (False, True):
        for genre_id in genre_ids:
            if (genre_id in WEAK_GENRES) is wanted_weak:
                if name := GENRE_NAMES.get(genre_id):
                    return name
    return None
