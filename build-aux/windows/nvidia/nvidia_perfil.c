/* nvidia_perfil.c
 *
 * Copyright 2026 joaomgabaldi
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * nvidia-perfil.exe aplicar|remover "<caminho do Cartridges.exe>"
 *
 * Chamado pelo instalador (elevado) depois de instalar e antes de desinstalar.
 * Carrega a nvapi64.dll do driver em tempo de execução: num PC sem NVIDIA ela
 * não existe e o utilitário sai com 1. Códigos de saída em perfil.h.
 */

#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>
#include <windows.h>

#include "perfil.h"

typedef void *(*QueryInterface)(unsigned int id);

static int uso(void)
{
    fputs("uso: nvidia-perfil.exe aplicar|remover <caminho do Cartridges.exe>\n", stderr);
    return PERFIL_ERRO;
}

int wmain(int argc, wchar_t **argv)
{
    NvAPI_Status (*inicializar)(void);
    NvAPI_Status (*descarregar)(void);
    QueryInterface query;
    HMODULE dll;
    Nvapi api;
    int aplicando, r;
    void **campo;
    unsigned i;
    /* Na ordem dos campos de Nvapi */
    static const unsigned ids[] = {
        NVAPI_ID_DRS_CREATE_SESSION, NVAPI_ID_DRS_DESTROY_SESSION, NVAPI_ID_DRS_LOAD_SETTINGS,
        NVAPI_ID_DRS_SAVE_SETTINGS, NVAPI_ID_DRS_FIND_APPLICATION_BY_NAME,
        NVAPI_ID_DRS_FIND_PROFILE_BY_NAME, NVAPI_ID_DRS_CREATE_PROFILE,
        NVAPI_ID_DRS_CREATE_APPLICATION, NVAPI_ID_DRS_SET_SETTING, NVAPI_ID_DRS_DELETE_PROFILE,
        NVAPI_ID_GET_ERROR_MESSAGE,
    };
    _Static_assert(sizeof ids / sizeof ids[0] == sizeof(Nvapi) / sizeof(void *), "ids de Nvapi");

    if (argc != 3)
        return uso();
    if (wcscmp(argv[1], L"aplicar") == 0)
        aplicando = 1;
    else if (wcscmp(argv[1], L"remover") == 0)
        aplicando = 0;
    else
        return uso();

    /* Só para testar o plano B do instalador */
    if (_wgetenv(L"CARTRIDGES_NVIDIA_SIMULAR_FALHA")) {
        fputs("falha simulada\n", stderr);
        return PERFIL_SEM_NVAPI;
    }

    dll = LoadLibraryW(L"nvapi64.dll");
    query = dll ? (QueryInterface)(void *)GetProcAddress(dll, "nvapi_QueryInterface") : NULL;
    if (!query) {
        fputs("nvapi64.dll ausente\n", stderr);
        if (dll)
            FreeLibrary(dll);
        return PERFIL_SEM_NVAPI;
    }
    inicializar = (NvAPI_Status(*)(void))query(NVAPI_ID_INITIALIZE);
    descarregar = (NvAPI_Status(*)(void))query(NVAPI_ID_UNLOAD);
    campo = (void **)&api;
    for (i = 0; i < sizeof ids / sizeof ids[0]; i++)
        campo[i] = query(ids[i]);
    for (i = 0; i < sizeof ids / sizeof ids[0] && campo[i]; i++)
        ;
    if (!inicializar || !descarregar || i < sizeof ids / sizeof ids[0]) {
        fputs("o driver nao tem as funcoes da NVAPI DRS\n", stderr);
        FreeLibrary(dll);
        return PERFIL_SEM_NVAPI;
    }
    if (inicializar() != NVAPI_OK) {
        fputs("NvAPI_Initialize falhou\n", stderr);
        FreeLibrary(dll);
        return PERFIL_SEM_NVAPI;
    }

    r = aplicando ? perfil_aplicar(&api, argv[2]) : perfil_remover(&api, argv[2]);
    descarregar();
    FreeLibrary(dll);
    return r;
}
