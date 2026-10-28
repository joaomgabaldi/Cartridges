@echo off
rem Compila o QWindowKit 1.5.0 (estatico, so Core + Quick) e a qwk_ponte.dll.
rem Precisa de _deps\qt (SDK do Qt 6.12.0 MSVC 2022, o mesmo do PySide6) e
rem _deps\qwindowkit (tag 1.5.0 com o submodulo qmsetup).
setlocal
set AQUI=%~dp0
set DEPS=%AQUI%_deps
rem VS 2022 e o conjunto 14.44, o mesmo do Qt 6.12.0 (MSVC 19.44): um mais novo
rem poderia exigir um runtime mais novo que o msvcp140 que o PySide6 traz.
for /f "usebackq delims=" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -version [17^,18^) -property installationPath`) do set VS=%%i
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" -vcvars_ver=14.44 >nul || exit /b 1

cmake -S "%DEPS%\qwindowkit" -B "%DEPS%\build-qwk" -G Ninja -DCMAKE_BUILD_TYPE=Release ^
  -DCMAKE_PREFIX_PATH="%DEPS%\qt" -DCMAKE_INSTALL_PREFIX="%DEPS%\qwk" ^
  -DQWINDOWKIT_BUILD_STATIC=ON -DQWINDOWKIT_BUILD_WIDGETS=OFF -DQWINDOWKIT_BUILD_QUICK=ON || exit /b 1
cmake --build "%DEPS%\build-qwk" --target install || exit /b 1

cmake -S "%AQUI%." -B "%DEPS%\build-ponte" -G Ninja -DCMAKE_BUILD_TYPE=Release ^
  -DCMAKE_PREFIX_PATH="%DEPS%\qt;%DEPS%\qwk" -DCMAKE_INSTALL_PREFIX="%AQUI%..\..\..\cartridges\janela" || exit /b 1
cmake --build "%DEPS%\build-ponte" --target install || exit /b 1
