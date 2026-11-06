# apoio_aplicativo.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `Aplicativo` dos testes do domínio: anota o que o app mostraria (avisos, diálogos, perguntas, reinícios).

Não importa o `conftest` nem outro teste: as cópias abaixo são deliberadas.
"""

from collections.abc import Callable

from kyron import shared


class AvisosAnotados:
    """No lugar da `FilaDeAvisos`: guarda os textos e a última chamada inteira."""

    def __init__(self) -> None:
        self.textos: list[str] = []
        self.ultima: dict | None = None
        self.dispensados: list[int] = []

    def adicionar(self, texto, botao="", ao_clicar=None, segundos=5, chave=None) -> int:
        self.textos.append(texto)
        self.ultima = {"texto": texto, "botao": botao, "ao_clicar": ao_clicar, "segundos": segundos, "chave": chave}
        return len(self.textos)

    def dispensar(self, id: int) -> None:  # noqa: A002
        self.dispensados.append(id)


class AplicativoAnotado:
    """O que o domínio pede ao `Aplicativo`, anotado. As respostas são do teste (`responder`)."""

    def __init__(self) -> None:
        self.avisos = AvisosAnotados()
        self.dialogos: list[tuple[str, str]] = []
        self.confirmacoes: list[dict] = []
        self.reinicios = 0
        self.varredura_conquistas = None

    def pedir_dialogo(self, titulo, corpo, itens, ao_fechar, preferencias=None) -> None:  # noqa: ARG002
        self.dialogos.append((titulo, corpo))

    def pedir_confirmacao(
        self, titulo: str, corpo: str, rotulo: str, ao_responder: Callable[[bool], None], destrutivo: bool = False
    ) -> None:
        self.confirmacoes.append(
            {"titulo": titulo, "corpo": corpo, "rotulo": rotulo, "destrutivo": destrutivo, "ao_responder": ao_responder}
        )

    def responder(self, i: int, confirmou: bool) -> None:
        self.confirmacoes[i]["ao_responder"](confirmou)

    def pedir_reinicio(self) -> None:
        self.reinicios += 1


def instalar(monkeypatch) -> AplicativoAnotado:
    """Põe um `AplicativoAnotado` em `shared.aplicativo` até o fim do teste."""
    aplicativo = AplicativoAnotado()
    monkeypatch.setattr(shared, "aplicativo", aplicativo, raising=False)
    return aplicativo
