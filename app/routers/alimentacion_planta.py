from fastapi import APIRouter, Depends, status
from pymongo.database import Database

from app.db.mongo_client import get_database
from app.models.alimentacion_planta import (
    AlimentacionPlanta,
    AlimentacionPlantaApproved,
    AlimentacionPlantaCancel,
    AlimentacionPlantaCopy,
    AlimentacionPlantaCreate,
    AlimentacionPlantaObservation,
    AlimentacionPlantaOperationalState,
    AlimentacionPlantaScoopUnload,
    AlimentacionPlantaScoopUnloadCreated,
    AlimentacionesPlantaOrdered,
    AlimentacionesPlantaOrder,
    CircuitoActual,
)
from app.services.alimentacion_planta_service import (
    approve_alimentacion_planta,
    activate_alimentacion_planta,
    block_alimentacion_planta,
    cancel_alimentacion_planta,
    copy_alimentacion_planta,
    create_alimentacion_planta,
    list_alimentaciones_planta,
    get_circuito_actual,
    finalize_alimentacion_planta,
    register_scoop_unload,
    reorder_alimentaciones_planta,
    unblock_alimentacion_planta,
)


router = APIRouter(prefix='/alimentacion-planta', tags=['alimentacion-planta'])


@router.get('/alimentaciones', response_model=list[AlimentacionPlanta])
def list_alimentaciones(
    database: Database = Depends(get_database),
) -> list[AlimentacionPlanta]:
    return list_alimentaciones_planta(database)


@router.post(
    '/alimentaciones',
    response_model=AlimentacionPlanta,
    status_code=status.HTTP_201_CREATED,
)
def create_alimentacion(
    payload: AlimentacionPlantaCreate,
    database: Database = Depends(get_database),
) -> AlimentacionPlanta:
    return create_alimentacion_planta(database, payload)


@router.post(
    '/alimentaciones/{alimentacion_id}/aprobar',
    response_model=AlimentacionPlantaApproved,
)
def approve_alimentacion(
    alimentacion_id: str,
    database: Database = Depends(get_database),
) -> AlimentacionPlantaApproved:
    return approve_alimentacion_planta(database, alimentacion_id)


@router.post('/alimentaciones/{alimentacion_id}/copiar', response_model=AlimentacionPlanta, status_code=status.HTTP_201_CREATED)
def copy_alimentacion(
    alimentacion_id: str,
    payload: AlimentacionPlantaCopy,
    database: Database = Depends(get_database),
) -> AlimentacionPlanta:
    return copy_alimentacion_planta(database, alimentacion_id, payload)


@router.post('/alimentaciones/{alimentacion_id}/activar', response_model=AlimentacionPlantaOperationalState)
def activate_alimentacion(
    alimentacion_id: str, database: Database = Depends(get_database)
) -> AlimentacionPlantaOperationalState:
    return activate_alimentacion_planta(database, alimentacion_id)


@router.post('/alimentaciones/{alimentacion_id}/bloquear', response_model=AlimentacionPlantaOperationalState)
def block_alimentacion(
    alimentacion_id: str,
    payload: AlimentacionPlantaObservation | None = None,
    database: Database = Depends(get_database),
) -> AlimentacionPlantaOperationalState:
    return block_alimentacion_planta(database, alimentacion_id, payload or AlimentacionPlantaObservation())


@router.post('/alimentaciones/{alimentacion_id}/desbloquear', response_model=AlimentacionPlantaOperationalState)
def unblock_alimentacion(
    alimentacion_id: str,
    payload: AlimentacionPlantaObservation | None = None,
    database: Database = Depends(get_database),
) -> AlimentacionPlantaOperationalState:
    return unblock_alimentacion_planta(database, alimentacion_id, payload or AlimentacionPlantaObservation())


@router.post('/alimentaciones/{alimentacion_id}/finalizar', response_model=AlimentacionPlantaOperationalState)
def finalize_alimentacion(
    alimentacion_id: str,
    payload: AlimentacionPlantaObservation | None = None,
    database: Database = Depends(get_database),
) -> AlimentacionPlantaOperationalState:
    return finalize_alimentacion_planta(database, alimentacion_id, payload or AlimentacionPlantaObservation())


@router.post('/alimentaciones/{alimentacion_id}/cancelar', response_model=AlimentacionPlantaOperationalState)
def cancel_alimentacion(
    alimentacion_id: str,
    payload: AlimentacionPlantaCancel,
    database: Database = Depends(get_database),
) -> AlimentacionPlantaOperationalState:
    return cancel_alimentacion_planta(database, alimentacion_id, payload)


@router.get('/circuito/actual', response_model=CircuitoActual)
def get_current_circuit(
    database: Database = Depends(get_database),
) -> CircuitoActual:
    return get_circuito_actual(database)


@router.post(
    '/alimentaciones/{alimentacion_id}/descargas-pala',
    response_model=AlimentacionPlantaScoopUnloadCreated,
)
def register_unload(
    alimentacion_id: str,
    payload: AlimentacionPlantaScoopUnload,
    database: Database = Depends(get_database),
) -> AlimentacionPlantaScoopUnloadCreated:
    return register_scoop_unload(database, alimentacion_id, payload)


@router.put('/alimentaciones/orden', response_model=AlimentacionesPlantaOrdered)
def reorder_alimentaciones(
    payload: AlimentacionesPlantaOrder,
    database: Database = Depends(get_database),
) -> AlimentacionesPlantaOrdered:
    return reorder_alimentaciones_planta(database, payload)