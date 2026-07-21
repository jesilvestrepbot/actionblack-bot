"""Logging a consola y archivo, mas aviso opcional por webhook (ntfy, etc.)."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import requests


def configurar_logging(carpeta: str = "logs", nivel_consola: int = logging.INFO) -> logging.Logger:
    Path(carpeta).mkdir(exist_ok=True)
    log = logging.getLogger("actionbot")
    log.setLevel(logging.DEBUG)
    if log.handlers:
        return log
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    consola = logging.StreamHandler()
    consola.setLevel(nivel_consola)
    consola.setFormatter(fmt)
    log.addHandler(consola)

    archivo = logging.handlers.RotatingFileHandler(
        Path(carpeta) / "actionbot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    archivo.setLevel(logging.DEBUG)
    archivo.setFormatter(fmt)
    log.addHandler(archivo)
    return log


def notificar(url: str | None, mensaje: str) -> None:
    """POST simple con el texto del aviso. Pensado para ntfy.sh o similar."""
    if not url:
        return
    try:
        requests.post(url, data=mensaje.encode("utf-8"), timeout=8)
    except requests.RequestException:
        pass
