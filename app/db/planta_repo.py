from pymongo import DESCENDING
from pymongo.database import Database
from datetime import datetime


def ensure_plc_indexes(database: Database) -> None:
    database['planta_plc_raw'].create_index(
        [('payload.timestamp', DESCENDING)],
        name='payload_timestamp_desc',
    )


def find_latest_plc_reading(database: Database) -> dict | None:
    document = database['planta_plc_raw'].find_one(
        {'payload.timestamp': {'$type': 'date'}},
        {'_id': 0, 'payload': 1},
        sort=[('payload.timestamp', DESCENDING)],
    )
    return document['payload'] if document is not None else None


def find_latest_cinta_4_speed(database: Database) -> dict | None:
    document = database['planta_plc_raw'].find_one(
        {
            'payload.timestamp': {'$type': 'date'},
            'payload.fields.toneladas_Bascula_Cinta_4': {'$type': 'number'},
        },
        {'_id': 0, 'payload.timestamp': 1, 'payload.fields.toneladas_Bascula_Cinta_4': 1},
        sort=[('payload.timestamp', DESCENDING)],
    )
    return document['payload'] if document is not None else None


def find_plc_readings(
    database: Database,
    fecha_inicio: datetime | None = None,
    fecha_fin: datetime | None = None,
    limit: int = 100,
) -> list[dict]:
    query = {'payload.timestamp': {}}
    if fecha_inicio is not None:
        query['payload.timestamp']['$gte'] = fecha_inicio
    if fecha_fin is not None:
        query['payload.timestamp']['$lt'] = fecha_fin
    if not query['payload.timestamp']:
        query = {'payload.timestamp': {'$type': 'date'}}
    return [
        document['payload']
        for document in database['planta_plc_raw'].find(query, {'_id': 0, 'payload': 1}).sort('payload.timestamp', -1).limit(limit)
    ]