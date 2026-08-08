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
from .notify import avisar, configurar_logging, notificar_email

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
        obj_set = {(o.clase, o.hora) for o in plan.por_dia.get(wd, [])}
        print(f"\n{DIAS_NOMBRES[wd]}")
        for clase in sorted(mapa[wd]):
            marcas = []
            for h in sorted(mapa[wd][clase]):
                marcas.append(h + ("*" if (clase, h) in obj_set else ""))
            print(f"  {clase:10} {' '.join(marcas)}")

    print("\nPlan semanal (dispara el dia anterior a la misma hora de la clase):")
    for wd in sorted(plan.por_dia):
        previo = DIAS_NOMBRES[(wd - 1) % 7]
        for i, o in enumerate(plan.por_dia[wd]):
            rol = "principal" if i == 0 else "fallback "
            print(f"  {DIAS_NOMBRES[wd]:10} {rol} {o.clase:7} {o.hora}  ->  disparo el {previo} a las {o.hora}")


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
    dias_txt = ", ".join(f"{DIAS_NOMBRES[wd][:3]} {'/'.join(o.clase + ' ' + o.hora for o in ops)}"
                         for wd, ops in sorted(cfg.plan.por_dia.items()))
    print(f"Plan en {branch['name']}: horario exacto por dia -> {dias_txt}")
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


def cmd_probar_correo(args) -> None:
    cfg = cargar(args.config)
    if not cfg.notificar_email:
        sys.exit("config.yaml no tiene notificar_email")
    ok = notificar_email(cfg.notificar_email, "ActionBot: prueba de correo",
                         "Los avisos del bot de reservas estan funcionando.")
    if ok:
        print(f"Correo de prueba enviado a {cfg.notificar_email}, revisa la bandeja")
    else:
        sys.exit("No se envio. Falta GMAIL_APP_PASSWORD en el .env (contrasena de aplicacion de Gmail) o fallo el envio, revisa el log")


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
    nombre = _nombre(activity)
    open_at = scheduler.apertura_de(activity, cfg)
    offset = timedelta(0)
    if esperar_apertura:
        offset = scheduler.clock_offset(session)
        log.info("Offset del reloj frente al servidor: %+.1f s", offset.total_seconds())
        objetivo = open_at - timedelta(seconds=cfg.adelanto_seg)
        falta = (objetivo - scheduler.ahora_corregida(offset)).total_seconds()
        if falta > 0:
            log.info("Esperando la apertura de %s (faltan %.0f s)", nombre, falta)
            scheduler.esperar_hasta(objetivo, offset)

    if scheduler.ya_reservada(session, token, activity):
        log.info("La clase %s ya estaba reservada", nombre)
        return True

    log.info("Disparando reserva de %s", nombre)
    res = scheduler.rafaga_reserva(session, token, activity, branch, cfg, ventana_seg=ventana_seg)

    # Cuenta penalizada: el gimnasio bloquea los primeros 5 minutos de la
    # ventana de reserva. Se espera a que pase la sancion y se reintenta.
    if not res["ok"] and getattr(res.get("error"), "code", "") == "USER_PENALIZED_ERROR":
        reintento = open_at + timedelta(minutes=5, seconds=4)
        margen = (reintento - scheduler.ahora_corregida(offset)).total_seconds()
        if margen > -600:
            if margen > 0:
                log.info("Cuenta penalizada: bloqueo de los primeros 5 min de la ventana. "
                         "Reintento en %.0f s", margen)
                scheduler.esperar_hasta(reintento, offset)
            log.info("Reintento tras la sancion de 5 min: %s", nombre)
            res = scheduler.rafaga_reserva(session, token, activity, branch, cfg, ventana_seg=40)

    if res["ok"]:
        log.info("RESERVA OK en %s intentos: %s", res["intentos"], nombre)
        confirmada = scheduler.ya_reservada(session, token, activity)
        log.info("Verificacion en mis reservas: %s", "confirmada" if confirmada else "aun no aparece")
        avisar(cfg, f"Reserva OK: {nombre}")
        return True

    err = res.get("error")
    log.warning("Reserva fallida tras %s intentos: %s", res["intentos"], err)
    codigo = getattr(err, "code", "")
    if codigo == "USER_PENALIZED_ERROR":
        avisar(cfg, f"No se pudo reservar {nombre}: la cuenta sigue penalizada despues de los 5 min")
    elif codigo == "NO_AVAILABLE_SLOTS":
        avisar(cfg, f"No se pudo reservar {nombre}: la clase se lleno (la sancion de 5 min dejo pasar los cupos)")
    return False


def _buscar_actividad(acts: list[dict], fecha: str, hora: str, clase: str) -> dict | None:
    for a in acts:
        if (a["start_time"][:10] == fecha
                and a["start_time"][11:16] == hora
                and a["activity_name"].strip().upper() == clase.upper()):
            return a
    return None


