# Cria o .venv do desenvolvimento (Python 3.15) e instala as dependências fixadas.
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$reserva = Join-Path $env:LOCALAPPDATA "Python\pythoncore-3.15-64\python.exe"

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.15 -m venv (Join-Path $raiz ".venv")
} elseif (Test-Path $reserva) {
    & $reserva -m venv (Join-Path $raiz ".venv")
} else {
    throw "Python 3.15 não encontrado (nem pelo 'py -3.15', nem em $reserva)."
}
if ($LASTEXITCODE -ne 0) { throw "Falha ao criar o .venv." }

$python = Join-Path $raiz ".venv\Scripts\python.exe"
& $python -m pip install -r (Join-Path $raiz "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as dependências." }
