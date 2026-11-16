# atualizar_versoes.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Decide a combinação mais nova que funciona em conjunto e reescreve as versões fixadas no repositório.

    python build-aux/windows/atualizar_versoes.py [--verificar] [--json CAMINHO]

Saída: uma linha por troca ("peça: de → para") e por aviso ("Aviso: …"). Códigos: 0 = ok (ou nada novo no
`--verificar`); 1 = `--verificar` com novidade; 2 = um ponto a reescrever ausente ou repetido (defeito do script).
Peça sem hash publicado, fonte fora do ar ou versão nova incompatível: fica a atual e sai um aviso.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import fontes_de_versao as fontes
from fontes_de_versao import FonteIndisponivel, Pino, SemHash, _chave, _normalizado

RAIZ = Path(__file__).resolve().parent.parent.parent

PYTHON_VERSION = ".python-version"
README = "README.md"
REQ_IN, REQ_DEV_IN = "requirements.in", "requirements-dev.in"
REQ, REQ_DEV = "requirements.txt", "requirements-dev.txt"
MONTAR = "build-aux/windows/montar_app_qt.py"
QT_SDK = "tools/baixar_qt_sdk.py"
INNO = "build-aux/windows/instalar_inno.ps1"
METAINFO = "data/io.github.joaomgabaldi.Cartridges.metainfo.xml.in"
REPOSITORIO = "joaomgabaldi/Cartridges"
# Componentes nomeados (masculino); as bibliotecas (feminino) usam o nome do pip. Os pacotes irmãos do PySide6
# andam com ele e não ganham item próprio.
NOMES = {"python": "Python", "pyside6": "PySide6", "qt-sdk": "Qt", "qwindowkit": "QWindowKit",
         "ffmpeg": "FFmpeg", "ludusavi": "Ludusavi", "inno-setup": "Inno Setup"}
IRMAOS_DO_PYSIDE6 = {"pyside6-addons", "pyside6-essentials", "shiboken6"}
_TOPO = re.compile(r"^[ \t]*<release\b[^>]*>.*?</release>", re.M | re.S)
_FIM_DA_LISTA = re.compile(r"^([ \t]*)</ul>", re.M)
_VERSAO_DO_TOPO = re.compile(r'<release\b[^>]*\bversion="([^"]*)"')

CONSTANTES = {
    MONTAR: ("PYTHON_SHA256", "FFMPEG_VERSAO", "FFMPEG_SHA256", "FFMPEG_FONTE",
             "LUDUSAVI_VERSAO", "LUDUSAVI_SHA256", "LUDUSAVI_LEGAL_SHA256"),
    QT_SDK: ("QT_VERSAO", "QT_DATA", "QTBASE_SHA256", "QTDECLARATIVE_SHA256", "QWK_TAG", "QWK_COMMIT", "QMSETUP_COMMIT"),
}
_VERSAO = re.compile(r"\d+(\.\d+){1,3}")
_INNO_VERSAO = re.compile(r"(\$InnoVersao = ')([0-9.]+)(')")
_INNO_HASH = re.compile(r"(\$InnoSha256 = ')([0-9A-Fa-f]{64})(')")
_README = re.compile(r"Python \d+\.\d+ com PySide6 [0-9.]+")
_PINO = re.compile(r"^(\S+)==(\S+) --hash=sha256:([0-9a-f]{64})\r?$", re.M)


class PontoAusente(Exception):
    """Um ponto a reescrever não foi achado exatamente uma vez: defeito do script, não da fonte."""


@dataclass(frozen=True)
class Troca:
    peca: str
    de: str
    para: str


@dataclass
class Resultado:
    trocas: list[Troca]
    avisos: list[str]


def _uma(padrao: re.Pattern, texto: str, onde: str) -> re.Match:
    achados = list(padrao.finditer(texto))
    if len(achados) != 1:
        raise PontoAusente(f"{onde}: esperava 1 ocorrência de {padrao.pattern!r}, achei {len(achados)}")
    return achados[0]


def _padrao_constante(nome: str) -> re.Pattern:
    return re.compile(rf'^({re.escape(nome)} = ")([^"\r\n]*)(")', re.M)


def ler_constante(texto: str, nome: str) -> str:
    return _uma(_padrao_constante(nome), texto, nome).group(2)


