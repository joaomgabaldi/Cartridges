/* cartridges.c
 *
 * Copyright 2026 joaomgabaldi
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Kyron.exe: abre o Python embutido do app (..\python\python315.dll) já
 * rodando `-m kyron`. O Python roda dentro deste processo, então é
 * "Kyron.exe" que o Windows mostra no Gerenciador de Tarefas, na barra de
 * tarefas e nas configurações de GPU, e não "pythonw.exe".
 *
 * A DLL é carregada à mão (LoadLibraryExW + GetProcAddress): o lançador não
 * depende da biblioteca de importação nem dos cabeçalhos do Python. Compilado
 * com o MSVC (/MT: nenhum runtime além do que o Windows já tem).
 */

#include <stdlib.h>
#include <wchar.h>
#include <windows.h>

typedef int (*PyMainFn)(int, wchar_t **);

static int falha(void)
{
    MessageBoxW(NULL, L"Não foi possível abrir o Kyron. Reinstale o aplicativo.",
                L"Kyron", MB_OK | MB_ICONERROR);
    return 1;
}

int WINAPI wWinMain(HINSTANCE instancia, HINSTANCE anterior, PWSTR linha, int exibir)
{
    wchar_t exe[MAX_PATH];
    wchar_t dll[MAX_PATH];
    wchar_t *barra;
    HMODULE python;
    PyMainFn py_main;
    int i;
    int argc = __argc + 2;
    wchar_t **argv = calloc(argc + 1, sizeof *argv);
    wchar_t m[] = L"-m";
    wchar_t pacote[] = L"kyron";

    DWORD n = GetModuleFileNameW(NULL, exe, MAX_PATH);
    /* A pasta atual não entra na busca de DLLs */
    SetDllDirectoryW(L"");
    if (!argv || n == 0 || n >= MAX_PATH)
        return falha();

    wcscpy_s(dll, MAX_PATH, exe);
    barra = wcsrchr(dll, L'\\');
    if (!barra || (barra - dll) + wcslen(L"\\..\\python\\python315.dll") >= MAX_PATH)
        return falha();
    wcscpy_s(barra, MAX_PATH - (barra - dll), L"\\..\\python\\python315.dll");

    /* Com o caminho alterado, o Windows procura as dependências da DLL
       (vcruntime140.dll, ...) na pasta dela. */
    python = LoadLibraryExW(dll, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!python)
        return falha();
    py_main = (PyMainFn)GetProcAddress(python, "Py_Main");
    if (!py_main)
        return falha();

    argv[0] = exe;
    argv[1] = m;
    argv[2] = pacote;
    for (i = 1; i < __argc; i++)
        argv[i + 2] = __wargv[i];
    /* Sem console: um código diferente de zero (instalação danificada, QML que não carrega) sairia em silêncio. */
    int r = py_main(argc, argv);
    return r ? falha() : 0;
}
