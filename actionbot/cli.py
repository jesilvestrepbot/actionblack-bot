"""CLI del bot de reservas de Action Black."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from . import api, scheduler
from .config import Config, cargar
from .notify import configurar_logging, notificar

log = logging.getLogger("actionbot")

ESTADO_PATH = Path("logs/estado.json")


def cargar_estado() -> dict:
    try:
        estado = json.loads(ESTADO_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    limite = datetime.now() - timedelta(days=15)
    vigente = {}
    for k, v in estado.items():
        try:
            if datetime.fromisoformat(v.get("ts")) >= limite:
                vigente[k] = v
        except Exception:
            continue
    return vigente


def guardar_estado(estado: dict) -> None:
    ESTADO_PATH.parent.mkdir(exist_ok=True)
    ESTADO_PATH.write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")


def _branch(session: requests.Session, cfg: Config) -> dict:
    b = api.find_branch(session, cfg.sede)
    if not b:
        sys.exit(f"Sede no encontrada: {cfg.sede}. Mira los nombres con: python -m actionbot sedes")
    return b


def _requiere_credenciales(cfg: Config) -> None:
    if not cfg.email or not cfg.password:
        sys.exit("Faltan ACTION_EMAIL o ACTION_PASSWORD. Copia .env.example a .env y completalo.")


def _nombre(activity: dict) -> str:
    return f"{activity['activity_name']} {activity['start_time'][:10]} {activity['start_time'][11:16]}"


def cmd_sedes(args) -> None:
    session = api.new_session()
    print(f"{'nombre':32} {'nombre visible':32} ciudad")
    for b in sorted(api.get_branches(session), key=lambda x: (x.get("city_name") or "", x["name"])):
        if b.get("is_deleted"):
            continue
        print(f"{b['name']:32} {b.get('display_name') or '':32} {b.get('city_name') or ''}")


def cmd_calendario(args) -> None:
    cfg = cargar(args.config)
    session = api.new_session()
    branch = _branch(session, cfg)
    print(f"Sede {branch['name']} ({branch.get('display_name')})")
    for a in scheduler.calendario_dos_semanas(session, branch):
        if args.clase and a["activity_name"].strip().upper() != args.clase.upper():
            continue
        s = a["start_time"]
        print(f"{s[:10]} {s[11:16]}  {a['activity_name']:10} cupos {a['occupation']:>2}/{a['capacity']:<2} {a['status_name']}")


def cmd_plan(args) -> None:
    cfg = cargar(args.config)
    session = api.new_session()
    branch = _branch(session, cfg)
    tz = ZoneInfo(branch["timezone"])
    targets = scheduler.objetivos_de_la_agenda(scheduler.calendario_dos_semanas(session, branch), cfg)
    if not targets:
        print("Ningun objetivo coincide con el calendario actual, revisa config.yaml")
        return
    ahora = datetime.now(timezone.utc)
    print(f"Objetivos detectados en {branch['name']} (apertura {cfg.apertura_horas:g} h antes):")
    for t in targets:
        a = t["activity"]
        abre = t["open_at"]
        if abre <= ahora:
            estado = "apertura ya pasada"
        else:
            estado = f"abre {abre.astimezone(tz):%Y-%m-%d %H:%M:%S}"
        print(f"  {_nombre(a):32} cupos {a['occupation']:>2}/{a['capacity']:<2} {estado}")


def cmd_login_test(args) -> None:
    cfg = cargar(args.config)
    _requiere_credenciales(cfg)
    session = api.new_session()
    branch = _branch(session, cfg)
    token, _ = api.login(session, cfg.email, cfg.password, branch)
    print("Login correcto")
    claims = api.jwt_claims(token)
    resumen = {k: v for k, v in claims.items() if isinstance(v, (str, int, float)) and len(str(v)) < 80}
    if resumen:
        print(json.dumps(resumen, indent=2, ensure_ascii=False, default=str))


def cmd_reservas(args) -> None:
    cfg = cargar(args.config)
    _requiere_credenciales(cfg)
    session = api.new_session()
    branch = _branch(session, cfg)
    token, _ = api.login(session, cfg.email, cfg.password, branch)
    data = api.my_bookings(session, token)
    print(json.dumps(data, indent=2, ensure_ascii=False))


def ejecutar_reserva(session: requests.Session, token: str, activity: dict, branch: dict,
                     cfg: Config, esperar_apertura: bool, ventana_seg: float | None = None) -> bool:
    start = scheduler.parse_start(activity)
    open_at = start - timedelta(hours=cfg.apertura_horas)
    offset = scheduler.clock_offset(session)
    log.info("Offset del reloj frente al servidor: %+.1f s", offset.total_seconds())

    if esperar_apertura:
        objetivo = open_at - timedelta(seconds=cfg.adelanto_seg)
        falta = (objetivo - scheduler.ahora_corregida(offset)).total_seconds()
        if falta > 0:
            log.info("Esperando la apertura de %s (faltan %.0f s)", _nombre(activity), falta)
            scheduler.esperar_hasta(objetivo, offset)

    if scheduler.ya_reservada(session, token, activity):
        log.info("La clase %s ya estaba reservada", _nombre(activity))
        return True

    log.info("Disparando reserva de %s", _nombre(activity))
    res = scheduler.rafaga_reserva(session, token, activity, branch, cfg, ventana_seg=ventana_seg)
    nombre = _nombre(activity)
    if res["ok"]:
        log.info("RESERVA OK en %s intentos: %s", res["intentos"], nombre)
        confirmada = scheduler.ya_reservada(session, token, activity)
        log.info("Verificacion en mis reservas: %s", "confirmada" if confirmada else "aun no aparece")
        notificar(cfg.notificar_url, f"Reserva OK: {nombre}")
        return True
    log.error("Reserva fallida tras %s intentos: %s", res["intentos"], res.get("error"))
    notificar(cfg.notificar_url, f"Reserva FALLIDA: {nombre}: {res.get('error')}")
    return False


def _buscar_actividad(acts: list[dict], fecha: str, hora: str, clase: str) -> dict | None:
    for a in acts:
        if (a["start_time"][:10] == fecha
                and a["start_time"][11:16] == hora
                and a["activity_name"].strip().upper() == clase.upper()):
            return a
    return None


def cmd_reservar(args) -> None:
    cfg = cargar(args.config)
    _requiere_credenciales(cfg)
    session = api.new_session()
    branch = _branch(session, cfg)
    acts = scheduler.calendario_dos_semanas(session, branch)
    a = _buscar_actividad(acts, args.fecha, args.hora, args.clase)
    if not a:
        sys.exit("No encontre esa clase. Revisa fecha (YYYY-MM-DD), hora (HH:MM) y nombre con: python -m actionbot calendario")
    if a.get("status_name") != "Available":
        sys.exit(f"La clase {_nombre(a)} esta en estado {a.get('status_name')}, no se puede reservar")
    token, _ = api.login(session, cfg.email, cfg.password, branch)
    ok = ejecutar_reserva(session, token, a, branch, cfg, esperar_apertura=args.esperar,
                          ventana_seg=None if args.esperar else 30)
    sys.exit(0 if ok else 1)


def cmd_vigilar(args) -> None:
    cfg = cargar(args.config)
    _requiere_credenciales(cfg)
    session = api.new_session()
    branch = _branch(session, cfg)
    log.info("Vigilando sede %s. Objetivos: %s", branch["name"],
             " | ".join(",".join(o.clases) for o in cfg.objetivos))
    estado = cargar_estado()

    while True:
        try:
            acts = scheduler.calendario_dos_semanas(session, branch)
            targets = scheduler.objetivos_de_la_agenda(acts, cfg)
            ahora = datetime.now(timezone.utc)
            pendientes = [
                t for t in targets
                if scheduler.clave(t["activity"]) not in estado
                and t["start"] > ahora + timedelta(minutes=5)
            ]
            if not pendientes:
                log.info("Sin objetivos pendientes por ahora, vuelvo a revisar en 30 min")
                time.sleep(1800)
                continue

            t = pendientes[0]
            a = t["activity"]
            falta = (t["open_at"] - ahora).total_seconds()

            if falta > 150:
                dormir = min(falta - 120, 3600)
                log.info("Proximo objetivo: %s, abre %s, duermo %.0f s",
                         _nombre(a),
                         t["open_at"].astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                         dormir)
                time.sleep(dormir)
                continue

            # Ventana de disparo: refrescar la actividad, iniciar sesion y esperar al segundo exacto
            acts2 = scheduler.calendario_dos_semanas(session, branch)
            a2 = next((x for x in acts2 if scheduler.clave(x) == scheduler.clave(a)), None)
            if a2 is None or a2.get("status_name") != "Available":
                log.warning("La clase %s ya no aparece disponible, la salto", _nombre(a))
                estado[scheduler.clave(a)] = {"resultado": "no_disponible", "clase": _nombre(a),
                                              "ts": datetime.now().isoformat()}
                guardar_estado(estado)
                continue

            ventana = None
            if falta < -600:
                # La apertura paso hace rato, no hay carrera: intento corto por si queda cupo
                ventana = 20.0
            elif len(pendientes) > 1:
                separacion = (pendientes[1]["open_at"] - t["open_at"]).total_seconds()
                if separacion < cfg.rafaga_seg:
                    ventana = max(20.0, separacion - 5)

            token, _ = api.login(session, cfg.email, cfg.password, branch)
            ok = ejecutar_reserva(session, token, a2, branch, cfg, esperar_apertura=True,
                                  ventana_seg=ventana)
            estado[scheduler.clave(a)] = {"resultado": "ok" if ok else "fallo", "clase": _nombre(a),
                                          "ts": datetime.now().isoformat()}
            guardar_estado(estado)
            if args.una_vez:
                return
        except api.ApiError as e:
            log.error("Error de API en el ciclo: %s", e)
            time.sleep(60)
        except requests.RequestException as e:
            log.error("Error de red en el ciclo: %s", e)
            time.sleep(60)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="actionbot", description="Bot de reservas para clases de Action Black")
    p.add_argument("--config", default="config.yaml", help="Ruta del config.yaml (por defecto el del directorio actual)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sedes", help="Lista las sedes disponibles").set_defaults(fn=cmd_sedes)

    c = sub.add_parser("calendario", help="Muestra el calendario de la sede (semana actual y siguiente)")
    c.add_argument("--clase", help="Filtra por nombre de clase, ejemplo SAVAGE")
    c.set_defaults(fn=cmd_calendario)

    sub.add_parser("plan", help="Muestra que clases se reservarian y a que hora abre cada una").set_defaults(fn=cmd_plan)

    r = sub.add_parser("reservar", help="Reserva una clase puntual")
    r.add_argument("--fecha", required=True, help="Fecha de la clase, YYYY-MM-DD")
    r.add_argument("--hora", required=True, help="Hora de inicio de la clase, HH:MM")
    r.add_argument("--clase", required=True, help="Nombre de la clase, ejemplo SAVAGE")
    r.add_argument("--esperar", action="store_true",
                   help="Si la apertura aun no llega, espera y dispara a la hora exacta")
    r.set_defaults(fn=cmd_reservar)

    v = sub.add_parser("vigilar", help="Proceso continuo que reserva solo segun config.yaml")
    v.add_argument("--una-vez", action="store_true", dest="una_vez",
                   help="Procesa solo el proximo objetivo y termina")
    v.set_defaults(fn=cmd_vigilar)

    sub.add_parser("reservas", help="Lista tus reservas vigentes").set_defaults(fn=cmd_reservas)
    sub.add_parser("login-test", help="Prueba las credenciales del .env").set_defaults(fn=cmd_login_test)

    args = p.parse_args(argv)
    configurar_logging()
    try:
        args.fn(args)
    except KeyboardInterrupt:
        print("\nDetenido")


if __name__ == "__main__":
    main()
