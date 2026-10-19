import logging
from datetime import datetime, timezone
from math import floor

from fastapi import HTTPException, status
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.db.alimentacion_planta_repo import (
    approve_alimentacion,
    cards_already_assigned,
    cards_available_in_stock,
    cards_have_unreserved_stock,
    count_alimentaciones,
    create_alimentacion,
    consume_stock_measurement,
    get_alimentacion,
    append_scoop_unload,
    list_alimentaciones,
    list_stock_mineral_measurements,
    stock_kg_by_card,
    find_active_or_blocked,
    find_next_approved,
    reorder_alimentaciones,
    transition_alimentacion,
)
from app.models.alimentacion_planta import (
    AlimentacionPlanta,

    AlimentacionPlantaApproved,
    AlimentacionPlantaCreate,
    AlimentacionPlantaCopy,
    AlimentacionPlantaCancel,
    AlimentacionPlantaObservation,
    AlimentacionPlantaOperationalState,
    CircuitoActual,
    CircuitoAlimentacion,
    CircuitoMineralLimitante,
    AlimentacionPlantaScoopUnload,
    AlimentacionPlantaScoopUnloadCreated,
    AlimentacionesPlantaOrdered,
    AlimentacionesPlantaOrder,
)
from app.services.planta_service import get_cinta_4_speed


logger = logging.getLogger(__name__)


def _mineral_limitante(alimentacion: dict) -> dict | None:
    ronda = alimentacion.get('ronda', [])
    caudal_efectivo_tph = alimentacion.get('caudalEfectivoTph', 0)
    if not ronda or caudal_efectivo_tph <= 0:
        return None
    return min(
        ronda,
        key=lambda card: card['toneladasPlanificadas'] / caudal_efectivo_tph,
    )


def _planned_cards(alimentacion: dict) -> list[dict]:
    return alimentacion.get('ronda', []) + alimentacion.get('hora', [])


def _planned_total_tons(alimentacion: dict) -> int | float:
    return sum(card['toneladasPlanificadas'] for card in _planned_cards(alimentacion))


def _progress_percentage(alimentacion: dict) -> int | float:
    planned_total = _planned_total_tons(alimentacion)
    if not planned_total:
        return 0
    downloaded_total = sum(
        min(
            card['toneladasPlanificadas'],
            sum(
                unload.get('toneladas', 0)
                for unload in alimentacion.get('descargasPala', [])
                if unload['nombre'] == card['nombre'] and unload['producto'] == card['producto']
            ),
        )
        for card in _planned_cards(alimentacion)
    )
    return 100 * downloaded_total / planned_total


def _to_response(alimentacion: dict) -> AlimentacionPlanta:
    return AlimentacionPlanta(
        id=str(alimentacion['_id']),
        codigo=alimentacion['codigo'],
        estado=alimentacion['estado'],
        creadaEn=alimentacion['creadaEn'],
        aprobadaEn=alimentacion.get('aprobadaEn'),
        ronda=alimentacion['ronda'],
        hora=alimentacion['hora'],
        orden=alimentacion['orden'],
        velocidadEstimadaTph=alimentacion.get('velocidadEstimadaTph', 0),
        ciclosAlimentacionHora=alimentacion.get('ciclosAlimentacionHora', 0),
        cargaPalaEstimadaTon=alimentacion.get('cargaPalaEstimadaTon', 0),
        caudalEfectivoTph=alimentacion.get('caudalEfectivoTph', 0),
        esSubplanificacion=alimentacion.get('esSubplanificacion', False),
        planificacionPadreId=alimentacion.get('planificacionPadreId'),
        activadaEn=alimentacion.get('activadaEn'),
        bloqueadaEn=alimentacion.get('bloqueadaEn'),
        finalizadaEn=alimentacion.get('finalizadaEn'),
        canceladaEn=alimentacion.get('canceladaEn'),
        observacionesCancelacion=alimentacion.get('observacionesCancelacion'),
        mineralLimitante=_mineral_limitante(alimentacion),
        descargasPala=alimentacion.get('descargasPala', []),
        progresoPorcentaje=_progress_percentage(alimentacion),
    )


def list_alimentaciones_planta(database: Database) -> list[AlimentacionPlanta]:
    return [_to_response(alimentacion) for alimentacion in list_alimentaciones(database)]


