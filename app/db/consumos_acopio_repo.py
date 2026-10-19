from datetime import date, datetime, time, timedelta

from pymongo import ASCENDING
from pymongo.database import Database


def ensure_consumption_indexes(database: Database) -> None:
    database['consumos_acopio'].create_index(
        [('mineral', ASCENDING), ('fecha', ASCENDING)],
        name='mineral_fecha',
    )


def create_consumption(
    database: Database,
    mineral: str,
    fecha: date,
    peso_neto: int | float,
) -> dict:
    consumption = {
        'mineral': mineral,
        'fecha': datetime.combine(fecha, time.min),
        'pesoNeto': peso_neto,
    }
    result = database['consumos_acopio'].insert_one(consumption)
    consumption['_id'] = result.inserted_id
    return consumption


def sum_consumption_by_mineral_and_date(
    database: Database,
    mineral: str | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
) -> list[dict]:
    match: dict = {
        'mineral': {'$type': 'string', '$ne': ''},
        'pesoNeto': {'$type': 'number'},
        'fecha': {'$type': 'date'},
    }
    if mineral is not None:
        match['mineral'] = mineral
    if fecha_desde is not None or fecha_hasta is not None:
        date_filter: dict = {}
        if fecha_desde is not None:
            date_filter['$gte'] = datetime.combine(fecha_desde, time.min)
        if fecha_hasta is not None:
            date_filter['$lt'] = datetime.combine(fecha_hasta + timedelta(days=1), time.min)
        match['fecha'] = date_filter

    return list(
        database['consumos_acopio'].aggregate(
            [
                {'$match': match},
                {
                    '$group': {
                        '_id': {
                            'mineral': '$mineral',
                            'fecha': {
                                '$dateTrunc': {
                                    'date': '$fecha',
                                    'unit': 'day',
                                    'timezone': 'UTC',
                                }
                            },
                        },
                        'total': {'$sum': '$pesoNeto'},
                    }
                },
                {
                    '$project': {
                        '_id': 0,
                        'mineral': '$_id.mineral',
                        'fecha': '$_id.fecha',
                        'total': 1,
                    }
                },
                {
                    '$lookup': {
                        'from': 'bascula',
                        'let': {'mineral': '$mineral'},
                        'pipeline': [
                            {
                                '$match': {
                                    '$expr': {
                                        '$and': [
                                            {
                                                '$eq': [
                                                    '$Area_Nivel',
                                                    '$$mineral',
                                                ]
                                            },
                                            {
                                                '$eq': [
                                                    {'$type': '$Fecha'},
                                                    'date',
                                                ]
                                            },
                                        ]
                                    }
                                }
                            },
                            {'$sort': {'Fecha': -1}},
                            {'$limit': 1},
                            {
                                '$project': {
                                    '_id': 0,
                                    'fechaSubida': '$Fecha',
                                    'producto': {
                                        '$cond': [
                                            {
                                                '$eq': [
                                                    {'$type': '$Producto'},
                                                    'string',
                                                ]
                                            },
                                            '$Producto',
                                            None,
                                        ]
                                    },
                                }
                            },
                        ],
                        'as': 'entrada',
                    }
                },
                {
                    '$set': {
                        'fechaSubida': {
                            '$arrayElemAt': ['$entrada.fechaSubida', 0]
                        },
                        'producto': {'$arrayElemAt': ['$entrada.producto', 0]},
                    }
                },
                {'$project': {'entrada': 0}},
                {'$sort': {'fecha': -1, 'mineral': 1}},
            ]
        )
    )