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

DIAS_NOMBRES = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]

# Respaldo local de reservas logradas por el bot. El endpoint de bookings
# a veces responde total_items > 0 con items vacios y no se puede confiar
# solo en el para saber si un dia ya quedo cubierto.
BOT_RESERVAS = Path("logs/bot_reservas.json")


def cargar_bot_reservas() -> dict:
    try:
        datos = json.loads(BOT_RESERVAS.read_text(encoding="utf-8"))
    except Exception:
        return {}
    limite = (datetime.now() - timedelta(days=15)).date().isoformat()
    return {f: v for f, v in datos.items() if f >= limite}


def guardar_bot_reservas(datos: dict) -> None:
    BOT_RESERVAS.parent.mkdir(exist_ok=True)
    BOT_RESERVAS.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")


def registrar_bot_reserva(fecha: str, activity: dict) -> None:
    datos = cargar_bot_reservas()
    datos[fecha] = {"clase": _nombre(activity), "ts": datetime.now().isoformat()}
    guardar_bot_reservas(datos)


def _bookings_items(bookings) -> list:
    if isinstance(bookings, dict):
        return bookings.get("items") or bookings.get("bookings") or []
    return bookings or []


def _bookings_saludable(bookings) -> bool:
    """El endpoint a veces responde total_items > 0 con items vacios.
    En ese estado no sirve para decidir si un dia esta cubierto."""
    items = _bookings_items(bookings)
    if items:
        return True
    if isinstance(bookings, dict):
        try:
            return int(bookings.get("total_items") or 0) == 0
        except (TypeError, ValueError):
            return False
    return False


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


def cmd_horarios(args) -> None:
    """Mapa semanal de horarios por clase, con las clases del plan marcadas."""
    cfg = cargar(args.config)
    session = api.new_session()
    branch = _branch(session, cfg)
    acts = scheduler.calendario_dos_semanas(session, branch)
    plan = cfg.plan

    mapa: dict[int, dict[str, set]] = {}
    for a in acts:
        wd = scheduler.parse_start(a).weekday()
        nombre = a["activity_name"].strip().upper()
        mapa.setdefault(wd, {}).setdefault(nombre, set()).add(a["start_time"][11:16])

    print(f"Horarios de {branch['name']} segun las proximas dos semanas. * = objetivo del plan")
    for wd in sorted(mapa):
        print(f"\n{DIAS_NOMBRES[wd]}")
        for clase in sorted(mapa[wd]):
            marcas = []
            for h in sorted(mapa[wd][clase]):
                es_plan = (clase in plan.prioridad
                           and wd in plan.dias
                           and plan.entre[0] <= h <= plan.entre[1])
                marcas.append(h + ("*" if es_plan else ""))
            print(f"  {clase:10} {' '.join(marcas)}")

    print("\nAperturas del plan: el bot dispara a la misma hora del dia anterior")
    for wd in sorted(mapa):
        if wd not in plan.dias:
            continue
        for clase in plan.prioridad:
            horas = sorted(h for h in mapa[wd].get(clase, set())
                           if plan.entre[0] <= h <= plan.entre[1])
            if horas:
                previo = DIAS_NOMBRES[(wd - 1) % 7]
                print(f"  {DIAS_NOMBRES[wd]:10} {clase:8} {horas[0]}  ->  disparo el {previo} a las {horas[0]}")
                break


def _cubierto_str(reserva: dict) -> str:
    return f"{reserva.get('activity_name')} {str(reserva.get('start_time'))[11:16]} (spot {reserva.get('spot_number') or '?'})"


