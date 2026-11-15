"""Saving an observation can start one AI follow-up after explicit opt-in."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from plant_care.gemini import AnalysisError
from plant_care.snapshot import dump_store, restore_connection
from plant_care.storage import PlantStore
from test_gemini import RESULT


APP_PATH = Path(__file__).resolve().parents[1] / 'app.py'


class AutomaticObservationTests(unittest.TestCase):
    def test_opt_in_analyzes_new_observation_once_and_opens_result(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {'PLANT_CARE_DATA_DIR': folder, 'STORAGE_BACKEND': 'local'}), \
                patch('plant_care.ai_ui.api_key', return_value='test-key'), \
                patch('plant_care.ai_ui.analyze', return_value=(RESULT, {'total_tokens': 15})) as ai:
            store = PlantStore(folder)
            plant = store.add_plant('집 식물')
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            app.button(key=f'open_plant_{plant}').click().run()
            self.assertFalse(store.get_plant(plant)['auto_ai_enabled'])
            app.text_area(key='care_notes').set_value('새 잎과 흙을 살펴봤어요')
            next(button for button in app.button if button.label == '기록 저장').click().run()
            self.assertEqual(len(store.list_logs(plant)), 1)
            self.assertEqual(store.list_analyses(plant), [])
            ai.assert_not_called()

            app.button(key=f'auto_ai_change_{plant}').click().run()
            self.assertEqual(store.get_plant(plant)['auto_ai_enabled'], 1)
            app.selectbox(key='care_kind').select('observation')
            app.text_area(key='care_notes').set_value('잎 끝이 마르고 있어요')
            next(button for button in app.button if button.label == '기록 저장').click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(store.list_logs(plant)[0]['kind'], 'observation')
            self.assertEqual(store.get_plant(plant)['auto_ai_enabled'], 1)
            self.assertEqual(ai.call_count, 1)
            self.assertEqual(len(store.list_logs(plant)), 2)
            saved = store.list_analyses(plant)
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]['source_log_id'], store.list_logs(plant)[0]['id'])
            self.assertIn('잎 끝이 마르고 있어요', saved[0]['input']['current_state'])
            self.assertEqual(app.session_state[f'plant_tabs_{plant}'], 'AI 분석')
            app.run()
            self.assertEqual(ai.call_count, 1)
            self.assertEqual(len(store.list_analyses(plant)), 1)
            app.button(key='detail_record').click().run()
            app.selectbox(key='care_kind').select('watering')
            app.text_area(key='care_notes').set_value('흙을 확인하고 물을 줬어요')
            next(button for button in app.button if button.label == '기록 저장').click().run()
            self.assertEqual(ai.call_count, 2)
            self.assertEqual(store.list_analyses(plant)[0]['source_log_id'], store.list_logs(plant)[0]['id'])
            self.assertEqual(PlantStore(folder).get_plant(plant)['auto_ai_enabled'], 1)

    def test_ai_failure_keeps_the_record_and_old_snapshot_starts_opted_out(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as target, \
                patch.dict(os.environ, {'PLANT_CARE_DATA_DIR': folder, 'STORAGE_BACKEND': 'local'}), \
                patch('plant_care.ai_ui.api_key', return_value='test-key'), \
                patch('plant_care.ai_ui.analyze', side_effect=AnalysisError('분석 연결 실패')):
            store = PlantStore(folder)
            plant = store.add_plant('집 식물')
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            app.button(key=f'open_plant_{plant}').click().run()
            app.button(key=f'auto_ai_change_{plant}').click().run()
            app.selectbox(key='care_kind').select('observation')
            app.text_area(key='care_notes').set_value('오늘 관찰')
            next(button for button in app.button if button.label == '기록 저장').click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(store.list_logs(plant)), 1)
            self.assertEqual(store.list_analyses(plant), [])
            self.assertTrue(any('관리 기록은 저장됐어요' in item.value for item in app.warning))

            state = dump_store(store)
            for row in state['tables']['plants']:
                row.pop('auto_ai_enabled')
            restored = PlantStore(target)
            with restored._connection() as connection:
                restore_connection(connection, state)
            self.assertEqual(restored.get_plant(plant)['auto_ai_enabled'], 0)

    def test_snapshot_restores_analysis_link_to_its_observation(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as target:
            store = PlantStore(folder)
            plant = store.add_plant('첫 식물')
            store.set_auto_ai(plant, True)
            log_id = store.add_log(plant, 'observation', '2026-11-15', notes='새 잎')
            store.add_analysis(plant, 'fixture', {'current_state': '새 잎'}, RESULT, {}, source_log_id=log_id)
            restored = PlantStore(target)
            with restored._connection() as connection:
                restore_connection(connection, dump_store(store))
            self.assertEqual(restored.get_plant(plant)['auto_ai_enabled'], 1)
            self.assertEqual(restored.list_analyses(plant)[0]['source_log_id'], log_id)


if __name__ == '__main__':
    unittest.main()
