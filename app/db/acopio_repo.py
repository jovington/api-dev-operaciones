from datetime import datetime, timezone
import logging
import re

from bson import ObjectId
from pymongo import DESCENDING, ReturnDocument
from pymongo.database import Database


logger = logging.getLogger(__name__)


def _valid_measurement_filter(filter_query: dict | None = None) -> dict:
    valid_fields = {
        'Area_Nivel': {'$type': 'string', '$ne': ''},
        'Peso_Neto': {'$type': 'number'},
        'Fecha': {'$type': 'date'},
    }
    if filter_query is None:
        return valid_fields
    return {'$and': [filter_query, valid_fields]}


def _measurement_filter(medicion_id: str) -> dict:
    possible_ids: list[object] = [medicion_id]
    if ObjectId.is_valid(medicion_id):
        possible_ids.append(ObjectId(medicion_id))
    return {'_id': {'$in': possible_ids}}


def _measurements_filter(medicion_ids: list[str]) -> dict:
    possible_ids: list[object] = []
    for medicion_id in medicion_ids:
        possible_ids.append(medicion_id)
        if ObjectId.is_valid(medicion_id):
            possible_ids.append(ObjectId(medicion_id))
    return {'_id': {'$in': possible_ids}}


def list_measurements(database: Database) -> list[dict]:
    return list(
        database['bascula']
        .find(_valid_measurement_filter())
        .sort('Fecha', DESCENDING)
    )


def get_measurement(database: Database, medicion_id: str) -> dict | None:
    return database['bascula'].find_one(
        _valid_measurement_filter(_measurement_filter(medicion_id))
    )


def replace_measurement_groups(
    database: Database,
    medicion_id: str,
    groups: list[dict],
) -> dict | None:
    return database['bascula'].find_one_and_update(
        _valid_measurement_filter(_measurement_filter(medicion_id)),
        {'$set': {'grupo': groups}},
        return_document=ReturnDocument.AFTER,
    )


def append_measurement_group(
    database: Database,
    medicion_id: str,
    group: dict,
) -> dict | None:
    return database['bascula'].find_one_and_update(
        _valid_measurement_filter(_measurement_filter(medicion_id)),
        {'$push': {'grupo': group}},
        return_document=ReturnDocument.AFTER,
    )


def remove_measurement_group(
    database: Database,
    medicion_id: str,
    grupo_id: str,
) -> dict | None:
    return database['bascula'].find_one_and_update(
        _valid_measurement_filter(_measurement_filter(medicion_id)),
        {'$pull': {'grupo': {'id': grupo_id}}},
        return_document=ReturnDocument.AFTER,
    )


def classify_measurement(
    database: Database,
    medicion_id: str,
    state_group: dict,
) -> dict | None:
    return database['bascula'].find_one_and_update(
        _valid_measurement_filter(_measurement_filter(medicion_id)),
        [
            {
                '$set': {
                    'grupo': {
                        '$concatArrays': [
                            {
                                '$filter': {
                                    'input': {'$ifNull': ['$grupo', []]},
                                    'as': 'group',
                                    'cond': {
                                        '$not': [
                                            {
                                                '$in': [
                                                    '$$group.id',
                                                    ['estado-stock', 'estado-esteril'],
                                                ]
                                            }
                                        ]
                                    },
                                }
                            },
                            [state_group],
                        ]
                    }
                }
            }
        ],
        return_document=ReturnDocument.AFTER,
    )


def _principal_name(nombre: str) -> str:
    return re.sub(r'(?:_bal.*|\s+bal.*)$', '', nombre, flags=re.IGNORECASE)


def _operational_state(groups: list[dict]) -> tuple[str, str, str] | None:
    operational_groups = [
        group
        for group in groups
        if group.get('id') in {'estado-stock', 'estado-esteril'}
    ]
    if not operational_groups:
        return None
    if len(operational_groups) != 1:
        raise ValueError('La tarjeta contiene más de un estado operativo.')

    state = operational_groups[0]
    state_id = state.get('id')
    state_name = state.get('nombre')
    state_type = state.get('tipo')
    if (
        state_id == 'estado-stock'
        and state_name == 'Stock'
        and state_type in {'mineral', 'baja_ley'}
    ):
        return state_id, state_name, state_type
    if (
        state_id == 'estado-esteril'
        and state_name == 'Esteril'
        and state_type == 'esteril'
    ):
        return state_id, state_name, state_type
    raise ValueError('La tarjeta contiene un estado operativo no válido.')


def _has_balizado_origin(groups: list[dict]) -> bool:
    return any(group.get('id') == 'origen-balizado' for group in groups)


