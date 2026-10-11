from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from plant_care.gemini import analysis_context
from plant_care.storage import PlantStore
from test_gemini import RESULT
from test_storage import test_photo_bytes


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = PlantStore(self.root)
        self.plant = self.store.add_plant('몬스테라')
        self.other = self.store.add_plant('다른 식물')
        self.original_context = analysis_context(self.store, self.plant, '상태를 살펴봐 주세요', False)
        self.analysis = self.store.add_analysis(self.plant, 'test-model', self.original_context, RESULT, {})
        self.suggestion = self.store.list_suggestions(self.plant)[0]['id']

    def record(self, link_type='execution', **overrides):
        values = dict(plant_id=self.plant, kind='observation', occurred_on=date.today(),
                      notes='흙이 촉촉해서 물을 주지 않고 지켜봄', suggestion_id=self.suggestion, link_type=link_type)
        values.update(overrides)
        return self.store.add_log(**values)

    def test_complete_loop_persists_and_next_analysis_uses_it_without_changing_old_snapshot(self):
        execution = self.record(photo=test_photo_bytes())
        observed = self.record('outcome', notes='새 잎이 펴졌음', outcome='improved', photo=test_photo_bytes())
        reopened = PlantStore(self.root)
        suggestion = reopened.list_suggestions(self.plant)[0]
        self.assertEqual(suggestion['execution']['id'], execution)
        self.assertEqual(suggestion['observations'][0]['id'], observed)
        self.assertTrue(reopened.photo_path(suggestion['observations'][0]['photo_path']).exists())
        self.assertEqual(reopened.list_analyses(self.plant)[0]['input'], self.original_context)
        context = analysis_context(reopened, self.plant, '이후 상태를 확인해 주세요', False)
        previous = context['previous_suggestions'][0]
        self.assertEqual(previous['suggestion'], RESULT['actions'][0])
        self.assertEqual(previous['execution']['notes'], '흙이 촉촉해서 물을 주지 않고 지켜봄')
        self.assertEqual(previous['observations'][0]['outcome'], 'improved')
        for local_field in ('photo_path', 'suggestion_id', 'analysis_id', 'plant_id'):
            self.assertNotIn(local_field, json.dumps(context))
        self.assertEqual(reopened.last_watered(self.plant), None)
        self.assertEqual(reopened.list_suggestions(self.other), [])
        self.assertEqual(reopened.export_plant(self.plant)['ai_suggestions'][0]['execution']['id'], execution)
        self.assertEqual(reopened.export_plant(self.plant)['schema_version'], 2)

    def test_invalid_links_do_not_create_records_or_photos(self):
        for overrides in ({'plant_id': self.other}, {'suggestion_id': 999}, {'link_type': None},
                          {'link_type': 'unknown'}, {'suggestion_id': None}, {'notes': ''},
                          {'occurred_on': date.today() - timedelta(days=1)},
                          {'outcome': 'improved'}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.record(photo=test_photo_bytes(), **overrides)
        self.assertEqual(self.store.list_logs(self.plant), [])
        self.assertEqual(self.store.list_logs(self.other), [])
        self.assertFalse((self.root / 'photos').exists())

    def test_observation_requires_execution_and_cannot_predate_it(self):
        with self.assertRaises(ValueError):
            self.record('outcome', outcome='improved')
        with closing(sqlite3.connect(self.store.db_path)) as db, db:
            db.execute('UPDATE ai_analyses SET created_at = ? WHERE id = ?',
                       ((date.today() - timedelta(days=3)).isoformat() + 'T00:00:00+00:00', self.analysis))
        self.record(occurred_on=date.today() - timedelta(days=1))
        with self.assertRaises(ValueError):
            self.record('outcome', occurred_on=date.today() - timedelta(days=2), outcome='improved')
        with self.assertRaises(ValueError):
            self.record('outcome', kind='watering', outcome='improved')
        with self.assertRaises(ValueError):
            self.record('outcome', notes='')
        self.record('outcome', notes='변화는 아직 확인하지 못함')
        self.assertEqual(self.store.list_suggestions(self.plant)[0]['observations'][0]['outcome'], 'unrecorded')

    def test_two_simultaneous_execution_saves_leave_one_record_and_one_photo(self):
        def save():
            try:
                return self.record(photo=test_photo_bytes())
            except (ValueError, sqlite3.Error):
                return None
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: save(), range(2)))
        self.assertEqual(sum(value is not None for value in results), 1)
        self.assertEqual(len(self.store.list_logs(self.plant)), 1)
        self.assertEqual(len(list((self.root / 'photos').glob('*.jpg'))), 1)

    def test_failed_insert_rolls_back_record_and_removes_saved_photo(self):
        original = self.store._validate_link
        def reject_after_validation(connection, *args):
            original(connection, *args)
            connection.execute("CREATE TRIGGER reject_log BEFORE INSERT ON care_logs BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with patch.object(self.store, '_validate_link', side_effect=reject_after_validation), self.assertRaises(sqlite3.IntegrityError):
            self.record(photo=test_photo_bytes())
        self.assertEqual(self.store.list_logs(self.plant), [])
        self.assertEqual(list((self.root / 'photos').glob('*.jpg')), [])

    def test_context_bounds_observations_and_does_not_recurse_into_prior_inputs(self):
        self.record()
        for index in range(5):
            self.record('outcome', notes=f'관찰 {index}', outcome='unchanged')
        context = analysis_context(self.store, self.plant, '다음 관리', False)
        self.assertEqual([o['notes'] for o in context['previous_suggestions'][0]['observations']], ['관찰 2', '관찰 3', '관찰 4'])
        self.store.add_analysis(self.plant, 'test-model', context, RESULT, {})
        next_context = analysis_context(self.store, self.plant, '다음 상태', False)
        self.assertIsNone(next_context['previous_suggestions'][0]['execution'])
        self.assertNotIn('input', next_context['previous_suggestions'][0])
        self.assertEqual(len(self.store.list_suggestions(self.plant)[-1]['observations']), 5)

    def test_legacy_database_migration_is_additive_and_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / 'plants.db'
            with closing(sqlite3.connect(db_path)) as db, db:
                db.executescript('''
                    CREATE TABLE plants(id INTEGER PRIMARY KEY, name TEXT NOT NULL, species TEXT, location TEXT, notes TEXT, photo_path TEXT, created_at TEXT);
                    CREATE TABLE care_logs(id INTEGER PRIMARY KEY, plant_id INTEGER REFERENCES plants(id), kind TEXT, occurred_on TEXT, notes TEXT, outcome TEXT, photo_path TEXT, created_at TEXT);
                    CREATE TABLE ai_analyses(id INTEGER PRIMARY KEY, plant_id INTEGER REFERENCES plants(id), model TEXT, input_json TEXT, result_json TEXT, usage_json TEXT, photo_path TEXT, created_at TEXT);
                    INSERT INTO plants VALUES (1, '기존 식물', '', '', '원래 메모', NULL, '2026-01-01T00:00:00+00:00');
                    INSERT INTO care_logs VALUES (1, 1, 'watering', '2026-01-02', '기존 물주기', 'unrecorded', NULL, '2026-01-02T00:00:00+00:00');
                ''')
                db.execute('INSERT INTO ai_analyses VALUES (1, 1, ?, ?, ?, ?, NULL, ?)',
                           ('old-model', json.dumps(self.original_context), json.dumps(RESULT), '{}', '2026-01-03T00:00:00+00:00'))
            migrated = PlantStore(folder)
            first_ids = [s['id'] for s in migrated.list_suggestions(1)]
            reopened = PlantStore(folder)
            self.assertEqual([s['id'] for s in reopened.list_suggestions(1)], first_ids)
            self.assertEqual(reopened.get_plant(1)['notes'], '원래 메모')
            self.assertEqual(reopened.list_logs(1)[0]['notes'], '기존 물주기')
            self.assertIsNone(reopened.list_logs(1)[0]['suggestion_id'])
            self.assertIsNone(reopened.list_suggestions(1)[0]['execution'])
            self.assertEqual(reopened.list_analyses(1)[0]['input'], self.original_context)