def create_alimentacion_planta(
    database: Database,
    payload: AlimentacionPlantaCreate,
) -> AlimentacionPlanta:
    cards = [
        card.model_dump()
        for card in payload.ronda + payload.hora
    ]
    if not cards_available_in_stock(database, cards):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Alguna tarjeta no existe o no está disponible en Stock Mineral.',
        )
    if not cards_have_unreserved_stock(database, cards):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='Alguna tarjeta no tiene stock no planificado suficiente.',
        )
    limitante = _mineral_limitante({
        'ronda': [card.model_dump() for card in payload.ronda],
        'caudalEfectivoTph': payload.caudalEfectivoTph,
    })
    if limitante is not None:
        nominal_duration = limitante['toneladasPlanificadas'] / payload.caudalEfectivoTph
        for card in payload.hora:
            stock_tons = stock_kg_by_card(database, card.model_dump()) / 1000
            expected_tons = min(
                stock_tons,
                floor(nominal_duration * card.entradasPorHora) * payload.cargaPalaEstimadaTon,
            )
            if abs(card.toneladasPlanificadas - expected_tons) > 0.01:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail='Las toneladasPlanificadas de hora no coinciden con los ciclos completos calculados.',
                )

    if payload.planificacionPadreId is not None and get_alimentacion(
        database, payload.planificacionPadreId
    ) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='La planificación padre no existe.',
        )

    try:
        alimentacion = create_alimentacion(
            database,
            payload.codigo,
            [card.model_dump() for card in payload.ronda],
            [card.model_dump() for card in payload.hora],
            payload.velocidadEstimadaTph,
            payload.ciclosAlimentacionHora,
            payload.cargaPalaEstimadaTon,
            payload.caudalEfectivoTph,
            payload.insertarDespuesDeId,
            payload.planificacionPadreId,
            datetime.now(timezone.utc),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except RuntimeError as error:
        logger.warning('Inserción de alimentación incompleta: %s', error)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='El orden cambió mientras se insertaba la alimentación.',
        ) from error
    except DuplicateKeyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='El código de alimentación ya existe.',
        ) from error
    return _to_response(alimentacion)


def copy_alimentacion_planta(
    database: Database,
    alimentacion_id: str,
    payload: AlimentacionPlantaCopy,
) -> AlimentacionPlanta:
    origin = get_alimentacion(database, alimentacion_id)
    if origin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='La alimentación no existe.')
    if origin['estado'] not in {'aprobada', 'activa', 'bloqueada', 'finalizada'}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='La alimentación no se puede copiar.')
    copy_payload = payload.model_copy(update={'planificacionPadreId': alimentacion_id})
    return create_alimentacion_planta(database, copy_payload)


def approve_alimentacion_planta(
    database: Database,
    alimentacion_id: str,
) -> AlimentacionPlantaApproved:
    alimentacion = approve_alimentacion(
        database,
        alimentacion_id,
        datetime.now(timezone.utc),
    )
    if alimentacion is None:
        existing_alimentacion = get_alimentacion(database, alimentacion_id)
        if existing_alimentacion is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='La alimentación no existe.',
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='La alimentación ya está aprobada.',
        )
    return AlimentacionPlantaApproved(
        id=str(alimentacion['_id']),
        estado='aprobada',
        aprobadaEn=alimentacion['aprobadaEn'],
    )


def reorder_alimentaciones_planta(
    database: Database,
    payload: AlimentacionesPlantaOrder,
) -> AlimentacionesPlantaOrdered:
    if count_alimentaciones(database, payload.ids) != len(payload.ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='ids debe incluir una vez cada alimentación existente.',
        )
    total_alimentaciones = len(list_alimentaciones(database))
    if total_alimentaciones != len(payload.ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='ids debe incluir una vez cada alimentación existente.',
        )

    result = reorder_alimentaciones(database, payload.ids)
    if result.matched_count != len(payload.ids) or result.modified_count != len(payload.ids):
        logger.warning(
            'Reordenado de Alimentación Planta incompleto: esperadas=%s, '
            'coincidentes=%s, modificadas=%s, ids=%s',
            len(payload.ids),
            result.matched_count,
            result.modified_count,
            payload.ids,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='El reordenado no se completó.',
        )
    return AlimentacionesPlantaOrdered(ids=payload.ids)


def _operational_state(alimentacion: dict) -> AlimentacionPlantaOperationalState:
    return AlimentacionPlantaOperationalState(
        id=str(alimentacion['_id']), estado=alimentacion['estado']
    )


def _planned_remaining_tons(alimentacion: dict, card: dict) -> int | float:
    initial_tons = next(
        planned_card['toneladasPlanificadas']
        for planned_card in _planned_cards(alimentacion)
        if all(planned_card[key] == card[key] for key in ('nombre', 'producto', 'tipo'))
    )
    consumed_tons = sum(
        unload.get('toneladas', 0)
        for unload in alimentacion.get('descargasPala', [])
        if unload['nombre'] == card['nombre'] and unload['producto'] == card['producto']
    )
    return max(initial_tons - consumed_tons, 0)