def cmd_plan(args) -> None:
    cfg = cargar(args.config)
    session = api.new_session()
    branch = _branch(session, cfg)
    tz = ZoneInfo(branch["timezone"])
    por_fecha = scheduler.candidatos_por_dia(scheduler.calendario_dos_semanas(session, branch), cfg)
    if not por_fecha:
        print("Ningun dia del plan tiene clases candidatas, revisa config.yaml")
        return

    bookings = None
    if cfg.email and cfg.password:
        try:
            token, _ = api.login(session, cfg.email, cfg.password, branch)
            bookings = api.my_bookings(session, token)
        except Exception as e:
            print(f"(no pude consultar tus reservas: {e})")

    ahora = datetime.now(timezone.utc)
    print(f"Plan en {branch['name']}: una clase por dia, prioridad {' > '.join(cfg.plan.prioridad)}, franja {cfg.plan.entre[0]} a {cfg.plan.entre[1]}")
    for fecha in sorted(por_fecha):
        cands = [c for c in por_fecha[fecha] if scheduler.parse_start(c) > ahora]
        if not cands:
            continue
        reserva = scheduler.dia_cubierto(bookings, fecha) if bookings else None
        print(f"\n{fecha} ({DIAS_NOMBRES[scheduler.parse_start(cands[0]).weekday()]})")
        if reserva:
            print(f"  cubierto: ya tienes {_cubierto_str(reserva)}")
            continue
        for i, c in enumerate(cands):
            ap = scheduler.apertura_de(c, cfg)
            if ap <= ahora:
                cuando = "ventana abierta, entra al rescate"
            else:
                cuando = f"abre {ap.astimezone(tz):%Y-%m-%d %H:%M:%S}"
            rol = "principal" if i == 0 else "fallback"
            print(f"  {rol:9} {c['activity_name']:8} {c['start_time'][11:16]}  cupos {c['occupation']:>2}/{c['capacity']:<2} {c['status_name']:9} {cuando}")


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
    if esperar_apertura:
        open_at = scheduler.apertura_de(activity, cfg)
        offset = scheduler.clock_offset(session)
        log.info("Offset del reloj frente al servidor: %+.1f s", offset.total_seconds())
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
    log.warning("Reserva fallida tras %s intentos: %s", res["intentos"], res.get("error"))
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
    if a.get("status_name") not in ("Available", "Full"):
        sys.exit(f"La clase {_nombre(a)} esta en estado {a.get('status_name')}, no se puede reservar")
    token, _ = api.login(session, cfg.email, cfg.password, branch)
    ok = ejecutar_reserva(session, token, a, branch, cfg, esperar_apertura=args.esperar,
                          ventana_seg=None if args.esperar else 30)
    if ok:
        registrar_bot_reserva(a["start_time"][:10], a)
    else:
        notificar(cfg.notificar_url, f"Reserva FALLIDA: {_nombre(a)}")
    sys.exit(0 if ok else 1)


def secuencia_apertura(session: requests.Session, token: str, branch: dict, cfg: Config,
                       fecha: str, cands: list[dict]) -> dict | None:
    """Dispara la reserva del candidato principal a su hora exacta de apertura.
    Si falla, recorre los fallbacks: espera su apertura si aun no llega,
    o intenta de una si su ventana ya abrio. Devuelve la clase lograda."""
    principal = cands[0]
    log.info("Secuencia de apertura del %s: %s", fecha,
             " > ".join(f"{c['activity_name']} {c['start_time'][11:16]}" for c in cands))
    if ejecutar_reserva(session, token, principal, branch, cfg, esperar_apertura=True):
        return principal
    for c in cands[1:]:
        log.info("Fallback: %s", _nombre(c))
        if ejecutar_reserva(session, token, c, branch, cfg, esperar_apertura=True, ventana_seg=45):
            return c
    log.warning("El %s no se logro ninguna clase en la apertura, pasa al rescate", fecha)
    notificar(cfg.notificar_url, f"Apertura fallida el {fecha}, el bot queda buscando cupos liberados")
    return None


