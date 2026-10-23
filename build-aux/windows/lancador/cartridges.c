/* cartridges.c
 *
 * Copyright 2026 joaomgabaldi
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Cartridges.exe: o mesmo que o pythonw.exe, mas já apontando para o script
 * bin\cartridges. O Python roda dentro deste processo, então é "Cartridges.exe"
 * que o Windows mostra no Gerenciador de Tarefas, na barra de tarefas e nas
 * configurações de GPU, e não "pythonw.exe".
 */

#include <stdlib.h>
#include <windows.h>

/* Declarado à mão para o lançador não depender dos cabeçalhos do Python */
int Py_Main(int argc, wchar_t **argv);

int WINAPI wWinMain(HINSTANCE instancia, HINSTANCE anterior, PWSTR linha, int exibir)
{
    wchar_t exe[MAX_PATH];
    wchar_t script[MAX_PATH];
    wchar_t *barra;
    int i;
    int argc = __argc + 1;
    wchar_t **argv = calloc(argc + 1, sizeof *argv);

    DWORD n = GetModuleFileNameW(NULL, exe, MAX_PATH);
    if (!argv || n == 0 || n >= MAX_PATH)
        return 1;

    wcscpy(script, exe);
    barra = wcsrchr(script, L'\\');
    if (!barra || (barra - script) + wcslen(L"\\cartridges") >= MAX_PATH)
        return 1;
    wcscpy(barra + 1, L"cartridges");

    argv[0] = exe;
    argv[1] = script;
    for (i = 1; i < __argc; i++)
        argv[i + 1] = __wargv[i];
    return Py_Main(argc, argv);
}
