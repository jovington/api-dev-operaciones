from datetime import datetime
from math import floor

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument, UpdateOne, InsertOne
from pymongo.database import Database


def ensure_alimentacion_planta_indexes(database: Database) -> None:
    collection = database['alimentaciones_planta']
    collection.create_index([('codigo', ASCENDING)], unique=True, name='codigo_unique')
    collection.create_index([('estado', ASCENDING)], name='estado')
    collection.create_index([('orden', ASCENDING)], name='orden')
    collection.create_index(
        [('circuitoActivoClave', ASCENDING)],
        unique=True,
        partialFilterExpression={'estado': {'$in': ['activa', 'bloqueada']}},
        name='circuito_activo_unique',
    )


def _document_id_filter(document_id: str) -> dict:
    possible_ids: list[object] = [document_id]
    if ObjectId.is_valid(document_id):
        possible_ids.append(ObjectId(document_id))
    return {'_id': {'$in': possible_ids}}


def _document_ids_filter(document_ids: list[str]) -> dict:
    possible_ids: list[object] = []
    for document_id in document_ids:
        possible_ids.append(document_id)
        if ObjectId.is_valid(document_id):
            possible_ids.append(ObjectId(document_id))
    return {'_id': {'$in': possible_ids}}


def _stock_mineral_card_filter(card: dict) -> dict:
    return {
        'Area_Nivel': card['nombre'],
        'Producto': card['producto'],
        'Peso_Neto': {'$type': 'number'},
        'Fecha': {'$type': 'date'},
        'grupo': {
            '$elemMatch': {
                'id': 'estado-stock',
                'nombre': 'Stock',
                'tipo': 'mineral',
            }
        },
    }


def _approved_alimentacion_filter(alimentacion_id: str) -> dict:
    return {
        '$and': [
            _document_id_filter(alimentacion_id),
            {'estado': 'aprobada'},
        ]
    }


def list_alimentaciones(database: Database) -> list[dict]:
    return list(database['alimentaciones_planta'].find().sort('orden', ASCENDING))


def migrate_scoop_unloads_to_tons(database: Database) -> int:
    migrated_documents = 0
    for alimentacion in database['alimentaciones_planta'].find(
        {'descargasPala': {'$elemMatch': {'pesoKg': {'$exists': True}}}},
        {'descargasPala': 1},
    ):
        updated_unloads = []
        changed = False
        for unload in alimentacion.get('descargasPala', []):
            updated_unload = dict(unload)
            if 'toneladas' not in updated_unload and 'pesoKg' in updated_unload:
                updated_unload['toneladas'] = updated_unload['pesoKg'] / 1000
            if 'pesoKg' in updated_unload:
                del updated_unload['pesoKg']
                changed = True
            updated_unloads.append(updated_unload)
        if changed:
            result = database['alimentaciones_planta'].update_one(
                {'_id': alimentacion['_id']},
                {'$set': {'descargasPala': updated_unloads}},
            )
            migrated_documents += result.modified_count
    return migrated_documents


def migrate_hour_cards_to_planned_tons(database: Database) -> int:
    migrated_documents = 0
    for alimentacion in database['alimentaciones_planta'].find(
        {'hora': {'$elemMatch': {'toneladasPlanificadas': {'$exists': False}}}},
        {'hora': 1, 'ronda': 1, 'caudalEfectivoTph': 1, 'cargaPalaEstimadaTon': 1},
    ):
        ronda = alimentacion.get('ronda', [])
        flow = alimentacion.get('caudalEfectivoTph')
        scoop_load = alimentacion.get('cargaPalaEstimadaTon')
        if not ronda or not isinstance(flow, (int, float)) or flow <= 0 or not isinstance(scoop_load, (int, float)) or scoop_load <= 0:
            raise RuntimeError(
                f"No se pueden reconstruir las toneladas de hora para la alimentación {alimentacion['_id']}."
            )
        limitante = min(ronda, key=lambda card: card['toneladasPlanificadas'] / flow)
        nominal_duration = limitante['toneladasPlanificadas'] / flow
        updated_cards = []
        changed = False
        for card in alimentacion.get('hora', []):
            updated_card = dict(card)
            if 'toneladasPlanificadas' not in updated_card:
                stock_kg = stock_kg_by_card(database, updated_card)
                if stock_kg <= 0:
                    raise RuntimeError(
                        f"No hay stock fiable para reconstruir la tarjeta hora {card['nombre']} de la alimentación {alimentacion['_id']}."
                    )
                cycles = floor(nominal_duration * updated_card['entradasPorHora'])
                updated_card['toneladasPlanificadas'] = min(stock_kg / 1000, cycles * scoop_load)
                if updated_card['toneladasPlanificadas'] <= 0:
                    raise RuntimeError(
                        f"La tarjeta hora {card['nombre']} de la alimentación {alimentacion['_id']} no tiene ciclos completos planificables."
                    )
                changed = True
            updated_cards.append(updated_card)
        if changed:
            result = database['alimentaciones_planta'].update_one(
                {'_id': alimentacion['_id']},
                {'$set': {'hora': updated_cards}},
            )
            migrated_documents += result.modified_count
    return migrated_documents


