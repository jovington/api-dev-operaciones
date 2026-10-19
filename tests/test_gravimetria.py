from datetime import datetime, timezone
import unittest

from pydantic import ValidationError

from app.models.gravimetria import GravimetriaPredictionRecord


class GravimetriaPredictionRecordTests(unittest.TestCase):
    def test_serializes_only_the_chart_contract(self) -> None:
        record = GravimetriaPredictionRecord.model_validate({
            'created_at': datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
            'metadata': {
                'camera_id': 'CAM02',
                'granulometria': {'fino': 20, 'medio': 50, 'grueso': 100},
                'ignored': 'value',
            },
            'predictions': {
                'timestamp': datetime(2026, 1, 1, 10, 1, tzinfo=timezone.utc),
                'rocks_by_model_class': {'fino': 12, 'grueso': 3},
                'total_objects_in_roi': 15,
                'oversize_ratio_pct': 6.98,
                'ignored': True,
            },
            'ignored': True,
        })

        self.assertEqual(record.model_dump(mode='json'), {
            'created_at': '2026-01-01T10:00:00.000Z',
            'metadata': {
                'camera_id': 'CAM02',
                'granulometria': {'fino': 20, 'medio': 50, 'grueso': 100},
            },
            'predictions': {
                'timestamp': '2026-01-01T10:01:00.000Z',
                'rocks_by_model_class': {'fino': 12, 'grueso': 3},
                'total_objects_in_roi': 15,
                'oversize_ratio_pct': 6.98,
            },
        })

    def test_rejects_empty_classes_and_non_positive_roi(self) -> None:
        with self.assertRaises(ValidationError):
            GravimetriaPredictionRecord.model_validate({
                'created_at': datetime.now(timezone.utc),
                'metadata': {'camera_id': 'CAM02', 'granulometria': {'fino': 20}},
                'predictions': {
                    'timestamp': datetime.now(timezone.utc),
                    'rocks_by_model_class': {},
                    'total_objects_in_roi': 0,
                    'oversize_ratio_pct': 0,
                },
            })