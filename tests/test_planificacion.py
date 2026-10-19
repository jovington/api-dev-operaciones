import io
import unittest

from fastapi import UploadFile

from app.services.planificacion_service import (
    _area_nivel,
    _parse_european_float,
    import_planificacion,
)


class _BulkResult:
    def __init__(self, upserted_count: int, modified_count: int):
        self.upserted_count = upserted_count
        self.modified_count = modified_count


class _Collection:
    def __init__(self):
        self.documents: dict[str, dict] = {}

    def bulk_write(self, operations, ordered: bool):
        inserted = 0
        updated = 0
        for operation in operations:
            key = operation._filter['clave_importacion']
            document = dict(operation._doc['$set'])
            if key in self.documents:
                updated += int(self.documents[key] != document)
            else:
                inserted += 1
                document.update(operation._doc['$setOnInsert'])
            self.documents[key] = document
        return _BulkResult(inserted, updated)


class _Database:
    def __init__(self):
        self.collection = _Collection()

    def __getitem__(self, _: str):
        return self.collection


def _upload(content: bytes) -> UploadFile:
    return UploadFile(filename='plan.csv', file=io.BytesIO(content))


class PlanificacionImportTests(unittest.TestCase):
    def test_area_nivel_uses_operational_format(self):
        self.assertEqual(
            _area_nivel({'ZONA': '02.NW', 'NIVEL': '-040', 'SUBNIVEL': '0', 'ACTTYPE': 'GL', 'CAMARA': 's'}),
            'NW-40_GLS',
        )
        self.assertEqual(
            _area_nivel({'ZONA': '01.A2', 'NIVEL': '+326', 'SUBNIVEL': '0', 'ACTTYPE': 'SP', 'CAMARA': 'z'}),
            'A2+326_0SPz',
        )

    def test_parses_european_decimals_and_empty_values(self):
        self.assertEqual(_parse_european_float('1.234,50', 2, 'valor'), 1234.5)
        self.assertIsNone(_parse_european_float('', 2, 'valor'))

    def test_imports_rows_even_when_all_daily_values_are_zero(self):
        database = _Database()
        content = (
            b'Tarea;ID;Name;ZONA;NIVEL;SUBNIVEL;ACTTYPE;CAMARA;PLANTA;RMR_1;Description;07/08/2026;08/08/2026;09/08/2026\n'
            b'tonnes;A2-id;01.A2.+326.0.SPz..;01.A2;+326;0;SP;z;No;37,08607331;Descripcion;0;240,5;150,0\n'
            b'meters;NW-id;02.NW.-040.0.GLs..;02.NW;-040;0;GL;s;Si;2;Otra;0;0;0\n'
        )

        result = import_planificacion(database, _upload(content), 'mensual')

        self.assertEqual(result.registrosImportados, 2)
        self.assertEqual(result.registrosActualizados, 0)
        self.assertEqual(result.filasDescartadas, 0)
        self.assertEqual(len(database.collection.documents), 2)

        first_document = next(
            document for document in database.collection.documents.values() if document['Area_Nivel'] == 'A2+326_0SPz'
        )
        second_document = next(
            document for document in database.collection.documents.values() if document['Area_Nivel'] == 'NW-40_GLS'
        )

        self.assertEqual(first_document['cronograma'][0]['toneladas'], 0.0)
        self.assertEqual(first_document['cronograma'][1]['toneladas'], 240.5)
        self.assertEqual(first_document['cronograma'][2]['toneladas'], 150.0)
        self.assertEqual(second_document['cronograma'][0]['toneladas'], 0.0)
        self.assertEqual(second_document['cronograma'][1]['toneladas'], 0.0)
        self.assertEqual(second_document['cronograma'][2]['toneladas'], 0.0)