def trocar_constante(texto: str, nome: str, valor: str) -> str:
    """A linha `NOME = "…"` (exatamente uma) passa a ter `valor`; o resto do texto fica intacto."""
    a = _uma(_padrao_constante(nome), texto, nome)
    return texto[:a.start(2)] + valor + texto[a.end(2):]


def _trocar_grupo(texto: str, padrao: re.Pattern, grupo: int, valor: str, onde: str) -> str:
    a = _uma(padrao, texto, onde)
    return texto[:a.start(grupo)] + valor + texto[a.end(grupo):]


def _maior(nova: str, atual: str) -> bool:
    return _chave(nova) > _chave(atual)


def _lib_menor(nova: str, atual: str) -> bool:
    """Compara só a parte numérica de versões do PyPI ("1.0.post1", "6.12.0.140"); o que não tem número não conta."""
    a, b = (re.match(r"\d+(\.\d+)*", v) for v in (nova, atual))
    return bool(a and b) and _chave(a.group()) < _chave(b.group())


def _xy(versao: str) -> str:
    return ".".join(versao.split(".")[:2])


def _resolver(raiz: Path, xy: str, restricoes: list[str], rodar) -> tuple[list[Pino], list[Pino]] | None:
    """(libs do app, libs só de teste) para o Python `xy`; as de teste são resolvidas com as do app fixadas."""
    app = fontes.resolver_libs([raiz / REQ_IN], xy, restricoes, rodar)
    if app is None:
        return None
    todas = fontes.resolver_libs(
        [raiz / REQ_IN, raiz / REQ_DEV_IN], xy, restricoes + [f"{p.nome}=={p.versao}" for p in app], rodar
    )
    if todas is None:
        return None
    nomes = {_normalizado(p.nome) for p in app}
    return app, [p for p in todas if _normalizado(p.nome) not in nomes]


def _versoes(pinos) -> dict[str, str]:
    return {_normalizado(p.nome): p.versao for p in pinos}


def _decidir_python_e_libs(raiz, py_atual, qt_atual, libs_atuais, ler, rodar, avisos):
    """(python, sha256 do embutido ou None, libs, qt) da maior versão X.Y que resolve; None se nem a atual resolve.

    `qt` é `(versão, data, sha base, sha declarative)` quando o PySide6 sobe junto com o SDK do Qt, senão None.
    """
    try:
        no_setup = fontes.versoes_do_setup_python(ler)
        candidatas = [v for v in fontes.versoes_do_python(ler) if v in no_setup and _maior(v, py_atual)]
    except FonteIndisponivel as erro:
        avisos.append(f"Python: fica no {py_atual}; a lista de versões não está disponível ({erro}).")
        candidatas = []
    candidatas.append(py_atual)
    sdk_do_qt = {}
    nao_resolvem = set()
    for v in candidatas:
        xy = _xy(v)
        if xy in nao_resolvem:
            continue
        sha = None
        if v != py_atual:
            try:
                sha = fontes.python_embutido(v, ler).sha256
            except (FonteIndisponivel, SemHash) as erro:
                avisos.append(f"Python {v} fica de fora: {erro}.")
                continue
        libs = _resolver(raiz, xy, [], rodar)
        qt = None
        if libs:
            pyside = _versoes(libs[0]).get("pyside6", qt_atual)
            if pyside != qt_atual:
                if pyside not in sdk_do_qt:
                    try:
                        sdk_do_qt[pyside] = fontes.qt_sdk(pyside, ler)
                    except (FonteIndisponivel, SemHash, ValueError) as erro:
                        avisos.append(f"Qt {pyside}: {erro}.")
                        sdk_do_qt[pyside] = None
                qt = sdk_do_qt[pyside] and (pyside, *sdk_do_qt[pyside])
                if qt is None:
                    avisos.append(f"O SDK do Qt {pyside} para MSVC 64 bits não está publicado; PySide6 e Qt ficam no {qt_atual}.")
                    libs = _resolver(raiz, xy, [f"PySide6=={qt_atual}"], rodar)
        if libs:
            novas = _versoes(libs[0] + libs[1])
            menores = [n for n, ver in novas.items() if n in libs_atuais and _lib_menor(ver, libs_atuais[n])]
            if menores:
                avisos.append(f"Com o Python {xy}, o pip escolheria versões menores que as atuais ({', '.join(menores)}).")
                libs = None
        if libs is None:
            nao_resolvem.add(xy)
            if v != py_atual:
                avisos.append(f"Python {v} fica de fora: as bibliotecas não resolvem com ele.")
            continue
        return v, sha, libs, qt
    avisos.append(f"As bibliotecas não resolvem com o Python {py_atual}; ficam as versões atuais.")
    return None


