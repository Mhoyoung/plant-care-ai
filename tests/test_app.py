import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from plant_care.storage import PlantStore
from plant_care.gemini import AnalysisError
from test_gemini import RESULT
from test_storage import test_photo_bytes


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def click_button(app, label):
    next(button for button in app.button if button.label == label).click().run()


class AppTests(unittest.TestCase):
    def test_garden_navigation_preserves_photo_records_and_never_calls_ai(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"PLANT_CARE_DATA_DIR": folder}), \
                patch("plant_care.ai_ui.analyze") as api:
            store = PlantStore(folder)
            plant = store.add_plant("사진 있는 식물", photo=test_photo_bytes())
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            self.assertEqual(app.selectbox(key="selected_plant").value, -1)
            self.assertEqual(len(app.exception), 0)
            app.button(key=f"open_plant_{plant}").click().run()
            self.assertEqual(app.selectbox(key="selected_plant").value, plant)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual([tab.label for tab in app.tabs], ["한눈에 보기", "관리 기록", "AI 분석"])
            app.button(key="back_to_garden").click().run()
            self.assertEqual(app.selectbox(key="selected_plant").value, -1)
            app.button(key="garden_add").click().run()
            self.assertEqual(app.selectbox(key="selected_plant").value, 0)
            self.assertTrue(store.photo_path(store.get_plant(plant)["photo_path"]).is_file())
            api.assert_not_called()

    def test_ai_requires_consent_saves_once_and_survives_relaunch(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"PLANT_CARE_DATA_DIR": folder}), \
                patch("plant_care.ai_ui.api_key", return_value="local-test-key"), \
                patch("plant_care.ai_ui.analyze", return_value=(RESULT, {"total_tokens": 100})) as api:
            store = PlantStore(folder)
            plant = store.add_plant("몬스테라")
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            app.selectbox(key="selected_plant").select(plant).run()
            app.text_area(key="ai_state").set_value("잎이 처져요")
            click_button(app, "Gemini로 분석")
            api.assert_not_called()
            self.assertEqual(len(app.error), 1)
            app.checkbox(key="ai_consent").check()
            click_button(app, "Gemini로 분석")
            self.assertEqual(len(app.exception), 0)
            api.assert_called_once()
            self.assertEqual(len(store.list_analyses(plant)), 1)
            app.run()
            api.assert_called_once()
            relaunched = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            relaunched.selectbox(key="selected_plant").select(plant).run()
            self.assertEqual(len(relaunched.exception), 0)
            self.assertTrue(any("최근 관찰" in item.label for item in relaunched.expander))
            api.assert_called_once()

    def test_missing_api_key_disables_analysis(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"PLANT_CARE_DATA_DIR": folder}), \
                patch("plant_care.ai_ui.api_key", return_value=""), patch("plant_care.ai_ui.analyze") as api:
            PlantStore(folder).add_plant("몬스테라")
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            app.selectbox(key="selected_plant").select(1).run()
            self.assertTrue(next(button for button in app.button if button.label == "Gemini로 분석").disabled)
            self.assertEqual(len(app.exception), 0)
            api.assert_not_called()

    def test_failed_api_does_not_store_analysis(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"PLANT_CARE_DATA_DIR": folder}), \
                patch("plant_care.ai_ui.api_key", return_value="test-key"), \
                patch("plant_care.ai_ui.analyze", side_effect=AnalysisError("무료 한도 초과")) as api:
            store = PlantStore(folder)
            store.add_plant("몬스테라")
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            app.selectbox(key="selected_plant").select(1).run()
            app.text_area(key="ai_state").set_value("잎이 처져요")
            app.checkbox(key="ai_consent").check()
            click_button(app, "Gemini로 분석")
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.error), 1)
            self.assertEqual(store.list_analyses(1), [])
            api.assert_called_once()

    def test_registration_recording_and_relaunch(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"PLANT_CARE_DATA_DIR": folder}):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            self.assertEqual(len(app.exception), 0)
            app.text_input(key="plant_name").set_value("테스트 몬스테라")
            app.text_input(key="plant_species").set_value("몬스테라")
            click_button(app, "식물 등록")
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(PlantStore(folder).list_plants()), 1)
            app.text_area(key="care_notes").set_value("첫 물주기 기록")
            click_button(app, "기록 저장")
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(PlantStore(folder).list_logs(1)[0]["notes"], "첫 물주기 기록")
            app.selectbox(key="care_kind").select("observation")
            app.selectbox(key="care_outcome").select("improved")
            app.text_area(key="care_notes").set_value("잎 상태가 나아졌다")
            click_button(app, "기록 저장")
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(PlantStore(folder).list_logs(1)[0]["outcome"], "improved")
            relaunched = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            relaunched.selectbox(key="selected_plant").select(1).run()
            self.assertEqual(len(relaunched.exception), 0)
            self.assertEqual(len(PlantStore(folder).list_logs(1)), 2)

    def test_blank_registration_shows_error_without_creating_record(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"PLANT_CARE_DATA_DIR": folder}):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            click_button(app, "식물 등록")
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.error), 1)
            self.assertEqual(PlantStore(folder).list_plants(), [])


if __name__ == "__main__":
    unittest.main()
