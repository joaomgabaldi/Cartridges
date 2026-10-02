"""Os leitores dos arquivos de conquista, um formato por teste."""

import json
import os

import pytest

from cartridges.conquistas import formatos
from cartridges.conquistas.formatos import Desbloqueio
from tests.apoio_conquistas import kv_bytes, schema_de_teste


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


# Os três estados reais da prova de 02/10/2026 (100% Orange Juice, appID 282800):
# antes de marcar, marcado e pendente de envio, e marcado e confirmado.
STEAM_ANTES = bytes.fromhex(
    "006361636865000263726300000000000250656e64696e674368616e67657300000000000808"
)
STEAM_PENDENTE = bytes.fromhex(
    "006361636865000263726300000000000250656e64696e674368616e676573000100000000"
    "310002646174610000400000027374617465000200000002"
    "70656e64696e6762697473000000000000416368696576656d656e7454696d6573000231"
    "34002bc3bf6a08080808"
)
STEAM_CONFIRMADO = bytes.fromhex(
    "0063616368650002637263006ba339950250656e64696e674368616e676573000000000000"
    "31000264617461000040000000416368696576656d656e7454696d657300023134002bc3bf6a08080808"
)
SCHEMA_282800 = schema_de_teste(
    "282800", {"1": {"13": {"name": "ACH_OUTRA"}, "14": {"name": "ACH_BONUS_MANY_STARS"}}}
)


def _stats_da_steam(pasta, estado: bytes, schema=SCHEMA_282800, appid="282800"):
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"UserGameStats_123_{appid}.bin"
    caminho.write_bytes(estado)
    if schema is not None:
        (pasta / f"UserGameStatsSchema_{appid}.bin").write_bytes(schema)
    return caminho


@pytest.mark.parametrize("estado", [STEAM_PENDENTE, STEAM_CONFIRMADO], ids=["pendente", "confirmado"])
def test_steam_stats_reais_da_prova(tmp_path, estado):
    caminho = _stats_da_steam(tmp_path / "stats", estado)
    assert formatos.ler(caminho, formatos.STEAM_STATS) == [
        Desbloqueio("ACH_BONUS_MANY_STARS", 1790952235)
    ]


def test_steam_stats_sem_conquistas(tmp_path):
    caminho = _stats_da_steam(tmp_path / "stats", STEAM_ANTES)
    assert formatos.ler_ou_none(caminho, formatos.STEAM_STATS) == []


def test_steam_stats_varios_blocos_bit_31_e_sem_hora(tmp_path):
    schema = schema_de_teste(
        "570",
        {"1": {"0": {"name": "A"}, "31": {"name": "B"}, "5": {"name": "NAO"}}, "9": {"2": {"name": "C"}}},
    )
    estado = kv_bytes(
        {
            "cache": {
                "crc": 0,
                "1": {"data": -(2**31) | 1, "AchievementTimes": {"0": 100, "31": -7}},
                "9": {"data": 4},
            }
        }
    )
    caminho = _stats_da_steam(tmp_path / "stats", estado, schema, appid="570")
    assert formatos.ler(caminho, formatos.STEAM_STATS) == [
        Desbloqueio("A", 100),
        Desbloqueio("B", 0),
        Desbloqueio("C", 0),
    ]


def test_steam_stats_so_blocos_de_conquistas(tmp_path):
    schema = kv_bytes(
        {
            "570": {
                "stats": {
                    "1": {"type": 4, "bits": {"0": {"name": "A"}}},
                    "2": {"type": "INT", "name": "STAT_X", "bits": {"0": {"name": "NAO"}}},
                    "3": {"type": "ACHIEVEMENTS", "bits": {"40": {"name": "FORA"}, "x": {"name": "NAO"}}},
                }
            }
        }
    )
    estado = kv_bytes({"cache": {"1": {"data": 1}, "2": {"data": 1}, "3": {"data": -1}}})
    caminho = _stats_da_steam(tmp_path / "stats", estado, schema, appid="570")
    assert formatos.ler(caminho, formatos.STEAM_STATS) == [Desbloqueio("A", 0)]


def test_steam_stats_sem_schema_nao_tem_nome(tmp_path):
    caminho = _stats_da_steam(tmp_path / "stats", STEAM_CONFIRMADO, schema=None)
    assert formatos.ler_ou_none(caminho, formatos.STEAM_STATS) == []


def test_schema_ilegivel_e_falha(tmp_path):
    caminho = _stats_da_steam(tmp_path / "stats", STEAM_CONFIRMADO, schema=b"\x00lixo")
    assert formatos.ler_ou_none(caminho, formatos.STEAM_STATS) is None


