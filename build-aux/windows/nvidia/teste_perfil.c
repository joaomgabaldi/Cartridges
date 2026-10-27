/* teste_perfil.c
 *
 * Copyright 2026 joaomgabaldi
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A lógica do perfil contra uma NVAPI falsa. Imprime "ok" e sai com 0 quando
 * tudo passa; o montar_app.py roda este teste antes de compilar o utilitário.
 */

#undef NDEBUG
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>

#include "perfil.h"

#define EXE L"C:\\Program Files\\Cartridges Revamped\\bin\\Cartridges.exe"

static NvDRSSessionHandle const SESSAO = (NvDRSSessionHandle)0x10;
static NvDRSProfileHandle const NOSSO = (NvDRSProfileHandle)0x20;
static NvDRSProfileHandle const DE_TERCEIROS = (NvDRSProfileHandle)0x30;

/* O que a falsa devolve e o que ela viu */
static struct {
    NvAPI_Status st_aplicativo, st_salvar;
    NvDRSProfileHandle perfil_do_exe; /* NULL: o exe não está em perfil nenhum */
    int perfil_existe;
    const wchar_t *exe; /* o que achar_aplicativo deve receber */
    const char *chamadas[32];
    int n;
    NvU32 id_gravado, valor_gravado, tipo_gravado;
    wchar_t perfil_criado[64], app_criado[512], amigavel[64];
} f;

static void registrar(const char *nome)
{
    assert(f.n < 32);
    f.chamadas[f.n++] = nome;
}

static int chamou(const char *nome)
{
    for (int i = 0; i < f.n; i++)
        if (strcmp(f.chamadas[i], nome) == 0)
            return 1;
    return 0;
}

static NvAPI_Status criar_sessao(NvDRSSessionHandle *s) { registrar("criar_sessao"); *s = SESSAO; return NVAPI_OK; }
static NvAPI_Status destruir_sessao(NvDRSSessionHandle s) { assert(s == SESSAO); registrar("destruir_sessao"); return NVAPI_OK; }
static NvAPI_Status carregar(NvDRSSessionHandle s) { (void)s; registrar("carregar"); return NVAPI_OK; }
static NvAPI_Status salvar(NvDRSSessionHandle s) { (void)s; registrar("salvar"); return f.st_salvar; }

static NvAPI_Status achar_aplicativo(NvDRSSessionHandle s, NvAPI_UnicodeString nome,
                                     NvDRSProfileHandle *p, NVDRS_APPLICATION_V4 *app)
{
    (void)s;
    registrar("achar_aplicativo");
    assert(wcsncmp((wchar_t *)nome, f.exe, NVAPI_UNICODE_STRING_MAX - 1) == 0);
    assert(nome[NVAPI_UNICODE_STRING_MAX - 1] == 0);
    assert(app->version == NVDRS_APPLICATION_VER);
    if (f.st_aplicativo != NVAPI_OK)
        return f.st_aplicativo;
    if (!f.perfil_do_exe)
        return NVAPI_EXECUTABLE_NOT_FOUND;
    *p = f.perfil_do_exe;
    return NVAPI_OK;
}

static NvAPI_Status achar_perfil(NvDRSSessionHandle s, NvAPI_UnicodeString nome, NvDRSProfileHandle *p)
{
    (void)s;
    registrar("achar_perfil");
    assert(wcscmp((wchar_t *)nome, L"Cartridges") == 0);
    if (!f.perfil_existe)
        return NVAPI_PROFILE_NOT_FOUND;
    *p = NOSSO;
    return NVAPI_OK;
}

static NvAPI_Status criar_perfil(NvDRSSessionHandle s, NVDRS_PROFILE_V1 *info, NvDRSProfileHandle *p)
{
    (void)s;
    registrar("criar_perfil");
    assert(info->version == NVDRS_PROFILE_VER);
    wcsncpy(f.perfil_criado, (wchar_t *)info->profileName, 63);
    f.perfil_existe = 1;
    *p = NOSSO;
    return NVAPI_OK;
}

static NvAPI_Status criar_aplicativo(NvDRSSessionHandle s, NvDRSProfileHandle p, NVDRS_APPLICATION_V4 *app)
{
    (void)s;
    registrar("criar_aplicativo");
    assert(p == NOSSO);
    assert(app->version == NVDRS_APPLICATION_VER);
    wcsncpy(f.app_criado, (wchar_t *)app->appName, 511);
    wcsncpy(f.amigavel, (wchar_t *)app->userFriendlyName, 63);
    return NVAPI_OK;
}

static NvAPI_Status gravar(NvDRSSessionHandle s, NvDRSProfileHandle p, NVDRS_SETTING_V1 *c)
{
    (void)s;
    registrar("gravar");
    assert(p == NOSSO);
    assert(c->version == NVDRS_SETTING_VER);
    f.id_gravado = c->settingId;
    f.tipo_gravado = c->settingType;
    f.valor_gravado = c->u32CurrentValue;
    return NVAPI_OK;
}

static NvAPI_Status apagar_perfil(NvDRSSessionHandle s, NvDRSProfileHandle p)
{
    (void)s;
    registrar("apagar_perfil");
    assert(p == NOSSO);
    return NVAPI_OK;
}

static NvAPI_Status mensagem(NvAPI_Status st, NvAPI_ShortString texto)
{
    snprintf(texto, NVAPI_SHORT_STRING_MAX, "erro %d", st);
    return NVAPI_OK;
}

static const Nvapi API = {
    criar_sessao, destruir_sessao, carregar, salvar, achar_aplicativo, achar_perfil,
    criar_perfil, criar_aplicativo, gravar, apagar_perfil, mensagem,
};

