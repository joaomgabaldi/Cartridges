# build-installer.ps1
#
# Monta o app no canal final e empacota com o Inno Setup, fora da CI (teste rápido).
# Chamado pelo build-installer.bat na raiz do projeto (dois cliques).
# Não abre nada no fim: a pasta montada e o instalador usam os dados reais.

$ErrorActionPreference = 'Stop'

$repo   = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$python = Join-Path $repo '.venv\Scripts\python.exe'
# Inno Setup 7 no PC e na CI: o 6 compila o [Code] de outro jeito.
$iscc   = Join-Path ${env:ProgramFiles} 'Inno Setup 7\ISCC.exe'
$dist   = Join-Path $repo '_dist'
$pasta  = Join-Path $dist 'qt-final'

function Etapa($texto) { Write-Host "`n=== $texto ===" -ForegroundColor Cyan }
function Falha($texto) { Write-Host "`nERRO: $texto" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $python)) { Falha "Não achei $python." }
if (-not (Test-Path $iscc)) { Falha 'Não achei o ISCC do Inno Setup 7 (o 6 não serve).' }

Etapa 'Montando a pasta do app'
& $python (Join-Path $PSScriptRoot 'montar_app_qt.py') --canal final --destino $pasta
if ($LASTEXITCODE -ne 0) { Falha 'A montagem da pasta do app falhou. Veja a saída acima.' }

Etapa 'Empacotando com o Inno Setup'
& $iscc "/DRepo=$repo" "/DPastaApp=$pasta" "/O$dist\instalador" "$pasta.iss" | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { Falha 'O Inno Setup falhou.' }

$exe = Join-Path $dist 'instalador\Kyron Windows.exe'
if (-not (Test-Path $exe)) { Falha "O instalador não apareceu em $exe." }

$info = Get-Item $exe
Etapa 'Pronto'
Write-Host ("  {0}" -f $info.FullName)
Write-Host ("  {0} MB - versão {1}" -f [math]::Round($info.Length/1MB,1), $info.VersionInfo.ProductVersion.Trim())
