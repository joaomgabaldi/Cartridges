# __main__.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

import sys

from kyron.aquecer_direct3d import aquecer

# Antes dos imports pesados: o driver de vídeo acorda enquanto o resto carrega.
aquecer(sys.argv)

# pylint: disable=wrong-import-position
from kyron.app import main  # noqa: E402

sys.exit(main(sys.argv))