def cmd_reservar(args) -> None:
    t0 = time.monotonic()
    cfg = cargar(args.config)
    _requiere_credenciales(cfg)
    session = api.new_session()
    branch = _branch(session, cfg)
    log.info("Sede resuelta en %.1f s", time.monotonic() - t0)
    t1 = time.monotonic()
    # Solo la semana de la fecha pedida, para no perder tiempo
    acts = api.get_calendar(session, branch, args.fecha)
    a = _buscar_actividad(acts, args.fecha, args.hora, args.clase)
    if not a:
        sys.exit("No encontre esa clase. Revisa fecha (YYYY-MM-DD), hora (HH:MM) y nombre con: python -m actionbot calendario")
    if a.get("status_name") not in ("Available", "Full"):
        sys.exit(f"La clase {_nombre(a)} esta en estado {a.get('status_name')}, no se puede reservar")
    log.info("Calendario consultado en %.1f s", time.monotonic() - t1)
    t2 = time.monotonic()
    token, _ = api.login(session, cfg.email, cfg.password, branch)
    log.info("Login en %.1f s", time.monotonic() - t2)
    ok = ejecutar_reserva(session, token, a, branch, cfg, esperar_apertura=args.esperar,
                          ventana_seg=None if args.esperar else 30)
    log.info("Tiempo total del comando: %.1f s", time.monotonic() - t0)
    if ok:
        registrar_bot_reserva(a["start_time"][:10], a)
    else:
        avisar(cfg, f"Reserva FALLIDA: {_nombre(a)}")
    sys.exit(0 if ok else 1)


