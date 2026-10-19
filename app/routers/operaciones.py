from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pymongo.database import Database

from app.db.mongo_client import get_operaciones_database
from app.models.operaciones import DesactivarMedicion, LoginQrRequest, LoginRequest, ParteChecklist, ParteOperacion, UsuarioPlanta, VehiculosTemplate
from app.services.operaciones_service import PARTES, TEMPLATES, authenticate, list_blending, list_measurements, save_user, store_photo, sync_checklist
from app.services.xrf_service import deactivate, export_rows, list_xrf

router = APIRouter(tags=['operaciones'])


@router.get('/mediciones')
def mediciones(limit: int = Query(100, ge=1, le=5000), database: Database = Depends(get_operaciones_database)):
    return list_measurements(database, limit)


@router.get('/blending/historico')
def blending_historico(limit: int = Query(500, ge=1, le=5000), database: Database = Depends(get_operaciones_database)):
    return list_blending(database, limit)


@router.post('/planta/partes', status_code=201)
def crear_parte(parte: ParteOperacion, database: Database = Depends(get_operaciones_database)):
    document = parte.model_dump(exclude_none=True)
    document.setdefault('createdAt', __import__('datetime').datetime.utcnow())
    result = database[PARTES].insert_one(document)
    return {'mensaje': 'Parte de operación guardado correctamente', 'id_documento_mongo': str(result.inserted_id), 'ID_Parte': parte.ID}


@router.get('/planta/partes')
def listar_partes(tipo_parte: str | None = None, turno: str | None = None, fecha: str | None = None, database: Database = Depends(get_operaciones_database)):
    query = {key: value for key, value in (('Tipo_Parte', tipo_parte), ('Turno', turno), ('Fecha', fecha)) if value}
    documents = list(database[PARTES].find(query, {'_id': 0}).limit(1000))
    return {'total': len(documents), 'partes': documents}


@router.post('/checklist/partes')
def sincronizar_parte(parte: ParteChecklist, database: Database = Depends(get_operaciones_database)):
    return sync_checklist(database, parte.model_dump(exclude_none=True))


@router.get('/checklist/vehiculos')
def obtener_vehiculos(database: Database = Depends(get_operaciones_database)):
    document = database[TEMPLATES].find_one({'nombre': 'LV'}) or database[TEMPLATES].find_one({'id': {'$regex': 'vehiculos'}})
    if not document:
        document = {'titulo': 'Listado de vehiculos - Checklist', 'id': 'Listado de vehiculos', 'nombre': 'LV', 'version': '1.0', 'equipamiento': []}
        database[TEMPLATES].insert_one(document.copy())
    for vehicle in document.get('equipamiento', []):
        vehicle.setdefault('qr_token', __import__('secrets').token_hex(16))
        vehicle.setdefault('estado', 'Activo')
    if '_id' in document:
        document['_id'] = str(document['_id'])
    return document


@router.post('/checklist/vehiculos')
def guardar_vehiculos(payload: VehiculosTemplate, database: Database = Depends(get_operaciones_database)):
    document = payload.model_dump(exclude_none=True)
    for vehicle in document['equipamiento']:
        vehicle.setdefault('qr_token', __import__('secrets').token_hex(16))
        vehicle.setdefault('estado', 'Activo')
    result = database[TEMPLATES].update_one({'nombre': document['nombre']}, {'$set': document}, upsert=True)
    return {'status': 'success', 'matched_count': result.matched_count, 'modified_count': result.modified_count, 'upserted_id': str(result.upserted_id) if result.upserted_id else None}


@router.get('/checklist/templates')
def listar_templates(departamento: str | None = None, database: Database = Depends(get_operaciones_database)):
    query = {'departamentos': departamento} if departamento else {}
    documents = list(database[TEMPLATES].find(query, {'_id': 0}).limit(100))
    return {'status': 'success', 'total': len(documents), 'data': documents}


@router.get('/checklist/templates/{tipo_parte}')
def template_por_tipo(tipo_parte: str, database: Database = Depends(get_operaciones_database)):
    document = database[TEMPLATES].find_one({'tipo_parte': tipo_parte}, {'_id': 0})
    if not document:
        raise HTTPException(status_code=404, detail=f"Plantilla con tipo '{tipo_parte}' no encontrada")
    return document


@router.post('/planta/partes/{id_parte}/fotos')
async def foto_general(id_parte: str, request: Request, database: Database = Depends(get_operaciones_database)):
    return await _photo_from_form(request, id_parte, None, database)


@router.post('/planta/partes/{id_parte}/items/{item_id}/fotos')
async def foto_item(id_parte: str, item_id: str, request: Request, database: Database = Depends(get_operaciones_database)):
    return await _photo_from_form(request, id_parte, item_id, database)


async def _photo_from_form(request: Request, part_id: str, item_id: str | None, database: Database):
    form = await request.form()
    upload = next((form.get(name) for name in ('file', 'imagen', 'foto', 'archivo') if form.get(name)), None)
    if upload is None or not hasattr(upload, 'filename') or not hasattr(upload, 'read'):
        raise HTTPException(status_code=422, detail='No se ha encontrado ningún archivo válido en la petición multipart')
    return store_photo(database, part_id, item_id, upload)


@router.get('/uploads/partes/{nombre_archivo}')
def servir_foto(nombre_archivo: str):
    path = Path('/app/uploads/partes') / Path(nombre_archivo).name
    if not path.is_file():
        raise HTTPException(status_code=404, detail='La imagen solicitada no existe en el servidor')
    return FileResponse(path)


@router.post('/planta/usuarios', status_code=201)
def usuario(payload: UsuarioPlanta, database: Database = Depends(get_operaciones_database)):
    return save_user(database, payload.model_dump(exclude_none=True))


@router.get('/planta/usuarios')
def usuarios(database: Database = Depends(get_operaciones_database)):
    documents = list(database['UsuariosPlanta'].find({}, {'_id': 0, 'password': 0}).limit(500))
    return {'total': len(documents), 'usuarios': documents}


@router.post('/planta/login')
def login(payload: LoginRequest, database: Database = Depends(get_operaciones_database)):
    return authenticate(database, n_empleado=payload.n_empleado, password=payload.password)


@router.post('/planta/login-qr')
def login_qr(payload: LoginQrRequest, database: Database = Depends(get_operaciones_database)):
    return authenticate(database, qr_token=payload.qr_token)


@router.get('/planta-xrf/hoy')
def xrf_hoy(database: Database = Depends(get_operaciones_database)):
    return list_xrf(database, today=True)


@router.get('/planta-xrf/ultimas')
def xrf_ultimas(limite: int = Query(25, ge=1, le=5000), database: Database = Depends(get_operaciones_database)):
    return list_xrf(database, limit=limite)


@router.patch('/planta-xrf/{id_medicion}/desactivar')
def xrf_desactivar(id_medicion: str, payload: DesactivarMedicion, database: Database = Depends(get_operaciones_database)):
    return deactivate(database, id_medicion, payload.desactive_medicion)


@router.get('/planta-xrf/exportarxrf')
def xrf_exportar(limite: int = Query(5, ge=1, le=5000), database: Database = Depends(get_operaciones_database)):
    return export_rows(database, limite)
