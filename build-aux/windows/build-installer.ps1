# build-installer.ps1
#
# Compila o app, empacota com o Inno Setup e abre o instalador (fora da CI).
# Chamado pelo build-installer.bat na raiz do projeto (dois cliques).

$ErrorActionPreference = 'Stop'

$repo    = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$patches = Join-Path $PSScriptRoot 'gtk-patches'
$msys    = 'C:\msys64'
$prefix  = Join-Path $msys 'ucrt64'
# Inno Setup 7 no PC, 6 na CI (o que o runner traz ou o choco instala).
$iscc    = @(
    (Join-Path ${env:ProgramFiles} 'Inno Setup 7\ISCC.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
$dist    = Join-Path $repo '_dist'

function Etapa($texto) { Write-Host "`n=== $texto ===" -ForegroundColor Cyan }
function Falha($texto) { Write-Host "`nERRO: $texto" -ForegroundColor Red; exit 1 }

# ── 1. A libgtk corrigida ─────────────────────────────────────────────────
#
# A pasta do app é montada a partir de C:\msys64\ucrt64\bin, então ela leva
# junto a libgtk que estiver instalada ali. Se um `pacman -Syu` sobrescrever a
# build corrigida, o instalador sai com o bug do monitor de volta — e sem
# nenhum aviso, porque tudo compila e empacota normalmente. Daí esta checagem.
# O pacote corrigido sai do workflow "Compilar GTK corrigido" (gtk-patches\README.md).

Etapa 'Conferindo a libgtk corrigida'

$estado = Join-Path $patches 'patched-gtk.txt'
$dll    = Join-Path $prefix 'bin\libgtk-4-1.dll'

if (-not (Test-Path $estado)) {
    Falha "Falta $estado. Sem ele não dá para saber se a libgtk instalada tem a correção."
}

$esperado = @{}
Get-Content $estado | ForEach-Object {
    if ($_ -match '^\s*(\w+)\s*=\s*(.+)$') { $esperado[$Matches[1]] = $Matches[2].Trim() }
}

$versaoAtual = ((& (Join-Path $msys 'usr\bin\pacman.exe') -Q mingw-w64-ucrt-x86_64-gtk4 2>$null) -replace '^\S+\s+','').Trim()
$pacote = "mingw-w64-ucrt-x86_64-gtk4-$($esperado['gtk4_package_version'])-any.pkg.tar.zst"
$link   = "https://github.com/joaomgabaldi/Cartridges/releases/download/gtk-corrigido/$pacote"

if ($versaoAtual -ne $esperado['gtk4_package_version']) {
    Falha @"
O pacote gtk4 instalado é $versaoAtual, mas a trava está em $($esperado['gtk4_package_version']).

Para passar a usar a versão nova: execute o workflow "Compilar GTK corrigido" no
GitHub, instale o pacote gerado neste PC, teste, e atualize patched-gtk.txt com
as duas linhas mostradas no resumo do workflow.
Passo a passo em $patches\README.md
"@
}

if ((Get-FileHash $dll -Algorithm SHA256).Hash -ne $esperado['libgtk_sha256']) {
    Falha @"
A libgtk instalada não é a corrigida (o pacman provavelmente reinstalou a oficial).
Instale a corrigida no terminal UCRT64 do MSYS2:
  curl -fLO $link && pacman -U --noconfirm $pacote
"@
}

Write-Host "OK - gtk4 $versaoAtual com a correcao aplicada." -ForegroundColor Green

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

# ── 4. Incluir o Ludusavi ─────────────────────────────────────────────────
#
# O backup dos saves chama o ludusavi.exe que fica em bin\, ao lado do Python.
# Vai depois da montagem porque o montar_app.py apaga a pasta do app a cada
# execucao; os zips ficam em _build\ludusavi e so sao baixados uma vez.

Etapa 'Incluindo o Ludusavi'

$ludusaviVersao = 'v0.31.0'
$ludusaviBase   = "https://github.com/mtkennerly/ludusavi/releases/download/$ludusaviVersao"
$ludusaviZips   = @{
    "ludusavi-$ludusaviVersao-win64.zip" = 'f47a8ad8c708f01d2eb124704973beffab205e292f5287a10fc4a101f8d68706'
    "ludusavi-$ludusaviVersao-legal.zip" = '9fce11fc44942efdd5969928d89b106c229f9a041d7a713c424a6da981660ebf'
}
$cache = Join-Path $repo '_build\ludusavi'
$app   = Join-Path $repo '_build\app'
New-Item -ItemType Directory -Force $cache | Out-Null

foreach ($nome in $ludusaviZips.Keys) {
    $zip = Join-Path $cache $nome
    if (-not (Test-Path $zip)) {
        & curl.exe -fsSL -o $zip "$ludusaviBase/$nome"
        if ($LASTEXITCODE -ne 0) { Remove-Item $zip -ErrorAction SilentlyContinue; Falha "Nao consegui baixar $nome." }
    }
    if ((Get-FileHash $zip -Algorithm SHA256).Hash -ne $ludusaviZips[$nome]) {
        Remove-Item $zip
        Falha "O SHA-256 de $nome nao confere com o esperado. O arquivo foi apagado do cache."
    }
}

Expand-Archive (Join-Path $cache "ludusavi-$ludusaviVersao-win64.zip") (Join-Path $app 'bin') -Force
$licencas = Join-Path $app 'share\licenses\ludusavi'
New-Item -ItemType Directory -Force $licencas | Out-Null
Expand-Archive (Join-Path $cache "ludusavi-$ludusaviVersao-legal.zip") $licencas -Force

if (-not (Test-Path (Join-Path $app 'bin\ludusavi.exe'))) { Falha 'O zip do Ludusavi nao trouxe o ludusavi.exe.' }
Write-Host "OK - Ludusavi $ludusaviVersao em bin\." -ForegroundColor Green

# ── 5. Empacotar ──────────────────────────────────────────────────────────
#
# Tem que ser o .iss do diretorio de build, nao o instalado no prefixo: os
# caminhos relativos dele (..\..\..\LICENSE) so fecham a partir dali.

Etapa 'Empacotando com o Inno Setup'

$iss = Join-Path $repo '_build\build-aux\windows\Cartridges.iss'
if (-not (Test-Path $iss)) { Falha "Nao achei $iss. O meson gerou o build?" }
if (-not $iscc) { Falha 'Nao achei o ISCC do Inno Setup 7 nem do 6.' }

& $iscc "/O$dist" $iss | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { Falha 'O Inno Setup falhou.' }

# ── 6. Abrir ──────────────────────────────────────────────────────────────

$exe = Join-Path $dist 'Cartridges Windows.exe'
if (-not (Test-Path $exe)) { Falha "O instalador nao apareceu em $exe." }

$info = Get-Item $exe
Etapa 'Pronto'
Write-Host ("  {0}" -f $info.FullName)
Write-Host ("  {0} MB - versao {1}" -f [math]::Round($info.Length/1MB,1), $info.VersionInfo.ProductVersion.Trim())

# Na CI (o GitHub define CI=true) não há quem instale.
if (-not $env:CI) { Start-Process $exe }