def _peca_independente(nome: str, buscar, avisos):
    try:
        return buscar()
    except (FonteIndisponivel, SemHash, ValueError) as erro:
        avisos.append(f"{nome}: fica na versão atual ({erro}).")
        return None


def _release(repo: str, prefixo: str, antes_da_versao: str, ler) -> tuple[str, dict[str, str]]:
    tag, assets = fontes.release_do_github(repo, ler, prefixo)
    versao = tag[len(antes_da_versao):].replace("_", ".")
    if not _VERSAO.fullmatch(versao):
        raise ValueError(f"tag ilegível {tag!r}")
    return versao, assets


def _hashes(assets: dict[str, str], nomes: list[str], versao: str) -> list[str]:
    faltam = [n for n in nomes if n not in assets]
    if faltam:
        raise SemHash(f"a release {versao} não publica o SHA-256 de {', '.join(faltam)}")
    return [assets[n] for n in nomes]


def _topo(metainfo: str) -> re.Match:
    achado = _TOPO.search(metainfo)
    if not achado or not _VERSAO_DO_TOPO.search(achado.group(0)):
        raise PontoAusente(f"{METAINFO}: sem <release version=...> no topo")
    return achado


def escrever_changelog(metainfo: str, trocas: list[Troca]) -> str:
    """Um `<li>` por peça ao fim da `<ul>` da `<release>` do topo; peça que já tem item só troca a versão."""
    topo = _topo(metainfo)
    bloco = topo.group(0)
    for t in trocas:
        if t.peca in IRMAOS_DO_PYSIDE6 or not t.para:
            continue
        nome = escape(NOMES.get(t.peca, t.peca))
        existente = re.compile(rf"(<li>{re.escape(nome)} atualizad[oa] para )[^<]*(\.</li>)")
        if existente.search(bloco):
            bloco = existente.sub(lambda m: f"{m.group(1)}{escape(t.para)}{m.group(2)}", bloco, 1)
            continue
        fim = _uma(_FIM_DA_LISTA, bloco, METAINFO)
        quebra = "\r\n" if "\r\n" in bloco else "\n"
        genero = "atualizado" if t.peca in NOMES else "atualizada"
        item = f"{fim.group(1)}  <li>{nome} {genero} para {escape(t.para)}.</li>{quebra}"
        bloco = bloco[:fim.start()] + item + bloco[fim.start():]
    return metainfo[:topo.start()] + bloco + metainfo[topo.end():]


def _publicada_como_final(metainfo: str, ler) -> tuple[str, bool | None]:
    """(versão do topo, se já é release final no GitHub; None se não deu para conferir)."""
    versao = _VERSAO_DO_TOPO.search(_topo(metainfo).group(0)).group(1)
    try:
        dados = json.loads(ler(f"https://api.github.com/repos/{REPOSITORIO}/releases/tags/v{versao}"))
        return versao, dados["prerelease"] is False
    except fontes.NaoEncontrado:
        return versao, False
    except (FonteIndisponivel, ValueError, KeyError, TypeError):
        return versao, None


