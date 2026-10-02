"""Os leitores dos arquivos de conquista, um formato por teste."""

import json

from cartridges.conquistas import formatos
from cartridges.conquistas.formatos import Desbloqueio


def _arquivo(tmp_path, nome, texto):
    caminho = tmp_path / nome
    caminho.write_text(texto, encoding="utf-8")
    return caminho


def test_codex_le_so_as_desbloqueadas(tmp_path):
    caminho = _arquivo(
        tmp_path,
        "achievements.ini",
        "[SteamAchievements]\n00000=ACH_A\nCount=2\n"
        "[ACH_A]\nAchieved=1\nCurProgress=0\nUnlockTime=1700000000\n"
        "[ACH_B]\nAchieved=0\nUnlockTime=0\n",
    )
    assert formatos.ler(caminho, formatos.PADRAO) == [Desbloqueio("ACH_A", 1700000000)]


def test_ini_com_bom_e_comentarios(tmp_path):
    caminho = _arquivo(
        tmp_path, "a.ini", "\ufeff; comentário\n# outro\n[ACH_A]\nAchieved=1\nUnlockTime=5\n"
    )
    assert formatos.ler(caminho, formatos.PADRAO) == [Desbloqueio("ACH_A", 5)]


def test_goldberg_em_lista_e_em_dicionario(tmp_path):
    lista = _arquivo(
        tmp_path,
        "lista.json",
        json.dumps(
            [
                {"name": "ACH_A", "earned": True, "earned_time": 100},
                {"name": "ACH_B", "earned": False, "earned_time": 0},
            ]
        ),
    )
    dicionario = _arquivo(
        tmp_path,
        "dic.json",
        json.dumps(
            {
                "ACH_A": {"earned": True, "earned_time": 100},
                "ACH_B": {"earned": False, "earned_time": 0},
                "   ": {"earned": True, "earned_time": 1},
            }
        ),
    )
    assert formatos.ler(lista, formatos.GOLDBERG) == [Desbloqueio("ACH_A", 100)]
    assert formatos.ler(dicionario, formatos.GOLDBERG) == [Desbloqueio("ACH_A", 100)]


def test_json_pela_metade_nao_levanta(tmp_path):
    caminho = _arquivo(tmp_path, "a.json", '{"ACH_A": {"earned": tr')
    assert formatos.ler(caminho, formatos.GOLDBERG) == []


def test_arquivo_que_nao_existe(tmp_path):
    assert formatos.ler(tmp_path / "nada.ini", formatos.PADRAO) == []


def test_ler_ou_none_distingue_falha_de_vazio(tmp_path):
    corrompido = _arquivo(tmp_path, "a.json", '{"ACH_A": {"earned": tr')
    valido = _arquivo(tmp_path, "b.json", json.dumps({"ACH_A": {"earned": True, "earned_time": 7}}))
    sem_nada = _arquivo(tmp_path, "c.ini", "[ACH_A]\nAchieved=0\n")
    assert formatos.ler_ou_none(corrompido, formatos.GOLDBERG) is None
    assert formatos.ler_ou_none(tmp_path / "nada.ini", formatos.PADRAO) == []
    assert formatos.ler_ou_none(valido, formatos.GOLDBERG) == [Desbloqueio("ACH_A", 7)]
    assert formatos.ler_ou_none(sem_nada, formatos.PADRAO) == []
    assert formatos.ler_ou_none(valido, "flt") == []


def test_hora_fora_do_que_o_historico_aceita_vira_zero(tmp_path):
    grande = _arquivo(tmp_path, "a.json", '{"ACH_A": {"earned": true, "earned_time": 1e30}}')
    enorme = _arquivo(
        tmp_path, "b.json", '{"ACH_A": {"earned": true, "earned_time": ' + "9" * 400 + "}}"
    )
    limite = _arquivo(
        tmp_path, "c.json", '{"ACH_A": {"earned": true, "earned_time": %d}}' % 2**62
    )
    assert formatos.ler_ou_none(grande, formatos.GOLDBERG) == [Desbloqueio("ACH_A", 0)]
    assert formatos.ler_ou_none(enorme, formatos.GOLDBERG) == [Desbloqueio("ACH_A", 0)]
    assert formatos.ler_ou_none(limite, formatos.GOLDBERG) == [Desbloqueio("ACH_A", 2**62)]


def test_formato_desconhecido(tmp_path):
    caminho = _arquivo(tmp_path, "a.ini", "[ACH_A]\nAchieved=1\n")
    assert formatos.ler(caminho, "flt") == []


