import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError
from pymongo import MongoClient

from app.models.acopio import (
    AcopioCardsMerge,
    AcopioMeasurementClassification,
    AcopioMeasurementsRename,
)
from app.services.acopio_service import (
    classify_acopio_measurement,
    get_acopio_measurement,
    merge_acopio_cards,
    rename_acopio_measurements,
)


TEST_MONGO_URI = os.getenv('ACOPIO_TEST_MONGO_URI')


def _measurement(
    measurement_id: str,
    name: str,
    weight: int,
    groups: list[dict] | None = None,
) -> dict:
    return {
        '_id': measurement_id,
        'Area_Nivel': name,
        'Peso_Neto': weight,
        'Fecha': datetime(2026, 8, 10, 9, 30, tzinfo=timezone.utc),
        'grupo': groups or [],
    }


class ConcurrentMergeCollection:
    def __init__(self, measurements: list[dict]):
        self.measurements = measurements
        self.update_calls = 0

    def find(self, _filter):
        return self.measurements

    def update_many(self, _filter, _update):
        self.update_calls += 1
        return SimpleNamespace(matched_count=0, modified_count=0)


class ConcurrentMergeDatabase:
    def __init__(self, measurements: list[dict]):
        self.bascula = ConcurrentMergeCollection(measurements)

    def __getitem__(self, collection_name: str):
        if collection_name != 'bascula':
            raise KeyError(collection_name)
        return self.bascula


@unittest.skipUnless(
    TEST_MONGO_URI,
    'Defina ACOPIO_TEST_MONGO_URI con una base de datos MongoDB de pruebas.',
)
class AcopioRenameStandaloneIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = MongoClient(TEST_MONGO_URI)
        cls.database = cls.client.get_default_database()
        if cls.database is None:
            raise unittest.SkipTest('La URI de pruebas debe incluir el nombre de la base de datos.')

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def setUp(self):
        self.database['bascula'].delete_many({})

    def test_rename_one_measurement_adds_embedded_audit(self):
        self.database['bascula'].insert_one(_measurement('measurement-1', 'ZV Balizar', 100))

        result = rename_acopio_measurements(
            self.database,
            AcopioMeasurementsRename(
                medicionIds=[' measurement-1 '],
                nombre=' ZV ',
            ),
        )

        self.assertEqual(result.nombre, 'ZV')
        self.assertEqual(result.medicion_ids, ['measurement-1'])
        measurement = self.database['bascula'].find_one({'_id': 'measurement-1'})
        self.assertEqual(measurement['Area_Nivel'], 'ZV')
        audit = measurement['auditoria_acopio'][0]
        self.assertEqual(audit['accion'], 'renombrar_medicion')
        self.assertEqual(audit['nombreAnterior'], 'ZV Balizar')
        self.assertEqual(audit['nombreNuevo'], 'ZV')
        self.assertTrue(audit['fecha'].endswith('Z'))

    def test_rename_multiple_measurements_of_same_card(self):
        self.database['bascula'].insert_many(
            [
                _measurement('measurement-1', 'ZV Balizar', 100),
                _measurement('measurement-2', 'ZV Balizar', 200),
            ]
        )

        rename_acopio_measurements(
            self.database,
            AcopioMeasurementsRename(
                medicionIds=['measurement-1', 'measurement-2'],
                nombre='ZV',
            ),
        )

        measurements = list(self.database['bascula'].find().sort('_id'))
        self.assertEqual([measurement['Area_Nivel'] for measurement in measurements], ['ZV', 'ZV'])
        self.assertTrue(all('auditoria_acopio' in measurement for measurement in measurements))

    def test_rename_missing_measurement_returns_404_without_updates(self):
        self.database['bascula'].insert_one(_measurement('measurement-1', 'ZV Balizar', 100))

        with self.assertRaises(HTTPException) as context:
            rename_acopio_measurements(
                self.database,
                AcopioMeasurementsRename(
                    medicionIds=['measurement-1', 'missing'],
                    nombre='ZV',
                ),
            )

        self.assertEqual(context.exception.status_code, 404)
        measurement = self.database['bascula'].find_one({'_id': 'measurement-1'})
        self.assertEqual(measurement['Area_Nivel'], 'ZV Balizar')
        self.assertNotIn('auditoria_acopio', measurement)

    def test_rename_different_cards_returns_422_without_updates(self):
        self.database['bascula'].insert_many(
            [
                _measurement('measurement-1', 'ZV Balizar', 100),
                _measurement('measurement-2', 'Other', 200),
            ]
        )

        with self.assertRaises(HTTPException) as context:
            rename_acopio_measurements(
                self.database,
                AcopioMeasurementsRename(
                    medicionIds=['measurement-1', 'measurement-2'],
                    nombre='ZV',
                ),
            )

        self.assertEqual(context.exception.status_code, 422)
        self.assertEqual(
            self.database['bascula'].find_one({'_id': 'measurement-1'})['Area_Nivel'],
            'ZV Balizar',
        )

    def test_rename_rejects_empty_name_and_duplicate_ids(self):
        with self.assertRaises(ValidationError):
            AcopioMeasurementsRename(medicionIds=['measurement-1'], nombre='  ')
        with self.assertRaises(ValidationError):
            AcopioMeasurementsRename(
                medicionIds=['measurement-1', 'measurement-1'],
                nombre='ZV',
            )