def _activate_next_approved(database: Database) -> str | None:
    next_alimentacion = find_next_approved(database)
    if next_alimentacion is None:
        return None
    try:
        activated = transition_alimentacion(
            database,
            str(next_alimentacion['_id']),
            'aprobada',
            {
                'estado': 'activa',
                'activadaEn': datetime.now(timezone.utc),
                'circuitoActivoClave': 'principal',
            },
        )
    except DuplicateKeyError:
        logger.warning('No se activó la siguiente alimentación por concurrencia de circuito.')
        return None
    return str(activated['_id']) if activated is not None else None


def activate_alimentacion_planta(
    database: Database, alimentacion_id: str
) -> AlimentacionPlantaOperationalState:
    if find_active_or_blocked(database) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Ya existe una alimentación en circuito.')
    try:
        activated = transition_alimentacion(
            database,
            alimentacion_id,
            'aprobada',
            {
                'estado': 'activa',
                'activadaEn': datetime.now(timezone.utc),
                'circuitoActivoClave': 'principal',
            },
        )
    except DuplicateKeyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='Ya existe una alimentación en circuito.',
        ) from error
    if activated is None:
        if get_alimentacion(database, alimentacion_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='La alimentación no existe.')
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='La alimentación debe estar aprobada.')
    return _operational_state(activated)


def block_alimentacion_planta(
    database: Database, alimentacion_id: str, payload: AlimentacionPlantaObservation
) -> AlimentacionPlantaOperationalState:
    blocked = transition_alimentacion(
        database, alimentacion_id, 'activa',
        {'estado': 'bloqueada', 'bloqueadaEn': datetime.now(timezone.utc), 'observacionParada': payload.observacion},
    )
    if blocked is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='La alimentación debe estar activa.')
    return _operational_state(blocked)


def unblock_alimentacion_planta(
    database: Database, alimentacion_id: str, payload: AlimentacionPlantaObservation
) -> AlimentacionPlantaOperationalState:
    unblocked = transition_alimentacion(
        database, alimentacion_id, 'bloqueada',
        {'estado': 'activa', 'observacionParada': payload.observacion},
    )
    if unblocked is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='La alimentación debe estar bloqueada.')
    return _operational_state(unblocked)


def cancel_alimentacion_planta(
    database: Database, alimentacion_id: str, payload: AlimentacionPlantaCancel
) -> AlimentacionPlantaOperationalState:
    cancelled = transition_alimentacion(
        database, alimentacion_id, 'activa',
        {
            'estado': 'cancelada',
            'canceladaEn': datetime.now(timezone.utc),
            'observacionesCancelacion': payload.observaciones,
            'circuitoActivoClave': None,
        },
    )
    if cancelled is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='La alimentación debe estar activa.')
    return AlimentacionPlantaOperationalState(
        id=str(cancelled['_id']),
        estado='cancelada',
        alimentacionSiguienteActivadaId=_activate_next_approved(database),
    )


def finalize_alimentacion_planta(
    database: Database, alimentacion_id: str, payload: AlimentacionPlantaObservation
) -> AlimentacionPlantaOperationalState:
    alimentacion = get_alimentacion(database, alimentacion_id)
    if alimentacion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='La alimentación no existe.')
    if alimentacion['estado'] not in {'activa', 'bloqueada'}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='La alimentación debe estar activa o bloqueada.',
        )
    finalized = transition_alimentacion(
        database,
        alimentacion_id,
        alimentacion['estado'],
        {
            'estado': 'finalizada',
            'finalizadaEn': datetime.now(timezone.utc),
            'observacionFinalizacion': payload.observacion,
            'circuitoActivoClave': None,
        },
    )
    if finalized is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='La finalización no se completó por concurrencia.')
    return AlimentacionPlantaOperationalState(
        id=str(finalized['_id']),
        estado='finalizada',
        alimentacionSiguienteActivadaId=_activate_next_approved(database),
    )


def get_circuito_actual(database: Database) -> CircuitoActual:
    alimentacion = find_active_or_blocked(database)
    if alimentacion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No hay alimentación en circuito.')
    limitante = _mineral_limitante(alimentacion)
    if limitante is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='La alimentación no tiene tarjetas de ronda para calcular el circuito.',
        )
    initial_tons = limitante['toneladasPlanificadas']
    remaining_tons = _planned_remaining_tons(alimentacion, limitante)
    speed = get_cinta_4_speed(database)
    return CircuitoActual(
        alimentacion=CircuitoAlimentacion(id=str(alimentacion['_id']), codigo=alimentacion['codigo'], estado=alimentacion['estado']),
        mineralLimitante=CircuitoMineralLimitante(nombre=limitante['nombre'], producto=limitante['producto'], toneladasIniciales=initial_tons, toneladasRestantes=remaining_tons),
        velocidadEstimadaTph=alimentacion['velocidadEstimadaTph'],
        velocidadRealCinta4Tph=speed.toneladasHora,
        duracionNominalHoras=initial_tons / alimentacion['caudalEfectivoTph'],
        duracionRealEstimadaHoras=remaining_tons / speed.toneladasHora,
        progresoPorcentaje=_progress_percentage(alimentacion),
    )


