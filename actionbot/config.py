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
class Objetivo:
    clases: list[str]
    dias: list[int] = field(default_factory=list)
    horas: list[str] = field(default_factory=list)
    entre: tuple[str, str] | None = None
    max_por_dia: int = 1


@dataclass
class Config:
    sede: str
    apertura_horas: float
    objetivos: list[Objetivo]
    email: str
    password: str
    adelanto_seg: float = 2.0
    rafaga_seg: float = 180.0
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

    objetivos: list[Objetivo] = []
    for o in raw.get("objetivos", []):
        clases = o.get("clases") or ([o["clase"]] if o.get("clase") else [])
        if not clases:
            raise ValueError("Cada objetivo necesita el campo clase o clases")
        entre = None
        if o.get("entre"):
            if len(o["entre"]) != 2:
                raise ValueError('El campo entre debe tener dos horas, ejemplo ["05:00", "07:00"]')
            entre = (_parse_hhmm(o["entre"][0]), _parse_hhmm(o["entre"][1]))
        objetivos.append(
            Objetivo(
                clases=[str(c).strip().upper() for c in clases],
                dias=[_parse_dia(d) for d in (o.get("dias") or [])],
                horas=[_parse_hhmm(h) for h in (o.get("horas") or [])],
                entre=entre,
                max_por_dia=int(o.get("max_por_dia", 1)),
            )
        )
    if not objetivos:
        raise ValueError("config.yaml no tiene objetivos definidos")

    sede = str(raw.get("sede") or "").strip()
    if not sede:
        raise ValueError("config.yaml necesita el campo sede")

    return Config(
        sede=sede,
        apertura_horas=float(raw.get("apertura_horas", 24)),
        objetivos=objetivos,
        email=email,
        password=password,
        adelanto_seg=float(raw.get("adelanto_seg", 2.0)),
        rafaga_seg=float(raw.get("rafaga_seg", 180)),
        intervalo_seg=float(raw.get("intervalo_seg", 0.5)),
        notificar_url=(raw.get("notificar_url") or None),
    )
