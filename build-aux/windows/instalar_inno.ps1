# Instala o Inno Setup 7 no runner da CI. A mesma versão do PC do desenvolvedor: o Inno 6 que o runner traz
# compila o [Code] de outro jeito (recusa Variant onde o 7 aceita). O choco ainda não tem o 7; o instalador
# vem das releases oficiais, com o SHA-256 fixo.
# A versão e o SHA-256 abaixo são reescritos por build-aux/windows/atualizar_versoes.py.
$ErrorActionPreference = 'Stop'
$InnoVersao = '7.1.0'
$InnoSha256 = '0362A383ED217D4C4239B5933866DD96D3EB2102737DA92F80F6057A4B40DF2F'

$url = "https://github.com/jrsoftware/issrc/releases/download/is-$($InnoVersao.Replace('.', '_'))/innosetup-$InnoVersao-x64.exe"
$exe = Join-Path $env:RUNNER_TEMP 'innosetup.exe'
curl.exe -fsSL -o $exe $url
if ($LASTEXITCODE -ne 0) { throw 'Não consegui baixar o instalador do Inno Setup 7.' }
if ((Get-FileHash $exe -Algorithm SHA256).Hash -ne $InnoSha256) {
  throw 'O SHA-256 do instalador do Inno Setup 7 não confere.'
}
Start-Process $exe -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/ALLUSERS' -Wait
if (-not (Test-Path "$env:ProgramFiles\Inno Setup 7\ISCC.exe")) { throw 'O Inno Setup 7 não foi instalado.' }