def register_scoop_unload(
    database: Database,
    alimentacion_id: str,
    payload: AlimentacionPlantaScoopUnload,
) -> AlimentacionPlantaScoopUnloadCreated:
    alimentacion = get_alimentacion(database, alimentacion_id)
    if alimentacion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='La alimentación no existe.',
        )
    if alimentacion['estado'] != 'activa':
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='La alimentación debe estar activa.',
        )

    card = {
        'nombre': payload.nombre,
        'producto': payload.producto,
        'tipo': 'mineral',
    }
    ronda_card = next(
        (
            planned_card for planned_card in alimentacion['ronda']
            if all(planned_card[key] == card[key] for key in ('nombre', 'producto', 'tipo'))
        ),
        None,
    )
    hora_card = next(
        (
            planned_card for planned_card in alimentacion['hora']
            if all(planned_card[key] == card[key] for key in ('nombre', 'producto', 'tipo'))
        ),
        None,
    )
    if ronda_card is None and hora_card is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='La tarjeta no pertenece a la alimentación.',
        )

    if payload.toneladas > _planned_remaining_tons(alimentacion, card):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='Las toneladas solicitadas superan las toneladas planificadas restantes.',
        )

    measurements = list_stock_mineral_measurements(database, card)
    if not measurements:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='La tarjeta no existe en Stock Mineral.',
        )
    stock_available_kg = sum(measurement['Peso_Neto'] for measurement in measurements)
    peso_kg = payload.toneladas * 1000
    if peso_kg > stock_available_kg:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='El peso solicitado supera el stock disponible.',
        )

    fecha = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace(
        '+00:00', 'Z'
    )
    pending_weight = peso_kg
    for measurement in measurements:
        consumed_weight = min(measurement['Peso_Neto'], pending_weight)
        if consumed_weight == 0:
            continue
        audit = {
            'accion': 'descarga_pala_alimentacion',
            'fecha': fecha,
            'alimentacionId': alimentacion_id,
            'nombre': payload.nombre,
            'producto': payload.producto,
            'pesoDescargadoKg': consumed_weight,
        }
        if not consume_stock_measurement(
            database,
            measurement['_id'],
            card,
            consumed_weight,
            audit,
        ):
            logger.warning(
                'Descarga de pala interrumpida por concurrencia: alimentacion_id=%s, '
                'medicion_id=%s, peso_pendiente=%s',
                alimentacion_id,
                measurement['_id'],
                pending_weight,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail='El descuento no se completó por un conflicto de concurrencia.',
            )
        pending_weight -= consumed_weight
        if pending_weight == 0:
            break

    if pending_weight != 0:
        logger.warning(
            'Descarga de pala incompleta: alimentacion_id=%s, peso_pendiente=%s',
            alimentacion_id,
            pending_weight,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='El descuento no se completó por un conflicto de concurrencia.',
        )

    if not append_scoop_unload(
        database,
        alimentacion_id,
        {
            'fecha': fecha,
            'nombre': payload.nombre,
            'producto': payload.producto,
            'toneladas': payload.toneladas,
        },
    ):
        logger.warning(
            'Descarga de pala descontada sin registro en alimentación: alimentacion_id=%s',
            alimentacion_id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='La descarga no se pudo registrar por un conflicto de concurrencia.',
        )

    updated_alimentacion = get_alimentacion(database, alimentacion_id)
    limitante = _mineral_limitante(updated_alimentacion)
    limitante_remaining = (
        _planned_remaining_tons(updated_alimentacion, limitante)
        if limitante is not None else 0
    )
    next_activated_id = None
    if limitante is not None and limitante_remaining == 0:
        finalized = transition_alimentacion(
            database,
            alimentacion_id,
            'activa',
            {
                'estado': 'finalizada',
                'finalizadaEn': datetime.now(timezone.utc),
                'circuitoActivoClave': None,
            },
        )
        if finalized is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='La finalización no se completó por concurrencia.')
        next_activated_id = _activate_next_approved(database)

    return AlimentacionPlantaScoopUnloadCreated(
        alimentacionId=alimentacion_id,
        nombre=payload.nombre,
        producto=payload.producto,
        toneladas=payload.toneladas,
        stockRestanteToneladas=(stock_available_kg - peso_kg) / 1000,
        progresoPorcentaje=_progress_percentage(updated_alimentacion),
        alimentacionSiguienteActivadaId=next_activated_id,
    )