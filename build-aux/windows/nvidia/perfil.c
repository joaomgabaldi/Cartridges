/* perfil.c
 *
 * Copyright 2026 joaomgabaldi
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include <stdio.h>
#include <string.h>

#include "perfil.h"

#define NOME_DO_PERFIL L"Cartridges"

/* Por NvU16, não por wchar_t: o limite vale mesmo onde wchar_t tem 4 bytes */
static void copiar(NvAPI_UnicodeString destino, const wchar_t *origem)
{
    size_t i = 0;
    for (; i < NVAPI_UNICODE_STRING_MAX - 1 && origem[i]; i++)
        destino[i] = (NvU16)origem[i];
    memset(destino + i, 0, (NVAPI_UNICODE_STRING_MAX - i) * sizeof *destino);
}

static int falhou(const Nvapi *api, const char *etapa, NvAPI_Status st)
{
    NvAPI_ShortString texto = "";
    if (api->mensagem(st, texto) != NVAPI_OK)
        snprintf(texto, sizeof texto, "status %d", st);
    fprintf(stderr, "%s: %s\n", etapa, texto);
    return PERFIL_ERRO;
}

/* O perfil "Cartridges", ou NULL se ele não existe. PERFIL_OK ou PERFIL_ERRO. */
static int achar_o_nosso(const Nvapi *api, NvDRSSessionHandle sessao, NvDRSProfileHandle *perfil)
{
    NvAPI_UnicodeString nome;
    NvAPI_Status st;

    copiar(nome, NOME_DO_PERFIL);
    *perfil = NULL;
    st = api->achar_perfil(sessao, nome, perfil);
    if (st == NVAPI_PROFILE_NOT_FOUND) {
        *perfil = NULL;
        return PERFIL_OK;
    }
    return st == NVAPI_OK ? PERFIL_OK : falhou(api, "FindProfileByName", st);
}

static int aplicar(const Nvapi *api, NvDRSSessionHandle sessao, const wchar_t *exe)
{
    NvDRSProfileHandle nosso, do_exe = NULL;
    NvAPI_UnicodeString nome;
    NVDRS_APPLICATION_V4 app;
    NVDRS_SETTING_V1 config;
    NvAPI_Status st;
    int r;

    if ((r = achar_o_nosso(api, sessao, &nosso)) != PERFIL_OK)
        return r;

    memset(&app, 0, sizeof app);
    app.version = NVDRS_APPLICATION_VER;
    copiar(nome, exe);
    st = api->achar_aplicativo(sessao, nome, &do_exe, &app);
    if (st == NVAPI_OK && do_exe != nosso) {
        /* Mexer nele mudaria os outros programas daquele perfil */
        /* Em ASCII: o console do Windows não mostra o UTF-8 do fwprintf */
        fwprintf(stderr, L"%ls: o exe esta em outro perfil\n", exe);
        return PERFIL_DE_TERCEIROS;
    }
    if (st == NVAPI_EXECUTABLE_NOT_FOUND) {
        if (!nosso) {
            NVDRS_PROFILE_V1 info;
            memset(&info, 0, sizeof info);
            info.version = NVDRS_PROFILE_VER;
            copiar(info.profileName, NOME_DO_PERFIL);
            if ((st = api->criar_perfil(sessao, &info, &nosso)) != NVAPI_OK)
                return falhou(api, "CreateProfile", st);
        }
        memset(&app, 0, sizeof app);
        app.version = NVDRS_APPLICATION_VER;
        copiar(app.appName, exe);
        copiar(app.userFriendlyName, NOME_DO_PERFIL);
        if ((st = api->criar_aplicativo(sessao, nosso, &app)) != NVAPI_OK)
            return falhou(api, "CreateApplication", st);
    } else if (st != NVAPI_OK) {
        return falhou(api, "FindApplicationByName", st);
    }

    memset(&config, 0, sizeof config);
    config.version = NVDRS_SETTING_VER;
    config.settingId = OGL_CPL_PREFER_DXPRESENT_ID;
    config.settingType = NVDRS_DWORD_TYPE;
    config.u32CurrentValue = OGL_CPL_PREFER_DXPRESENT_PREFER_DISABLED;
    if ((st = api->gravar(sessao, nosso, &config)) != NVAPI_OK)
        return falhou(api, "SetSetting", st);
    if ((st = api->salvar(sessao)) != NVAPI_OK)
        return falhou(api, "SaveSettings", st);
    return PERFIL_OK;
}

static int remover(const Nvapi *api, NvDRSSessionHandle sessao)
{
    NvDRSProfileHandle nosso;
    NvAPI_Status st;
    int r;

    if ((r = achar_o_nosso(api, sessao, &nosso)) != PERFIL_OK || !nosso)
        return r;
    if ((st = api->apagar_perfil(sessao, nosso)) != NVAPI_OK)
        return falhou(api, "DeleteProfile", st);
    if ((st = api->salvar(sessao)) != NVAPI_OK)
        return falhou(api, "SaveSettings", st);
    return PERFIL_OK;
}

/* Abre a sessão, roda a operação e fecha a sessão em todos os caminhos */
static int com_sessao(const Nvapi *api, const wchar_t *exe, int aplicando)
{
    NvDRSSessionHandle sessao = NULL;
    NvAPI_Status st;
    int r;

    if ((st = api->criar_sessao(&sessao)) != NVAPI_OK)
        return falhou(api, "CreateSession", st);
    if ((st = api->carregar(sessao)) != NVAPI_OK)
        r = falhou(api, "LoadSettings", st);
    else
        r = aplicando ? aplicar(api, sessao, exe) : remover(api, sessao);
    api->destruir_sessao(sessao);
    return r;
}

int perfil_inicio(int tem_dll, int tem_funcoes, NvAPI_Status inicio)
{
    if (!tem_dll)
        return PERFIL_SEM_PLACA;
    if (!tem_funcoes)
        return PERFIL_SEM_NVAPI;
    if (inicio == NVAPI_NVIDIA_DEVICE_NOT_FOUND)
        return PERFIL_SEM_PLACA;
    return inicio == NVAPI_OK ? PERFIL_OK : PERFIL_SEM_NVAPI;
}

int perfil_aplicar(const Nvapi *api, const wchar_t *exe)
{
    return com_sessao(api, exe, 1);
}

int perfil_remover(const Nvapi *api, const wchar_t *exe)
{
    return com_sessao(api, exe, 0);
}
