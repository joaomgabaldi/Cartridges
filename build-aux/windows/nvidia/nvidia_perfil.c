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
 * não existe e o utilitário sai com 4. Códigos de saída em perfil.h.
 */

#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>
#include <windows.h>

#include "perfil.h"

typedef void *(*QueryInterface)(unsigned int id);

/* Quanto o instalador pode esperar pela NVAPI antes de seguir sem o ajuste */
#define PRAZO_EM_SEGUNDOS 30

static DWORD WINAPI vigiar(LPVOID prazo)
{
    Sleep((DWORD)(UINT_PTR)prazo * 1000);
    fputs("tempo esgotado esperando a NVAPI\n", stderr);
    fflush(stderr);
    ExitProcess(PERFIL_ERRO);
    return 0;
}

static int uso(void)
{
    fputs("uso: nvidia-perfil.exe aplicar|remover <caminho do Cartridges.exe>\n", stderr);
    return PERFIL_ERRO;
}

int wmain(int argc, wchar_t **argv)
{
    NvAPI_Status (*inicializar)(void) = NULL;
    NvAPI_Status (*descarregar)(void) = NULL;
    QueryInterface query = NULL;
    const wchar_t *trava;
    HMODULE dll;
    Nvapi api;
    int aplicando, r, completa;
    UINT_PTR prazo = PRAZO_EM_SEGUNDOS;

    if (argc != 3)
        return uso();
    if (wcscmp(argv[1], L"aplicar") == 0)
        aplicando = 1;
    else if (wcscmp(argv[1], L"remover") == 0)
        aplicando = 0;
    else
        return uso();

    /* Só para testar o instalador: "4" simula um PC sem placa NVIDIA; qualquer
       outro valor, a NVAPI indisponível (o plano B) */
    trava = _wgetenv(L"CARTRIDGES_NVIDIA_SIMULAR_FALHA");
    if (trava) {
        fputs("falha simulada\n", stderr);
        return _wtoi(trava) == PERFIL_SEM_PLACA ? PERFIL_SEM_PLACA : PERFIL_SEM_NVAPI;
    }
    /* Só para testar o vigia: trava de propósito, com o prazo em segundos */
    trava = _wgetenv(L"CARTRIDGES_NVIDIA_SIMULAR_TRAVA");
    if (trava)
        prazo = (UINT_PTR)_wtoi(trava);
    CloseHandle(CreateThread(NULL, 0, vigiar, (LPVOID)prazo, 0, NULL));
    if (trava)
        Sleep(INFINITE);

    /* Só do System32, onde o driver a instala: o processo roda elevado, e uma
       nvapi64.dll posta na pasta do exe seria carregada antes */
    dll = LoadLibraryExW(L"nvapi64.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (dll)
        query = (QueryInterface)(void *)GetProcAddress(dll, "nvapi_QueryInterface");

/* Cada campo recebe o ponteiro já no tipo dele (void * para ponteiro de função
   é o que o GetProcAddress e o QueryInterface entregam no Windows) */
#define BUSCAR(campo, id) (((campo) = (__typeof__(campo))query(id)) != NULL)
    completa = query
        && BUSCAR(inicializar, NVAPI_ID_INITIALIZE)
        && BUSCAR(descarregar, NVAPI_ID_UNLOAD)
        && BUSCAR(api.criar_sessao, NVAPI_ID_DRS_CREATE_SESSION)
        && BUSCAR(api.destruir_sessao, NVAPI_ID_DRS_DESTROY_SESSION)
        && BUSCAR(api.carregar, NVAPI_ID_DRS_LOAD_SETTINGS)
        && BUSCAR(api.salvar, NVAPI_ID_DRS_SAVE_SETTINGS)
        && BUSCAR(api.achar_aplicativo, NVAPI_ID_DRS_FIND_APPLICATION_BY_NAME)
        && BUSCAR(api.achar_perfil, NVAPI_ID_DRS_FIND_PROFILE_BY_NAME)
        && BUSCAR(api.criar_perfil, NVAPI_ID_DRS_CREATE_PROFILE)
        && BUSCAR(api.criar_aplicativo, NVAPI_ID_DRS_CREATE_APPLICATION)
        && BUSCAR(api.gravar, NVAPI_ID_DRS_SET_SETTING)
        && BUSCAR(api.apagar_perfil, NVAPI_ID_DRS_DELETE_PROFILE)
        && BUSCAR(api.mensagem, NVAPI_ID_GET_ERROR_MESSAGE);
#undef BUSCAR

    r = perfil_inicio(query != NULL, completa, completa ? inicializar() : NVAPI_ERROR);
    if (r == PERFIL_OK) {
        r = aplicando ? perfil_aplicar(&api, argv[2]) : perfil_remover(&api, argv[2]);
        descarregar();
    } else {
        fprintf(stderr, "NVAPI indisponivel (codigo %d)\n", r);
    }
    if (dll)
        FreeLibrary(dll);
    return r;
}