def atualizar(raiz: Path, *, gravar: bool, ler=fontes.ler_da_rede, rodar=subprocess.run) -> Resultado:
    raiz = Path(raiz)
    caminhos = [PYTHON_VERSION, README, REQ, REQ_DEV, MONTAR, QT_SDK, INNO, METAINFO]
    # newline="" preserva o fim de linha de cada arquivo; o BOM, se houver, volta junto no texto.
    textos = {c: (raiz / c).read_text(encoding="utf-8", newline="") for c in caminhos}
    novos = dict(textos)
    trocas: list[Troca] = []
    avisos: list[str] = []

    # Valores de hoje, lidos dos próprios arquivos (um ponto ausente para aqui, antes de qualquer rede).
    py_atual = _uma(re.compile(r"\A\d+\.\d+\.\d+(?=\r?\n?\Z)"), textos[PYTHON_VERSION], PYTHON_VERSION).group()
    c = {nome: ler_constante(textos[arq], nome) for arq, nomes in CONSTANTES.items() for nome in nomes}
    inno_atual = _uma(_INNO_VERSAO, textos[INNO], INNO).group(2)
    pinos_de = {arq: {(_normalizado(m[0]), m[1], m[2]) for m in _PINO.findall(textos[arq])} for arq in (REQ, REQ_DEV)}
    libs_atuais = {nome: versao for pinos in pinos_de.values() for nome, versao, _ in pinos}
    hashes_mudaram = False
    n = dict(c)
    python, pyside, inno = py_atual, c["QT_VERSAO"], (inno_atual, None)

    # 1-2. Python, libs e PySide6/Qt (andam juntos).
    decisao = _decidir_python_e_libs(raiz, py_atual, c["QT_VERSAO"], libs_atuais, ler, rodar, avisos)
    if decisao:
        python, sha_py, (app, dev), qt = decisao
        if python != py_atual:
            trocas.append(Troca("python", py_atual, python))
            n["PYTHON_SHA256"] = sha_py
        libs_novas = _versoes(app + dev)
        trocas_libs = [
            Troca(nome, libs_atuais.get(nome, ""), libs_novas.get(nome, ""))
            for nome in sorted(libs_atuais.keys() | libs_novas.keys())
            if libs_atuais.get(nome) != libs_novas.get(nome)
        ]
        trocas += trocas_libs
        # O hash é da roda daquele Python: mesma versão com outro Python (ou roda republicada) também regrava.
        if any(pinos_de[arq] != {(_normalizado(p.nome), p.versao, p.sha256) for p in pinos}
               for arq, pinos in ((REQ, app), (REQ_DEV, dev))):
            novos[REQ] = fontes.texto_requirements(app, [])
            novos[REQ_DEV] = fontes.texto_requirements(dev, [f"-r {REQ}"])
            if not trocas_libs:
                hashes_mudaram = True
                avisos.append("Os hashes das bibliotecas mudaram sem mudança de versão; os requirements foram refeitos.")
        if qt:
            pyside = qt[0]
            trocas.append(Troca("qt-sdk", c["QT_VERSAO"], pyside))
            n["QT_VERSAO"], n["QT_DATA"], n["QTBASE_SHA256"], n["QTDECLARATIVE_SHA256"] = qt

    # 3. Peças independentes: só sobem para versão maior, com hash publicado.
    qwk = _peca_independente("QWindowKit", lambda: fontes.qwindowkit(ler), avisos)
    if qwk and _maior(qwk[0], c["QWK_TAG"]):
        trocas.append(Troca("qwindowkit", c["QWK_TAG"], qwk[0]))
        n["QWK_TAG"], n["QWK_COMMIT"], n["QMSETUP_COMMIT"] = qwk

    ff = _peca_independente("ffmpeg", lambda: fontes.ffmpeg(ler), avisos)
    if ff and _maior(ff[0].versao, c["FFMPEG_VERSAO"]):
        trocas.append(Troca("ffmpeg", c["FFMPEG_VERSAO"], ff[0].versao))
        n["FFMPEG_VERSAO"], n["FFMPEG_SHA256"], n["FFMPEG_FONTE"] = ff[0].versao, ff[0].sha256, ff[1]

    def ludusavi():
        versao, assets = _release("mtkennerly/ludusavi", "v", "v", ler)
        if not _maior(versao, c["LUDUSAVI_VERSAO"]):
            return None
        return versao, *_hashes(assets, [f"ludusavi-v{versao}-win64.zip", f"ludusavi-v{versao}-legal.zip"], versao)

    lud = _peca_independente("Ludusavi", ludusavi, avisos)
    if lud:
        trocas.append(Troca("ludusavi", c["LUDUSAVI_VERSAO"], lud[0]))
        n["LUDUSAVI_VERSAO"], n["LUDUSAVI_SHA256"], n["LUDUSAVI_LEGAL_SHA256"] = lud

    def inno_setup():
        versao, assets = _release("jrsoftware/issrc", "is-7_", "is-", ler)
        if not _maior(versao, inno_atual):
            return None
        return versao, _hashes(assets, [f"innosetup-{versao}-x64.exe"], versao)[0]

    nova_inno = _peca_independente("Inno Setup", inno_setup, avisos)
    if nova_inno:
        trocas.append(Troca("inno-setup", inno_atual, nova_inno[0]))
        inno = nova_inno

    # 4. Reescrita em memória de todos os pontos (os que não mudam também: confere que existem).
    novos[PYTHON_VERSION] = _trocar_grupo(textos[PYTHON_VERSION], re.compile(r"\A(\d+\.\d+\.\d+)"), 1, python, PYTHON_VERSION)
    for arq, nomes in CONSTANTES.items():
        for nome in nomes:
            novos[arq] = trocar_constante(novos[arq], nome, n[nome])
    novos[README] = _trocar_grupo(textos[README], re.compile(f"({_README.pattern})"), 1,
                                  f"Python {_xy(python)} com PySide6 {pyside}", README)
    texto = textos[INNO]
    if inno[1]:
        texto = _trocar_grupo(texto, _INNO_VERSAO, 2, inno[0], INNO)
        texto = _trocar_grupo(texto, _INNO_HASH, 2, inno[1].upper(), INNO)
    else:
        _uma(_INNO_HASH, texto, INNO)
    novos[INNO] = texto

    if trocas:
        versao, publicada = _publicada_como_final(textos[METAINFO], ler)
        if publicada is None:
            avisos.append(f"Não foi possível conferir se a versão {versao} já foi publicada; o changelog não foi atualizado.")
        elif publicada:
            avisos.append(f"A versão {versao} já foi publicada: suba a VERSION em kyron/shared.py e abra uma <release> "
                          "nova para registrar as atualizações.")
        else:
            novos[METAINFO] = escrever_changelog(textos[METAINFO], trocas)

    if gravar and (trocas or hashes_mudaram):
        for arq, texto in novos.items():
            if texto != textos[arq]:
                temporario = raiz / (arq + ".novo")
                temporario.write_text(texto, encoding="utf-8", newline="")
                os.replace(temporario, raiz / arq)
    return Resultado(trocas, list(dict.fromkeys(avisos)))


