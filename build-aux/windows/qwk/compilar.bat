@echo off
rem Compila o QWindowKit (estatico, so Core + Quick) e a qwk_ponte.dll.
rem Precisa de _deps\qt (SDK do Qt MSVC 2022, o mesmo do PySide6) e
rem _deps\qwindowkit (com o submodulo qmsetup), ambos de tools\baixar_qt_sdk.py.
setlocal
set AQUI=%~dp0
set DEPS=%AQUI%_deps
rem VS 2022 e o conjunto MSVC que o proprio SDK do Qt declara (_deps\qt\.vcvars_ver, gravado por
rem baixar_qt_sdk.py): um mais novo poderia exigir um runtime mais novo que o msvcp140 que o PySide6 traz.
if not exist "%DEPS%\qt\.vcvars_ver" (echo Falta _deps\qt\.vcvars_ver: rode tools\baixar_qt_sdk.py antes. & exit /b 1)
set VCVER=
set /p VCVER=<"%DEPS%\qt\.vcvars_ver"
if not defined VCVER (echo Arquivo _deps\qt\.vcvars_ver vazio: rode tools\baixar_qt_sdk.py. & exit /b 1)
for /f "usebackq delims=" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -version [17^,18^) -property installationPath`) do set VS=%%i
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" -vcvars_ver=%VCVER% >nul || (echo Falta o conjunto MSVC %VCVER%: instale-o pelo Visual Studio Installer. & exit /b 1)
where cmake >nul 2>&1 || (echo Falta o CMake: instale o componente "Ferramentas do CMake do C++" das Ferramentas de Build do Visual Studio 2022. & exit /b 1)
where ninja >nul 2>&1 || (echo Falta o Ninja: instale o componente "Ferramentas do CMake do C++" das Ferramentas de Build do Visual Studio 2022. & exit /b 1)

cmake -S "%DEPS%\qwindowkit" -B "%DEPS%\build-qwk" -G Ninja -DCMAKE_BUILD_TYPE=Release ^
  -DCMAKE_PREFIX_PATH="%DEPS%\qt" -DCMAKE_INSTALL_PREFIX="%DEPS%\qwk" ^
  -DQWINDOWKIT_BUILD_STATIC=ON -DQWINDOWKIT_BUILD_WIDGETS=OFF -DQWINDOWKIT_BUILD_QUICK=ON || exit /b 1
cmake --build "%DEPS%\build-qwk" --target install || exit /b 1

cmake -S "%AQUI%." -B "%DEPS%\build-ponte" -G Ninja -DCMAKE_BUILD_TYPE=Release ^
  -DCMAKE_PREFIX_PATH="%DEPS%\qt;%DEPS%\qwk" -DCMAKE_INSTALL_PREFIX="%AQUI%..\..\..\kyron\janela" || exit /b 1
cmake --build "%DEPS%\build-ponte" --target install || exit /b 1
