# instalador-online.ps1
#
# Dispara o workflow "Gerar instalador (beta)" no GitHub, acompanha até o fim,
# traz o commit "Versão AAAA.MM.DD" que ele faz no main e abre a pré-release.
# Chamado pelo build-installer.bat na raiz do projeto (opção online).

$ErrorActionPreference = 'Stop'

$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $repo

function Etapa($texto) { Write-Host "`n=== $texto ===" -ForegroundColor Cyan }
function Falha($texto) { Write-Host "`nERRO: $texto" -ForegroundColor Red; exit 1 }

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { Falha 'O GitHub CLI (gh) não está instalado.' }
if ((git branch --show-current) -ne 'main') { Falha 'O workflow roda sobre o main; mude para o branch main.' }
# O workflow compila o que está no GitHub: o que só existe aqui ficaria de fora.
git fetch -q origin main
if ($LASTEXITCODE) { Falha 'Não foi possível consultar o GitHub (git fetch).' }
if (git rev-list origin/main..main) { Falha 'Há commits locais que não estão no GitHub. Envie-os com git push antes.' }
if (git status --porcelain --untracked-files=no) { Falha 'Há alterações não commitadas; o git pull do final não seria possível.' }

Etapa 'Disparando o workflow'
$antes = gh run list --workflow instalador.yml -L 1 --json databaseId --jq '.[0].databaseId // 0'
gh workflow run instalador.yml --ref main
if ($LASTEXITCODE) { Falha 'Não foi possível disparar o workflow.' }

# O run aparece na lista alguns segundos depois do disparo.
$run = $null
for ($i = 0; $i -lt 30 -and -not $run; $i++) {
    Start-Sleep -Seconds 2
    $ultimo = gh run list --workflow instalador.yml -L 1 --json databaseId --jq '.[0].databaseId // 0'
    if ($ultimo -and $ultimo -ne $antes) { $run = $ultimo }
}
if (-not $run) { Falha 'O workflow foi disparado, mas a execução não apareceu no GitHub.' }

Etapa 'Aguardando o workflow (cerca de 1 hora)'
# Uma queda de rede derruba o watch sem que o run tenha falhado: vale o resultado do run.
do {
    gh run watch $run --interval 30
    if ($LASTEXITCODE) { Start-Sleep -Seconds 30 }
    $status = gh run view $run --json status --jq .status
} while ($status -ne 'completed')
if ((gh run view $run --json conclusion --jq .conclusion) -ne 'success') {
    gh run view $run --web
    Falha 'O workflow falhou; a página da execução foi aberta.'
}

Etapa 'Atualizando o repositório local'
git pull --ff-only origin main
if ($LASTEXITCODE) { Falha 'O git pull falhou.' }

$versao = (Select-String -Path meson.build -Pattern "^  version: '(.*)',$").Matches[0].Groups[1].Value
Etapa "Abrindo a pré-release v$versao"
gh release view "v$versao" --web