def cmd_cazar(args) -> None:
    """Caza enfocada de una clase concreta para una fecha, franja horaria opcional.
    Corre en bucle hasta conseguir cupo, hasta que pasen todas las clases del
    rango, o hasta que lo detengan. Pensado para cuando la clase ya esta llena
    y solo queda esperar a que alguien cancele. No toca el dia si ya tienes una
    reserva (respeta una clase por dia): espera a que canceles la otra."""
    cfg = cargar(args.config)
    _requiere_credenciales(cfg)
    session = api.new_session()
    branch = _branch(session, cfg)
    intervalo = max(30.0, args.intervalo_min * 60)
    tz = ZoneInfo(branch["timezone"])

    # Dos modos: objetivos exactos (CLASE:HH:MM, en orden de preferencia) o
    # una clase en una franja horaria.
    objetivos_spec: list[tuple[str, str]] | None = None
    if getattr(args, "objetivo", None):
        objetivos_spec = []
        for spec in args.objetivo:
            partes = spec.split(":")
            if len(partes) < 3 or not partes[1].isdigit() or not partes[2].isdigit():
                sys.exit(f"--objetivo invalido: {spec}. Usa CLASE:HH:MM, ejemplo TONIC:08:15")
            objetivos_spec.append((partes[0].strip().upper(), f"{int(partes[1]):02d}:{int(partes[2]):02d}"))
        descr = " > ".join(f"{c} {h}" for c, h in objetivos_spec)
    else:
        if not args.clase:
            sys.exit("Falta --clase (o usa --objetivo CLASE:HH:MM, repetible)")
        clase = args.clase.strip().upper()
        desde = args.desde or "00:00"
        hasta = args.hasta or "23:59"
        descr = f"{clase} {desde}-{hasta}"

    log.info("Cazando %s para %s, sede %s. Reviso cada %g min",
             descr, args.fecha, branch["name"], args.intervalo_min)

    def candidatos(acts: list[dict]) -> list[dict]:
        """Clases objetivo del dia, en orden de preferencia."""
        if objetivos_spec is not None:
            orden: list[tuple[int, dict]] = []
            for pri, (cl, hr) in enumerate(objetivos_spec):
                for a in acts:
                    if (a["start_time"][:10] == args.fecha
                            and a["activity_name"].strip().upper() == cl
                            and a["start_time"][11:16] == hr
                            and a.get("status_name") != "Canceled"):
                        orden.append((pri, a))
            orden.sort(key=lambda t: t[0])
            return [a for _, a in orden]
        objs = [a for a in acts
                if a["start_time"][:10] == args.fecha
                and a["activity_name"].strip().upper() == clase
                and desde <= a["start_time"][11:16] <= hasta
                and a.get("status_name") != "Canceled"]
        objs.sort(key=lambda a: a["start_time"])
        return objs

    token: str | None = None

    def tok(forzar: bool = False) -> str:
        nonlocal token
        if token is None or forzar:
            token, _ = api.login(session, cfg.email, cfg.password, branch)
        return token

    while True:
        try:
            acts = api.get_calendar(session, branch, args.fecha)
            objetivos = candidatos(acts)
            if not objetivos:
                log.warning("No hay clases objetivo (%s) en %s, nada que cazar", descr, args.fecha)
                return
            futuras = [a for a in objetivos if scheduler.parse_start(a) > datetime.now(tz)]
            if not futuras:
                log.warning("Ya pasaron todas las clases objetivo de %s, termino sin conseguir cupo", args.fecha)
                avisar(cfg, f"No se consiguio clase para {args.fecha}, ya pasaron todas")
                return

            # Cobertura del dia: NO nos fiamos del contador total_items, su
            # endpoint es poco fiable (se queda pegado en 1 con lista vacia,
            # incluso despues de cancelar). Solo respetamos "una clase por dia"
            # si REALMENTE podemos ver una reserva de ese dia en la lista.
            # Si no, vamos por la clase: el gimnasio solo rechaza (OVERLAPPING)
            # cuando el horario se cruza con otra reserva, no por ser dos.
            data = api.my_bookings(session, tok())
            items = (data.get("items") or []) if isinstance(data, dict) else (data or [])
            total = int(data.get("total_items") or 0) if isinstance(data, dict) else len(items)
            mismo_dia = [it for it in items if isinstance(it, dict)
                         and str(it.get("start_time"))[:10] == args.fecha
                         and (it.get("status_name") or "").lower() == "booked"]
            if mismo_dia:
                otras = ", ".join(f'{it.get("activity_name")} {str(it.get("start_time"))[11:16]}' for it in mismo_dia)
                log.info("Ya tienes clase ese dia (%s), respeto una por dia. No reservo, reviso en %g min",
                         otras, args.intervalo_min)
                time.sleep(intervalo)
                continue
            if total >= 1 and not items:
                log.info("El contador del gimnasio dice %s reserva(s) pero no me deja verlas (bug de su endpoint). "
                         "Voy por la clase igual; solo se rechazaria si el horario se cruza con otra clase tuya", total)

            disponibles = [a for a in futuras
                           if a.get("status_name") == "Available"
                           and int(a.get("occupation") or 0) < int(a.get("capacity") or 0)]
            if disponibles:
                obj = disponibles[0]
                log.info("Cupo detectado en %s (%s/%s), disparo reserva",
                         _nombre(obj), obj["occupation"], obj["capacity"])
                res = scheduler.rafaga_reserva(session, tok(), obj, branch, cfg, ventana_seg=20)
                if res["ok"]:
                    log.info("CAZADA: %s", _nombre(obj))
                    registrar_bot_reserva(args.fecha, obj)
                    avisar(cfg, f"Cazada {_nombre(obj)}")
                    return
                err = res.get("error")
                if getattr(err, "code", "") == "ACTIVITIES_OVERLAPPING":
                    log.warning("Tienes otra clase que cruza ese horario; cancela esa si la quieres. Sigo revisando")
                else:
                    log.warning("No entro (%s), sigo cazando", err)
            else:
                estados = ", ".join(f'{a["activity_name"]} {a["start_time"][11:16]} {a["occupation"]}/{a["capacity"]}' for a in futuras)
                log.info("Aun sin cupo (%s). Reviso en %g min", estados, args.intervalo_min)
            time.sleep(intervalo)
        except api.ApiError as e:
            if e.status in (401, 403):
                tok(forzar=True)
                continue
            log.error("Error de API cazando: %s", e)
            time.sleep(60)
        except requests.RequestException as e:
            log.error("Error de red cazando: %s", e)
            time.sleep(60)