def test_onlinefix_nas_duas_grafias(tmp_path):
    caminho = _arquivo(
        tmp_path,
        "Achievements.ini",
        "[ACH_A]\nachieved=true\ntimestamp=1700000000\n"
        "[ACH_B]\nAchieved=true\nTimeUnlocked=1234567\n"
        "[ACH_C]\nachieved=false\ntimestamp=0\n",
    )
    assert formatos.ler(caminho, formatos.ONLINEFIX) == [
        Desbloqueio("ACH_A", 1700000000),
        # Sete dígitos: a regra de `parseUnlockTime` do Hydra (multiplica por mil).
        Desbloqueio("ACH_B", 1234567000),
    ]


def test_creamapi(tmp_path):
    caminho = _arquivo(
        tmp_path, "c.cfg", "[ACH_A]\nachieved=true\nunlocktime=1700000000\n[ACH_B]\nachieved=false\n"
    )
    assert formatos.ler(caminho, formatos.CREAMAPI) == [Desbloqueio("ACH_A", 1700000000)]


def test_skidrow(tmp_path):
    caminho = _arquivo(
        tmp_path, "achiev.ini", "[Achievements]\nACH_A=1@0@0@1700000000\nACH_B=0@0@0@0\n"
    )
    assert formatos.ler(caminho, formatos.SKIDROW) == [Desbloqueio("ACH_A", 1700000000)]


def test_3dm_hora_em_hexadecimal(tmp_path):
    # 1700000000 = 0x6553F100, gravado em little-endian: 00 F1 53 65.
    caminho = _arquivo(
        tmp_path,
        "achievements.ini",
        "[State]\nACH_A=0101\nACH_B=0000\n[Time]\nACH_A=00F15365\nACH_B=00000000\n",
    )
    assert formatos.ler(caminho, formatos.TRES_DM) == [Desbloqueio("ACH_A", 1700000000)]


def test_rld_estado_e_hora_em_hexadecimal(tmp_path):
    caminho = _arquivo(
        tmp_path,
        "achievements.ini",
        "[Steam]\nCount=2\n"
        "[ACH_A]\nState=01000000\nTime=00F15365\n"
        "[ACH_B]\nState=00000000\nTime=00000000\n",
    )
    assert formatos.ler(caminho, formatos.RLD) == [Desbloqueio("ACH_A", 1700000000)]


def test_userstats(tmp_path):
    caminho = _arquivo(
        tmp_path,
        "user_stats.ini",
        '[ACHIEVEMENTS]\n"ACH_A"={unlocked = true, time = 1700000000}\n'
        "ACH_B={unlocked = false, time = 0}\n",
    )
    assert formatos.ler(caminho, formatos.USERSTATS) == [Desbloqueio("ACH_A", 1700000000)]


def test_ali213(tmp_path):
    caminho = _arquivo(
        tmp_path, "Achievements.Bin", "[ACH_A]\nHaveAchieved=1\nHaveAchievedTime=1700000000\n"
    )
    assert formatos.ler(caminho, formatos.ALI213) == [Desbloqueio("ACH_A", 1700000000)]


def test_razor1911(tmp_path):
    caminho = _arquivo(tmp_path, "achievement", "ACH_A 1 1700000000\nACH_B 0 0\n\n")
    assert formatos.ler(caminho, formatos.RAZOR1911) == [Desbloqueio("ACH_A", 1700000000)]


def test_cache_da_steam_le_todas_as_listas(tmp_path):
    caminho = _arquivo(
        tmp_path,
        "570.json",
        json.dumps(
            [
                ["friends", {"data": {}}],
                [
                    "achievements",
                    {
                        "data": {
                            "vecHighlight": [
                                {"strID": "ACH_A", "bAchieved": True, "rtUnlocked": 1700000000}
                            ],
                            "vecUnachieved": [{"strID": "ACH_B", "bAchieved": False}],
                            "vecAchievedHidden": [
                                {"strID": "ACH_C", "bAchieved": True, "rtUnlocked": 1700000500}
                            ],
                            "nTotal": 3,
                        }
                    },
                ],
            ]
        ),
    )
    assert formatos.ler(caminho, formatos.STEAM) == [
        Desbloqueio("ACH_A", 1700000000),
        Desbloqueio("ACH_C", 1700000500),
    ]


def test_hora_infinita_no_ini_nao_levanta(tmp_path):
    caminho = _arquivo(tmp_path, "a.ini", "[ACH_A]\nAchieved=1\nUnlockTime=inf\n")
    assert formatos.ler(caminho, formatos.PADRAO) == [Desbloqueio("ACH_A", 0)]


def test_hora_gigante_no_json_nao_levanta(tmp_path):
    # Escrito à mão: `json.dumps` não produz 1e999.
    caminho = _arquivo(tmp_path, "a.json", '{"ACH_A": {"earned": true, "earned_time": 1e999}}')
    assert formatos.ler(caminho, formatos.GOLDBERG) == [Desbloqueio("ACH_A", 0)]
