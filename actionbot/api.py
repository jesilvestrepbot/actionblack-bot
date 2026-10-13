"""Cliente HTTP para la API de reservas de Action Black.

Endpoints mapeados desde el bundle web de actionblack.co/reservas.
Los tokens estaticos de este archivo son los mismos que el sitio publico
entrega a cualquier visitante en su JavaScript, no son secretos de usuario.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

EXP_BASE = "https://prod.action-exp-api.com/api/v1"
CLOUD_BASE = "https://action-cloud.com/v1"
CLOUD_TOKEN = "6259c6246400c9b24ed672d1dda8ad80b6a0dde8"

BASE_HEADERS = {
    "Content-Type": "application/json",
    "X-Client-Origin": "WEB",
    "Origin": "https://www.actionblack.co",
    "Referer": "https://www.actionblack.co/reservas",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
}

# Errores que no tiene sentido reintentar dentro de la rafaga.
# OJO: INVALID_PARAMETER NO va aqui. La API lo devuelve cuando se intenta
# reservar antes de que abra la ventana de 24 h (validado 2026-07-21 con
# el mismo payload que si funciona dentro de la ventana). Por eso debe
# reintentarse: el bot dispara unos segundos antes de la apertura y tiene
# que insistir hasta que la ventana abre en el segundo exacto.
STOP_CODES = {
    "ACTIVITIES_OVERLAPPING",       # ya tienes una clase en ese horario
    "USER_BLOCKED_ERROR",           # cuenta bloqueada
    "USER_PENALIZED_ERROR",         # penalizado (no-show); no se levanta en la rafaga
    "MISSING_PARAMETER",            # falta un campo del payload, es un bug, no insistir
    "PAST_EVENT_CHANGE_DENIED",     # la clase ya paso, no tiene sentido insistir
}

# Errores que significan "la ventana aun no abre", se reintenta hasta que abra
RETRY_EARLY_CODES = {
    "INVALID_PARAMETER",
    "ACTIVITIES_SCHEDULE_VALIDATION_ERROR",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str | None, description: str | None, payload=None):
        self.status = status
        self.code = code or "UNEXPECTED_ERROR"
        self.description = description or "Error desconocido"
        self.payload = payload
        super().__init__(f"[{status}] {self.code}: {self.description}")


def _check(resp: requests.Response) -> None:
    if resp.ok:
        return
    code = None
    desc = None
    payload = None
    try:
        payload = resp.json()
        err = (payload.get("errors") or [{}])[0]
        code = err.get("code")
        desc = err.get("description") or payload.get("message") or payload.get("detail")
    except ValueError:
        desc = resp.text[:300]
    raise ApiError(resp.status_code, code, desc, payload)


def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(BASE_HEADERS)
    # El servidor cierra las conexiones keep-alive inactivas a los ~60 s; si
    # se reutiliza justo en ese instante llega RemoteDisconnected. Los GET se
    # reintentan solos con conexion nueva. Los POST (login, reserva) no.
    reintentos = Retry(total=3, connect=3, read=2, backoff_factor=0.5,
                       status_forcelist=(502, 503, 504), allowed_methods=frozenset({"GET"}),
                       raise_on_status=False)
    adaptador = HTTPAdapter(max_retries=reintentos)
    s.mount("https://", adaptador)
    s.mount("http://", adaptador)
    return s


def get_branches(session: requests.Session) -> list[dict]:
    r = session.get(
        f"{CLOUD_BASE}/branches",
        headers={"Authorization": f"Token {CLOUD_TOKEN}"},
        timeout=20,
    )
    _check(r)
    return r.json().get("result", [])


def find_branch(session: requests.Session, name: str) -> dict | None:
    wanted = name.strip().lower().replace(" ", "")
    for b in get_branches(session):
        if b.get("is_deleted"):
            continue
        candidates = {
            (b.get("name") or "").lower().replace(" ", ""),
            (b.get("display_name") or "").lower().replace(" ", ""),
        }
        if wanted in candidates:
            return b
    return None


def get_calendar(session: requests.Session, branch: dict, date_str: str) -> list[dict]:
    """Calendario publico de la semana que contiene date_str (no requiere login)."""
    params = {
        "timezone": branch["timezone"],
        "token_branch": branch["evo_token"],
        "activities_date": date_str,
        "partner_name": branch.get("partner_name") or "EVO",
        "show_full_week": "true",
    }
    r = session.get(f"{EXP_BASE}/activities/generic", params=params, timeout=20)
    _check(r)
    return r.json().get("data", [])


def login(session: requests.Session, email: str, password: str, branch: dict) -> tuple[str, str | None]:
    body = {
        "email": email,
        "password": password,
        "partner_data": {
            "partner_name": branch.get("partner_name") or "EVO",
            "branch_id": branch.get("id") or "",
            "branch_name": branch.get("name") or "",
            "token_branch": branch.get("evo_token") or "",
            "country_code": branch.get("country_code") or "",
        },
    }
    r = session.post(f"{EXP_BASE}/auth/login", json=body, timeout=20)
    _check(r)
    data = r.json().get("data") or {}
    token = data.get("access_token")
    if not token:
        raise ApiError(r.status_code, "NO_TOKEN", "La respuesta de login no trajo access_token", data)
    return token, data.get("refresh_token")


def jwt_claims(token: str) -> dict:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def booking_payload(activity: dict, branch: dict) -> dict:
    """Mismo cuerpo que arma el sitio web al pulsar RESERVAR."""
    date_field = activity.get("date") or activity.get("activity_date") or activity["start_time"]
    return {
        "activity_id": activity["activity_id"],
        "activ_config_id": activity["activ_config_id"],
        "activity_date": str(date_field)[:10],
        "token_branch": branch.get("evo_token") or str(branch.get("id")),
        "activity_start": activity["start_time"][11:16],
        "timezone": activity.get("timezone") or branch.get("timezone"),
        "activity_name": activity.get("activity_name"),
        "capacity": activity.get("capacity"),
        "branch_name": activity.get("branch_name") or branch.get("name"),
        "branch_id": str(activity.get("branch_id") or branch.get("id")),
        "partner_name": branch.get("partner_name") or "EVO",
        "country_code": branch.get("country_code") or "CO",
        "booking_origin": "WEB",
    }


def book(session: requests.Session, access_token: str, activity: dict, branch: dict, timeout: float = 12) -> dict:
    r = session.post(
        f"{EXP_BASE}/activities/booking",
        json=booking_payload(activity, branch),
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=timeout,
    )
    _check(r)
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text[:300]}


def my_bookings(session: requests.Session, access_token: str, page_size: int = 50,
                page_number: int = 1, is_current: bool = True):
    r = session.get(
        f"{EXP_BASE}/activities/bookings",
        params={
            "page_size": page_size,
            "page_number": page_number,
            "is_current": str(is_current).lower(),
        },
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    _check(r)
    body = r.json()
    return body.get("data", body)


def server_now(session: requests.Session) -> datetime | None:
    """Hora del servidor de reservas segun su header Date, en UTC."""
    try:
        r = session.get(f"{EXP_BASE}/ping", timeout=10)
        d = r.headers.get("Date")
        if d:
            return parsedate_to_datetime(d).astimezone(timezone.utc)
    except requests.RequestException:
        pass
    return None
