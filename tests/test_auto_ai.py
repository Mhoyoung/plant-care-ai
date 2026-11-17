"""Saving an observation can start one AI follow-up after explicit opt-in."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from plant_care.gemini import AnalysisError
from plant_care.ai_ui import analyze_saved_log
from plant_care.snapshot import dump_store, restore_connection
from plant_care.storage import PlantStore
from test_gemini import RESULT
from test_storage import test_photo_bytes


APP_PATH = Path(__file__).resolve().parents[1] / 'app.py'


class AutomaticObservationTests(unittest.TestCase):
    def test_registration_opt_in_analyzes_each_later_record_with_history(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {'PLANT_CARE_DATA_DIR': folder, 'STORAGE_BACKEND': 'local'}), \
                patch('plant_care.ai_ui.api_key', return_value='test-key'), \
                patch('plant_care.ai_ui.analyze', return_value=(RESULT, {})) as ai:
            store = PlantStore(folder)
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            app.text_input(key='plant_name').set_value('매일 관찰할 식물')
            app.checkbox(key='plant_auto_ai').check()
            next(button for button in app.button if button.label == '식물 등록').click().run()
            plant = store.list_plants()[0]['id']
            self.assertEqual(store.get_plant(plant)['auto_ai_enabled'], 1)
            ai.assert_not_called()

            app.text_area(key='care_notes').set_value('첫날 잎은 초록색이에요')
            next(button for button in app.button if button.label == '기록 저장').click().run()
            self.assertEqual(ai.call_count, 1)
            app.button(key='detail_record').click().run()
            app.text_area(key='care_notes').set_value('둘째 날 잎 끝이 갈색이에요')
            next(button for button in app.button if button.label == '기록 저장').click().run()
            self.assertEqual(ai.call_count, 2)
            context = ai.call_args.args[1]
            self.assertEqual(len(context['recent_care_logs']), 2)
            self.assertEqual(context['recent_care_logs'][0]['notes'], '첫날 잎은 초록색이에요')
            self.assertEqual(context['recent_care_logs'][1]['notes'], '둘째 날 잎 끝이 갈색이에요')
            self.assertEqual(len(store.list_analyses(plant)), 2)

    def test_uses_saved_profile_photo_for_identity_then_prefers_new_photo(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch('plant_care.ai_ui.api_key', return_value='test-key'), \
                patch('plant_care.ai_ui.analyze', return_value=(RESULT, {})) as ai:
            store = PlantStore(folder)
            plant = store.add_plant('집 식물', photo=test_photo_bytes())
            store.set_auto_ai(plant, True)
            log_id = store.add_log(plant, 'observation', '2026-11-15', notes='새 잎을 봤어요')
            self.assertTrue(analyze_saved_log(store, plant, log_id))
            context, image = ai.call_args.args[1:]
            self.assertIn('대표 사진', context['photo_source'])
            self.assertEqual(image, store.read_photo(store.get_plant(plant)['photo_path']))
            self.assertNotIn('photo_path', context)
            self.assertFalse(analyze_saved_log(store, plant, log_id))
            self.assertEqual(ai.call_count, 1)

            new_log = store.add_log(plant, 'observation', '2026-11-16', photo=test_photo_bytes())
            self.assertTrue(analyze_saved_log(store, plant, new_log))
            context, image = ai.call_args.args[1:]
            self.assertIn('이번 관리 기록 사진', context['photo_source'])
            self.assertEqual(image, store.read_photo(store.list_logs(plant)[0]['photo_path']))

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
            self.assertTrue(any('이 식물은 어떤 종류일까요?' in item.proto.body for item in app.get('html')))
            self.assertTrue(any('함께 돌보는 방법' in item.proto.body for item in app.get('html')))
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

    def test_older_saved_results_without_identity_still_open(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {'PLANT_CARE_DATA_DIR': folder, 'STORAGE_BACKEND': 'local'}):
            store = PlantStore(folder)
            plant = store.add_plant('지난 관찰')
            old_result = {key: value for key, value in RESULT.items() if key not in ('identity', 'care_guide')}
            store.add_analysis(plant, 'old-model', {'current_state': '예전 질문', 'recent_care_logs': [],
                                                    'has_photo': False}, old_result, {})
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            app.button(key=f'open_plant_{plant}').click().run()
            app.button(key='detail_ai').click().run()
            self.assertEqual(len(app.exception), 0)


if __name__ == '__main__':
    unittest.main()
