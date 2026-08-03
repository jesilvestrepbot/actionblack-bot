"""Carga y validacion de config.yaml y credenciales del .env."""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

DIAS = {"lun": 0, "mar": 1, "mie": 2, "jue": 3, "vie": 4, "sab": 5, "dom": 6}


def _sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _parse_dia(d: str) -> int:
    key = _sin_acentos(str(d).strip().lower())[:3]
    if key not in DIAS:
        raise ValueError(f"Dia no reconocido: {d} (usa lun, mar, mie, jue, vie, sab, dom)")
    return DIAS[key]


def _parse_hhmm(h: str) -> str:
    partes = str(h).strip().split(":")
    if len(partes) != 2 or not partes[0].isdigit() or not partes[1].isdigit():
        raise ValueError(f"Hora invalida: {h}, usa formato HH:MM")
    return f"{int(partes[0]):02d}:{int(partes[1]):02d}"


@dataclass
class ClaseObjetivo:
    clase: str
    hora: str  # "HH:MM"


@dataclass
class PlanSemanal:
    # dia de la semana (0=lunes) -> opciones en orden de preferencia.
    # Los dias que no esten aqui no se reservan.
    por_dia: dict[int, list[ClaseObjetivo]] = field(default_factory=dict)


@dataclass
class Rescate:
    activo: bool = True
    intervalo_min: float = 15.0


@dataclass
class Config:
    sede: str
    apertura_horas: float
    plan: PlanSemanal
    rescate: Rescate
    email: str
    password: str
    adelanto_seg: float = 2.0
    rafaga_seg: float = 120.0
    intervalo_seg: float = 0.5
    notificar_url: str | None = None


def cargar(path: str | Path = "config.yaml") -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}. Copia config.yaml al directorio de trabajo.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    load_dotenv(path.resolve().parent / ".env")
    email = os.environ.get("ACTION_EMAIL", "").strip()
    password = os.environ.get("ACTION_PASSWORD", "").strip()

    plan_raw = raw.get("plan_semanal") or {}
    por_dia: dict[int, list[ClaseObjetivo]] = {}
    for dia_str, opciones in plan_raw.items():
        wd = _parse_dia(dia_str)
        if isinstance(opciones, dict):
            opciones = [opciones]
        lista: list[ClaseObjetivo] = []
        for o in opciones or []:
            clase = str(o.get("clase") or "").strip().upper()
            if not clase or not o.get("hora"):
                raise ValueError(f"plan_semanal.{dia_str}: cada objetivo necesita clase y hora")
            lista.append(ClaseObjetivo(clase=clase, hora=_parse_hhmm(o["hora"])))
        if lista:
            por_dia[wd] = lista
    if not por_dia:
        raise ValueError("config.yaml necesita plan_semanal con al menos un dia (ejemplo: mie: [{clase: TONIC, hora: '12:10'}])")
    plan = PlanSemanal(por_dia=por_dia)

    rescate_raw = raw.get("rescate") or {}
    rescate = Rescate(
        activo=bool(rescate_raw.get("activo", True)),
        intervalo_min=float(rescate_raw.get("intervalo_min", 15)),
    )

    sede = str(raw.get("sede") or "").strip()
    if not sede:
        raise ValueError("config.yaml necesita el campo sede")

    return Config(
        sede=sede,
        apertura_horas=float(raw.get("apertura_horas", 24)),
        plan=plan,
        rescate=rescate,
        email=email,
        password=password,
        adelanto_seg=float(raw.get("adelanto_seg", 2.0)),
        rafaga_seg=float(raw.get("rafaga_seg", 120)),
        intervalo_seg=float(raw.get("intervalo_seg", 0.5)),
        notificar_url=(raw.get("notificar_url") or None),
    )
