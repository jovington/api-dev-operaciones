from datetime import date, datetime, timezone

from fastapi import HTTPException, status
from pymongo.database import Database

from app.db.acopio_repo import (
    append_measurement_group,
    classify_measurement,
    get_measurement,
    list_measurements,
    merge_cards,
    remove_measurement_group,
    rename_measurements,
    replace_measurement_groups,
    sum_stock_by_mineral,
)
from app.db.bascula_repo import sum_net_weight_by_mineral
from app.db.consumos_acopio_repo import (
    create_consumption,
    sum_consumption_by_mineral_and_date,
)
from app.models.acopio import (
    AcopioGroup,
    AcopioMeasurement,
    AcopioMeasurementGroups,
    AcopioMeasurementClassification,
    AcopioCardsMerged,
    AcopioCardsMerge,
    AcopioMeasurementsRenamed,
    AcopioMeasurementsRename,
    ConsumptionCreate,
    ConsumptionCreated,
    ConsumptionTotal,
    MineralStock,
)
from app.models.bascula import MineralSummary


def get_mineral_totals(database: Database) -> list[MineralSummary]:
    return [
        MineralSummary(
            mineral=total['_id'],
            producto=total.get('producto'),
            total=total['total'],
            fecha_subida=total.get('fechaSubida'),
        )
        for total in sum_net_weight_by_mineral(database)
    ]


def create_acopio_consumption(
    database: Database,
    consumption: ConsumptionCreate,
) -> ConsumptionCreated:
    created = create_consumption(
        database,
        mineral=consumption.mineral,
        fecha=consumption.fecha,
        peso_neto=consumption.peso_neto,
    )
    return ConsumptionCreated(
        id=str(created['_id']),
        mineral=created['mineral'],
        fecha=created['fecha'].date(),
        pesoNeto=created['pesoNeto'],
    )


def get_consumption_totals(
    database: Database,
    mineral: str | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
) -> list[ConsumptionTotal]:
    return [
        ConsumptionTotal(**total)
        for total in sum_consumption_by_mineral_and_date(
            database,
            mineral=mineral,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
    ]


def get_mineral_stock(database: Database) -> list[MineralStock]:
    return [MineralStock(**stock) for stock in sum_stock_by_mineral(database)]


def _measurement_response(measurement: dict) -> AcopioMeasurement:
    return AcopioMeasurement(
        id=str(measurement['_id']),
        nombre=measurement['Area_Nivel'],
        cantidad=measurement['Peso_Neto'],
        matricula=measurement.get('Matricula'),
        fecha_subida=measurement['Fecha'],
        producto=measurement.get('Producto'),
        grupo=measurement.get('grupo', []),
    )


def _measurement_groups_response(measurement: dict) -> AcopioMeasurementGroups:
    return AcopioMeasurementGroups(
        id=str(measurement['_id']),
        grupo=measurement.get('grupo', []),
    )


def _get_existing_measurement(database: Database, medicion_id: str) -> dict:
    measurement = get_measurement(database, medicion_id)
    if measurement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='La medición no existe.',
        )
    return measurement


def get_acopio_measurements(database: Database) -> list[AcopioMeasurement]:
    return [_measurement_response(measurement) for measurement in list_measurements(database)]


def get_acopio_measurement(
    database: Database,
    medicion_id: str,
) -> AcopioMeasurement:
    return _measurement_response(_get_existing_measurement(database, medicion_id))


def replace_acopio_measurement_groups(
    database: Database,
    medicion_id: str,
    groups: list[AcopioGroup],
) -> AcopioMeasurementGroups:
    measurement = replace_measurement_groups(
        database,
        medicion_id,
        [group.model_dump(by_alias=True) for group in groups],
    )
    if measurement is None:
        _get_existing_measurement(database, medicion_id)
        raise RuntimeError('No se pudo actualizar la medición.')
    return _measurement_groups_response(measurement)


def add_acopio_measurement_group(
    database: Database,
    medicion_id: str,
    group: AcopioGroup,
) -> AcopioMeasurementGroups:
    measurement = append_measurement_group(
        database,
        medicion_id,
        group.model_dump(by_alias=True),
    )
    if measurement is None:
        _get_existing_measurement(database, medicion_id)
        raise RuntimeError('No se pudo actualizar la medición.')
    return _measurement_groups_response(measurement)


def delete_acopio_measurement_group(
    database: Database,
    medicion_id: str,
    grupo_id: str,
) -> None:
    measurement = remove_measurement_group(database, medicion_id, grupo_id)
    if measurement is None:
        _get_existing_measurement(database, medicion_id)


def classify_acopio_measurement(
    database: Database,
    medicion_id: str,
    classification: AcopioMeasurementClassification,
) -> AcopioMeasurementGroups:
    state_groups = {
        'mineral': ('estado-stock', 'Stock'),
        'baja_ley': ('estado-stock', 'Stock'),
        'esteril': ('estado-esteril', 'Esteril'),
    }
    state_id, state_name = state_groups[classification.tipo]
    measurement = classify_measurement(
        database,
        medicion_id,
        {
            'id': state_id,
            'nombre': state_name,
            'tipo': classification.tipo,
            'fechaAsignacion': datetime.now(timezone.utc),
        },
    )
    if measurement is None:
        _get_existing_measurement(database, medicion_id)
        raise RuntimeError('No se pudo clasificar la medición.')
    return _measurement_groups_response(measurement)


def merge_acopio_cards(
    database: Database,
    payload: AcopioCardsMerge,
) -> AcopioCardsMerged:
    try:
        merged = merge_cards(
            database,
            payload.origenMedicionIds,
            payload.destinoMedicionIds,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    if merged is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Alguna de las mediciones no existe o no es válida para Acopio.',
        )
    return AcopioCardsMerged(
        nombre=merged['nombre'],
        medicion_ids=merged['medicionIds'],
        total=merged['total'],
    )


def rename_acopio_measurements(
    database: Database,
    payload: AcopioMeasurementsRename,
) -> AcopioMeasurementsRenamed:
    try:
        nombre_anterior = rename_measurements(
            database,
            payload.medicion_ids,
            payload.nombre,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    if nombre_anterior is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Alguna de las mediciones no existe.',
        )
    return AcopioMeasurementsRenamed(
        nombre=payload.nombre,
        medicion_ids=payload.medicion_ids,
    )