def cards_available_in_stock(database: Database, cards: list[dict]) -> bool:
    return all(
        database['bascula'].find_one(_stock_mineral_card_filter(card), {'_id': 1})
        is not None
        for card in cards
    )


def stock_kg_by_card(database: Database, card: dict) -> int | float:
    return sum(
        measurement['Peso_Neto']
        for measurement in list_stock_mineral_measurements(database, card)
    )


def reserved_tons_by_card(database: Database, card: dict) -> int | float:
    reserved_tons = 0
    for alimentacion in database['alimentaciones_planta'].find(
        {'estado': {'$in': ['pendiente', 'aprobada', 'activa', 'bloqueada']}},
        {'ronda': 1, 'hora': 1},
    ):
        for planned_card in alimentacion.get('ronda', []) + alimentacion.get('hora', []):
            if all(planned_card.get(key) == card[key] for key in ('nombre', 'producto', 'tipo')):
                reserved_tons += planned_card.get('toneladasPlanificadas', 0)
    return reserved_tons


def cards_have_unreserved_stock(database: Database, cards: list[dict]) -> bool:
    return all(
        card['toneladasPlanificadas'] * 1000
        <= stock_kg_by_card(database, card) - reserved_tons_by_card(database, card) * 1000
        for card in cards
    )


def cards_already_assigned(database: Database, cards: list[dict]) -> bool:
    card_filters = [
        {
            '$or': [
                {'ronda': {'$elemMatch': card}},
                {'hora': {'$elemMatch': card}},
            ]
        }
        for card in cards
    ]
    return database['alimentaciones_planta'].find_one({'$or': card_filters}) is not None


def create_alimentacion(
    database: Database,
    codigo: str,
    ronda: list[dict],
    hora: list[dict],
    velocidad_estimada_tph: int | float,
    ciclos_alimentacion_hora: int,
    carga_pala_estimada_ton: int | float,
    caudal_efectivo_tph: int | float,
    insertar_despues_de_id: str | None,
    planificacion_padre_id: str | None,
    creada_en: datetime,
) -> dict:
    current = list_alimentaciones(database)
    insert_index = len(current)
    if insertar_despues_de_id is not None:
        for index, current_alimentacion in enumerate(current):
            if str(current_alimentacion['_id']) == insertar_despues_de_id:
                insert_index = index + 1
                break
        else:
            raise ValueError('insertarDespuesDeId no corresponde a una alimentación.')
    alimentacion = {
        '_id': ObjectId(),
        'codigo': codigo,
        'estado': 'pendiente',
        'creadaEn': creada_en,
        'aprobadaEn': None,
        'ronda': ronda,
        'hora': hora,
        'orden': insert_index + 1,
        'velocidadEstimadaTph': velocidad_estimada_tph,
        'ciclosAlimentacionHora': ciclos_alimentacion_hora,
        'cargaPalaEstimadaTon': carga_pala_estimada_ton,
        'caudalEfectivoTph': caudal_efectivo_tph,
        'esSubplanificacion': planificacion_padre_id is not None,
        'planificacionPadreId': planificacion_padre_id,
        'activadaEn': None,
        'bloqueadaEn': None,
        'finalizadaEn': None,
        'canceladaEn': None,
        'observacionesCancelacion': None,
        'mineralLimitante': min(
            ronda,
            key=lambda card: card['toneladasPlanificadas'] / velocidad_estimada_tph,
        ) if ronda else None,
    }
    operations = [
        UpdateOne(
            {'_id': current_alimentacion['_id'], 'orden': current_alimentacion.get('orden')},
            {'$set': {'orden': current_index + 1 if current_index < insert_index else current_index + 2}},
        )
        for current_index, current_alimentacion in enumerate(current)
    ]
    operations.append(InsertOne(alimentacion))
    result = database['alimentaciones_planta'].bulk_write(operations, ordered=True)
    if result.matched_count != len(current) or result.inserted_count != 1:
        raise RuntimeError('El orden cambió mientras se insertaba la alimentación.')
    return alimentacion


