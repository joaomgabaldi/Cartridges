# xinput.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A parte do controle do Xbox que só fala com o Windows (XInput): a DLL, a leitura e a vibração.

Sem gi nem Qt: serve à grade do app Qt (`modelos/controle.py`) e ao módulo GTK `gamepad.py`.
Os valores (constantes, zona morta, presets de vibração) são os da `main`.
"""

import ctypes
import logging
import time
from ctypes import wintypes
from typing import Any, Optional

# How often the pad is read while the window has focus. 30 Hz is well past the
# rate a person can navigate a grid at, and halves the wakeups of a 60 Hz loop.
POLL_INTERVAL_MS = 33
# XInput is slow to answer for an empty slot (a documented quirk, roughly a
# millisecond per unused slot), so unplugged slots are only scanned occasionally
# instead of on every tick.
SCAN_INTERVAL_US = 2_000_000

# Key-repeat feel for a held direction: a pause before it starts running, then
# a steady rate. Tuned by hand — expect to adjust these two with a pad in hand.
REPEAT_DELAY_US = 400_000
REPEAT_INTERVAL_US = 120_000

# Stick thresholds. The release value sits below the press value on purpose:
# with a single threshold, a stick resting near the edge flickers across it and
# the selection stutters. Requiring a return past the lower value to re-arm is
# what makes a held direction read as one continuous push.
THUMB_PRESS = 16_000
THUMB_RELEASE = 10_000

# A dormant pad also wakes on the stick alone, but only on a near-full push:
# half of the 0–32767 range on either axis. Connect-time drift sits far below
# this, so it still cannot wake anything, while someone who navigates by stick
# and never touches a button is not made to reach for one first. Set this high
# on purpose — the stick is pushed all the way or not at all, so there is no
# gentle nudge here to miss.
THUMB_WAKE = 16_384

# Length of a scroll between rows, matching the feel of the viewport's own
# scroll-to-focus that this module takes over from
SCROLL_DURATION_MS = 200

# Rumble presets, as (left motor, right motor, milliseconds). The two motors
# are not interchangeable: the left one is the heavy low-frequency weight and
# reads as a thud, the right one is light and high-frequency and reads as a
# click. Hence the tick on the right and the wall on the left.
RUMBLE_MOVE = (0.0, 0.14, 12)  # per card crossed, deliberately barely there
# Nowhere further to go. Leans on the heavy motor with a little of the light
# one for definition, so it lands as a firm stop rather than a vague hum — it
# is now the only feedback for hitting the end, the system beep having been
# silenced for pad navigation.
RUMBLE_EDGE = (0.6, 0.2, 70)
# Both motors, near full, and long enough to read as a send-off rather than a
# tick. This one is allowed to be the loudest thing the pad does: it fires once,
# it confirms an action that takes over the whole screen, and it is the last
# thing the app says before the window minimises and gets out of the way.
RUMBLE_LAUNCH = (0.85, 0.85, 400)
# Salto de dez jogos no Big Picture (LB/RB): só o motor leve, mais longo que o
# tique de um passo, para soar como um deslize e não como um clique.
RUMBLE_PULO = (0.0, 0.35, 25)
# Troca de capa no Big Picture: o toque da grade (12 ms a 14%) é curto demais
# para o motor girar. Sai no máximo um por duração + 60 ms, para os toques
# ficarem distintos em vez de emendarem num zumbido.
RUMBLE_CAPA = (0.5, 1.0, 90)

# XInput button masks
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
    """Return the newest XInput DLL present, or None on failure.

    1.4 ships with Windows 8 and later; the older names are only reached on
    systems where it is missing. Any failure disables the feature silently —
    a missing DLL must never stop the app from starting.
    """
    for name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
        try:
            library = ctypes.WinDLL(name)  # type: ignore[attr-defined]
            # Looking the exports up has to happen inside the try as well. A
            # DLL can load perfectly and still not export what we need — the
            # xinput stubs and wrapper DLLs people drop next to games (and
            # Wine/Proton's own builds) are the common case, and a missing
            # XInputSetState raises AttributeError here rather than at load.
            # Outside the try that escaped through GamepadManager.__init__ into
            # do_activate, where PyGObject swallows it at the vfunc boundary:
            # the process survived, but everything scheduled after the gamepad
            # manager — the update and news checkers included — never ran, for
            # a feature that is meant to fail silently.
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
            # OSError: DLL absent. AttributeError: not Windows at all, where
            # ctypes has no WinDLL — the feature simply does not exist there —
            # or a DLL that loads without the entry points we need. Either way,
            # move on to the next candidate name.
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
