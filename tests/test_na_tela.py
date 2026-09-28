"""A entrega de uma thread para a tela não fica atrás do redesenho contínuo."""

from gi.repository import GLib

from cartridges.utils.na_tela import entregar_na_tela

GDK_PRIORITY_REDRAW = 120


def _roda_durante_redesenho_continuo(agendar) -> bool:
    """Agenda um callback enquanto uma fonte na prioridade do redesenho está
    sempre pronta — o que um spinner animando faz quando cada quadro ocupa o
    intervalo inteiro da tela — e diz se ele chegou a rodar."""
    rodou = []
    redesenho = GLib.idle_add(lambda: True, priority=GDK_PRIORITY_REDRAW)
    entrega = agendar(lambda: rodou.append(True) or False)
    contexto = GLib.MainContext.default()
    for _ in range(50):
        contexto.iteration(False)
    GLib.source_remove(redesenho)
    if not rodou:
        GLib.source_remove(entrega)
    return bool(rodou)


def test_entrega_passa_na_frente_do_redesenho_continuo():
    assert _roda_durante_redesenho_continuo(entregar_na_tela)


def test_idle_add_comum_fica_atras_do_redesenho_continuo():
    # Controle: sem isto, o teste acima passaria mesmo que a simulação não
    # prendesse nada. É o defeito medido em 28/09/2026.
    assert not _roda_durante_redesenho_continuo(GLib.idle_add)
