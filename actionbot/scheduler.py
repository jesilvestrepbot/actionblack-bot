"""Seleccion de clases objetivo y disparo de la reserva a la hora exacta de apertura."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from . import api
from .config import Config, Objetivo

log = logging.getLogger("actionbot")


def parse_start(activity: dict) -> datetime:
    return datetime.fromisoformat(activity["start_time"])


def clave(activity: dict) -> str:
    """Identificador unico de una instancia de clase.
    El activity_id de la API se repite entre dias, por eso se combina
    con la fecha y hora de inicio."""
    return f"{activity['activity_id']}|{activity['start_time'][:16]}"


def _hhmm(activity: dict) -> str:
    return activity["start_time"][11:16]


def calendario_dos_semanas(session: requests.Session, branch: dict) -> list[dict]:
    """La API devuelve la semana domingo a sabado de la fecha pedida.
    Se consultan la semana actual y la siguiente para no perder aperturas
    de fin de semana."""
    hoy = datetime.now(ZoneInfo(branch["timezone"])).date()
    vistos: dict[str, dict] = {}
    for delta in (0, 7):
        fecha = (hoy + timedelta(days=delta)).isoformat()
        for a in api.get_calendar(session, branch, fecha):
            vistos[clave(a)] = a
    return sorted(vistos.values(), key=lambda a: a["start_time"])


def coincide(activity: dict, obj: Objetivo) -> bool:
    if activity.get("status_name") != "Available":
        return False
    if activity["activity_name"].strip().upper() not in obj.clases:
        return False
    start = parse_start(activity)
    if obj.dias and start.weekday() not in obj.dias:
        return False
    h = _hhmm(activity)
    if obj.horas:
        return h in obj.horas
    if obj.entre:
        return obj.entre[0] <= h <= obj.entre[1]
    return True


def objetivos_de_la_agenda(activities: list[dict], cfg: Config) -> list[dict]:
    """Devuelve [{activity, start, open_at}] ordenado por hora de apertura."""
    elegidos: list[dict] = []
    for obj in cfg.objetivos:
        por_dia: dict[str, list[dict]] = {}
        for a in activities:
            if not coincide(a, obj):
                continue
            por_dia.setdefault(a["start_time"][:10], []).append(a)
        for lista in por_dia.values():
            lista.sort(key=lambda x: x["start_time"])
            elegidos.extend(lista[: obj.max_por_dia])

    unicos = {clave(a): a for a in elegidos}
    out = []
    for a in unicos.values():
        start = parse_start(a)
        out.append({
            "activity": a,
            "start": start,
            "open_at": start - timedelta(hours=cfg.apertura_horas),
        })
    out.sort(key=lambda x: x["open_at"])
    return out


def clock_offset(session: requests.Session) -> timedelta:
    """Diferencia servidor menos reloj local, mediana de tres muestras."""
    muestras = []
    for _ in range(3):
        t0 = datetime.now(timezone.utc)
        srv = api.server_now(session)
        t1 = datetime.now(timezone.utc)
        if srv is None:
            continue
        punto_medio = t0 + (t1 - t0) / 2
        muestras.append(srv - punto_medio)
    if not muestras:
        return timedelta(0)
    muestras.sort()
    return muestras[len(muestras) // 2]


def ahora_corregida(offset: timedelta) -> datetime:
    return datetime.now(timezone.utc) + offset


def esperar_hasta(objetivo_utc: datetime, offset: timedelta, poll: float = 0.05) -> None:
    while True:
        falta = (objetivo_utc - ahora_corregida(offset)).total_seconds()
        if falta <= 0:
            return
        if falta > 2:
            time.sleep(min(falta - 1, 60))
        else:
            time.sleep(poll)


def rafaga_reserva(session: requests.Session, token: str, activity: dict, branch: dict,
                   cfg: Config, ventana_seg: float | None = None) -> dict:
    """Intenta la reserva en bucle hasta lograrla, hasta un error definitivo
    o hasta agotar la ventana. Los errores de validacion (ventana aun cerrada)
    y los errores de red se reintentan."""
    ventana = ventana_seg if ventana_seg is not None else cfg.rafaga_seg
    fin = time.monotonic() + ventana
    intentos = 0
    ultimo: Exception | None = None
    while time.monotonic() < fin:
        intentos += 1
        try:
            res = api.book(session, token, activity, branch)
            return {"ok": True, "intentos": intentos, "respuesta": res}
        except api.ApiError as e:
            ultimo = e
            if e.code in api.STOP_CODES:
                return {"ok": False, "intentos": intentos, "error": e, "definitivo": True}
            log.debug("Intento %s rechazado: %s", intentos, e)
        except requests.RequestException as e:
            ultimo = e
            log.debug("Intento %s con error de red: %s", intentos, e)
        time.sleep(cfg.intervalo_seg)
    return {"ok": False, "intentos": intentos, "error": ultimo, "definitivo": False}


def ya_reservada(session: requests.Session, token: str, activity: dict) -> bool:
    """Busca la actividad en las reservas vigentes del usuario.
    Tolerante al esquema porque la forma exacta de la respuesta puede variar."""
    try:
        data = api.my_bookings(session, token)
    except Exception as e:
        log.debug("No pude consultar mis reservas: %s", e)
        return False
    if isinstance(data, dict):
        items = data.get("bookings") or data.get("items") or data.get("results") or []
    else:
        items = data or []
    for b in items:
        if not isinstance(b, dict):
            continue
        st = str(b.get("start_time") or b.get("activity_start_time") or "")
        misma_hora = bool(st) and st[:16] == activity["start_time"][:16]
        mismo_id = str(b.get("activity_id")) == str(activity["activity_id"])
        # El activity_id se repite entre dias, solo cuenta junto con la hora
        if misma_hora and (not b.get("activity_id") or mismo_id):
            return True
    return False