def get_alimentacion(database: Database, alimentacion_id: str) -> dict | None:
    return database['alimentaciones_planta'].find_one(_document_id_filter(alimentacion_id))


def approve_alimentacion(
    database: Database,
    alimentacion_id: str,
    aprobada_en: datetime,
) -> dict | None:
    return database['alimentaciones_planta'].find_one_and_update(
        {
            '$and': [
                _document_id_filter(alimentacion_id),
                {'estado': 'pendiente'},
            ]
        },
        {'$set': {'estado': 'aprobada', 'aprobadaEn': aprobada_en}},
        return_document=ReturnDocument.AFTER,
    )


def reorder_alimentaciones(database: Database, alimentacion_ids: list[str]):
    return database['alimentaciones_planta'].bulk_write(
        [
            UpdateOne(_document_id_filter(alimentacion_id), {'$set': {'orden': index}})
            for index, alimentacion_id in enumerate(alimentacion_ids, start=1)
        ],
        ordered=True,
    )


def count_alimentaciones(database: Database, alimentacion_ids: list[str]) -> int:
    return database['alimentaciones_planta'].count_documents(
        _document_ids_filter(alimentacion_ids)
    )


def list_stock_mineral_measurements(
    database: Database,
    card: dict,
) -> list[dict]:
    return list(
        database['bascula']
        .find(_stock_mineral_card_filter(card), {'_id': 1, 'Peso_Neto': 1, 'Fecha': 1})
        .sort([('Fecha', ASCENDING), ('_id', ASCENDING)])
    )


def consume_stock_measurement(
    database: Database,
    measurement_id: object,
    card: dict,
    peso_kg: int | float,
    audit: dict,
) -> bool:
    result = database['bascula'].update_one(
        {
            '$and': [
                {'_id': measurement_id},
                _stock_mineral_card_filter(card),
                {'Peso_Neto': {'$gte': peso_kg}},
            ]
        },
        {
            '$inc': {'Peso_Neto': -peso_kg},
            '$push': {'auditoria_acopio': audit},
        },
    )
    return result.modified_count == 1


def append_scoop_unload(
    database: Database,
    alimentacion_id: str,
    unload: dict,
) -> bool:
    result = database['alimentaciones_planta'].update_one(
        {'$and': [_document_id_filter(alimentacion_id), {'estado': 'activa'}]},
        {'$push': {'descargasPala': unload}},
    )
    return result.modified_count == 1


def transition_alimentacion(
    database: Database,
    alimentacion_id: str,
    expected_state: str,
    changes: dict,
) -> dict | None:
    return database['alimentaciones_planta'].find_one_and_update(
        {'$and': [_document_id_filter(alimentacion_id), {'estado': expected_state}]},
        {'$set': changes},
        return_document=ReturnDocument.AFTER,
    )


def find_active_or_blocked(database: Database) -> dict | None:
    return database['alimentaciones_planta'].find_one(
        {'estado': {'$in': ['activa', 'bloqueada']}},
        sort=[('orden', ASCENDING)],
    )


def find_next_approved(database: Database) -> dict | None:
    return database['alimentaciones_planta'].find_one(
        {'estado': 'aprobada'}, sort=[('orden', ASCENDING)]
    )