def _de_para(t: Troca) -> str:
    return f"{t.de or '(nova)'} → {t.para or '(removida)'}"


def linha_do_commit(r: Resultado) -> str:
    return "Versões atualizadas: " + ", ".join(f"{t.peca} {_de_para(t)}" for t in r.trocas)


def main(argv=None, *, raiz: Path = RAIZ, ler=fontes.ler_da_rede, rodar=subprocess.run) -> int:
    parser = argparse.ArgumentParser(description="Atualiza as versões fixadas para as mais novas compatíveis.")
    parser.add_argument("--verificar", action="store_true", help="só mostra o que mudaria, sem gravar")
    parser.add_argument("--json", type=Path, help="grava as trocas, os avisos e a linha do commit neste arquivo")
    args = parser.parse_args(argv)
    for fluxo in (sys.stdout, sys.stderr):  # o console da CI não é UTF-8 e a saída tem "→"
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8")
    try:
        r = atualizar(raiz, gravar=not args.verificar, ler=ler, rodar=rodar)
    except PontoAusente as erro:
        print(f"Erro: ponto a reescrever ausente ou repetido. {erro}", file=sys.stderr)
        return 2
    except Exception as erro:  # o código 1 quer dizer "há novidade"; um defeito nunca pode sair com ele
        print(f"Erro inesperado: {erro!r}", file=sys.stderr)
        return 2
    for t in r.trocas:
        print(f"{t.peca}: {_de_para(t)}")
    for a in r.avisos:
        print(f"Aviso: {a}")
    if not r.trocas:
        print("Nenhuma versão nova.")
    if args.json:
        dados = {"trocas": [asdict(t) for t in r.trocas], "avisos": r.avisos,
                 "linha": linha_do_commit(r) if r.trocas else ""}
        args.json.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if args.verificar and r.trocas else 0


if __name__ == "__main__":
    sys.exit(main())