static void zerar(void)
{
    memset(&f, 0, sizeof f);
    f.st_aplicativo = NVAPI_OK;
    f.st_salvar = NVAPI_OK;
    f.exe = EXE;
    f.id_gravado = f.valor_gravado = 0xFFFFFFFFu;
}

/* Toda sessão aberta é fechada, e por último */
static void sessao_fechada(void)
{
    assert(f.n > 0 && strcmp(f.chamadas[0], "criar_sessao") == 0);
    assert(strcmp(f.chamadas[f.n - 1], "destruir_sessao") == 0);
}

static void gravou_preferir_nativo(void)
{
    assert(chamou("gravar") && chamou("salvar"));
    assert(f.id_gravado == 0x20D690F8u);
    assert(f.tipo_gravado == NVDRS_DWORD_TYPE);
    assert(f.valor_gravado == 0);
}

static void teste_aplicar_ja_no_nosso_perfil(void)
{
    zerar();
    f.perfil_existe = 1;
    f.perfil_do_exe = NOSSO;
    assert(perfil_aplicar(&API, EXE) == PERFIL_OK);
    gravou_preferir_nativo();
    assert(!chamou("criar_perfil") && !chamou("criar_aplicativo"));
    sessao_fechada();
}

static void teste_aplicar_sem_perfil_algum(void)
{
    zerar();
    assert(perfil_aplicar(&API, EXE) == PERFIL_OK);
    assert(wcscmp(f.perfil_criado, L"Cartridges") == 0);
    assert(wcscmp(f.app_criado, EXE) == 0);
    assert(wcscmp(f.amigavel, L"Cartridges") == 0);
    gravou_preferir_nativo();
    sessao_fechada();
}

static void teste_aplicar_reaproveita_perfil(void)
{
    zerar();
    f.perfil_existe = 1;
    assert(perfil_aplicar(&API, EXE) == PERFIL_OK);
    assert(!chamou("criar_perfil") && chamou("criar_aplicativo"));
    gravou_preferir_nativo();
    sessao_fechada();
}

static void teste_aplicar_perfil_de_terceiros(void)
{
    zerar();
    f.perfil_existe = 1;
    f.perfil_do_exe = DE_TERCEIROS;
    assert(perfil_aplicar(&API, EXE) == PERFIL_DE_TERCEIROS);
    assert(!chamou("gravar") && !chamou("salvar"));
    assert(!chamou("criar_perfil") && !chamou("criar_aplicativo"));
    sessao_fechada();
}

static void teste_aplicar_erro_na_busca(void)
{
    zerar();
    f.st_aplicativo = NVAPI_ERROR;
    assert(perfil_aplicar(&API, EXE) == PERFIL_ERRO);
    assert(!chamou("criar_perfil") && !chamou("criar_aplicativo") && !chamou("gravar"));
    sessao_fechada();
}

static void teste_aplicar_erro_ao_salvar(void)
{
    zerar();
    f.perfil_existe = 1;
    f.perfil_do_exe = NOSSO;
    f.st_salvar = NVAPI_ERROR;
    assert(perfil_aplicar(&API, EXE) == PERFIL_ERRO);
    sessao_fechada();
}

static void teste_remover_com_perfil(void)
{
    zerar();
    f.perfil_existe = 1;
    assert(perfil_remover(&API, EXE) == PERFIL_OK);
    assert(chamou("apagar_perfil") && chamou("salvar"));
    sessao_fechada();
}

static void teste_remover_sem_perfil(void)
{
    zerar();
    assert(perfil_remover(&API, EXE) == PERFIL_OK);
    assert(!chamou("apagar_perfil") && !chamou("salvar"));
    sessao_fechada();
}

/* Caminho maior que a NvAPI_UnicodeString: corta no limite e termina em zero */
static void teste_caminho_longo(void)
{
    static wchar_t longo[NVAPI_UNICODE_STRING_MAX + 100];
    wmemset(longo, L'a', NVAPI_UNICODE_STRING_MAX + 99);
    zerar();
    f.exe = longo;
    f.st_aplicativo = NVAPI_ERROR;
    assert(perfil_aplicar(&API, longo) == PERFIL_ERRO);
    assert(chamou("achar_aplicativo"));
    sessao_fechada();
}

/* Sem driver NVIDIA não há Vulkan da NVIDIA nem moldura: 4, sem página. Driver
   sem as funções ou Initialize com outro erro: 1, com página. */
static void teste_inicio(void)
{
    assert(perfil_inicio(0, 0, NVAPI_OK) == PERFIL_SEM_PLACA);
    assert(perfil_inicio(1, 0, NVAPI_OK) == PERFIL_SEM_NVAPI);
    assert(perfil_inicio(1, 1, NVAPI_NVIDIA_DEVICE_NOT_FOUND) == PERFIL_SEM_PLACA);
    assert(perfil_inicio(1, 1, NVAPI_ERROR) == PERFIL_SEM_NVAPI);
    assert(perfil_inicio(1, 1, NVAPI_OK) == PERFIL_OK);
}

int main(void)
{
    teste_inicio();
    teste_aplicar_ja_no_nosso_perfil();
    teste_aplicar_sem_perfil_algum();
    teste_aplicar_reaproveita_perfil();
    teste_aplicar_perfil_de_terceiros();
    teste_aplicar_erro_na_busca();
    teste_aplicar_erro_ao_salvar();
    teste_remover_com_perfil();
    teste_remover_sem_perfil();
    teste_caminho_longo();
    puts("ok");
    return 0;
}
