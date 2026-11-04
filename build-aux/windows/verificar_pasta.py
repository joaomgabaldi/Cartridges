# verificar_pasta.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Roda a pasta montada sozinha, antes de ela virar instalador: se faltar algo, o build para aqui.

Importa o app inteiro e o que ele carrega tarde, com o PATH só do Windows, e converte um vídeo em capa pelo
`ffmpeg.exe` montado, que é a prova do `libwebp_anim` do build. Com dados e registro temporários. A pasta do canal
final só roda na CI: fora dela, esses dados seriam a última proteção dos dados reais.

Uso: <pasta>\\python\\python.exe -B verificar_pasta.py <pasta>
"""

import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

destino = Path(sys.argv[1]).resolve()
canal = json.loads((destino / "app" / "cartridges" / "instalacao.json").read_text(encoding="utf-8"))["canal"]
if canal == "final" and os.environ.get("GITHUB_ACTIONS") != "true":
    sys.exit("A pasta do canal final só roda na CI.")
assert Path(sys.prefix).samefile(destino / "python"), f"o Python veio de {sys.prefix}"

temporaria = Path(tempfile.mkdtemp(prefix="verificar-pasta-"))
os.environ["CARTRIDGES_DADOS"] = str(temporaria / "dados")
os.environ["CARTRIDGES_REGISTRO"] = "Software\\CartridgesVerificacao"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
# Nada de fora da pasta: nem outro Python, nem outro ffmpeg, nem DLL do runner.
os.environ["PATH"] = str(Path(os.environ["SystemRoot"], "System32"))
# No app instalado o `sys.executable` é o lançador: `capa_video` e `ludusavi` procuram ao lado dele.
sys.executable = str(destino / "bin" / "Cartridges.exe")

import certifi  # noqa: E402
import PySide6.QtQuick  # noqa: E402, F401
import requests  # noqa: E402
import ssl  # noqa: E402
import tinytuya  # noqa: E402
from PIL import Image  # noqa: E402

ssl.create_default_context(cafile=certifi.where())
requests.Session().close()
assert tinytuya.AESCipher.CRYPTOLIB == "pyca/cryptography", tinytuya.AESCipher.CRYPTOLIB

import cartridges.app  # noqa: E402, F401 (instala o `_` nos builtins, como no app)

pacote = destino / "app" / "cartridges"
# Todo .py, não `pkgutil.walk_packages`: ele pula as pastas sem `__init__.py`.
for fonte in pacote.rglob("*.py"):
    partes = fonte.relative_to(pacote.parent).with_suffix("").parts
    if partes[-1] == "__main__":  # roda o app
        continue
    importlib.import_module(".".join(partes[:-1] if partes[-1] == "__init__" else partes))

from cartridges import shared  # noqa: E402
from cartridges.saves import ludusavi  # noqa: E402
from cartridges.utils import capa_video  # noqa: E402

assert Path(shared.__file__).is_relative_to(destino), shared.__file__
assert ludusavi.executavel() == destino / "bin" / "ludusavi.exe", ludusavi.executavel()
assert ludusavi.executavel().stat().st_size > 0, "ludusavi.exe vazio"
ffmpeg = capa_video.executavel()
assert ffmpeg == destino / "bin" / "ffmpeg.exe", ffmpeg
codificadores = subprocess.run(
    [str(ffmpeg), "-hide_banner", "-encoders"], capture_output=True, text=True, errors="replace", check=True
).stdout
assert "libwebp_anim" in codificadores, "o ffmpeg montado não tem o libwebp_anim"

video = temporaria / "teste.mp4"
subprocess.run(
    [str(ffmpeg), "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10", "-t", "1",
     "-c:v", "mpeg4", str(video)],
    check=True,
)  # fmt: skip
capa = capa_video.converter(video)
with Image.open(capa) as imagem:
    assert imagem.is_animated and imagem.size == shared.image_size, (imagem.size, imagem.n_frames)
capa.unlink()
print("ok")
