from math import isfinite
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from pymongo.database import Database

from app.db.planta_repo import find_latest_cinta_4_speed, find_latest_plc_reading, find_plc_readings
from app.models.alimentacion_planta import Cinta4Speed


def get_latest_plc_reading(database: Database) -> dict[str, Any]:
    reading = find_latest_plc_reading(database)
    if reading is None:
        raise HTTPException(status_code=404, detail='No hay lecturas del PLC disponibles.')
    return _normalize_non_finite_numbers(reading)


def get_plc_readings(
    database: Database,
    fecha_inicio: datetime | None = None,
    fecha_fin: datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return [_normalize_non_finite_numbers(item) for item in find_plc_readings(database, fecha_inicio, fecha_fin, limit)]


def get_cinta_4_speed(database: Database) -> Cinta4Speed:
    reading = find_latest_cinta_4_speed(database)
    if reading is None:
        raise HTTPException(status_code=503, detail='La velocidad de Cinta 4 no está disponible.')
    speed = reading.get('fields', {}).get('toneladas_Bascula_Cinta_4')
    if not isinstance(speed, (int, float)) or isinstance(speed, bool) or not isfinite(speed) or speed <= 0:
        raise HTTPException(status_code=503, detail='La velocidad de Cinta 4 no está disponible.')
    return Cinta4Speed(toneladasHora=speed, fecha=reading['timestamp'])


def _normalize_non_finite_numbers(value: Any) -> Any:
    if isinstance(value, float):
        return value if isfinite(value) else None
    if isinstance(value, dict):
        return {
            field_name: _normalize_non_finite_numbers(field_value)
            for field_name, field_value in value.items()
        }
    if isinstance(value, list):
        return [_normalize_non_finite_numbers(item) for item in value]
    return value