def cmd_vigilar(args) -> None:
    cfg = cargar(args.config)
    _requiere_credenciales(cfg)
    session = api.new_session()
    branch = _branch(session, cfg)
    log.info("Vigilando %s. Prioridad %s, franja %s a %s, dias %s. Rescate cada %g min: %s",
             branch["name"], " > ".join(cfg.plan.prioridad), cfg.plan.entre[0], cfg.plan.entre[1],
             ",".join(DIAS_NOMBRES[d][:3] for d in cfg.plan.dias),
             cfg.rescate.intervalo_min, "activo" if cfg.rescate.activo else "apagado")

    token: str | None = None
    aperturas_hechas: set[str] = set()
    cubiertos_avisados: set[str] = set()

    def obtener_token(forzar: bool = False) -> str:
        nonlocal token
        if token is None or forzar:
            token, _ = api.login(session, cfg.email, cfg.password, branch)
            log.info("Sesion iniciada")
        return token

    def bookings_actuales():
        try:
            return api.my_bookings(session, obtener_token())
        except api.ApiError as e:
            if e.status in (401, 403):
                return api.my_bookings(session, obtener_token(forzar=True))
            raise

    while True:
        try:
            acts = scheduler.calendario_dos_semanas(session, branch)
            por_fecha = scheduler.candidatos_por_dia(acts, cfg)
            bookings = bookings_actuales()
            saludable = _bookings_saludable(bookings)
            if not saludable:
                log.debug("El listado de reservas vino inconsistente (total > 0 con items vacios)")
            bot_res = cargar_bot_reservas()
            ahora = datetime.now(timezone.utc)

            proxima_apertura = None   # (open_at, fecha, cands)
            rescates = []             # (fecha, cands)
            for fecha in sorted(por_fecha):
                cands = [c for c in por_fecha[fecha]
                         if scheduler.parse_start(c) > ahora + timedelta(minutes=2)]
                if not cands:
                    continue

                reserva = scheduler.dia_cubierto(bookings, fecha)
                if reserva is None and fecha in bot_res:
                    if saludable:
                        # El bot habia reservado este dia y la reserva ya no existe:
                        # la cancelaron, vuelve a buscar clase para ese dia
                        log.warning("La reserva del %s (%s) ya no aparece, la cancelaron, vuelvo a buscar",
                                    fecha, bot_res[fecha].get("clase"))
                        notificar(cfg.notificar_url,
                                  f"Cancelaron tu reserva del {fecha}, el bot vuelve a buscar cupo")
                        bot_res.pop(fecha)
                        guardar_bot_reservas(bot_res)
                        cubiertos_avisados.discard(fecha)
                    else:
                        # Listado inconsistente: confia en el registro propio
                        reserva = {"activity_name": bot_res[fecha].get("clase"), "start_time": ""}

                if reserva:
                    if fecha not in cubiertos_avisados:
                        log.info("El %s ya esta cubierto: %s", fecha, _cubierto_str(reserva))
                        cubiertos_avisados.add(fecha)
                    continue
                cubiertos_avisados.discard(fecha)

                principal = next((c for c in cands if c.get("status_name") == "Available"), cands[0])
                open_at = scheduler.apertura_de(principal, cfg)
                if open_at > ahora and fecha not in aperturas_hechas:
                    if proxima_apertura is None or open_at < proxima_apertura[0]:
                        proxima_apertura = (open_at, fecha, cands)
                elif cfg.rescate.activo:
                    rescates.append((fecha, cands))

            # Disparo exacto si la proxima apertura esta encima
            if proxima_apertura:
                falta = (proxima_apertura[0] - datetime.now(timezone.utc)).total_seconds()
                if falta <= 150:
                    _, fecha, cands = proxima_apertura
                    ganada = secuencia_apertura(session, obtener_token(), branch, cfg, fecha, cands)
                    if ganada:
                        registrar_bot_reserva(fecha, ganada)
                    aperturas_hechas.add(fecha)
                    if args.una_vez:
                        return
                    continue

            # Rescate: busca cupos liberados en dias no cubiertos con la ventana ya abierta
            for fecha, cands in rescates:
                for c in cands:
                    if c.get("status_name") == "Finalized":
                        continue
                    if int(c.get("occupation") or 0) >= int(c.get("capacity") or 0):
                        continue
                    log.info("Rescate del %s: %s tiene %s/%s, intento",
                             fecha, _nombre(c), c["occupation"], c["capacity"])
                    if ejecutar_reserva(session, obtener_token(), c, branch, cfg,
                                        esperar_apertura=False, ventana_seg=15):
                        registrar_bot_reserva(fecha, c)
                        break

            # Cadencia: rescate cada intervalo_min, o hasta 2 min antes de la apertura
            espera = cfg.rescate.intervalo_min * 60 if cfg.rescate.activo else 1800
            detalle = "proximo ciclo de rescate" if rescates else "proxima revision"
            if proxima_apertura:
                falta = (proxima_apertura[0] - datetime.now(timezone.utc)).total_seconds()
                if falta - 120 < espera:
                    espera = max(5.0, falta - 120)
                    detalle = f"apertura del {proxima_apertura[1]} ({_nombre(proxima_apertura[2][0])})"
            log.info("Duermo %.0f s, %s", espera, detalle)
            if args.una_vez:
                return
            time.sleep(espera)
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

    sub.add_parser("horarios", help="Mapa semanal de horarios por clase y aperturas del plan").set_defaults(fn=cmd_horarios)
    sub.add_parser("plan", help="Que reservaria el bot cada dia y a que hora abre").set_defaults(fn=cmd_plan)

    r = sub.add_parser("reservar", help="Reserva una clase puntual")
    r.add_argument("--fecha", required=True, help="Fecha de la clase, YYYY-MM-DD")
    r.add_argument("--hora", required=True, help="Hora de inicio de la clase, HH:MM")
    r.add_argument("--clase", required=True, help="Nombre de la clase, ejemplo SAVAGE")
    r.add_argument("--esperar", action="store_true",
                   help="Si la apertura aun no llega, espera y dispara a la hora exacta")
    r.set_defaults(fn=cmd_reservar)

    v = sub.add_parser("vigilar", help="Proceso continuo: aperturas exactas mas rescate de cupos liberados")
    v.add_argument("--una-vez", action="store_true", dest="una_vez",
                   help="Ejecuta un solo ciclo y termina")
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
