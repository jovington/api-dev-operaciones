import os
import unittest
from datetime import datetime, timezone

from fastapi import HTTPException
from pymongo import MongoClient

from app.models.alimentacion_planta import (
    AlimentacionPlantaCreate as AlimentacionPlantaCreateModel,
    AlimentacionPlantaCancel,
    AlimentacionPlantaCopy,
    AlimentacionPlantaObservation,
    AlimentacionPlantaScoopUnload,
    AlimentacionesPlantaOrder,
)
from app.services.alimentacion_planta_service import (
    approve_alimentacion_planta,
    activate_alimentacion_planta,
    block_alimentacion_planta,
    cancel_alimentacion_planta,
    copy_alimentacion_planta,
    get_circuito_actual,
    _mineral_limitante,
    create_alimentacion_planta,
    finalize_alimentacion_planta,
    list_alimentaciones_planta,
    register_scoop_unload,
    reorder_alimentaciones_planta,
    unblock_alimentacion_planta,
)
from app.db.alimentacion_planta_repo import (
    migrate_hour_cards_to_planned_tons,
    migrate_scoop_unloads_to_tons,
)


TEST_MONGO_URI = os.getenv('ALIMENTACION_PLANTA_TEST_MONGO_URI')


def _stock_measurement(name: str, product: str, weight_kg: int | float = 1000) -> dict:
    return {
        'Area_Nivel': name,
        'Producto': product,
        'Peso_Neto': weight_kg,
        'Fecha': datetime(2026, 8, 10, tzinfo=timezone.utc),
        'grupo': [
            {
                'id': 'estado-stock',
                'nombre': 'Stock',
                'tipo': 'mineral',
                'fechaAsignacion': datetime(2026, 8, 10, tzinfo=timezone.utc),
            }
        ],
    }


def _card(name: str, product: str, tons: int | float = 1) -> dict:
    return {
        'nombre': name,
        'producto': product,
        'tipo': 'mineral',
        'toneladasPlanificadas': tons,
    }


def _hour_card(
    name: str,
    product: str,
    entries_per_hour: int = 1,
    planned_tons: int | float | None = None,
) -> dict:
    card = {
        'nombre': name,
        'producto': product,
        'tipo': 'mineral',
        'entradasPorHora': entries_per_hour,
    }
    if planned_tons is not None:
        card['toneladasPlanificadas'] = planned_tons
    return card


def _planning_values() -> dict:
    return {
        'ciclosAlimentacionHora': 3,
        'cargaPalaEstimadaTon': 14,
        'caudalEfectivoTph': 42,
    }


def AlimentacionPlantaCreate(**values) -> AlimentacionPlantaCreateModel:
    return AlimentacionPlantaCreateModel(**{**_planning_values(), **values})


def _approved_alimentacion(card: dict) -> dict:
    return {
        'codigo': 'AL-1',
        'estado': 'aprobada',
        'creadaEn': datetime(2026, 8, 10, tzinfo=timezone.utc),
        'aprobadaEn': datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
        'ronda': [card],
        'hora': [],
        'orden': 1,
        'velocidadEstimadaTph': 40,
        'esSubplanificacion': False,
        'planificacionPadreId': None,
        'mineralLimitante': card,
    }


