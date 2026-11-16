# Cria o .venv do desenvolvimento (o Python de .python-version) e instala as dependências fixadas.
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$xy = ((Get-Content (Join-Path $raiz ".python-version") -TotalCount 1).Trim().Split(".") | Select-Object -First 2) -join "."
$reserva = Join-Path $env:LOCALAPPDATA "Python\pythoncore-$xy-64\python.exe"

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -$xy -m venv (Join-Path $raiz ".venv")
} elseif (Test-Path $reserva) {
    & $reserva -m venv (Join-Path $raiz ".venv")
} else {
    throw "Python $xy não encontrado (nem pelo 'py -$xy', nem em $reserva)."
}
if ($LASTEXITCODE -ne 0) { throw "Falha ao criar o .venv." }

$python = Join-Path $raiz ".venv\Scripts\python.exe"
& $python -m pip install -r (Join-Path $raiz "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar as dependências." }
