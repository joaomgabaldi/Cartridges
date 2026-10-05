"""Os saneadores compartilhados pelas APIs das lojas."""

import pytest

from cartridges.conquistas.saneamento import numero_finito


@pytest.mark.parametrize("valor", [0, 1, -1, 4.5, 100, 10**300])
def test_numero_finito_aceita_numeros(valor):
    assert numero_finito(valor) is True


@pytest.mark.parametrize(
    "valor",
    [True, False, None, "4", [], {}, float("nan"), float("inf"), float("-inf"), 10**400, -(10**400)],
    ids=["True", "False", "None", "texto", "lista", "dict", "nan", "inf", "-inf", "enorme", "-enorme"],
)
def test_numero_finito_recusa_o_resto_sem_levantar(valor):
    assert numero_finito(valor) is False
