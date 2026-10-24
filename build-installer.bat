:inicio
@echo off
rem Gera o instalador do Cartridges: online pelo workflow do GitHub ou offline aqui.
rem A logica esta em build-aux\windows\instalador-online.ps1 e build-installer.ps1;
rem este arquivo existe para dar dois cliques.

title Cartridges - build do instalador
echo [1] Online: gera a pre-release pelo GitHub Actions e faz o git pull
echo [2] Offline: compila e empacota neste PC
choice /c 12 /n /m "Escolha 1 ou 2: "
rem choice devolve 0 se interrompido: so o 1 explicito dispara o workflow.
if errorlevel 2 (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-aux\windows\build-installer.ps1"
) else if errorlevel 1 (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-aux\windows\instalador-online.ps1"
)

echo Feito. Feche para finalizar ou pressione qualquer tecla para reiniciar o processo novamente.
pause
goto inicio