def cmd_sesion(args) -> None:
    """Una sesion de reserva que corre una vez y se cierra sola. Busca el
    proximo dia sin cubrir, y:
      - si su apertura esta cerca (dentro de max_espera), espera al segundo
        exacto, reserva con prioridad y fallbacks, y termina;
      - si la apertura ya paso (arranque tarde), caza cupo hasta que empiece
        la clase o se agote max_espera;
      - si la apertura esta lejos, se cierra para que la tarea la relance.
    Pensada para una tarea programada diaria: se despierta cerca de la hora
    de reserva, hace su trabajo y se apaga. No es un demonio 24/7."""
    cfg = cargar(args.config)
    _requiere_credenciales(cfg)
    session = api.new_session()
    branch = _branch(session, cfg)
    token, _ = api.login(session, cfg.email, cfg.password, branch)
    acts = scheduler.calendario_dos_semanas(session, branch)
    por_fecha = scheduler.candidatos_por_dia(acts, cfg)
    bot_res = cargar_bot_reservas()
    try:
        bookings = api.my_bookings(session, token)
    except Exception:
        bookings = {}
    ahora = datetime.now(timezone.utc)
    max_espera = max(60.0, args.max_espera_min * 60)

    def cubierto(fecha: str) -> bool:
        # Fuente principal: registro propio del bot (fiable). Secundaria: la
        # lista de reservas del gym cuando el endpoint la devuelve (intermitente).
        if fecha in bot_res:
            return True
        return scheduler.dia_cubierto(bookings, fecha) is not None

    objetivo = None
    for fecha in sorted(por_fecha):
        cands = [c for c in por_fecha[fecha] if scheduler.parse_start(c) > ahora]
        if not cands or cubierto(fecha):
            continue
        objetivo = (fecha, cands)
        break
    if objetivo is None:
        log.info("Nada por reservar: los proximos dias del plan ya estan cubiertos")
        return

    fecha, cands = objetivo
    principal = cands[0]
    open_at = scheduler.apertura_de(principal, cfg)
    espera = (open_at - ahora).total_seconds()
    if espera > max_espera:
        log.info("Proxima apertura: %s, abre en %.0f min (limite %g min). Me cierro; la tarea diaria me relanza mas cerca.",
                 _nombre(principal), espera / 60, args.max_espera_min)
        return

    ganada = None
    if espera > 0:
        log.info("Apertura de %s en %.0f s. Espero y disparo.", _nombre(principal), espera)
        ganada = secuencia_apertura(session, token, branch, cfg, fecha, cands)
    else:
        fin = time.monotonic() + max_espera
        inicio_clase = scheduler.parse_start(principal)
        log.info("La apertura de %s ya paso; cazo cupo hasta %g min o hasta que empiece la clase",
                 fecha, args.max_espera_min)
        while ganada is None and time.monotonic() < fin and datetime.now(timezone.utc) < inicio_clase - timedelta(minutes=2):
            acts2 = api.get_calendar(session, branch, fecha)
            for c in cands:
                a2 = next((x for x in acts2 if scheduler.clave(x) == scheduler.clave(c)), None)
                if a2 and a2.get("status_name") == "Available" \
                        and int(a2.get("occupation") or 0) < int(a2.get("capacity") or 0):
                    if scheduler.rafaga_reserva(session, token, a2, branch, cfg, ventana_seg=20)["ok"]:
                        ganada = a2
                        break
            if ganada is None:
                time.sleep(cfg.rescate.intervalo_min * 60)

    if ganada:
        registrar_bot_reserva(fecha, ganada)
        log.info("Sesion completada, reservado: %s", _nombre(ganada))
        avisar(cfg, f"Reserva OK: {_nombre(ganada)}")
    else:
        log.warning("Sesion sin exito para %s (se cerro la clase o no hubo cupo)", fecha)
        avisar(cfg, f"Sin exito reservando para {fecha}")


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
    avisar(cfg, f"Apertura fallida el {fecha}, el bot queda buscando cupos liberados")
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
                        avisar(cfg, f"Cancelaron tu reserva del {fecha}, el bot vuelve a buscar cupo")
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

    s = sub.add_parser("sesion", help="Reserva el proximo dia sin cubrir y se cierra (para tarea diaria)")
    s.add_argument("--max-espera-min", type=float, default=150.0, dest="max_espera_min",
                   help="Si la proxima apertura esta a mas de estos minutos, se cierra (por defecto 150)")
    s.set_defaults(fn=cmd_sesion)

    z = sub.add_parser("cazar", help="Caza enfocada de clases para una fecha (espera cupo liberado)")
    z.add_argument("--fecha", required=True, help="Fecha de la clase, YYYY-MM-DD")
    z.add_argument("--objetivo", action="append",
                   help="Objetivo exacto CLASE:HH:MM, repetible en orden de preferencia. "
                        "Ej: --objetivo TONIC:08:15 --objetivo SAVAGE:07:15")
    z.add_argument("--clase", help="Modo simple: nombre de clase (usa --desde/--hasta). Alternativa a --objetivo")
    z.add_argument("--desde", help="Hora minima de inicio, HH:MM (modo --clase)")
    z.add_argument("--hasta", help="Hora maxima de inicio, HH:MM (modo --clase)")
    z.add_argument("--intervalo-min", type=float, default=5.0, dest="intervalo_min",
                   help="Cada cuantos minutos revisar si se libero cupo (por defecto 5)")
    z.set_defaults(fn=cmd_cazar)

    sub.add_parser("reservas", help="Lista tus reservas vigentes").set_defaults(fn=cmd_reservas)
    sub.add_parser("login-test", help="Prueba las credenciales del .env").set_defaults(fn=cmd_login_test)
    sub.add_parser("probar-correo", help="Envia un correo de prueba con la config actual").set_defaults(fn=cmd_probar_correo)

    args = p.parse_args(argv)
    configurar_logging()
    try:
        args.fn(args)
    except KeyboardInterrupt:
        print("\nDetenido")


if __name__ == "__main__":
    main()
