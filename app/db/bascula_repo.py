from pymongo.database import Database


def sum_net_weight_by_mineral(database: Database) -> list[dict]:
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
                    '$sort': {'Fecha': -1},
                },
                {
                    '$group': {
                        '_id': '$Area_Nivel',
                        'total': {'$sum': '$Peso_Neto'},
                        'fechaSubida': {'$max': '$Fecha'},
                        'producto': {
                            '$first': {
                                '$cond': [
                                    {'$eq': [{'$type': '$Producto'}, 'string']},
                                    '$Producto',
                                    None,
                                ]
                            }
                        },
                        'paquetes': {
                            '$push': {
                                'nombre': '$Area_Nivel',
                                'cantidad': '$Peso_Neto',
                                'matricula': {
                                    '$cond': [
                                        {
                                            '$eq': [
                                                {'$type': '$Matricula'},
                                                'string',
                                            ]
                                        },
                                        '$Matricula',
                                        None,
                                    ]
                                },
                                'fechaSubida': '$Fecha',
                            }
                        },
                    }
                },
                {'$sort': {'_id': 1}},
            ]
        )
    )