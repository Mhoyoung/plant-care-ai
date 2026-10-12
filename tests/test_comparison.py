from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from plant_care.comparison import demo_context, export_trial, new_trial, run_side
from plant_care.gemini import AnalysisError
from plant_care.storage import PlantStore
from test_gemini import RESULT
from test_storage import test_photo_bytes

APP = Path(__file__).resolve().parents[1] / "app.py"


class ComparisonTests(unittest.TestCase):
    def test_only_history_changes_between_conditions_and_source_is_unchanged(self):
        for case in ("wet", "dry", "followup"):
            with self.subTest(case=case):
                context = demo_context(case)
                context['plant']['notes'] = '등록 메모에 적힌 과거 관리 기록'
                original = deepcopy(context)
                trial = new_trial(context, test_photo_bytes(), {"kind": "synthetic"})
                baseline, history = trial['inputs'].values()
                differences = {key for key in history if key not in baseline or baseline[key] != history[key]}
                self.assertEqual(differences, {'last_watered', 'recent_care_logs', 'previous_suggestions'})
                self.assertEqual(context, original)
                self.assertEqual(baseline['plant']['notes'], '')
                self.assertTrue(baseline['has_photo'])
                self.assertEqual(json.loads(export_trial(trial))['photo_sha256'], trial['photo_sha256'])
                self.assertNotIn('photo', json.loads(export_trial(trial)))

    def test_manual_calls_share_photo_and_completed_calls_do_not_repeat(self):
        photo = test_photo_bytes()
        trial = new_trial(demo_context('wet'), photo)
        with patch('plant_care.comparison.analyze', return_value=(RESULT, {'total_tokens': 30})) as api:
            with self.assertRaises(ValueError):
                run_side(trial, 'baseline', 'test-key', False)
            api.assert_not_called()
            self.assertEqual(trial['attempts'], {})
            run_side(trial, 'baseline', 'test-key', True)
            run_side(trial, 'history', 'test-key', True)
            self.assertEqual(api.call_count, 2)
            self.assertEqual(api.call_args_list[0].args[2], photo)
            self.assertEqual(api.call_args_list[1].args[2], photo)
            with self.assertRaises(ValueError):
                run_side(trial, 'baseline', 'test-key', True)
            self.assertEqual(api.call_count, 2)
            self.assertNotIn('test-key', export_trial(trial))

    def test_failed_second_call_preserves_first_and_never_retries_automatically(self):
        trial = new_trial(demo_context('followup'))
        with patch('plant_care.comparison.analyze', side_effect=[(RESULT, {}), AnalysisError('무료 한도 초과')]) as api:
            run_side(trial, 'baseline', 'key', True)
            with self.assertRaises(AnalysisError):
                run_side(trial, 'history', 'key', True)
            self.assertEqual(trial['results']['baseline']['result'], RESULT)
            self.assertEqual(trial['attempts']['history']['status'], 'failed')
            with self.assertRaises(ValueError):
                run_side(trial, 'history', 'key', True)
            self.assertEqual(api.call_count, 2)

    def test_comparison_screen_requires_consent_keeps_results_on_navigation_and_never_changes_garden(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'PLANT_CARE_DATA_DIR': folder, 'STORAGE_BACKEND': 'local'}), \
                patch('plant_care.comparison_ui.api_key', return_value='test-key'), \
                patch('plant_care.comparison.analyze', return_value=(RESULT, {})) as api:
            store = PlantStore(folder)
            pid = store.add_plant('보존할 식물', photo=test_photo_bytes())
            original = store.export_plant(pid)
            app = AppTest.from_file(str(APP)).run(timeout=15)
            app.button(key='nav_-2').click().run()
            app.button(key='comparison_prepare').click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(app.button(key='compare_baseline').disabled)
            api.assert_not_called()
            app.checkbox(key='comparison_consent').check().run()
            app.button(key='compare_baseline').click().run(timeout=15)
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(app.button(key='compare_baseline').disabled)
            app.button(key='compare_history').click().run(timeout=15)
            self.assertEqual(api.call_count, 2)
            self.assertEqual(len(app.exception), 0)
            app.button(key='nav_-1').click().run()
            app.button(key='nav_-2').click().run()
            self.assertEqual(len(app.session_state['comparison_trial']['results']), 2)
            api.assert_called()
            self.assertEqual(api.call_count, 2)
            self.assertEqual(store.export_plant(pid), original)
            self.assertTrue(store.photo_path(store.get_plant(pid)['photo_path']).exists())

    def test_preparing_a_new_case_resets_consent_and_does_not_call_api(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'PLANT_CARE_DATA_DIR': folder, 'STORAGE_BACKEND': 'local'}), \
                patch('plant_care.comparison_ui.api_key', return_value='test-key'), \
                patch('plant_care.comparison.analyze') as api:
            app = AppTest.from_file(str(APP)).run(timeout=15)
            app.button(key='nav_-2').click().run()
            app.button(key='comparison_prepare').click().run()
            app.checkbox(key='comparison_consent').check().run()
            old_id = app.session_state['comparison_trial']['id']
            app.selectbox(key='comparison_case').select('dry').run()
            self.assertEqual(app.session_state['comparison_trial']['source']['case'], 'wet')
            app.button(key='comparison_prepare').click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertNotEqual(app.session_state['comparison_trial']['id'], old_id)
            self.assertFalse(app.checkbox(key='comparison_consent').value)
            api.assert_not_called()

    def test_mobile_shortcut_opens_observation_without_logging_or_calling_ai(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'PLANT_CARE_DATA_DIR': folder, 'STORAGE_BACKEND': 'local'}), patch('plant_care.ai_ui.analyze') as api:
            store = PlantStore(folder)
            pid = store.add_plant('테스트 식물')
            app = AppTest.from_file(str(APP)).run(timeout=15)
            app.button(key=f'today_{pid}').click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state[f'plant_tabs_{pid}'], '관리 기록')
            self.assertEqual(app.selectbox(key='care_kind').value, 'observation')
            self.assertEqual(store.list_logs(pid), [])
            api.assert_not_called()


if __name__ == '__main__':
    unittest.main()
