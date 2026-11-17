"""Configuración común de la suite.

Las pruebas que leen snapshots crudos de cadenas (scripts/_rnd_lab_load.py, data/raw/<SIMBOLO>/<fecha>.json.gz)
se omiten, una por una, cuando el snapshot que piden no existe: data/raw/ está en .gitignore ("nunca en git") y
solo vive en la máquina donde se capturó. Las demás pruebas de esos archivos siguen corriendo. Sin esta regla, 35
pruebas fallan con FileNotFoundError y ocultan cualquier falla real (verificado el 2026-11-17: mismas 35 fallas
en 509e916 y en f7acd27, ninguna nueva por el merge del proveedor Tradier).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Las pruebas importan el cargador como `_rnd_lab_load` con scripts/ en sys.path; se parcha ese mismo módulo.
_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import _rnd_lab_load as _lab  # noqa: E402

_original = _lab.load_snapshot


def _load_or_skip(symbol: str, fecha: str) -> dict:
    ruta = _lab.RAW / symbol.upper() / f"{fecha}.json.gz"
    if not ruta.exists():
        pytest.skip(f"requiere el snapshot crudo {ruta.relative_to(_lab.RAW.parent.parent)} (data/raw no se versiona)")
    return _original(symbol, fecha)


_lab.load_snapshot = _load_or_skip