def test_estado_cortado_e_falha(tmp_path):
    caminho = _stats_da_steam(tmp_path / "stats", STEAM_CONFIRMADO[:-3])
    assert formatos.ler_ou_none(caminho, formatos.STEAM_STATS) is None


def test_estado_ausente_e_nada(tmp_path):
    assert formatos.ler_ou_none(tmp_path / "UserGameStats_123_570.bin", formatos.STEAM_STATS) == []


def test_nome_de_arquivo_estranho_e_nada(tmp_path):
    caminho = tmp_path / "outro.bin"
    caminho.write_bytes(STEAM_CONFIRMADO)
    assert formatos.ler_ou_none(caminho, formatos.STEAM_STATS) == []


# --- o schema interpretado fica em memória, por (caminho, mtime, tamanho) -----------


@pytest.fixture
def leituras_do_schema(monkeypatch):
    """Esvazia o cache de schemas e conta as leituras de `UserGameStatsSchema_*`."""
    formatos._schemas.clear()
    lidos = []
    original = formatos.keyvalues.ler

    def contando(caminho):
        if caminho.name.startswith("UserGameStatsSchema_"):
            lidos.append(caminho)
        return original(caminho)

    monkeypatch.setattr(formatos.keyvalues, "ler", contando)
    yield lidos
    formatos._schemas.clear()


def test_schema_igual_nao_e_lido_de_novo(tmp_path, leituras_do_schema):
    caminho = _stats_da_steam(tmp_path / "stats", STEAM_CONFIRMADO)
    esperado = [Desbloqueio("ACH_BONUS_MANY_STARS", 1790952235)]
    assert formatos.ler(caminho, formatos.STEAM_STATS) == esperado
    assert formatos.ler(caminho, formatos.STEAM_STATS) == esperado
    assert len(leituras_do_schema) == 1


def test_schema_regravado_e_relido(tmp_path, leituras_do_schema):
    caminho = _stats_da_steam(tmp_path / "stats", STEAM_CONFIRMADO)
    arquivo_do_schema = caminho.with_name("UserGameStatsSchema_282800.bin")
    assert formatos.ler(caminho, formatos.STEAM_STATS) == [
        Desbloqueio("ACH_BONUS_MANY_STARS", 1790952235)
    ]
    novo = schema_de_teste("282800", {"1": {"13": {"name": "ACH_OUTRA"}, "14": {"name": "ACH_RENOMEADA"}}})
    arquivo_do_schema.write_bytes(novo)
    mtime = arquivo_do_schema.stat().st_mtime_ns + 10**9  # o NTFS guarda 100 ns: passo de 1 s
    os.utime(arquivo_do_schema, ns=(mtime, mtime))
    assert formatos.ler(caminho, formatos.STEAM_STATS) == [Desbloqueio("ACH_RENOMEADA", 1790952235)]
    assert len(leituras_do_schema) == 2


def test_estado_sem_nenhum_bit_ligado_nao_le_o_schema(tmp_path, leituras_do_schema):
    pasta = tmp_path / "stats"
    caminho = _stats_da_steam(pasta, STEAM_ANTES)
    assert formatos.ler_ou_none(caminho, formatos.STEAM_STATS) == []
    zerado = kv_bytes({"cache": {"crc": 0, "1": {"data": 0}, "2": {"data": 0}, "3": 5}})
    caminho.write_bytes(zerado)
    assert formatos.ler_ou_none(caminho, formatos.STEAM_STATS) == []
    assert leituras_do_schema == []


def test_schema_ilegivel_nao_fica_guardado(tmp_path, leituras_do_schema):
    caminho = _stats_da_steam(tmp_path / "stats", STEAM_CONFIRMADO, schema=b"\x00lixo")
    for _vez in range(2):
        assert formatos.ler_ou_none(caminho, formatos.STEAM_STATS) is None
    assert len(leituras_do_schema) == 2 and not formatos._schemas


def test_cache_de_schemas_tem_tamanho_limitado(tmp_path, leituras_do_schema):
    for numero in range(formatos._SCHEMAS_GUARDADOS + 3):
        pasta = tmp_path / f"stats{numero}"
        caminho = _stats_da_steam(pasta, STEAM_CONFIRMADO)
        assert formatos.ler(caminho, formatos.STEAM_STATS)
    assert len(formatos._schemas) == formatos._SCHEMAS_GUARDADOS
