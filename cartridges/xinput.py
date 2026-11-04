# xinput.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A parte do controle do Xbox que só fala com o Windows (XInput): a DLL, a leitura e a vibração.

Sem gi nem Qt: serve à grade do app (`modelos/controle.py`).
"""

import ctypes
import logging
import time
from ctypes import wintypes
from typing import Any, Optional

# Com que frequência o controle é lido com a janela em foco: 30 Hz passa do ritmo em que se navega uma grade e tem
# metade das ativações de um laço de 60 Hz.
POLL_INTERVAL_MS = 33
# O XInput demora a responder para um slot vazio (cerca de 1 ms por slot), então os desconectados só são varridos de vez
# em quando.
SCAN_INTERVAL_US = 2_000_000

# Repetição de uma direção segurada: uma pausa antes de correr, depois um ritmo constante. Ajustado à mão.
REPEAT_DELAY_US = 400_000
REPEAT_INTERVAL_US = 120_000

# Limiares do stick. O de soltar fica abaixo do de apertar de propósito: com um limiar só, um stick no limite pisca e a
# seleção engasga.
THUMB_PRESS = 16_000
THUMB_RELEASE = 10_000

# Um controle dormente também acorda só com o stick, mas só num empurrão quase total (metade da faixa 0–32767): a deriva
# da conexão fica bem abaixo disso.
THUMB_WAKE = 16_384

# Duração de uma rolagem entre linhas, no ritmo da rolagem até o foco do próprio viewport, que este módulo substitui.
SCROLL_DURATION_MS = 200

# Presets de vibração (motor esquerdo, direito, milissegundos). Os motores não são intercambiáveis: o esquerdo é o peso
# grave (baque), o direito é leve e agudo (clique); daí o tique à direita e a parede à esquerda.
RUMBLE_MOVE = (0.0, 0.14, 12)  # per card crossed, deliberately barely there
# Sem mais para onde ir: o motor pesado com um pouco do leve, para soar como parada firme; é o único aviso de chegar ao
# fim, já que o bipe do sistema foi silenciado na navegação por controle.
RUMBLE_EDGE = (0.6, 0.2, 70)
# Os dois motores, quase no máximo e longos, como despedida: dispara uma vez, confirma uma ação que toma a tela inteira
# e é a última coisa que o app diz antes de a janela minimizar.
RUMBLE_LAUNCH = (0.85, 0.85, 400)
# Salto de dez jogos no Big Picture (LB/RB): só o motor leve, mais longo que o
# tique de um passo, para soar como um deslize e não como um clique.
RUMBLE_PULO = (0.0, 0.35, 25)
# Troca de capa no Big Picture: o toque da grade (12 ms a 14%) é curto demais
# para o motor girar. Sai no máximo um por duração + 60 ms, para os toques
# ficarem distintos em vez de emendarem num zumbido.
RUMBLE_CAPA = (0.5, 1.0, 90)

XINPUT_DPAD_UP = 0x0001
XINPUT_DPAD_DOWN = 0x0002
XINPUT_DPAD_LEFT = 0x0004
XINPUT_DPAD_RIGHT = 0x0008
XINPUT_START = 0x0010
XINPUT_BACK = 0x0020
XINPUT_LEFT_SHOULDER = 0x0100
XINPUT_RIGHT_SHOULDER = 0x0200
XINPUT_A = 0x1000
XINPUT_B = 0x2000
XINPUT_X = 0x4000
XINPUT_Y = 0x8000

ERROR_SUCCESS = 0

MAX_SLOTS = 4


class XInputGamepad(ctypes.Structure):
    """``XINPUT_GAMEPAD``"""

    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XInputState(ctypes.Structure):
    """``XINPUT_STATE``"""

    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XInputGamepad)]


class XInputVibration(ctypes.Structure):
    """``XINPUT_VIBRATION``"""

    _fields_ = [
        ("wLeftMotorSpeed", wintypes.WORD),
        ("wRightMotorSpeed", wintypes.WORD),
    ]


def carregar_xinput() -> Any:
    """A DLL do XInput mais nova presente, ou None em caso de falha.

    A 1.4 vem com o Windows 8 em diante; os nomes antigos só valem onde ela falta. Qualquer falha desliga o recurso em
    silêncio: uma DLL ausente nunca pode impedir o app de iniciar.
    """
    for name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
        try:
            library = ctypes.WinDLL(name)  # type: ignore[attr-defined]
            # A busca das exportações também fica dentro do try: uma DLL pode carregar sem exportar o necessário (stubs
            # e wrappers ao lado de jogos, builds do Wine/Proton), e um XInputSetState ausente levanta AttributeError
            # aqui, não no load; fora do try, escapava pela inicialização e travava tudo o que vinha depois.
            library.XInputGetState.argtypes = [
                wintypes.DWORD,
                ctypes.POINTER(XInputState),
            ]
            library.XInputGetState.restype = wintypes.DWORD
            library.XInputSetState.argtypes = [
                wintypes.DWORD,
                ctypes.POINTER(XInputVibration),
            ]
            library.XInputSetState.restype = wintypes.DWORD
        except (OSError, AttributeError):
            # OSError: DLL ausente. AttributeError: fora do Windows (ctypes sem WinDLL) ou DLL que carrega sem as
            # entradas necessárias. Nos dois casos, segue para o próximo nome.
            continue
        logging.debug("Gamepad support using %s", name)
        return library

    logging.debug("No XInput DLL found; gamepad support unavailable")
    return None


# Repetição do direcional no Big Picture: acelera depois de um segundo segurando.
INTERVALO_NORMAL_US = 120_000
ACELERAR_APOS_US = 1_000_000
INTERVALO_ACELERADO_US = 40_000


def intervalo_de_repeticao_us(segurando_us: int) -> int:
    if segurando_us >= ACELERAR_APOS_US:
        return INTERVALO_ACELERADO_US
    return INTERVALO_NORMAL_US


def agora_us() -> int:
    return time.monotonic_ns() // 1000


class LeitorXInput:
    """O primeiro controle presente nos quatro slots, lido a pedido de quem chama.

    `ler()` devolve o estado (`XInputGamepad`) ou None; `vibrar` liga os motores (0.0 a 1.0) e o
    chamador agenda o desligamento; `soltar()` devolve a DLL ao sistema.
    """

    def __init__(self) -> None:
        self.xinput = carregar_xinput()
        self.slot: Optional[int] = None
        self._ultima_varredura = -SCAN_INTERVAL_US

    @property
    def disponivel(self) -> bool:
        return self.xinput is not None

    def ler(self) -> Optional[XInputGamepad]:
        if self.xinput is None:
            return None
        estado = XInputState()
        if self.slot is not None:
            if self.xinput.XInputGetState(self.slot, ctypes.byref(estado)) == ERROR_SUCCESS:
                return estado.Gamepad
            self.slot = None  # desconectado: varre de novo no intervalo de sempre
        agora = agora_us()
        if agora - self._ultima_varredura < SCAN_INTERVAL_US:
            return None
        self._ultima_varredura = agora
        for slot in range(MAX_SLOTS):
            if self.xinput.XInputGetState(slot, ctypes.byref(estado)) == ERROR_SUCCESS:
                self.slot = slot
                logging.debug("Controle conectado no slot %s", slot)
                return estado.Gamepad
        return None

    def vibrar(self, esquerdo: float = 0.0, direito: float = 0.0) -> None:
        if self.xinput is None or self.slot is None:
            return
        vibracao = XInputVibration(
            wLeftMotorSpeed=int(max(0.0, min(1.0, esquerdo)) * 65535),
            wRightMotorSpeed=int(max(0.0, min(1.0, direito)) * 65535),
        )
        self.xinput.XInputSetState(self.slot, ctypes.byref(vibracao))

    def soltar(self) -> None:
        self.vibrar()
        self.slot = None
        self.xinput = None  # o ctypes descarrega a DLL quando ninguém mais a referencia
