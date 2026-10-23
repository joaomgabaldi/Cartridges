/* perfil.h
 *
 * Copyright 2026 joaomgabaldi
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * O perfil "Cartridges" no driver da NVIDIA. A lógica fala com a NVAPI por uma
 * tabela de funções, para o teste trocá-la por uma falsa. Recebe a NVAPI já
 * inicializada (Initialize/Unload ficam no nvidia_perfil.c).
 */

#ifndef PERFIL_H
#define PERFIL_H

#include <wchar.h>

#include "nvapi_drs.h"

/* SEM_NVAPI: driver antigo ou NVAPI com erro (o instalador mostra o passo a
   passo manual). SEM_PLACA: sem driver ou sem placa NVIDIA, então sem moldura
   (nenhuma página). */
enum { PERFIL_OK = 0, PERFIL_SEM_NVAPI = 1, PERFIL_ERRO = 2, PERFIL_DE_TERCEIROS = 3, PERFIL_SEM_PLACA = 4 };

typedef struct {
    NvAPI_Status (*criar_sessao)(NvDRSSessionHandle *);
    NvAPI_Status (*destruir_sessao)(NvDRSSessionHandle);
    NvAPI_Status (*carregar)(NvDRSSessionHandle);
    NvAPI_Status (*salvar)(NvDRSSessionHandle);
    NvAPI_Status (*achar_aplicativo)(NvDRSSessionHandle, NvAPI_UnicodeString, NvDRSProfileHandle *, NVDRS_APPLICATION_V4 *);
    NvAPI_Status (*achar_perfil)(NvDRSSessionHandle, NvAPI_UnicodeString, NvDRSProfileHandle *);
    NvAPI_Status (*criar_perfil)(NvDRSSessionHandle, NVDRS_PROFILE_V1 *, NvDRSProfileHandle *);
    NvAPI_Status (*criar_aplicativo)(NvDRSSessionHandle, NvDRSProfileHandle, NVDRS_APPLICATION_V4 *);
    NvAPI_Status (*gravar)(NvDRSSessionHandle, NvDRSProfileHandle, NVDRS_SETTING_V1 *);
    NvAPI_Status (*apagar_perfil)(NvDRSSessionHandle, NvDRSProfileHandle);
    NvAPI_Status (*mensagem)(NvAPI_Status, NvAPI_ShortString);
} Nvapi;

/* Se dá para seguir depois de carregar a NVAPI: PERFIL_OK ou o código de saída.
   tem_dll: a nvapi64.dll e o nvapi_QueryInterface existem; tem_funcoes: todas
   as funções usadas existem; inicio: o status do NvAPI_Initialize. */
int perfil_inicio(int tem_dll, int tem_funcoes, NvAPI_Status inicio);

/* Grava "Preferir nativo" para o exe no perfil "Cartridges". Devolve PERFIL_*. */
int perfil_aplicar(const Nvapi *api, const wchar_t *exe);

/* Apaga o perfil "Cartridges", se existir. Devolve PERFIL_OK ou PERFIL_ERRO. */
int perfil_remover(const Nvapi *api, const wchar_t *exe);

#endif
