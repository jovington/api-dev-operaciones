import hashlib
import logging
import math
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from pymongo.database import Database

PARTES = 'PartesOperacionPlanta'
USUARIOS = 'UsuariosPlanta'
TEMPLATES = 'PartesOperacionPlantaTemplate'
SESIONES = 'sesiones'
MEDICIONES = 'bascula'
UPLOAD_DIR = Path('/app/uploads/partes')
logger = logging.getLogger(__name__)


def _clean(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def list_measurements(database: Database, limit: int) -> list[dict[str, Any]]:
    documents = list(database[MEDICIONES].find().sort('Fecha', -1).limit(limit))
    return jsonable_encoder([_clean(document) for document in documents])


def list_blending(database: Database, limit: int) -> list[dict[str, Any]]:
    documents = database['HistoricoBlending'].find(
        {'metadata.fecha_reporte': {'$type': 'date'}}
    ).sort('metadata.fecha_reporte', -1).limit(limit)
    return [_clean(document) for document in documents]


def save_user(database: Database, payload: dict[str, Any]) -> dict[str, Any]:
    existing = database[USUARIOS].find_one({'N_Empleado': payload['N_Empleado']})
    password = payload.get('password')
    if password and not password.startswith('sha256$'):
        payload['password'] = 'sha256$' + hashlib.sha256(password.encode()).hexdigest()
    elif existing and existing.get('password'):
        payload['password'] = existing['password']
    if not payload.get('qr_token') or payload.pop('regenerar_qr', False) or payload.pop('forzar_actualizacion_token', False):
        payload['qr_token'] = secrets.token_hex(16)
    payload.setdefault('createdAt', existing.get('createdAt') if existing else datetime.now(timezone.utc))
    if existing:
        database[USUARIOS].update_one({'N_Empleado': payload['N_Empleado']}, {'$set': payload})
        message = 'Usuario actualizado correctamente'
    else:
        result = database[USUARIOS].insert_one(payload)
        payload['id_documento_mongo'] = str(result.inserted_id)
        message = 'Usuario creado correctamente'
    payload.pop('password', None)
    return {'mensaje': message, **_clean(payload)}


def authenticate(database: Database, *, n_empleado: int | None = None, password: str | None = None, qr_token: str | None = None) -> dict[str, Any]:
    user = database[USUARIOS].find_one({'qr_token': qr_token} if qr_token else {'N_Empleado': n_empleado})
    if not user or user.get('Estado', user.get('active', 'Activo')) not in ('Activo', True):
        raise HTTPException(status_code=401, detail='Usuario no válido o inactivo')
    if password is not None:
        expected = 'sha256$' + hashlib.sha256(password.encode()).hexdigest()
        if user.get('password') not in (expected, password):
            raise HTTPException(status_code=401, detail='Contraseña incorrecta')
    token = secrets.token_hex(32)
    now = datetime.now(timezone.utc)
    database[SESIONES].insert_one({'token': token, 'n_empleado': user.get('N_Empleado'), 'createdAt': now, 'expires_at': now + timedelta(hours=12)})
    return {'status': 'success', 'token_sesion': token, 'operador': {'nombre': user.get('Nombre', user.get('displayName')), 'n_empleado': user.get('N_Empleado'), 'Perfil': user.get('Perfil', user.get('role')), 'departamentos': user.get('departamentos', [])}}


def sync_checklist(database: Database, payload: dict[str, Any]) -> dict[str, str]:
    part_id = payload.get('ID') or payload.get('id_parte') or payload.get('id_partes')
    part_type = payload.get('Tipo_Parte') or payload.get('tipo_parte')
    if not part_id:
        raise HTTPException(status_code=422, detail='El campo ID es obligatorio')
    if len(part_id) != 6:
        raise HTTPException(status_code=422, detail='El campo ID debe tener exactamente 6 caracteres')
    if not part_type:
        raise HTTPException(status_code=422, detail='El campo Tipo_Parte es obligatorio')
    if database[PARTES].find_one({'ID': part_id}, {'_id': 1}):
        return {'status': 'ok', 'message': 'El parte ya había sido sincronizado previamente.', 'ID': part_id, 'id_parte': part_id}
    payload['ID'] = part_id
    payload['Tipo_Parte'] = part_type
    payload['createdAt'] = payload.get('createdAt') or datetime.now(timezone.utc)
    payload['Fecha'] = payload.get('Fecha') or payload.get('fecha_creacion')
    payload['Turno'] = payload.get('Turno') or payload.get('cabecera', {}).get('Turno')
    payload['datos'] = payload.get('datos') or [{'titulo': 'Checklist', 'items': payload.get('items', [])}]
    for key in ('id_parte', 'id_partes', 'tipo_parte', 'fecha_creacion', 'items'):
        payload.pop(key, None)
    if isinstance(payload.get('cabecera'), dict):
        payload['cabecera'].update({'ID': part_id, 'Tipo_Parte': part_type})
        for key in ('id_parte', 'id_partes', 'tipo_parte'):
            payload['cabecera'].pop(key, None)
    database[PARTES].insert_one(payload)
    return {'status': 'success', 'message': 'Parte sincronizado correctamente en el servidor', 'ID': part_id, 'id_parte': part_id}


def _same_item_id(value: Any, requested: str) -> bool:
    if str(value) == requested:
        return True
    try:
        return float(value) == float(requested)
    except (TypeError, ValueError):
        return False


def _append_photo_to_item(value: Any, requested: str, url: str) -> bool:
    if isinstance(value, list):
        return any(_append_photo_to_item(item, requested, url) for item in value)
    if not isinstance(value, dict):
        return False
    item_id = next((value[key] for key in ('id', 'item_id', 'ID') if key in value), None)
    if item_id is not None and _same_item_id(item_id, requested):
        value.setdefault('fotos', []).append(url)
        return True
    return any(_append_photo_to_item(item, requested, url) for item in value.values())


def store_photo(database: Database, part_id: str, item_id: str | None, upload: UploadFile) -> dict[str, str]:
    filename = upload.filename or ''
    if not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
        raise HTTPException(status_code=400, detail='Formato de archivo no válido. Solo se permiten imágenes.')
    safe_name = Path(filename).name.replace(' ', '_')
    prefix = f'item_{part_id}_{item_id}' if item_id else f'general_{part_id}'
    target = UPLOAD_DIR / f'{prefix}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S_%f}_{safe_name}'
    target.write_bytes(upload.file.read())
    url = f'/uploads/partes/{target.name}'
    try:
        if item_id:
            document = database[PARTES].find_one({'ID': part_id})
            if document is None:
                raise HTTPException(status_code=404, detail='No se encontró el parte especificado')
            data = document.get('datos', [])
            if not _append_photo_to_item(data, item_id, url):
                raise HTTPException(status_code=404, detail='No se encontró el ítem del checklist especificado')
            result = database[PARTES].update_one({'_id': document['_id']}, {'$set': {'datos': data}})
        else:
            result = database[PARTES].update_one({'ID': part_id}, {'$push': {'fotos': url}})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail='No se encontró el parte especificado')
        return {'status': 'success', 'ID': part_id, 'item_id': item_id or '', 'url_foto': url}
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except Exception as error:
        target.unlink(missing_ok=True)
        logger.exception('Error asociando foto %s al parte %s: %s', item_id or 'general', part_id, error)
        raise HTTPException(status_code=500, detail='Error al asociar la fotografía al parte') from error