@unittest.skipUnless(
    TEST_MONGO_URI,
    'Defina ACOPIO_TEST_MONGO_URI con una base de datos MongoDB de pruebas en replica set.',
)
class AcopioWorkflowIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = MongoClient(TEST_MONGO_URI)
        cls.database = cls.client.get_default_database()
        if cls.database is None:
            raise unittest.SkipTest('La URI de pruebas debe incluir el nombre de la base de datos.')

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def setUp(self):
        self.database['bascula'].delete_many({})

    def test_picking_initial_has_no_groups(self):
        self.database['bascula'].insert_one(_measurement('picking-1', 'BE_160-75', 5000))

        measurement = get_acopio_measurement(self.database, 'picking-1')

        self.assertEqual(measurement.grupo, [])

    def test_classification_sets_each_operational_state(self):
        expected_states = {
            'mineral': ('estado-stock', 'Stock'),
            'baja_ley': ('estado-stock', 'Stock'),
            'esteril': ('estado-esteril', 'Esteril'),
        }
        for classification, (state_id, state_name) in expected_states.items():
            measurement_id = f'classification-{classification}'
            self.database['bascula'].insert_one(
                _measurement(measurement_id, 'BE_160-75', 5000)
            )

            result = classify_acopio_measurement(
                self.database,
                measurement_id,
                AcopioMeasurementClassification(tipo=classification),
            )

            self.assertEqual(
                result.grupo[-1].model_dump(by_alias=True)['id'], state_id
            )
            self.assertEqual(result.grupo[-1].nombre, state_name)
            self.assertEqual(result.grupo[-1].tipo, classification)

    def test_classification_preserves_balizado_origin(self):
        marker = {
            'id': 'origen-balizado',
            'nombre': 'Origen balizado',
            'tipo': 'mineral',
            'fechaAsignacion': datetime.now(timezone.utc),
        }
        self.database['bascula'].insert_one(
            _measurement('marked-1', 'BE_160-75', 5000, [marker])
        )

        result = classify_acopio_measurement(
            self.database,
            'marked-1',
            AcopioMeasurementClassification(tipo='mineral'),
        )

        self.assertEqual(result.grupo[0].id, 'origen-balizado')

    def test_merge_updates_origins_and_embeds_audit(self):
        stock_group = {
            'id': 'estado-stock',
            'nombre': 'Stock',
            'tipo': 'mineral',
            'fechaAsignacion': datetime.now(timezone.utc),
        }
        self.database['bascula'].insert_many(
            [
                _measurement('origin-1', 'BE_160-75_Balizado', 5000),
                _measurement('origin-2', 'BE_160-75_Balizado', 3500),
                _measurement('destination-1', 'BE_160-75', 10000, [stock_group]),
            ]
        )

        result = merge_acopio_cards(
            self.database,
            AcopioCardsMerge(
                origenMedicionIds=['origin-1', 'origin-2'],
                destinoMedicionIds=['destination-1'],
            ),
        )

        self.assertEqual(result.nombre, 'BE_160-75')
        self.assertEqual(result.total, 18500)
        origin = self.database['bascula'].find_one({'_id': 'origin-1'})
        self.assertEqual(origin['Area_Nivel'], 'BE_160-75')
        self.assertEqual(
            [group['id'] for group in origin['grupo']],
            ['origen-balizado', 'estado-stock'],
        )
        self.assertEqual(origin['grupo'][-1]['tipo'], 'mineral')
        audit = origin['auditoria_acopio'][0]
        self.assertEqual(audit['accion'], 'fusionar_tarjetas')
        self.assertEqual(audit['nombreOrigen'], 'BE_160-75_Balizado')
        self.assertEqual(audit['nombreDestino'], 'BE_160-75')
        self.assertTrue(audit['fecha'].endswith('Z'))
        destination = self.database['bascula'].find_one({'_id': 'destination-1'})
        self.assertNotIn('auditoria_acopio', destination)

    def test_merge_accepts_ballizar_suffix(self):
        stock_group = {
            'id': 'estado-stock',
            'nombre': 'Stock',
            'tipo': 'mineral',
            'fechaAsignacion': datetime.now(timezone.utc),
        }
        self.database['bascula'].insert_many(
            [
                _measurement('origin-1', 'BE_160-75_Ballizar', 5000),
                _measurement('destination-1', 'BE_160-75', 10000, [stock_group]),
            ]
        )

        result = merge_acopio_cards(
            self.database,
            AcopioCardsMerge(
                origenMedicionIds=['origin-1'],
                destinoMedicionIds=['destination-1'],
            ),
        )

        self.assertEqual(result.nombre, 'BE_160-75')
        self.assertEqual(
            self.database['bascula'].find_one({'_id': 'origin-1'})['Area_Nivel'],
            'BE_160-75',
        )

    def test_merge_rejects_incompatible_names_without_changes(self):
        stock_group = {
            'id': 'estado-stock',
            'nombre': 'Stock',
            'tipo': 'mineral',
            'fechaAsignacion': datetime.now(timezone.utc),
        }
        self.database['bascula'].insert_many(
            [
                _measurement('origin-1', 'BE_160-75_Balizado', 5000),
                _measurement('destination-1', 'OTHER', 10000, [stock_group]),
            ]
        )

        with self.assertRaises(HTTPException) as context:
            merge_acopio_cards(
                self.database,
                AcopioCardsMerge(
                    origenMedicionIds=['origin-1'],
                    destinoMedicionIds=['destination-1'],
                ),
            )

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(
            self.database['bascula'].find_one({'_id': 'origin-1'})['Area_Nivel'],
            'BE_160-75_Balizado',
        )

    def test_merge_missing_measurement_returns_404(self):
        self.database['bascula'].insert_one(
            _measurement('origin-1', 'BE_160-75_Balizado', 5000)
        )

        with self.assertRaises(HTTPException) as context:
            merge_acopio_cards(
                self.database,
                AcopioCardsMerge(
                    origenMedicionIds=['origin-1'],
                    destinoMedicionIds=['missing'],
                ),
            )

        self.assertEqual(context.exception.status_code, 404)

    def test_merge_preserves_baja_ley_destination_state(self):
        stock_group = {
            'id': 'estado-stock',
            'nombre': 'Stock',
            'tipo': 'baja_ley',
            'fechaAsignacion': datetime.now(timezone.utc),
        }
        self.database['bascula'].insert_many(
            [
                _measurement('origin-1', 'BE_160-75_Balizado', 5000),
                _measurement('destination-1', 'BE_160-75', 10000, [stock_group]),
            ]
        )

        merge_acopio_cards(
            self.database,
            AcopioCardsMerge(
                origenMedicionIds=['origin-1'],
                destinoMedicionIds=['destination-1'],
            ),
        )
        origin = self.database['bascula'].find_one({'_id': 'origin-1'})
        self.assertEqual(origin['grupo'][-1]['tipo'], 'baja_ley')

    def test_merge_rejects_esteril_destination_without_updates(self):
        esteril_group = {
            'id': 'estado-esteril',
            'nombre': 'Esteril',
            'tipo': 'esteril',
            'fechaAsignacion': datetime.now(timezone.utc),
        }
        self.database['bascula'].insert_many(
            [
                _measurement('origin-1', 'BE_160-75_Balizar', 5000),
                _measurement('destination-1', 'BE_160-75', 10000, [esteril_group]),
            ]
        )

        with self.assertRaises(HTTPException) as context:
            merge_acopio_cards(
                self.database,
                AcopioCardsMerge(
                    origenMedicionIds=['origin-1'],
                    destinoMedicionIds=['destination-1'],
                ),
            )

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(
            self.database['bascula'].find_one({'_id': 'origin-1'})['Area_Nivel'],
            'BE_160-75_Balizar',
        )

    def test_merge_rejects_non_balizado_origin_without_updates(self):
        stock_group = {
            'id': 'estado-stock',
            'nombre': 'Stock',
            'tipo': 'mineral',
            'fechaAsignacion': datetime.now(timezone.utc),
        }
        self.database['bascula'].insert_many(
            [
                _measurement('origin-1', 'BE_160-75', 5000),
                _measurement('destination-1', 'BE_160-75', 10000, [stock_group]),
            ]
        )

        with self.assertRaises(HTTPException) as context:
            merge_acopio_cards(
                self.database,
                AcopioCardsMerge(
                    origenMedicionIds=['origin-1'],
                    destinoMedicionIds=['destination-1'],
                ),
            )

        self.assertEqual(context.exception.status_code, 409)
        self.assertNotIn(
            'auditoria_acopio',
            self.database['bascula'].find_one({'_id': 'origin-1'}),
        )


class AcopioMergeConcurrencyTests(unittest.TestCase):
    def test_merge_incomplete_update_returns_409_after_one_write(self):
        stock_group = {
            'id': 'estado-stock',
            'nombre': 'Stock',
            'tipo': 'mineral',
            'fechaAsignacion': datetime.now(timezone.utc),
        }
        database = ConcurrentMergeDatabase(
            [
                _measurement('origin-1', 'BE_160-75_Balizado', 5000),
                _measurement('destination-1', 'BE_160-75', 10000, [stock_group]),
            ]
        )

        with self.assertRaises(HTTPException) as context:
            merge_acopio_cards(
                database,
                AcopioCardsMerge(
                    origenMedicionIds=['origin-1'],
                    destinoMedicionIds=['destination-1'],
                ),
            )

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(database.bascula.update_calls, 1)