def _operational_state_filter(state: tuple[str, str, str] | None) -> dict:
    operational_ids = {'$in': ['estado-stock', 'estado-esteril']}
    if state is None:
        return {'grupo': {'$not': {'$elemMatch': {'id': operational_ids}}}}

    state_id, state_name, state_type = state
    return {
        '$and': [
            {
                'grupo': {
                    '$elemMatch': {
                        'id': state_id,
                        'nombre': state_name,
                        'tipo': state_type,
                    }
                }
            },
            {
                'grupo': {
                    '$not': {
                        '$elemMatch': {
                            'id': operational_ids,
                            '$or': [
                                {'id': {'$ne': state_id}},
                                {'nombre': {'$ne': state_name}},
                                {'tipo': {'$ne': state_type}},
                            ],
                        }
                    }
                }
            },
        ]
    }


def merge_cards(
    database: Database,
    origen_medicion_ids: list[str],
    destino_medicion_ids: list[str],
) -> dict | None:
    all_measurement_ids = origen_medicion_ids + destino_medicion_ids
    all_measurements_filter = _valid_measurement_filter(
        _measurements_filter(all_measurement_ids)
    )
    measurements = list(database['bascula'].find(all_measurements_filter))
    measurements_by_id = {
        str(measurement['_id']): measurement for measurement in measurements
    }
    if set(measurements_by_id) != set(all_measurement_ids):
        return None

    origin_measurements = [
        measurements_by_id[medicion_id] for medicion_id in origen_medicion_ids
    ]
    destination_measurements = [
        measurements_by_id[medicion_id] for medicion_id in destino_medicion_ids
    ]
    origin_cards = {
        (
            measurement['Area_Nivel'],
            measurement.get('Producto'),
            _operational_state(measurement.get('grupo', [])),
        )
        for measurement in origin_measurements
    }
    destination_cards = {
        (
            measurement['Area_Nivel'],
            measurement.get('Producto'),
            _operational_state(measurement.get('grupo', [])),
        )
        for measurement in destination_measurements
    }
    if len(origin_cards) != 1 or len(destination_cards) != 1:
        raise ValueError('Origen y destino deben pertenecer a una única tarjeta.')

    nombre_origen, producto_origen, estado_origen = origin_cards.pop()
    nombre_destino, producto_destino, estado_destino = destination_cards.pop()
    if producto_origen != producto_destino:
        raise ValueError('Origen y destino deben tener el mismo producto.')
    if estado_destino is None or estado_destino[2] not in {'mineral', 'baja_ley'}:
        raise ValueError('El destino debe estar clasificado como mineral o baja ley.')
    if _principal_name(nombre_origen) != _principal_name(nombre_destino):
        raise ValueError('Los nombres de origen y destino no son compatibles.')

    origin_is_balizado = nombre_origen != _principal_name(nombre_origen)
    origin_has_marker = all(
        _has_balizado_origin(measurement.get('grupo', []))
        for measurement in origin_measurements
    )
    if not origin_is_balizado and not origin_has_marker:
        raise ValueError('La tarjeta de origen no está marcada como balizada.')

    fecha = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace(
        '+00:00', 'Z'
    )
    state_id, state_name, state_type = estado_destino
    destination_state = {
        'id': state_id,
        'nombre': state_name,
        'tipo': state_type,
        'fechaAsignacion': fecha,
    }
    origin_filter = {
        '$and': [
            _measurements_filter(origen_medicion_ids),
            {'Area_Nivel': nombre_origen},
            {'Producto': producto_origen},
            _valid_measurement_filter(),
            _operational_state_filter(estado_origen),
        ]
    }
    update_result = database['bascula'].update_many(
        origin_filter,
        [
            {
                '$set': {
                    'Area_Nivel': nombre_destino,
                    'grupo': {
                        '$concatArrays': [
                            {
                                '$filter': {
                                    'input': {'$ifNull': ['$grupo', []]},
                                    'as': 'group',
                                    'cond': {
                                        '$not': [
                                            {
                                                '$in': [
                                                    '$$group.id',
                                                    [
                                                        'estado-stock',
                                                        'estado-esteril',
                                                        'origen-balizado',
                                                    ],
                                                ]
                                            }
                                        ]
                                    },
                                }
                            },
                            {
                                '$literal': [
                                    {
                                        'id': 'origen-balizado',
                                        'nombre': 'Origen balizado',
                                        'tipo': 'mineral',
                                        'fechaAsignacion': fecha,
                                    },
                                    destination_state,
                                ]
                            },
                        ]
                    },
                    'auditoria_acopio': {
                        '$concatArrays': [
                            {'$ifNull': ['$auditoria_acopio', []]},
                            {
                                '$literal': [
                                    {
                                        'accion': 'fusionar_tarjetas',
                                        'fecha': fecha,
                                        'nombreOrigen': nombre_origen,
                                        'nombreDestino': nombre_destino,
                                        'origenMedicionIds': origen_medicion_ids,
                                        'destinoMedicionIds': destino_medicion_ids,
                                    }
                                ]
                            },
                        ]
                    },
                }
            }
        ],
    )
    if (
        update_result.matched_count != len(origen_medicion_ids)
        or update_result.modified_count != len(origen_medicion_ids)
    ):
        logger.warning(
            'Fusión de Acopio con actualización incompleta: esperadas=%s, '
            'coincidentes=%s, modificadas=%s, origen_ids=%s',
            len(origen_medicion_ids),
            update_result.matched_count,
            update_result.modified_count,
            origen_medicion_ids,
        )
        raise RuntimeError('La actualización de la fusión no se completó.')
    total = sum(measurement['Peso_Neto'] for measurement in measurements)
    return {
        'nombre': nombre_destino,
        'medicionIds': all_measurement_ids,
        'total': total,
    }


