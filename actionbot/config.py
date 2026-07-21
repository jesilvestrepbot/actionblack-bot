"""Carga y validacion de config.yaml y credenciales del .env."""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
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
class PlanDiario:
    dias: list[int] = field(default_factory=lambda: list(range(7)))
    prioridad: list[str] = field(default_factory=list)
    entre: tuple[str, str] = ("00:00", "23:59")
    entre_festivos: tuple[str, str] = ("00:00", "23:59")
    festivos: set[str] = field(default_factory=set)


@dataclass
class Rescate:
    activo: bool = True
    intervalo_min: float = 15.0


@dataclass
class Config:
    sede: str
    apertura_horas: float
    plan: PlanDiario
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

    plan_raw = raw.get("plan_diario") or {}
    prioridad = [str(c).strip().upper() for c in (plan_raw.get("prioridad") or [])]
    if not prioridad:
        raise ValueError("config.yaml necesita plan_diario.prioridad con al menos una clase")
    entre_raw = plan_raw.get("entre") or ["00:00", "23:59"]
    if len(entre_raw) != 2:
        raise ValueError('plan_diario.entre debe tener dos horas, ejemplo ["06:00", "07:00"]')
    entre_fest_raw = plan_raw.get("entre_festivos") or entre_raw
    if len(entre_fest_raw) != 2:
        raise ValueError('plan_diario.entre_festivos debe tener dos horas, ejemplo ["07:00", "09:00"]')
    festivos = set()
    for f in raw.get("festivos") or []:
        fecha = str(f).strip()[:10]
        try:
            datetime.strptime(fecha, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Festivo invalido: {f}, usa formato YYYY-MM-DD")
        festivos.add(fecha)
    plan = PlanDiario(
        dias=[_parse_dia(d) for d in (plan_raw.get("dias") or [])] or list(range(7)),
        prioridad=prioridad,
        entre=(_parse_hhmm(entre_raw[0]), _parse_hhmm(entre_raw[1])),
        entre_festivos=(_parse_hhmm(entre_fest_raw[0]), _parse_hhmm(entre_fest_raw[1])),
        festivos=festivos,
    )

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
