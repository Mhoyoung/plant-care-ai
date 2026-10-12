from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from plant_care.storage import PlantStore
from test_gemini import RESULT


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        # UTC에서는 12일, 한국에서는 13일 00:30인 동일 시점.
        instant = cls(2026, 10, 12, 15, 30, tzinfo=timezone.utc)
        return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)


class UTCServerDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 12)


class KoreanDateTests(unittest.TestCase):
    def test_korean_today_is_accepted_and_tomorrow_rejected_on_utc_server(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch("plant_care.time_utils.datetime", FrozenDateTime), \
                patch("plant_care.storage.date", UTCServerDate), \
                patch("plant_care.storage.datetime", FrozenDateTime):
            store = PlantStore(folder)
            plant = store.add_plant("날짜 검증용 식물")
            store.add_analysis(plant, "test-model", {}, RESULT, {})
            suggestion = store.list_suggestions(plant)[0]
            today = date(2026, 10, 13)
            store.add_log(plant, "observation", today, notes="흙 상태를 확인했어요",
                          suggestion_id=suggestion["id"], link_type="execution")
            with self.assertRaisesRegex(ValueError, "오늘까지"):
                store.add_log(plant, "watering", today + timedelta(days=1))
            self.assertEqual(store.list_logs(plant)[0]["occurred_on"], today.isoformat())
            self.assertEqual(len(store.list_logs(plant)), 1)

    def test_same_day_suggestion_form_can_save_after_korean_midnight(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {"PLANT_CARE_DATA_DIR": folder, "STORAGE_BACKEND": "local"}), \
                patch("plant_care.time_utils.datetime", FrozenDateTime), \
                patch("plant_care.storage.date", UTCServerDate), \
                patch("plant_care.care_ui.date", UTCServerDate), \
                patch("plant_care.storage.datetime", FrozenDateTime), \
                patch("plant_care.ai_ui.api_key", return_value=""), \
                patch("plant_care.ai_ui.analyze") as api:
            store = PlantStore(folder)
            plant = store.add_plant("날짜 검증용 식물")
            from plant_care.gemini import analysis_context
            context = analysis_context(store, plant, "현재 상태 확인", False)
            store.add_analysis(plant, "test-model", context, RESULT, {})
            sid = store.list_suggestions(plant)[0]["id"]
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            app.selectbox(key="selected_plant").select(plant).run()
            app.button(key=f"analysis_suggestion_{sid}").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.date_input(key="care_date").value, date(2026, 10, 13))
            app.selectbox(key="care_kind").select("observation")
            app.text_area(key="care_notes").set_value("실제로 확인한 상태")
            next(b for b in app.button if b.label == "실행 기록 저장").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(store.list_suggestions(plant)[0]["execution"]["occurred_on"], "2026-10-13")
            api.assert_not_called()
