import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from plant_care.storage import PlantStore


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class AppTests(unittest.TestCase):
    def test_registration_recording_and_relaunch(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"PLANT_CARE_DATA_DIR": folder}):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            self.assertEqual(len(app.exception), 0)
            app.text_input(key="plant_name").set_value("테스트 몬스테라")
            app.text_input(key="plant_species").set_value("몬스테라")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(PlantStore(folder).list_plants()), 1)
            app.text_area(key="care_notes").set_value("첫 물주기 기록")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(PlantStore(folder).list_logs(1)[0]["notes"], "첫 물주기 기록")
            app.selectbox(key="care_kind").select("observation")
            app.selectbox(key="care_outcome").select("improved")
            app.text_area(key="care_notes").set_value("잎 상태가 나아졌다")
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(PlantStore(folder).list_logs(1)[0]["outcome"], "improved")
            relaunched = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            relaunched.selectbox(key="selected_plant").select(1).run()
            self.assertEqual(len(relaunched.exception), 0)
            self.assertEqual(len(PlantStore(folder).list_logs(1)), 2)

    def test_blank_registration_shows_error_without_creating_record(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"PLANT_CARE_DATA_DIR": folder}):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.error), 1)
            self.assertEqual(PlantStore(folder).list_plants(), [])


if __name__ == "__main__":
    unittest.main()
