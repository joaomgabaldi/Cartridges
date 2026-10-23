/* nvapi_drs.h
 *
 * O mínimo da NVAPI DRS (configurações de perfil do driver) que o
 * nvidia-perfil.exe usa, copiado do SDK oficial (github.com/NVIDIA/nvapi,
 * nvapi.h, nvapi_interface.h e NvApiDriverSettings.h de setembro de 2026).
 * Os layouts das structs têm que bater byte a byte com os do SDK.
 *
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: MIT
 *
 * Permission is hereby granted, free of charge, to any person obtaining a
 * copy of this software and associated documentation files (the "Software"),
 * to deal in the Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute, sublicense,
 * and/or sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
 * THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
 * DEALINGS IN THE SOFTWARE.
 */

#ifndef NVAPI_DRS_H
#define NVAPI_DRS_H

typedef unsigned char NvU8;
typedef unsigned short NvU16;
typedef unsigned int NvU32;
typedef unsigned long long NvU64;
typedef int NvAPI_Status;

#define NVAPI_UNICODE_STRING_MAX 2048
#define NVAPI_BINARY_DATA_MAX 4096
#define NVAPI_SHORT_STRING_MAX 64
typedef NvU16 NvAPI_UnicodeString[NVAPI_UNICODE_STRING_MAX];
typedef char NvAPI_ShortString[NVAPI_SHORT_STRING_MAX];

typedef struct NvDRSSessionHandle__ *NvDRSSessionHandle;
typedef struct NvDRSProfileHandle__ *NvDRSProfileHandle;

#define MAKE_NVAPI_VERSION(tipo, ver) ((NvU32)(sizeof(tipo) | ((ver) << 16)))

/* Status (nvapi_lite_common.h) */
#define NVAPI_OK 0
#define NVAPI_ERROR (-1)
#define NVAPI_NVIDIA_DEVICE_NOT_FOUND (-6)
#define NVAPI_PROFILE_NOT_FOUND (-163)
#define NVAPI_EXECUTABLE_NOT_FOUND (-166)

typedef enum {
    NVDRS_DWORD_TYPE,
    NVDRS_BINARY_TYPE,
    NVDRS_STRING_TYPE,
    NVDRS_WSTRING_TYPE,
    NVDRS_QWORD_TYPE
} NVDRS_SETTING_TYPE;

typedef enum {
    NVDRS_CURRENT_PROFILE_LOCATION,
    NVDRS_GLOBAL_PROFILE_LOCATION,
    NVDRS_BASE_PROFILE_LOCATION,
    NVDRS_DEFAULT_PROFILE_LOCATION
} NVDRS_SETTING_LOCATION;

/* 32 campos de 1 bit no SDK; o mesmo tamanho aqui */
typedef struct {
    NvU32 geforce : 1;
    NvU32 quadro : 1;
    NvU32 nvs : 1;
    NvU32 reserved : 29;
} NVDRS_GPU_SUPPORT;

typedef struct {
    NvU32 valueLength;
    NvU8 valueData[NVAPI_BINARY_DATA_MAX];
} NVDRS_BINARY_SETTING;

#pragma pack(push, 4)
typedef struct {
    NvU32 version;
    NvAPI_UnicodeString settingName;
    NvU32 settingId;
    NVDRS_SETTING_TYPE settingType;
    NVDRS_SETTING_LOCATION settingLocation;
    NvU32 isCurrentPredefined;
    NvU32 isPredefinedValid;
    union {
        NvU32 u32PredefinedValue;
        NVDRS_BINARY_SETTING binaryPredefinedValue;
        NvAPI_UnicodeString wszPredefinedValue;
        NvU64 u64PredefinedValue;
    };
    union {
        NvU32 u32CurrentValue;
        NVDRS_BINARY_SETTING binaryCurrentValue;
        NvAPI_UnicodeString wszCurrentValue;
        NvU64 u64CurrentValue;
    };
} NVDRS_SETTING_V1;
#pragma pack(pop)

typedef struct {
    NvU32 version;
    NvU32 isPredefined;
    NvAPI_UnicodeString appName;
    NvAPI_UnicodeString userFriendlyName;
    NvAPI_UnicodeString launcher;
    NvAPI_UnicodeString fileInFolder;
    NvU32 isMetro : 1;
    NvU32 isCommandLine : 1;
    NvU32 reserved : 30;
    NvAPI_UnicodeString commandLine;
} NVDRS_APPLICATION_V4;

typedef struct {
    NvU32 version;
    NvAPI_UnicodeString profileName;
    NVDRS_GPU_SUPPORT gpuSupport;
    NvU32 isPredefined;
    NvU32 numOfApps;
    NvU32 numOfSettings;
} NVDRS_PROFILE_V1;

#define NVDRS_SETTING_VER MAKE_NVAPI_VERSION(NVDRS_SETTING_V1, 1)
#define NVDRS_APPLICATION_VER MAKE_NVAPI_VERSION(NVDRS_APPLICATION_V4, 4)
#define NVDRS_PROFILE_VER MAKE_NVAPI_VERSION(NVDRS_PROFILE_V1, 1)

/* Os tamanhos do SDK: a versão leva o sizeof, e o driver recusa outro */
_Static_assert(sizeof(NVDRS_SETTING_V1) == 12320, "NVDRS_SETTING_V1");
_Static_assert(sizeof(NVDRS_APPLICATION_V4) == 20492, "NVDRS_APPLICATION_V4");
_Static_assert(sizeof(NVDRS_PROFILE_V1) == 4116, "NVDRS_PROFILE_V1");

/* IDs do nvapi_QueryInterface (nvapi_interface.h) */
#define NVAPI_ID_INITIALIZE 0x0150e828u
#define NVAPI_ID_UNLOAD 0xd22bdd7eu
#define NVAPI_ID_GET_ERROR_MESSAGE 0x6c2d048cu
#define NVAPI_ID_DRS_CREATE_SESSION 0x0694d52eu
#define NVAPI_ID_DRS_DESTROY_SESSION 0xdad9cff8u
#define NVAPI_ID_DRS_LOAD_SETTINGS 0x375dbd6bu
#define NVAPI_ID_DRS_SAVE_SETTINGS 0xfcbc7e14u
#define NVAPI_ID_DRS_FIND_APPLICATION_BY_NAME 0xeee566b2u
#define NVAPI_ID_DRS_FIND_PROFILE_BY_NAME 0x7e4a9a0bu
#define NVAPI_ID_DRS_CREATE_PROFILE 0xcc176068u
#define NVAPI_ID_DRS_CREATE_APPLICATION 0x4347a9deu
#define NVAPI_ID_DRS_SET_SETTING 0x577dd202u
#define NVAPI_ID_DRS_DELETE_PROFILE 0x17093206u

/* Método de apresentação Vulkan/OpenGL (NvApiDriverSettings.h) */
#define OGL_CPL_PREFER_DXPRESENT_ID 0x20D690F8u
#define OGL_CPL_PREFER_DXPRESENT_PREFER_DISABLED 0x00000000u /* "Preferir nativo" */

#endif
