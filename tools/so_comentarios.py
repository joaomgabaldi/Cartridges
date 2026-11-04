# so_comentarios.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Prova que uma mudança tocou só comentários e docstrings.

Uso: `python tools/so_comentarios.py <commit-base>` compara a base com a árvore de trabalho
(preparado, não preparado e novos) e sai com 1 listando os arquivos com diferença real.
Na dúvida, aponta diferença: um falso positivo custa refazer, um falso negativo deixa passar código.
"""

import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

# Marcadores que viram diretiva para ferramentas: tirar ou mudar um deles muda o comportamento.
_MARCADOR = re.compile(r"#\s*(noqa|type:|pragma|fmt:|pylint:|pyright:|mypy:|isort:|ruff:|-\*-\s*coding|(?:en)?coding[:=])", re.I)
_NAO_CODIGO = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}


def _marcadores(texto):
    """Cada marcador com o código da linha em que vale (a dele ou a da próxima linha com código)."""
    codigo, comentarios = {}, []
    for t in tokenize.generate_tokens(io.StringIO(texto).readline):
        if t.type == tokenize.COMMENT:
            if _MARCADOR.match(t.string):
                comentarios.append((t.start[0], t.string.strip()))
        elif t.type not in _NAO_CODIGO:
            codigo.setdefault(t.start[0], []).append(t.string)
    linhas = sorted(codigo)
    achados = []
    for numero, texto_comentario in comentarios:
        alvo = next((n for n in linhas if n >= numero), None)
        achados.append((texto_comentario, tuple(codigo.get(alvo, ()))))
    return achados


def _sem_docstrings(arvore):
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            corpo = no.body
            # Corpo só de docstring continua como está: tirá-la exige `pass`, que é código.
            if len(corpo) > 1 and isinstance(corpo[0], ast.Expr) and isinstance(corpo[0].value, ast.Constant) \
                    and isinstance(corpo[0].value.value, str):
                del corpo[0]
    return ast.dump(arvore)


def _py(texto):
    return _sem_docstrings(ast.parse(texto)), _marcadores(texto)


def _varrer(texto, linha=(), blocos=(), aspas="", escape="", multilinha=False, aqui_string=False,
            marca_precedida=False, livres=()):
    """Remove comentários fora de strings e normaliza espaços. `livres`: aberturas que não são comentário."""
    saida, i, n, ult = [], 0, len(texto), "\n"

    def emitir(s):
        nonlocal ult
        saida.append(s)
        ult = s[-1]

    def espaco(c):
        nonlocal ult
        if c == "\n":
            if ult == " ":
                saida.pop()
                ult = saida[-1][-1] if saida else "\n"
            if ult != "\n":
                emitir("\n")
        elif ult not in " \n":
            emitir(" ")

    while i < n:
        c = texto[i]
        bloco = next(((a, f) for a, f in blocos if texto.startswith(a, i)
                      and not any(texto.startswith(x, i) for x in livres)), None)
        if bloco:
            fim = texto.find(bloco[1], i + len(bloco[0]))
            if fim < 0:
                raise ValueError("comentário de bloco sem fecho")
            espaco("\n" if "\n" in texto[i:fim] else " ")
            i = fim + len(bloco[1])
            continue
        if any(texto.startswith(m, i) for m in linha) and (not marca_precedida or ult in " \n"):
            fim = texto.find("\n", i)
            i = n if fim < 0 else fim
            continue
        if aqui_string and c == "@" and i + 1 < n and texto[i + 1] in "'\"":
            m = re.match(r"@(['\"])[ \t]*\n", texto[i:])
            if m:
                fim = texto.find("\n" + m.group(1) + "@", i)
                if fim < 0:
                    raise ValueError("here-string sem fecho")
                fim += 3
                emitir(texto[i:fim])
                i = fim
                continue
        if c in aspas:
            j = i + 1
            while True:
                if j >= n:
                    if multilinha or c == "`":
                        raise ValueError("string sem fecho")
                    j = n - 1
                    break
                d = texto[j]
                if escape and d == escape:
                    j += 2
                    continue
                if d == c:
                    break
                if d == "\n" and not multilinha and c != "`":
                    j -= 1
                    break
                j += 1
            emitir(texto[i:j + 1])
            i = j + 1
            continue
        if c.isspace():
            espaco("\n" if c == "\n" else " ")
        else:
            emitir(c)
        i += 1
    return "".join(saida).strip()


def _linhas(texto, descartar, manter_indentacao=False):
    """Para formatos em que o espaço interno conta: só some a linha inteira de comentário."""
    saida = []
    for linha in texto.split("\n"):
        corte = linha.strip()
        if not corte or descartar(corte):
            continue
        saida.append(linha.rstrip() if manter_indentacao else corte)
    return "\n".join(saida)


def _c(texto):
    return _varrer(texto, linha=("//",), blocos=(("/*", "*/"),), aspas="\"'", escape="\\")


def _js(texto):
    return _varrer(texto, linha=("//",), blocos=(("/*", "*/"),), aspas="\"'`", escape="\\")


def _ps1(texto):
    return _varrer(texto, linha=("#",), blocos=(("<#", "#>"),), aspas="\"'", escape="`",
                   multilinha=True, aqui_string=True, marca_precedida=True)


def _cmake(texto):
    if "#[" in texto:
        raise ValueError("comentário de colchetes do CMake não suportado")
    return _varrer(texto, linha=("#",), aspas='"', escape="\\", multilinha=True, marca_precedida=True)


def _bat(texto):
    return _linhas(texto, lambda s: s.startswith("::") or re.match(r"@?rem(\s|$)", s, re.I))


def _hash_linhas(texto):
    return _linhas(texto, lambda s: s.startswith("#"))


def _ini(texto):
    return _linhas(texto, lambda s: s[0] in "#;")


_BLOCO_YML = re.compile(r"(?:^|[:-])\s+[|>][0-9+-]*$")


def _cortar_comentario_yml(linha):
    aspa = ""
    for i, c in enumerate(linha):
        if aspa:
            if c == "\\" and aspa == '"':
                continue
            if c == aspa:
                aspa = ""
        elif c in "\"'":
            aspa = c
        elif c == "#" and (i == 0 or linha[i - 1] in " \t"):
            return linha[:i]
    return linha


def _yml(texto):
    saida, bloco = [], None
    for linha in texto.split("\n"):
        recuo = len(linha) - len(linha.lstrip())
        if bloco is not None:
            if not linha.strip() or recuo > bloco:
                saida.append(linha)
                continue
            bloco = None
        limpa = _cortar_comentario_yml(linha).rstrip()
        if not limpa.strip():
            continue
        saida.append(limpa)
        if _BLOCO_YML.search(limpa):
            bloco = recuo
    return "\n".join(saida)


def _iss(texto):
    """Fora do [Code] só vale `;` no começo da linha; dentro, Pascal (`//`, `{ }`, `(* *)`)."""
    saida, secao, pedaco = [], "", []

    def fechar():
        if secao == "code":
            saida.append(_varrer("\n".join(pedaco), linha=("//",), blocos=(("{", "}"), ("(*", "*)")),
                                 aspas="'", livres=("{#", "{$")))
        else:
            saida.append(_linhas("\n".join(pedaco), lambda s: s.startswith(";")))

    for linha in texto.split("\n"):
        m = re.fullmatch(r"\s*\[(\w+)\]\s*", linha)
        if m:
            fechar()
            secao, pedaco = m.group(1).lower(), []
            saida.append(linha.strip().lower())
        else:
            pedaco.append(linha)
    fechar()
    return "\n".join(s for s in saida if s)


_JS = (".qml", ".js", ".mjs")
_C = (".c", ".h", ".cpp", ".hpp", ".rc")
_POR_EXTENSAO = {**dict.fromkeys(_JS, _js), **dict.fromkeys(_C, _c), ".ps1": _ps1, ".psm1": _ps1, ".bat": _bat, ".cmd": _bat,
                 ".yml": _yml, ".yaml": _yml, ".iss.in": _iss, ".ini": _ini, ".cfg": _ini, ".pylintrc": _ini}
_POR_NOME = {"cmakelists.txt": _cmake, "qmldir": _hash_linhas, ".gitignore": _hash_linhas}


def _terminacao(texto):
    return ("\r\n" in texto, bool(re.search(r"(?<!\r)\n", texto)))


def diferencas(antes: str, depois: str, extensao: str) -> list[str]:
    """Lista o que mudou além de comentários e docstrings; vazia quando só eles mudaram."""
    extensao = extensao.lower()
    if not extensao.startswith("."):
        extensao = "." + extensao
    if _terminacao(antes) != _terminacao(depois):
        return ["terminação de linha mudou"]
    if extensao in (".py", ".pyi"):
        tratar = _py
    elif extensao in _POR_EXTENSAO:
        tratar = _POR_EXTENSAO[extensao]
    else:
        return [f"extensão sem suporte ({extensao})"]
    return _comparar(tratar, antes, depois)


def _comparar(tratar, antes, depois):
    try:
        a, b = tratar(antes.replace("\r\n", "\n")), tratar(depois.replace("\r\n", "\n"))
    except (SyntaxError, ValueError, tokenize.TokenError) as erro:
        return [f"não foi possível analisar: {erro}"]
    if a == b:
        return []
    if isinstance(a, tuple):
        return ["código mudou" if a[0] != b[0] else "marcador (noqa, type, pragma, fmt) mudou"]
    return ["código mudou"]


def _git(*args, texto=True):
    return subprocess.run(["git", *args], capture_output=True, text=texto, encoding="utf-8" if texto else None,
                          check=True).stdout


def _nome_chave(caminho):
    nome = Path(caminho).name.lower()
    if nome.endswith(".iss.in"):
        return ".iss.in"
    return nome if nome in _POR_NOME else Path(caminho).suffix.lower() or nome


def _conferir_arquivo(caminho, antes, depois):
    chave = _nome_chave(caminho)
    if chave in _POR_NOME:
        if _terminacao(antes) != _terminacao(depois):
            return ["terminação de linha mudou"]
        return _comparar(_POR_NOME[chave], antes, depois)
    return diferencas(antes, depois, chave)


def conferir(base):
    """Arquivo -> motivos, para cada arquivo alterado entre `base` e a árvore de trabalho."""
    raiz = Path(_git("rev-parse", "--show-toplevel").strip())
    problemas = {}
    partes = _git("diff", "--no-renames", "--name-status", "-z", base).split("\0")[:-1]
    for status, caminho in zip(partes[::2], partes[1::2]):
        if status != "M":
            problemas[caminho] = ["arquivo novo ou apagado" if status in "AD" else f"estado {status}"]
            continue
        bruto_antes = subprocess.run(["git", "show", f"{base}:{caminho}"], capture_output=True, check=True).stdout
        bruto_depois = (raiz / caminho).read_bytes()
        try:
            antes, depois = bruto_antes.decode("utf-8"), bruto_depois.decode("utf-8")
        except UnicodeDecodeError:
            problemas[caminho] = ["arquivo binário ou fora de UTF-8"] if bruto_antes != bruto_depois else []
            continue
        # core.autocrlf: a árvore pode estar em CRLF e o blob em LF; aqui só o conteúdo importa.
        motivos = _conferir_arquivo(caminho, antes.replace("\r\n", "\n"), depois.replace("\r\n", "\n"))
        if motivos:
            problemas[caminho] = motivos
    for caminho in _git("ls-files", "--others", "--exclude-standard", "-z").split("\0")[:-1]:
        problemas[caminho] = ["arquivo novo"]
    return {c: m for c, m in problemas.items() if m}


def main(argv):
    if len(argv) != 2:
        print("uso: python tools/so_comentarios.py <commit-base>", file=sys.stderr)
        return 2
    problemas = conferir(argv[1])
    for caminho, motivos in sorted(problemas.items()):
        print(f"{caminho}: {'; '.join(motivos)}")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
