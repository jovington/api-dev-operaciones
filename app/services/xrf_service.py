from datetime import datetime
from typing import Any

from bson import ObjectId
from fastapi import HTTPException
from pymongo.database import Database

XRF = 'PlantaXrf'


def _timestamp(value: Any) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    if not isinstance(value, str):
        return 0
    for fmt in ('%d/%m/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(value, fmt).timestamp()
        except ValueError:
            continue
    return 0


def _value(results: list[dict[str, Any]] | None, element: str) -> float:
    for item in results or []:
        if str(item.get('element', '')).upper() == element.upper():
            try:
                return float(item.get('result_ppm') or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def list_xrf(database: Database, limit: int | None = None, today: bool = False) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if today:
        from datetime import timedelta
        query['createdAt'] = {'$gte': datetime.utcnow() - timedelta(hours=24)}
    cursor = database[XRF].find(query).sort('createdAt', -1)
    if limit:
        cursor = cursor.limit(limit)
    documents = list(cursor)
    return {'total': len(documents), 'mediciones': [{key: str(value) if key == '_id' else value for key, value in document.items() if key != '_id'} for document in documents]}


def deactivate(database: Database, measurement_id: str, active: bool) -> dict[str, Any]:
    query: Any = {'$or': [{'ID': measurement_id}]}
    if ObjectId.is_valid(measurement_id):
        query['$or'].append({'_id': ObjectId(measurement_id)})
    result = database[XRF].update_one(query, {'$set': {'desactive_medicion': active}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail='Medición XRF no encontrada')
    return {'status': 'success', 'ID': measurement_id, 'desactive_medicion': active}


def export_rows(database: Database, limit: int) -> dict[str, Any]:
    documents = list(database[XRF].find().sort('createdAt', -1).limit(max(200, limit * 10)))
    active = sorted((doc for doc in documents if not doc.get('desactive_medicion', False)), key=lambda doc: _timestamp(doc.get('Fecha')))
    groups: list[list[dict[str, Any]]] = []
    for document in active:
        if not groups or _timestamp(document.get('Fecha')) - _timestamp(groups[-1][0].get('Fecha')) > 7 * 60:
            groups.append([document])
        else:
            groups[-1].append(document)
    rows = []
    for group in reversed(groups[-limit:]):
        profiles = {(doc.get('profile_name') or '').upper(): doc for doc in group}
        cf = next((doc for name, doc in profiles.items() if 'CF' in name), None)
        rc = next((doc for name, doc in profiles.items() if name == 'RC' or ('RC' in name and 'AC' not in name)), None)
        ac = next((doc for name, doc in profiles.items() if name == 'AC' or ('AC' in name and 'RC' not in name)), None)
        if not rc:
            rc = next((doc for name, doc in profiles.items() if 'RC' in name and 'AC' in name), None)
        if not ac:
            ac = rc
        cu_rc, cu_ac = _value((rc or {}).get('resultados_analiticos'), 'Cu'), _value((ac or {}).get('resultados_analiticos'), 'Cu')
        rows.append({'Dia_Hora': group[0].get('Fecha', ''), 'Turno': next((doc.get('Turno') for doc in group if doc.get('Turno')), '-'), 'Ids_Detalle': [{'ID': doc.get('ID'), 'Perfil': doc.get('profile_name'), 'N_Medicion': doc.get('reading_number')} for doc in group], 'Resumen_Calculado': {'Cu_CF_Pct': f'{_value((cf or {}).get("resultados_analiticos"), "Cu") / 10000:.2f}' if cf else '-', 'As_CF_Pct': f'{_value((cf or {}).get("resultados_analiticos"), "As") / 10000:.2f}' if cf else '-', 'Sb_CF_Ppm': f'{_value((cf or {}).get("resultados_analiticos"), "Sb"):.2f}' if cf else '-', 'Bi_CF_Ppm': f'{_value((cf or {}).get("resultados_analiticos"), "Bi"):.2f}' if cf else '-', 'Cu_RC_Ppm': f'{cu_rc:.2f}' if rc else '-', 'Cu_AC_Ppm': f'{cu_ac:.2f}' if ac else '-', 'Recuperacion_Cu': f'{((cu_rc - cu_ac) / cu_rc) * 100:.2f}%' if cu_rc > 0 and cu_ac > 0 else '-'}})
    return {'status': 'success', 'total_filas': len(rows), 'filas': rows}
