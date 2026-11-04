# sobre.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O diálogo Sobre: as páginas e os textos."""

import logging
import lzma
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication

from cartridges import shared
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.utils.open_uri import abrir_url

METAINFO = Path(__file__).resolve().parent.parent.parent / "data" / f"{shared.APP_ID}.metainfo.xml.in"
ICONE = Path(__file__).resolve().parent.parent.parent / "data" / "icons" / "hicolor" / "scalable" / "apps" / f"{shared.APP_ID}.svg"

TITULOS = {
    "principal": "Sobre",
    "novidades": "Novidades",
    "creditos": "Créditos",
    "legal": "Aviso legal",
    "problemas": "Solução de problemas",
    "depuracao": "Informações de depuração",
}
DESENVOLVEDOR = "joaomgabaldi"
COPYRIGHT = "© 2022-2024 kramo\n© 2026 joaomgabaldi"
ABOUT_THANKS_TITLE = "O autor original agradece às pessoas abaixo pelas suas contribuições:"
URL_DA_LICENCA = "https://www.gnu.org/licenses/gpl-3.0.html"
ABOUT_LICENSE = (
    "Este aplicativo é fornecido sem nenhuma garantia. Veja a "
    f'<a href="{URL_DA_LICENCA}">Licença Pública '
    "Geral GNU, versão 3 ou posterior</a> para mais detalhes."
)
CREDITOS = [
    {"titulo": "", "nomes": ["Copyright (C) 2022-2024 kramo", "Copyright (C) 2026 joaomgabaldi"]},
    {
        "titulo": ABOUT_THANKS_TITLE,
        "nomes": [
            "Geoffrey Coulaud", "Rilic", "Arcitec", "Paweł Lidwin", "Domenico", "Rafael Mardojai CM",
            "Clara Hobbs", "Sabri Ünal",
        ],
    },
]  # fmt: skip
TEXTO_DE_SUPORTE = "As informações de depuração abaixo ajudam a diagnosticar problemas. Inclua-as ao solicitar suporte."
NOME_DO_LOG = "cartridges.log"


def informacoes_de_depuracao(arquivos: list[Path]) -> str:
    texto = ""
    for indice, caminho in enumerate(arquivos):
        if indice > 0:
            texto += "─" * 37 + "\n"
        try:
            with (
                lzma.open(caminho, "rt", encoding="utf-8", errors="replace")
                if caminho.name.endswith(".xz")
                else open(caminho, "r", encoding="utf-8", errors="replace")  # noqa: PTH123
            ) as log:
                texto += log.read()
        except (OSError, EOFError, lzma.LZMAError):
            texto += f"[{caminho.name}: ilegível]\n"
    return texto


def _texto(elemento: ET.Element) -> str:
    return " ".join("".join(elemento.itertext()).split())


def _raiz(metainfo: Path) -> ET.Element | None:
    try:
        return ET.parse(metainfo).getroot()  # noqa: S314 (o arquivo é do próprio app)
    except (OSError, ET.ParseError):
        logging.warning("Sobre: a metainfo %s não pôde ser lida", metainfo)
        return None


def novidades_da_versao(metainfo: Path, versao: str) -> list[dict]:
    raiz = _raiz(metainfo)
    if raiz is None:
        return []
    for release in raiz.findall("releases/release"):
        if release.get("version") != versao:
            continue
        itens: list[dict] = []
        descricao = release.find("description")
        for filho in () if descricao is None else descricao:
            if filho.tag == "p":
                itens.append({"tipo": "p", "texto": _texto(filho)})
            elif filho.tag in ("ul", "ol"):
                itens.extend({"tipo": "li", "texto": _texto(li)} for li in filho.findall("li"))
        return itens
    return []


def _area_de_transferencia() -> object:
    return QGuiApplication.clipboard()


class Sobre(QObject):
    alterado = Signal()

    def __init__(self, avisos: FilaDeAvisos | None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._avisos = avisos
        self._aberto = False
        self._pagina = "principal"
        self._versao = shared.VERSION
        self._novidades: list[dict] = []
        self._depuracao = ""

    @Property(bool, notify=alterado)
    def aberto(self) -> bool:
        return self._aberto

    @Property(str, notify=alterado)
    def pagina(self) -> str:
        return self._pagina

    @Property(str, notify=alterado)
    def versao(self) -> str:
        return self._versao

    @Property("QVariantList", notify=alterado)
    def novidades(self) -> list:
        return self._novidades

    @Property(bool, notify=alterado)
    def temNovidades(self) -> bool:  # noqa: N802
        return bool(self._novidades)

    @Property(str, notify=alterado)
    def depuracao(self) -> str:
        return self._depuracao

    @Property("QVariantMap", constant=True)
    def titulos(self) -> dict:
        return TITULOS

    @Property("QVariantList", constant=True)
    def creditos(self) -> list:
        return CREDITOS

    @Property(str, constant=True)
    def desenvolvedor(self) -> str:
        return DESENVOLVEDOR

    @Property(str, constant=True)
    def copyright(self) -> str:
        return COPYRIGHT

    @Property(str, constant=True)
    def licenca(self) -> str:
        return ABOUT_LICENSE

    @Property(str, constant=True)
    def urlDaLicenca(self) -> str:  # noqa: N802
        return URL_DA_LICENCA

    @Property(str, constant=True)
    def textoDeSuporte(self) -> str:  # noqa: N802
        return TEXTO_DE_SUPORTE

    @Property(str, constant=True)
    def nomeDoLog(self) -> str:  # noqa: N802
        return NOME_DO_LOG

    @Property(QUrl, constant=True)
    def icone(self) -> QUrl:
        return QUrl.fromLocalFile(str(ICONE))

    @Slot()
    def abrir(self) -> None:
        self._versao = shared.VERSION
        self._novidades = novidades_da_versao(METAINFO, self._versao)
        self._pagina = "principal"
        self._depuracao = ""
        self._aberto = True
        self.alterado.emit()

    @Slot()
    def fechar(self) -> None:
        if self._aberto:
            self._aberto = False
            self.alterado.emit()

    @Slot(str)
    def irPara(self, pagina: str) -> None:  # noqa: N802
        if pagina not in TITULOS:
            return
        if pagina == "depuracao":
            self._depuracao = informacoes_de_depuracao(list(shared.log_files))
        self._pagina = pagina
        self.alterado.emit()

    @Slot()
    def voltar(self) -> None:
        self.irPara("problemas" if self._pagina == "depuracao" else "principal")

    @Slot()
    def copiar(self) -> None:
        _area_de_transferencia().setText(self._depuracao)
        self._avisar_copia()

    @Slot()
    def copiarVersao(self) -> None:  # noqa: N802
        _area_de_transferencia().setText(self._versao)
        self._avisar_copia()

    def _avisar_copia(self) -> None:
        if self._avisos is not None:
            self._avisos.adicionar("Copiado para a área de transferência")

    @Slot(QUrl)
    def salvar(self, url: QUrl) -> None:
        if url.isEmpty():
            return
        try:
            Path(url.toLocalFile()).write_text(self._depuracao, encoding="utf-8")
        except OSError:
            logging.exception("Sobre: não foi possível salvar %s", url.toString())
            if self._avisos is not None:
                self._avisos.adicionar("Não foi possível salvar o arquivo")

    @Slot(str)
    def abrirLicenca(self, url: str) -> None:  # noqa: N802
        if url == URL_DA_LICENCA:
            abrir_url(url)
