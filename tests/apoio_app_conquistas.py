# apoio_app_conquistas.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ajudantes dos testes que antes viviam em `test_app_conquistas.py` e eram importados por outros arquivos de teste.

Um teste nunca importa outro `test_*.py`: importar um arquivo de teste de outro roda a coleta de novo.
"""


class _Gravador:
    """Um objeto cujos métodos anotam a chamada numa lista comum; `falhar` levanta no método dado."""

    def __init__(self, passos, nome, falhar=()):
        self._passos, self._nome, self._falhar = passos, nome, falhar

    def __getattr__(self, metodo):
        def chamar(*_):
            self._passos.append(f"{self._nome}.{metodo}")
            if metodo in self._falhar:
                raise RuntimeError(metodo)

        return chamar
