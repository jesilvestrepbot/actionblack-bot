"""Seleccion de clases objetivo y disparo de la reserva a la hora exacta de apertura."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from . import api
from .config import Config

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


def es_festivo(fecha: str, weekday: int, cfg: Config) -> bool:
    """Sabados, domingos y festivos declarados usan la franja de festivo."""
    return weekday >= 5 or fecha in cfg.plan.festivos


def candidatos_por_dia(activities: list[dict], cfg: Config) -> dict[str, list[dict]]:
    """Para cada fecha del plan: las clases candidatas ordenadas por prioridad
    y luego por hora. La franja depende del tipo de dia (normal o festivo).
    Si un dia entre semana no tiene clases en la franja normal, se asume
    horario de festivo no declarado y se usa la otra franja.
    Excluye las canceladas; el estado fino (Available, Full, Finalized)
    se filtra en cada uso."""
    plan = cfg.plan
    crudos: dict[str, list[dict]] = {}
    for a in activities:
        nombre = a["activity_name"].strip().upper()
        if nombre not in plan.prioridad:
            continue
        if a.get("status_name") == "Canceled":
            continue
        start = parse_start(a)
        if plan.dias and start.weekday() not in plan.dias:
            continue
        crudos.setdefault(a["start_time"][:10], []).append(a)

    por_fecha: dict[str, list[dict]] = {}
    for fecha, lista in crudos.items():
        wd = parse_start(lista[0]).weekday()
        franja = plan.entre_festivos if es_festivo(fecha, wd, cfg) else plan.entre
        sel = [a for a in lista if franja[0] <= _hhmm(a) <= franja[1]]
        if not sel and not es_festivo(fecha, wd, cfg):
            sel = [a for a in lista
                   if plan.entre_festivos[0] <= _hhmm(a) <= plan.entre_festivos[1]]
            if sel:
                log.info("El %s no tiene clases del plan en la franja normal, "
                         "parece festivo, uso la franja de festivo", fecha)
        if sel:
            sel.sort(key=lambda x: (plan.prioridad.index(x["activity_name"].strip().upper()),
                                    x["start_time"]))
            por_fecha[fecha] = sel
    return por_fecha


def apertura_de(activity: dict, cfg: Config) -> datetime:
    return parse_start(activity) - timedelta(hours=cfg.apertura_horas)


def dia_cubierto(bookings, fecha: str) -> dict | None:
    """Reserva vigente (Booked) de ese dia, si existe. Cuenta cualquier clase,
    tambien las hechas a mano desde la app: la regla es una clase por dia."""
    if isinstance(bookings, dict):
        items = bookings.get("items") or bookings.get("bookings") or []
    else:
        items = bookings or []
    for b in items:
        if not isinstance(b, dict):
            continue
        st = str(b.get("start_time") or "")
        if st[:10] == fecha and (b.get("status_name") or "").lower() == "booked":
            return b
    return None


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
            t_post = time.monotonic()
            res = api.book(session, token, activity, branch)
            log.info("POST de reserva respondio en %.2f s (intento %s)", time.monotonic() - t_post, intentos)
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
    """Busca esa misma clase en las reservas vigentes del usuario."""
    try:
        data = api.my_bookings(session, token)
    except Exception as e:
        log.debug("No pude consultar mis reservas: %s", e)
        return False
    if isinstance(data, dict):
        items = data.get("items") or data.get("bookings") or []
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
