# build-installer.ps1
#
# Monta o app no canal final e empacota com o Inno Setup, fora da CI (teste rápido).
# Chamado pelo build-installer.bat na raiz do projeto (dois cliques).
# No fim, abre o instalador gerado (ele usa os dados reais).

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

Etapa 'Atualizando versões'
New-Item -ItemType Directory -Force $dist | Out-Null
$jsonVersoes = Join-Path $dist 'versoes.json'
& $python (Join-Path $PSScriptRoot 'atualizar_versoes.py') --json $jsonVersoes
if ($LASTEXITCODE -ne 0) { Falha 'A atualização das versões falhou. Veja a saída acima.' }
$resumo = Get-Content $jsonVersoes -Raw -Encoding UTF8 | ConvertFrom-Json
$trocas = @($resumo.trocas)
function Trocou($peca) { return [bool]($trocas | Where-Object { $_.peca -eq $peca }) }

$dll = Join-Path $repo 'kyron\janela\qwk_ponte.dll'
$pythonNovo = $trocas | Where-Object { $_.peca -eq 'python' } | Select-Object -First 1
if ($pythonNovo) {
    $xyAntes = ($pythonNovo.de -split '\.' | Select-Object -First 2) -join '.'
    $xyDepois = ($pythonNovo.para -split '\.' | Select-Object -First 2) -join '.'
}
if ($pythonNovo -and $xyAntes -ne $xyDepois) {
    Etapa "Python ${xyDepois}: recriando o ambiente"
    & cmd /c "py -V:PythonCore/$xyDepois -c pass >nul 2>nul"
    if ($LASTEXITCODE -ne 0) {
        & py install -y $xyDepois
        if ($LASTEXITCODE -ne 0) { Falha "Não foi possível instalar o Python $xyDepois." }
    }
    Remove-Item -Recurse -Force (Join-Path $repo '.venv')
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo 'tools\ambiente_qt.ps1')
    if ($LASTEXITCODE -ne 0) { Falha 'Não foi possível recriar o ambiente de desenvolvimento. Rode tools\ambiente_qt.ps1 à mão para recriar o .venv.' }
} else {
    Etapa 'Instalando as bibliotecas de desenvolvimento'
    & $python -m pip install --require-hashes -r (Join-Path $repo 'requirements-dev.txt')
    if ($LASTEXITCODE -ne 0) { Falha 'A instalação das bibliotecas falhou. Veja a saída acima.' }
}

if ((Trocou 'pyside6') -or (Trocou 'qt-sdk') -or (Trocou 'qwindowkit') -or -not (Test-Path $dll)) {
    Etapa 'Compilando a qwk_ponte.dll'
    & $python (Join-Path $repo 'tools\baixar_qt_sdk.py')
    if ($LASTEXITCODE -ne 0) { Falha 'O download do SDK do Qt falhou. Veja a saída acima.' }
    & cmd /c (Join-Path $repo 'build-aux\windows\qwk\compilar.bat')
    if ($LASTEXITCODE -ne 0) { Falha 'A compilação da qwk_ponte.dll falhou. Veja a saída acima.' }
}

$fixado = [regex]::Match((Get-Content (Join-Path $PSScriptRoot 'instalar_inno.ps1') -Raw), "\`$InnoVersao\s*=\s*'([^']+)'").Groups[1].Value
$instalado = foreach ($raiz in 'HKLM:\SOFTWARE', 'HKLM:\SOFTWARE\WOW6432Node', 'HKCU:\SOFTWARE') {
    $v = (Get-ItemProperty "$raiz\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 7_is1" -ErrorAction SilentlyContinue).DisplayVersion
    if ($v) { $v; break }
}
if ($instalado -and $fixado -and $instalado -ne $fixado) {
    Write-Host "O Inno Setup instalado ($instalado) é diferente do fixado ($fixado). O build local segue com o instalado." -ForegroundColor Yellow
}

Etapa 'Rodando a suíte'
& $python -m pytest -n auto -q
if ($LASTEXITCODE -ne 0) { Falha 'A suíte falhou com as versões novas. Nada foi montado.' }

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
if ($trocas.Count -gt 0) {
    Write-Host "  $($resumo.linha)"
    Write-Host '  As versões novas estão no working tree, sem commit.'
}
Start-Process $exe