@unittest.skipUnless(
    TEST_MONGO_URI,
    'Defina ALIMENTACION_PLANTA_TEST_MONGO_URI con una base de datos MongoDB de pruebas.',
)
class AlimentacionPlantaIntegrationTests(unittest.TestCase):
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
        self.database['alimentaciones_planta'].delete_many({})

    def test_create_pending_plan_keeps_bascula_unchanged(self):
        source = _stock_measurement('BE_160-75', 'Mineral de Carles')
        self.database['bascula'].insert_one(source)

        result = create_alimentacion_planta(
            self.database,
            AlimentacionPlantaCreate(
                codigo=' AL-20260810-AB12 ',
                ronda=[_card('BE_160-75', 'Mineral de Carles')],
                hora=[],
                velocidadEstimadaTph=40,
            ),
        )

        self.assertEqual(result.codigo, 'AL-20260810-AB12')
        self.assertEqual(result.estado, 'pendiente')
        self.assertEqual(self.database['bascula'].find_one({})['Area_Nivel'], 'BE_160-75')

    def test_rejects_duplicate_card_between_lists(self):
        with self.assertRaises(Exception):
            AlimentacionPlantaCreate(
                codigo='AL-1',
                ronda=[_card('BE_160-75', 'Mineral de Carles')],
                hora=[_hour_card('BE_160-75', 'Mineral de Carles')],
                velocidadEstimadaTph=40,
            )

    def test_rejects_card_not_available_in_stock(self):
        with self.assertRaises(HTTPException) as context:
            create_alimentacion_planta(
                self.database,
                AlimentacionPlantaCreate(
                    codigo='AL-1',
                    ronda=[_card('BE_160-75', 'Mineral de Carles')],
                    hora=[],
                    velocidadEstimadaTph=40,
                ),
            )

        self.assertEqual(context.exception.status_code, 404)

    def test_prevents_active_card_assignment_and_approves_once(self):
        self.database['bascula'].insert_one(
            _stock_measurement('BE_160-75', 'Mineral de Carles')
        )
        payload = AlimentacionPlantaCreate(
            codigo='AL-1',
            ronda=[_card('BE_160-75', 'Mineral de Carles')],
            hora=[],
            velocidadEstimadaTph=40,
        )
        created = create_alimentacion_planta(self.database, payload)

        with self.assertRaises(HTTPException) as context:
            create_alimentacion_planta(
                self.database,
                AlimentacionPlantaCreate(codigo='AL-2', ronda=[_card('BE_160-75', 'Mineral de Carles')], hora=[], velocidadEstimadaTph=40),
            )
        self.assertEqual(context.exception.status_code, 409)

        approved = approve_alimentacion_planta(self.database, created.id)
        self.assertEqual(approved.estado, 'aprobada')
        with self.assertRaises(HTTPException) as context:
            approve_alimentacion_planta(self.database, created.id)
        self.assertEqual(context.exception.status_code, 409)

    def test_list_and_reorder_by_order(self):
        self.database['alimentaciones_planta'].insert_many(
            [
                {
                    'codigo': 'AL-1',
                    'estado': 'pendiente',
                    'creadaEn': datetime.now(timezone.utc),
                    'aprobadaEn': None,
                    'ronda': [],
                    'hora': [],
                    'orden': 1,
                    'velocidadEstimadaTph': 40,
                },
                {
                    'codigo': 'AL-2',
                    'estado': 'pendiente',
                    'creadaEn': datetime.now(timezone.utc),
                    'aprobadaEn': None,
                    'ronda': [],
                    'hora': [],
                    'orden': 2,
                    'velocidadEstimadaTph': 40,
                },
            ]
        )
        original = list_alimentaciones_planta(self.database)

        reorder_alimentaciones_planta(
            self.database,
            AlimentacionesPlantaOrder(ids=[original[1].id, original[0].id]),
        )

        reordered = list_alimentaciones_planta(self.database)
        self.assertEqual([item.codigo for item in reordered], ['AL-2', 'AL-1'])

    def test_register_scoop_unload_consumes_fifo_and_adds_audits(self):
        card = _card('BE_160-75', 'Mineral de Carles', 2)
        self.database['bascula'].insert_many(
            [
                {
                    **_stock_measurement(card['nombre'], card['producto']),
                    'Fecha': datetime(2026, 8, 10, 8, tzinfo=timezone.utc),
                },
                {
                    **_stock_measurement(card['nombre'], card['producto']),
                    'Fecha': datetime(2026, 8, 10, 9, tzinfo=timezone.utc),
                },
            ]
        )
        self.database['bascula'].update_one({}, {'$set': {'Peso_Neto': 1000}})
        active = _approved_alimentacion(card)
        active['estado'] = 'activa'
        active['circuitoActivoClave'] = 'principal'
        self.database['alimentaciones_planta'].insert_one(active)
        alimentacion = self.database['alimentaciones_planta'].find_one({})

        result = register_scoop_unload(
            self.database,
            str(alimentacion['_id']),
            AlimentacionPlantaScoopUnload(
                nombre=card['nombre'],
                producto=card['producto'],
                toneladas=1.5,
            ),
        )

        self.assertEqual(result.toneladas, 1.5)
        self.assertEqual(result.stockRestanteToneladas, 0.5)
        measurements = list(self.database['bascula'].find().sort('Fecha'))
        self.assertEqual([measurement['Peso_Neto'] for measurement in measurements], [0, 500])
        self.assertTrue(all(measurement['Peso_Neto'] >= 0 for measurement in measurements))
        self.assertEqual(
            [audit['pesoDescargadoKg'] for audit in (
                measurements[0]['auditoria_acopio'] + measurements[1]['auditoria_acopio']
            )],
            [1000, 500],
        )
        updated_alimentacion = self.database['alimentaciones_planta'].find_one({})
        self.assertEqual(updated_alimentacion['descargasPala'][0]['toneladas'], 1.5)
        self.assertNotIn('pesoKg', updated_alimentacion['descargasPala'][0])

    def test_rejects_scoop_unload_for_pending_alimentacion(self):
        card = _card('BE_160-75', 'Mineral de Carles')
        pending = _approved_alimentacion(card)
        pending['estado'] = 'pendiente'
        self.database['alimentaciones_planta'].insert_one(pending)
        alimentacion = self.database['alimentaciones_planta'].find_one({})

        with self.assertRaises(HTTPException) as context:
            register_scoop_unload(
                self.database,
                str(alimentacion['_id']),
                AlimentacionPlantaScoopUnload(
                    nombre=card['nombre'], producto=card['producto'], toneladas=0.1
                ),
            )

        self.assertEqual(context.exception.status_code, 409)

    def test_rejects_scoop_unload_for_card_outside_alimentacion(self):
        card = _card('BE_160-75', 'Mineral de Carles')
        self.database['alimentaciones_planta'].insert_one(_approved_alimentacion(card))
        alimentacion = self.database['alimentaciones_planta'].find_one({})

        with self.assertRaises(HTTPException) as context:
            register_scoop_unload(
                self.database,
                str(alimentacion['_id']),
                AlimentacionPlantaScoopUnload(
                    nombre='BE_160-76', producto='Mineral de Boinas', toneladas=0.1
                ),
            )

        self.assertEqual(context.exception.status_code, 409)

    def test_rejects_scoop_unload_larger_than_stock_without_changes(self):
        card = _card('BE_160-75', 'Mineral de Carles')
        self.database['bascula'].insert_one(
            _stock_measurement(card['nombre'], card['producto'])
        )
        self.database['alimentaciones_planta'].insert_one(_approved_alimentacion(card))
        alimentacion = self.database['alimentaciones_planta'].find_one({})

        with self.assertRaises(HTTPException) as context:
            register_scoop_unload(
                self.database,
                str(alimentacion['_id']),
                AlimentacionPlantaScoopUnload(
                    nombre=card['nombre'], producto=card['producto'], toneladas=1.001
                ),
            )

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(self.database['bascula'].find_one({})['Peso_Neto'], 1000)
        self.assertNotIn(
            'descargasPala', self.database['alimentaciones_planta'].find_one({})
        )

    def test_requires_valid_estimated_speed_and_available_planned_tons(self):
        with self.assertRaises(Exception):
            AlimentacionPlantaCreate(
                codigo='AL-1', ronda=[_card('BE_160-75', 'Mineral de Carles')], hora=[], velocidadEstimadaTph=0
            )
        self.database['bascula'].insert_one(_stock_measurement('BE_160-75', 'Mineral de Carles'))
        with self.assertRaises(HTTPException) as context:
            create_alimentacion_planta(
                self.database,
                AlimentacionPlantaCreate(
                    codigo='AL-2', ronda=[_card('BE_160-75', 'Mineral de Carles', 1.1)], hora=[], velocidadEstimadaTph=40
                ),
            )
        self.assertEqual(context.exception.status_code, 409)

    def test_unreserved_tons_can_be_planned_later(self):
        self.database['bascula'].insert_one(_stock_measurement('BE_160-75', 'Mineral de Carles'))
        first = create_alimentacion_planta(
            self.database,
            AlimentacionPlantaCreate(codigo='AL-1', ronda=[_card('BE_160-75', 'Mineral de Carles', 0.4)], hora=[], velocidadEstimadaTph=40),
        )
        second = create_alimentacion_planta(
            self.database,
            AlimentacionPlantaCreate(codigo='AL-2', ronda=[_card('BE_160-75', 'Mineral de Carles', 0.6)], hora=[], velocidadEstimadaTph=40),
        )
        self.assertEqual([first.estado, second.estado], ['pendiente', 'pendiente'])

    def test_activate_block_unblock_and_cancel_starts_next(self):
        first_card = _card('BE_160-75', 'Mineral de Carles')
        second_card = _card('BE_160-76', 'Mineral de Boinas')
        self.database['bascula'].insert_many([
            _stock_measurement(first_card['nombre'], first_card['producto']),
            _stock_measurement(second_card['nombre'], second_card['producto']),
        ])
        first = create_alimentacion_planta(self.database, AlimentacionPlantaCreate(codigo='AL-1', ronda=[first_card], hora=[], velocidadEstimadaTph=40))
        second = create_alimentacion_planta(self.database, AlimentacionPlantaCreate(codigo='AL-2', ronda=[second_card], hora=[], velocidadEstimadaTph=40))
        approve_alimentacion_planta(self.database, first.id)
        approve_alimentacion_planta(self.database, second.id)
        self.assertEqual(activate_alimentacion_planta(self.database, first.id).estado, 'activa')
        self.assertEqual(block_alimentacion_planta(self.database, first.id, AlimentacionPlantaObservation(observacion='Parada')).estado, 'bloqueada')
        self.assertEqual(unblock_alimentacion_planta(self.database, first.id, AlimentacionPlantaObservation()).estado, 'activa')
        cancel_alimentacion_planta(self.database, first.id, AlimentacionPlantaCancel(observaciones='Mantenimiento'))
        self.assertEqual(get_alimentacion(self.database, second.id)['estado'], 'activa')

    def test_copy_creates_pending_subplan_and_inserts_after_parent(self):
        card = _card('BE_160-75', 'Mineral de Carles')
        source = _stock_measurement(card['nombre'], card['producto'])
        source['Peso_Neto'] = 2000
        self.database['bascula'].insert_one(source)
        origin = create_alimentacion_planta(self.database, AlimentacionPlantaCreate(codigo='AL-1', ronda=[card], hora=[], velocidadEstimadaTph=40))
        approve_alimentacion_planta(self.database, origin.id)
        copied = copy_alimentacion_planta(
            self.database, origin.id,
            AlimentacionPlantaCopy(
                codigo='AL-2',
                ronda=[_card(card['nombre'], card['producto'], 0.5)],
                hora=[],
                velocidadEstimadaTph=35,
                insertarDespuesDeId=origin.id,
                **_planning_values(),
            ),
        )
        self.assertTrue(copied.esSubplanificacion)
        self.assertEqual(copied.planificacionPadreId, origin.id)
        self.assertEqual([item.id for item in list_alimentaciones_planta(self.database)], [origin.id, copied.id])

    def test_current_circuit_uses_limitante_and_real_cinta_4_speed(self):
        card = _card('BE_160-75', 'Mineral de Carles', 1)
        self.database['bascula'].insert_one(_stock_measurement(card['nombre'], card['producto']))
        alimentacion = create_alimentacion_planta(
            self.database,
            AlimentacionPlantaCreate(codigo='AL-1', ronda=[card], hora=[], velocidadEstimadaTph=40),
        )
        approve_alimentacion_planta(self.database, alimentacion.id)
        activate_alimentacion_planta(self.database, alimentacion.id)
        self.database['planta_plc_raw'].insert_one(
            {'payload': {'timestamp': datetime(2026, 8, 10, 12, tzinfo=timezone.utc), 'fields': {'toneladas_Bascula_Cinta_4': 20}}}
        )

        current = get_circuito_actual(self.database)

        self.assertEqual(current.mineralLimitante.toneladasIniciales, 1)
        self.assertEqual(current.duracionNominalHoras, 1 / 42)
        self.assertEqual(current.duracionRealEstimadaHoras, 0.05)

    def test_depleting_limitante_finalizes_and_activates_next(self):
        first_card = _card('BE_160-75', 'Mineral de Carles')
        second_card = _card('BE_160-76', 'Mineral de Boinas')
        self.database['bascula'].insert_many([
            _stock_measurement(first_card['nombre'], first_card['producto']),
            _stock_measurement(second_card['nombre'], second_card['producto']),
        ])
        first = create_alimentacion_planta(self.database, AlimentacionPlantaCreate(codigo='AL-1', ronda=[first_card], hora=[], velocidadEstimadaTph=40))
        second = create_alimentacion_planta(self.database, AlimentacionPlantaCreate(codigo='AL-2', ronda=[second_card], hora=[], velocidadEstimadaTph=40))
        approve_alimentacion_planta(self.database, first.id)
        approve_alimentacion_planta(self.database, second.id)
        activate_alimentacion_planta(self.database, first.id)
        result = register_scoop_unload(self.database, first.id, AlimentacionPlantaScoopUnload(nombre=first_card['nombre'], producto=first_card['producto'], toneladas=1))
        self.assertEqual(result.progresoPorcentaje, 100)
        self.assertEqual(result.alimentacionSiguienteActivadaId, second.id)
        self.assertEqual(get_alimentacion(self.database, first.id)['estado'], 'finalizada')

    def test_rejects_crossed_ronda_and_hora_contracts(self):
        invalid_payloads = [
            {'ronda': [{'nombre': 'BE-1', 'producto': 'A', 'tipo': 'mineral'}], 'hora': []},
            {'ronda': [], 'hora': [{'nombre': 'BE-1', 'producto': 'A', 'tipo': 'mineral'}]},
            {'ronda': [_card('BE-1', 'A', 0)], 'hora': []},
            {'ronda': [_card('BE-1', 'A', float('nan'))], 'hora': []},
            {'ronda': [_card('BE-1', 'A', 1)], 'hora': [_hour_card('BE-2', 'B', 0)]},
            {'ronda': [_card('BE-1', 'A', 1)], 'hora': [_hour_card('BE-2', 'B', 1.5)]},
            {'ronda': [_card('BE-1', 'A', 1)], 'hora': [_hour_card('BE-2', 'B', 1, -1)]},
            {'ronda': [{**_card('BE-1', 'A'), 'entradasPorHora': 1}], 'hora': []},
        ]
        for index, invalid_payload in enumerate(invalid_payloads):
            with self.subTest(index=index), self.assertRaises(Exception):
                AlimentacionPlantaCreate(
                    codigo=f'AL-invalid-{index}', velocidadEstimadaTph=40, **invalid_payload
                )

    def test_hour_card_uses_complete_cycles_reserves_stock_and_tracks_unloads(self):
        ronda = _card('BE_160-75', 'Mineral de Carles', 73.5)
        segunda_ronda = _card('BE_160-77', 'Mineral de Carlés', 73.5)
        hora = _hour_card('BE_160-76', 'Mineral de Boinas', 1, 21)
        self.database['bascula'].insert_many([
            _stock_measurement(ronda['nombre'], ronda['producto'], 73500),
            _stock_measurement(segunda_ronda['nombre'], segunda_ronda['producto'], 73500),
            _stock_measurement(hora['nombre'], hora['producto'], 21000),
        ])
        mixed = create_alimentacion_planta(
            self.database,
            AlimentacionPlantaCreate(
                codigo='AL-1', ronda=[ronda], hora=[hora], velocidadEstimadaTph=40,
                ciclosAlimentacionHora=3, cargaPalaEstimadaTon=7, caudalEfectivoTph=21,
            ),
        )
        self.assertEqual(mixed.hora[0].entradasPorHora, 1)
        self.assertEqual(mixed.hora[0].toneladasPlanificadas, 21)
        with self.assertRaises(HTTPException) as context:
            create_alimentacion_planta(
                self.database,
                AlimentacionPlantaCreate(
                    codigo='AL-2',
                    ronda=[segunda_ronda],
                    hora=[_hour_card(hora['nombre'], hora['producto'], 1, 21)],
                    velocidadEstimadaTph=40,
                    ciclosAlimentacionHora=3, cargaPalaEstimadaTon=7, caudalEfectivoTph=21,
                ),
            )
        self.assertEqual(context.exception.status_code, 409)
        approve_alimentacion_planta(self.database, mixed.id)
        activate_alimentacion_planta(self.database, mixed.id)

        result = register_scoop_unload(
            self.database, mixed.id,
            AlimentacionPlantaScoopUnload(nombre=hora['nombre'], producto=hora['producto'], toneladas=7),
        )

        self.assertEqual(
            self.database['bascula'].find_one({'Area_Nivel': hora['nombre']})['Peso_Neto'], 14000
        )
        self.assertEqual(result.progresoPorcentaje, 100 * 7 / 94.5)
        self.assertEqual(
            get_alimentacion(self.database, mixed.id)['descargasPala'][0]['toneladas'], 7
        )

    def test_rejects_hour_tons_that_include_a_fractional_cycle(self):
        ronda = _card('BE_160-75', 'Mineral de Carles', 73.5)
        hora = _hour_card('BE_160-76', 'Mineral de Boinas', 1, 24.5)
        self.database['bascula'].insert_many([
            _stock_measurement(ronda['nombre'], ronda['producto'], 73500),
            _stock_measurement(hora['nombre'], hora['producto'], 24500),
        ])

        with self.assertRaises(HTTPException) as context:
            create_alimentacion_planta(
                self.database,
                AlimentacionPlantaCreate(
                    codigo='AL-fraccion', ronda=[ronda], hora=[hora], velocidadEstimadaTph=40,
                    ciclosAlimentacionHora=3, cargaPalaEstimadaTon=7, caudalEfectivoTph=21,
                ),
            )

        self.assertEqual(context.exception.status_code, 422)

    def test_progress_uses_all_ronda_and_hora_planned_tons(self):
        self.database['alimentaciones_planta'].insert_one(
            {
                'codigo': 'AL-progreso',
                'estado': 'activa',
                'creadaEn': datetime.now(timezone.utc),
                'ronda': [_card('BE_324', 'Mineral de Boinás', 924.2)],
                'hora': [_hour_card('ZV_295.2', 'Mineral de Boinás', 1, 21)],
                'orden': 1,
                'velocidadEstimadaTph': 60,
                'caudalEfectivoTph': 60,
                'descargasPala': [
                    {'fecha': '2026-08-11T09:00:00.000Z', 'nombre': 'BE_324', 'producto': 'Mineral de Boinás', 'toneladas': 807.5},
                ],
            }
        )

        listed = list_alimentaciones_planta(self.database)

        self.assertEqual(listed[0].progresoPorcentaje, 100 * 807.5 / (924.2 + 21))

    def test_migrates_scoop_unloads_to_tons_idempotently(self):
        self.database['alimentaciones_planta'].insert_one(
            {
                'codigo': 'AL-migracion',
                'descargasPala': [
                    {'fecha': '2026-08-11T07:31:50.725Z', 'nombre': 'BE_324', 'producto': 'Mineral de Boinás', 'pesoKg': 20000},
                    {'fecha': '2026-08-11T08:31:50.725Z', 'nombre': 'BE_325', 'producto': 'Mineral de Boinás', 'toneladas': 21},
                ],
            }
        )

        self.assertEqual(migrate_scoop_unloads_to_tons(self.database), 1)
        self.assertEqual(migrate_scoop_unloads_to_tons(self.database), 0)
        unloads = self.database['alimentaciones_planta'].find_one({})['descargasPala']
        self.assertEqual(unloads[0]['toneladas'], 20)
        self.assertNotIn('pesoKg', unloads[0])
        self.assertEqual(unloads[1]['toneladas'], 21)

    def test_rejects_legacy_scoop_unload_payload(self):
        with self.assertRaises(Exception):
            AlimentacionPlantaScoopUnload(
                nombre='BE_324', producto='Mineral de Boinás', pesoKg=20000
            )

    def test_finalize_activates_next_approved_alimentacion(self):
        first_card = _card('BE_160-75', 'Mineral de Carles')
        second_card = _card('BE_160-76', 'Mineral de Boinas')
        self.database['bascula'].insert_many([
            _stock_measurement(first_card['nombre'], first_card['producto']),
            _stock_measurement(second_card['nombre'], second_card['producto']),
        ])
        first = create_alimentacion_planta(self.database, AlimentacionPlantaCreate(codigo='AL-1', ronda=[first_card], hora=[], velocidadEstimadaTph=40))
        second = create_alimentacion_planta(self.database, AlimentacionPlantaCreate(codigo='AL-2', ronda=[second_card], hora=[], velocidadEstimadaTph=40))
        approve_alimentacion_planta(self.database, first.id)
        approve_alimentacion_planta(self.database, second.id)
        activate_alimentacion_planta(self.database, first.id)

        result = finalize_alimentacion_planta(
            self.database, first.id, AlimentacionPlantaObservation(observacion='Fin manual')
        )

        self.assertEqual(result.estado, 'finalizada')
        self.assertEqual(result.alimentacionSiguienteActivadaId, second.id)
        self.assertEqual(get_alimentacion(self.database, first.id)['observacionFinalizacion'], 'Fin manual')
        self.assertEqual(get_alimentacion(self.database, second.id)['estado'], 'activa')

    def test_migrates_historical_hour_cards_to_complete_cycles(self):
        self.database['bascula'].insert_one(
            _stock_measurement('ZV_295.2', 'Mineral de Boinás', 21000)
        )
        self.database['alimentaciones_planta'].insert_one(
            {
                'codigo': 'AL-historica',
                'estado': 'pendiente',
                'creadaEn': datetime.now(timezone.utc),
                'aprobadaEn': None,
                'ronda': [_card('BE_160-75', 'Mineral de Carles', 147)],
                'hora': [{
                    'nombre': 'ZV_295.2',
                    'producto': 'Mineral de Boinás',
                    'tipo': 'mineral',
                    'entradasPorHora': 1,
                }],
                'orden': 1,
                'velocidadEstimadaTph': 40,
                'caudalEfectivoTph': 42,
                'cargaPalaEstimadaTon': 7,
            }
        )

        self.assertEqual(migrate_hour_cards_to_planned_tons(self.database), 1)
        self.assertEqual(migrate_hour_cards_to_planned_tons(self.database), 0)
        migrated = self.database['alimentaciones_planta'].find_one({})['hora'][0]
        self.assertEqual(migrated['toneladasPlanificadas'], 21)

    def test_requires_consistent_operational_planning_values(self):
        payload = {
            'codigo': 'AL-parametros',
            'ronda': [_card('BE_160-75', 'Mineral de Carles')],
            'hora': [],
            'velocidadEstimadaTph': 40,
            **_planning_values(),
        }
        plan = AlimentacionPlantaCreateModel(**payload)
        self.assertEqual(plan.caudalEfectivoTph, 42)

        with self.assertRaises(Exception):
            AlimentacionPlantaCreateModel(
                codigo='AL-sin-parametros',
                ronda=[_card('BE_160-75', 'Mineral de Carles')],
                hora=[],
                velocidadEstimadaTph=40,
            )

        for field, value in (
            ('ciclosAlimentacionHora', 0),
            ('cargaPalaEstimadaTon', 0),
            ('caudalEfectivoTph', 41),
        ):
            invalid_payload = {**payload, field: value}
            with self.subTest(field=field), self.assertRaises(Exception):
                AlimentacionPlantaCreateModel(**invalid_payload)

    def test_limitante_uses_smallest_nominal_duration(self):
        alimentacion = {
            'ronda': [
                _card('BE_160-75', 'Mineral de Carles', 3),
                _card('BE_160-76', 'Mineral de Boinas', 2),
            ],
            'caudalEfectivoTph': 40,
        }
        self.assertEqual(
            _mineral_limitante(alimentacion)['nombre'], 'BE_160-76'
        )