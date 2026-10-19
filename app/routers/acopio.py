from datetime import date

from fastapi import APIRouter, Depends, Query, status
from pymongo.database import Database

from app.db.mongo_client import get_database
from app.models.acopio import (
    AcopioCardsMerged,
    AcopioCardsMerge,
    AcopioGroup,
    AcopioMeasurement,
    AcopioMeasurementClassification,
    AcopioMeasurementGroups,
    AcopioMeasurementGroupsUpdate,
    AcopioMeasurementsRenamed,
    AcopioMeasurementsRename,
    ConsumptionCreate,
    ConsumptionCreated,
    ConsumptionTotal,
    MineralStock,
)
from app.models.bascula import MineralSummary
from app.services.acopio_service import (
    add_acopio_measurement_group,
    classify_acopio_measurement,
    create_acopio_consumption,
    delete_acopio_measurement_group,
    get_acopio_measurement,
    get_acopio_measurements,
    get_consumption_totals,
    get_mineral_stock,
    get_mineral_totals,
    merge_acopio_cards,
    rename_acopio_measurements,
    replace_acopio_measurement_groups,
)

router = APIRouter(tags=['acopio'])


@router.get('/acopio/total-por-mineral', response_model=list[MineralSummary])
def list_acopio_mineral_totals(
    database: Database = Depends(get_database),
) -> list[MineralSummary]:
    return get_mineral_totals(database)


@router.get('/acopio/stock-por-mineral', response_model=list[MineralStock])
def list_mineral_stock(
    database: Database = Depends(get_database),
) -> list[MineralStock]:
    return get_mineral_stock(database)


@router.get('/acopio/mediciones', response_model=list[AcopioMeasurement])
def list_acopio_measurements(
    database: Database = Depends(get_database),
) -> list[AcopioMeasurement]:
    return get_acopio_measurements(database)


@router.post(
    '/acopio/tarjetas/fusionar',
    response_model=AcopioCardsMerged,
)
def merge_acopio_cards_endpoint(
    payload: AcopioCardsMerge,
    database: Database = Depends(get_database),
) -> AcopioCardsMerged:
    return merge_acopio_cards(database, payload)


@router.patch(
    '/acopio/mediciones/renombrar',
    response_model=AcopioMeasurementsRenamed,
)
def rename_acopio_measurements_group(
    payload: AcopioMeasurementsRename,
    database: Database = Depends(get_database),
) -> AcopioMeasurementsRenamed:
    return rename_acopio_measurements(database, payload)


@router.get('/acopio/mediciones/{medicion_id}', response_model=AcopioMeasurement)
def get_acopio_measurement_by_id(
    medicion_id: str,
    database: Database = Depends(get_database),
) -> AcopioMeasurement:
    return get_acopio_measurement(database, medicion_id)


@router.put(
    '/acopio/mediciones/{medicion_id}/clasificacion',
    response_model=AcopioMeasurementGroups,
)
def classify_measurement(
    medicion_id: str,
    payload: AcopioMeasurementClassification,
    database: Database = Depends(get_database),
) -> AcopioMeasurementGroups:
    return classify_acopio_measurement(database, medicion_id, payload)


@router.put(
    '/acopio/mediciones/{medicion_id}/grupo',
    response_model=AcopioMeasurementGroups,
)
def replace_measurement_groups(
    medicion_id: str,
    payload: AcopioMeasurementGroupsUpdate,
    database: Database = Depends(get_database),
) -> AcopioMeasurementGroups:
    return replace_acopio_measurement_groups(database, medicion_id, payload.grupo)


@router.post(
    '/acopio/mediciones/{medicion_id}/grupo',
    response_model=AcopioMeasurementGroups,
)
def add_measurement_group(
    medicion_id: str,
    group: AcopioGroup,
    database: Database = Depends(get_database),
) -> AcopioMeasurementGroups:
    return add_acopio_measurement_group(database, medicion_id, group)


@router.delete(
    '/acopio/mediciones/{medicion_id}/grupo/{grupo_id}',
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_measurement_group(
    medicion_id: str,
    grupo_id: str,
    database: Database = Depends(get_database),
) -> None:
    delete_acopio_measurement_group(database, medicion_id, grupo_id)


@router.post(
    '/consumos-acopio',
    response_model=ConsumptionCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_consumption(
    consumption: ConsumptionCreate,
    database: Database = Depends(get_database),
) -> ConsumptionCreated:
    return create_acopio_consumption(database, consumption)


@router.get('/consumos-acopio', response_model=list[ConsumptionTotal])
def list_consumption_totals(
    mineral: str | None = Query(default=None, min_length=1),
    fecha_desde: date | None = Query(default=None, alias='fechaDesde'),
    fecha_hasta: date | None = Query(default=None, alias='fechaHasta'),
    database: Database = Depends(get_database),
) -> list[ConsumptionTotal]:
    return get_consumption_totals(database, mineral, fecha_desde, fecha_hasta)