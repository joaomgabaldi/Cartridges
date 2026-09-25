# build-installer.ps1
#
# Compila o app, empacota com o Inno Setup e abre o instalador.
# Chamado pelo build-installer.bat na raiz do projeto (dois cliques).

$ErrorActionPreference = 'Stop'

$repo    = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$patches = Join-Path $PSScriptRoot 'gtk-patches'
$msys    = 'C:\msys64'
$prefix  = Join-Path $msys 'ucrt64'
$iscc    = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
$dist    = Join-Path $repo '_dist'

function Etapa($texto) { Write-Host "`n=== $texto ===" -ForegroundColor Cyan }
function Falha($texto) { Write-Host "`nERRO: $texto" -ForegroundColor Red; exit 1 }

# ── 1. A libgtk corrigida ─────────────────────────────────────────────────
#
# A pasta do app é montada a partir de C:\msys64\ucrt64\bin, então ela leva
# junto a libgtk que estiver instalada ali. Se um `pacman -Syu` sobrescrever a nossa
# build corrigida, o instalador sai com o bug do monitor de volta — e sem
# nenhum aviso, porque tudo compila e empacota normalmente. Daí esta checagem.

Etapa 'Conferindo a libgtk corrigida'

$estado = Join-Path $patches 'patched-gtk.txt'
$backup = Join-Path $patches 'libgtk-4-1.dll'
$dll    = Join-Path $prefix 'bin\libgtk-4-1.dll'

if (-not (Test-Path $estado) -or -not (Test-Path $backup)) {
    Falha "Faltam $estado ou $backup. Sem eles não dá para saber se a libgtk instalada tem a correção."
}

$esperado = @{}
Get-Content $estado | Where-Object { $_ -match '^\s*(\w+)\s*=\s*(.+)$' } | ForEach-Object {
    if ($_ -match '^\s*(\w+)\s*=\s*(.+)$') { $esperado[$Matches[1]] = $Matches[2].Trim() }
}

$versaoAtual = ((& (Join-Path $msys 'usr\bin\pacman.exe') -Q mingw-w64-ucrt-x86_64-gtk4 2>$null) -replace '^\S+\s+','').Trim()

if ($versaoAtual -ne $esperado['gtk4_package_version']) {
    # Restaurar aqui seria pior que o bug: uma libgtk de outra versão junto do
    # resto do GTK atualizado quebra de formas bem menos óbvias que um recorte
    # de desenho.
    Falha @"
O pacote gtk4 mudou de $($esperado['gtk4_package_version']) para $versaoAtual.
A libgtk guardada em gtk-patches é da versão antiga e NÃO pode ser usada com esta.

O patch precisa ser refeito contra a versão nova:
  cd ~/gtk-build && git fetch --depth 1 origin <tag da versao nova> && git checkout FETCH_HEAD
  git apply $patches\gtk-dcomp-render-window-origin.patch
  ninja -C _build gtk/libgtk-4-1.dll && cp _build/gtk/libgtk-4-1.dll /ucrt64/bin/

Depois atualize a trava a mao: copie a DLL nova para gtk-patches\libgtk-4-1.dll
e troque versao e SHA256 em gtk-patches\patched-gtk.txt.
Contexto completo em gtk-patches\ISSUE.md
"@
}

$hashAtual = (Get-FileHash $dll -Algorithm SHA256).Hash

if ($hashAtual -ne $esperado['libgtk_sha256']) {
    # Mesma versão de pacote, DLL diferente: o pacman reinstalou por cima.
    # Aqui restaurar é seguro, porque a ABI é a mesma.
    Write-Host "A libgtk instalada foi sobrescrita (mesma versao do pacote). Restaurando a corrigida..." -ForegroundColor Yellow
    Copy-Item $backup $dll -Force
    $hashAtual = (Get-FileHash $dll -Algorithm SHA256).Hash
    if ($hashAtual -ne $esperado['libgtk_sha256']) { Falha 'A restauracao nao bateu com o hash esperado.' }
    Write-Host 'Restaurada.' -ForegroundColor Green
} else {
    Write-Host "OK - gtk4 $versaoAtual com a correcao aplicada." -ForegroundColor Green
}

# ── 2. Compilar e instalar no prefixo ─────────────────────────────────────

Etapa 'Compilando (ninja + meson install)'

# O pacote do app no prefixo e apagado antes do install: o meson install nunca
# remove modulo que saiu do repositorio, e o curinga do .iss o empacotaria.
#
# C:\Users\... -> /c/Users/...
$repoMsys = '/' + $repo.Substring(0,1).ToLower() + ($repo.Substring(2) -replace '\\','/')
$env:MSYSTEM = 'UCRT64'
$env:CHERE_INVOKING = '1'
# blueprint-compiler le os .blp na codificacao do locale; sem isto o Python do
# MSYS2 usa cp1252 dentro do bash -lc e um caractere acentuado (ex.: "Índia")
# derruba o ninja com UnicodeDecodeError.
$env:PYTHONUTF8 = '1'

& (Join-Path $msys 'usr\bin\bash.exe') -lc "cd '$repoMsys' && ninja -C _build && rm -rf /ucrt64/lib/python3*/site-packages/cartridges && meson install -C _build --quiet"
if ($LASTEXITCODE -ne 0) { Falha 'O build falhou. Veja a saida acima.' }

# ── 3. Montar a pasta do app ──────────────────────────────────────────────
#
# Só o que o app usa vai para _build\app, e é essa pasta que o Inno Setup
# empacota. O script confere no fim que ela roda sem enxergar o MSYS2.

Etapa 'Montando a pasta do app'

& (Join-Path $prefix 'bin\python.exe') (Join-Path $PSScriptRoot 'montar_app.py') $prefix (Join-Path $repo '_build\app')
if ($LASTEXITCODE -ne 0) { Falha 'A montagem da pasta do app falhou. Veja a saida acima.' }

# ── 4. Empacotar ──────────────────────────────────────────────────────────
#
# Tem que ser o .iss do diretorio de build, nao o instalado no prefixo: os
# caminhos relativos dele (..\..\..\LICENSE) so fecham a partir dali.

Etapa 'Empacotando com o Inno Setup'

$iss = Join-Path $repo '_build\build-aux\windows\Cartridges.iss'
if (-not (Test-Path $iss)) { Falha "Nao achei $iss. O meson gerou o build?" }
if (-not (Test-Path $iscc)) { Falha "Nao achei o ISCC em $iscc." }

& $iscc "/O$dist" $iss | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { Falha 'O Inno Setup falhou.' }

# ── 5. Abrir ──────────────────────────────────────────────────────────────

$exe = Join-Path $dist 'Cartridges Windows.exe'
if (-not (Test-Path $exe)) { Falha "O instalador nao apareceu em $exe." }

$info = Get-Item $exe
Etapa 'Pronto'
Write-Host ("  {0}" -f $info.FullName)
Write-Host ("  {0} MB - versao {1}" -f [math]::Round($info.Length/1MB,1), $info.VersionInfo.ProductVersion.Trim())

Start-Process $exe
