"""O navegador do schema de conquistas da Steam."""

from cartridges.conquistas import schema_da_steam
from cartridges.conquistas.schema_da_steam import ConquistaDoSchema


def _schema(bits, tipo="ACHIEVEMENTS", appid="570"):
    return {appid: {"stats": {"1": {"type": tipo, "bits": bits}}}}


def test_display_e_repassado_como_dicionario():
    display = {"name": {"brazilian": "Primeira"}, "icon": "a.jpg"}
    achadas = schema_da_steam.conquistas(_schema({"0": {"name": "A", "display": display}}), "570")
    assert achadas == [ConquistaDoSchema("1", 0, "A", display)]


def test_display_que_nao_e_dicionario_vira_vazio():
    achadas = schema_da_steam.conquistas(
        _schema({"0": {"name": "A", "display": "texto"}, "1": {"name": "B", "display": 7}, "2": {"name": "C"}}),
        "570",
    )
    assert [a.display for a in achadas] == [{}, {}, {}]


def test_chave_de_bit_gigante_e_ignorada_sem_levantar():
    gigante = "9" * 5000
    achadas = schema_da_steam.conquistas(
        _schema({gigante: {"name": "NAO"}, "100": {"name": "NAO"}, "3": {"name": "SIM"}}), "570"
    )
    assert achadas == [ConquistaDoSchema("1", 3, "SIM", {})]


def test_nome_so_vale_se_for_texto():
    achadas = schema_da_steam.conquistas(
        _schema(
            {
                "0": {"name": {"x": "y"}},
                "1": {"name": 42},
                "2": {"name": "   "},
                "3": {"name": "  OK  "},
            }
        ),
        "570",
    )
    assert achadas == [ConquistaDoSchema("1", 3, "OK", {})]


def test_formas_inesperadas_nao_levantam():
    for schema in (None, [], "x", {}, {"570": 1}, {"570": {"stats": []}}, {"570": {"stats": {"1": 5}}}):
        assert schema_da_steam.conquistas(schema, "570") == []
