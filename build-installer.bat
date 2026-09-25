:inicio
@echo off
rem Compila o Cartridges, empacota com o Inno Setup e abre o instalador.
rem A logica esta em build-aux\windows\build-installer.ps1; este arquivo existe
rem para dar dois cliques.

title Cartridges - build do instalador
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-aux\windows\build-installer.ps1"

echo Feito. Feche para finalizar ou pressione qualquer tecla para reiniciar o processo novamente.
pause
goto inicio