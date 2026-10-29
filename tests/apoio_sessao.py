# apoio_sessao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `shared.sessao` falso dos testes dos rastreadores."""


class SessaoFalsa:
    """O que os rastreadores pedem ao `ModeloDaSessao`, só registrado."""

    def __init__(self):
        self.blocker = []  # o jogo de cada show, None de cada hide
        self.avisos = []
        self.toasts = []
        self.presented = 0
        self.janelas = []  # as sessões manuais pedidas

    def show_session_blocker(self, game):
        self.blocker.append(game)

    def hide_session_blocker(self):
        self.blocker.append(None)

    def avisar(self, texto):
        self.avisos.append(texto)

    def session_toast(self, game, seconds):
        self.toasts.append((game, seconds))

    def present(self):
        self.presented += 1


    def abrir_janela_manual(self, manual):
        self.janelas.append(manual)