def rename_measurements(
    database: Database,
    medicion_ids: list[str],
    nombre_nuevo: str,
) -> str | None:
    measurements_filter = _valid_measurement_filter(_measurements_filter(medicion_ids))
    measurements = list(
        database['bascula'].find(
            measurements_filter,
            {'_id': 1, 'Area_Nivel': 1},
        )
    )
    found_ids = {str(measurement['_id']) for measurement in measurements}
    if found_ids != set(medicion_ids):
        return None

    nombres_anteriores = {measurement.get('Area_Nivel') for measurement in measurements}
    if len(nombres_anteriores) != 1:
        raise ValueError('Las mediciones seleccionadas no pertenecen a la misma tarjeta.')

    nombre_anterior = nombres_anteriores.pop()
    fecha = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace(
        '+00:00', 'Z'
    )
    update_filter = {
        '$and': [
            _measurements_filter(medicion_ids),
            {'Area_Nivel': nombre_anterior},
            _valid_measurement_filter(),
        ]
    }
    update_result = database['bascula'].update_many(
        update_filter,
        {
            '$set': {'Area_Nivel': nombre_nuevo},
            '$push': {
                'auditoria_acopio': {
                    'accion': 'renombrar_medicion',
                    'fecha': fecha,
                    'nombreAnterior': nombre_anterior,
                    'nombreNuevo': nombre_nuevo,
                }
            },
        },
    )
    if update_result.modified_count != len(medicion_ids):
        logger.warning(
            'Renombrado de Acopio con actualización incompleta: esperadas=%s, '
            'coincidentes=%s, modificadas=%s, ids=%s',
            len(medicion_ids),
            update_result.matched_count,
            update_result.modified_count,
            medicion_ids,
        )
        raise RuntimeError('La actualización de las mediciones no se completó.')
    return nombre_anterior


def sum_stock_by_mineral(database: Database) -> list[dict]:
    return list(
        database['bascula'].aggregate(
            [
                {
                    '$match': {
                        'Area_Nivel': {'$type': 'string', '$ne': ''},
                        'Peso_Neto': {'$type': 'number'},
                        'Fecha': {'$type': 'date'},
                    }
                },
                {
                    '$project': {
                        '_id': 0,
                        'mineral': '$Area_Nivel',
                        'entrado': '$Peso_Neto',
                        'consumido': {'$literal': 0},
                        'fechaSubida': '$Fecha',
                        'producto': {
                            '$cond': [
                                {'$eq': [{'$type': '$Producto'}, 'string']},
                                '$Producto',
                                None,
                            ]
                        },
                    }
                },
                {
                    '$unionWith': {
                        'coll': 'consumos_acopio',
                        'pipeline': [
                            {
                                '$match': {
                                    'mineral': {'$type': 'string', '$ne': ''},
                                    'pesoNeto': {'$type': 'number'},
                                }
                            },
                            {
                                '$project': {
                                    '_id': 0,
                                    'mineral': 1,
                                    'entrado': {'$literal': 0},
                                    'consumido': '$pesoNeto',
                                    'fechaSubida': {'$literal': None},
                                    'producto': {'$literal': None},
                                }
                            },
                        ],
                    }
                },
                {'$sort': {'fechaSubida': -1}},
                {
                    '$group': {
                        '_id': '$mineral',
                        'entrado': {'$sum': '$entrado'},
                        'consumido': {'$sum': '$consumido'},
                        'fechaSubida': {'$max': '$fechaSubida'},
                        'producto': {'$first': '$producto'},
                    }
                },
                {
                    '$project': {
                        '_id': 0,
                        'mineral': '$_id',
                        'entrado': 1,
                        'consumido': 1,
                        'disponible': {'$subtract': ['$entrado', '$consumido']},
                        'fechaSubida': 1,
                        'producto': 1,
                    }
                },
                {'$sort': {'mineral': 1}},
            ]
        )
    )