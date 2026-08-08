"""Logging a consola y archivo, mas avisos opcionales por correo y webhook."""

from __future__ import annotations

import logging
import logging.handlers
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

import requests

log = logging.getLogger("actionbot")


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


def notificar_email(destinatario: str | None, asunto: str, cuerpo: str) -> None:
    """Envia el aviso por correo con Gmail SMTP. La contrasena de aplicacion
    va en la variable de entorno SMTP_PASS. Si falta, no hace nada."""
    pw = os.environ.get("SMTP_PASS", "").strip()
    if not destinatario or not pw:
        return
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = destinatario
    msg["To"] = destinatario
    msg.set_content(cuerpo)
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as srv:
            srv.starttls()
            srv.login(destinatario, pw)
            srv.send_message(msg)
        log.info("Aviso enviado por correo a %s", destinatario)
    except Exception as e:
        log.warning("No pude enviar el correo (%s). Revisa SMTP_PASS y la contrasena de aplicacion.", e)


def avisar(cfg, mensaje: str) -> None:
    """Manda el aviso por todos los canales configurados (correo y webhook)."""
    notificar_email(getattr(cfg, "notificar_email", None), "ActionBot reservas", mensaje)
    notificar(getattr(cfg, "notificar_url", None), mensaje)
