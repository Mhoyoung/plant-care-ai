from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from plant_care.ai_context import build_context
from plant_care.storage import PlantStore


def test_photo_bytes():
    image = Image.new("RGB", (32, 24), "green")
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = PlantStore(self.root)

    def test_records_persist_after_reopening_and_stay_with_their_plant(self):
        first = self.store.add_plant("몬스테라 A")
        second = self.store.add_plant("스투키")
        self.store.add_log(first, "watering", date.today(), notes="물주기 완료")
        reopened = PlantStore(self.root)
        self.assertEqual(reopened.get_plant(first)["name"], "몬스테라 A")
        self.assertEqual(len(reopened.list_logs(first)), 1)
        self.assertEqual(reopened.list_logs(second), [])

    def test_timeline_uses_care_date_and_last_watering_ignores_other_kinds(self):
        plant = self.store.add_plant("몬스테라")
        today = date.today()
        self.store.add_log(plant, "watering", today - timedelta(days=2))
        self.store.add_log(plant, "watering", today - timedelta(days=5))
        self.store.add_log(plant, "observation", today, outcome="improved")
        self.assertEqual(self.store.last_watered(plant), (today - timedelta(days=2)).isoformat())
        self.assertEqual(self.store.list_logs(plant)[0]["kind"], "observation")
        self.assertEqual(self.store.list_logs(plant)[-1]["occurred_on"], (today - timedelta(days=5)).isoformat())

    def test_photo_is_reencoded_and_saved_with_record(self):
        plant = self.store.add_plant("식물", photo=test_photo_bytes())
        photo = self.store.photo_path(self.store.get_plant(plant)["photo_path"])
        self.assertTrue(photo.exists())
        with Image.open(photo) as saved:
            self.assertEqual(saved.format, "JPEG")
            self.assertEqual(saved.size, (32, 24))
        self.store.add_log(plant, "observation", date.today(), photo=test_photo_bytes())
        self.assertTrue(self.store.photo_path(self.store.list_logs(plant)[0]["photo_path"]).exists())

    def test_mpo_uses_primary_frame_for_plant_and_observation(self):
        source = BytesIO()
        Image.new("RGB", (32, 24), "red").save(
            source, "MPO", save_all=True, append_images=[Image.new("RGB", (32, 24), "blue")]
        )
        plant = self.store.add_plant("식물", photo=source.getvalue())
        self.store.add_log(plant, "observation", date.today(), photo=source.getvalue())
        for relative in (self.store.get_plant(plant)["photo_path"], self.store.list_logs(plant)[0]["photo_path"]):
            with self.subTest(relative=relative), Image.open(self.store.photo_path(relative)) as saved:
                self.assertEqual(saved.format, "JPEG")
                self.assertEqual(saved.size, (32, 24))
                red, green, blue = saved.getpixel((16, 12))
                self.assertGreater(red, 200)
                self.assertLess(green, 30)
                self.assertLess(blue, 30)

    def test_invalid_image_does_not_create_a_plant_or_leave_a_photo(self):
        with self.assertRaises(ValueError):
            self.store.add_plant("식물", photo=b"not an image")
        self.assertEqual(self.store.list_plants(), [])
        self.assertFalse((self.root / "photos").exists())

    def test_blank_name_is_rejected_before_saving_photo(self):
        with self.assertRaises(ValueError):
            self.store.add_plant("   ", photo=test_photo_bytes())
        self.assertEqual(self.store.list_plants(), [])
        self.assertFalse((self.root / "photos").exists())

    def test_nonexistent_plant_and_invalid_log_fields_are_rejected(self):
        plant = self.store.add_plant("식물")
        invalid = [
            {"plant_id": 999, "kind": "watering", "occurred_on": date.today()},
            {"plant_id": plant, "kind": "unknown", "occurred_on": date.today()},
            {"plant_id": plant, "kind": "watering", "occurred_on": "bad-date"},
            {"plant_id": plant, "kind": "watering", "occurred_on": date.today() + timedelta(days=1)},
            {"plant_id": plant, "kind": "watering", "occurred_on": date.today(), "outcome": "unknown"},
        ]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.store.add_log(**values)
        self.assertEqual(self.store.list_logs(plant), [])

    def test_sql_like_text_is_stored_as_text(self):
        name = "식물'); DROP TABLE plants; --"
        plant = self.store.add_plant(name)
        self.assertEqual(self.store.get_plant(plant)["name"], name)
        self.assertEqual(len(self.store.list_plants()), 1)

    def test_photo_lookup_cannot_escape_photo_directory(self):
        for value in ("../outside.jpg", "plants.db", str(self.root.parent / "outside.jpg")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.photo_path(value)

    def test_delete_record_removes_photo_and_its_unused_auto_analysis(self):
        plant = self.store.add_plant('식물')
        log_id = self.store.add_log(plant, 'observation', date.today(), photo=test_photo_bytes())
        log_photo = self.store.list_logs(plant)[0]['photo_path']
        self.store.add_analysis(plant, 'test', {}, {'actions': ['상태 확인']}, {},
                                photo=test_photo_bytes(), source_log_id=log_id)
        ai_photo = self.store.list_analyses(plant)[0]['photo_path']
        self.store.delete_log(plant, log_id)
        self.assertEqual(self.store.list_logs(plant), [])
        self.assertEqual(self.store.list_analyses(plant), [])
        self.assertEqual(self.store.list_suggestions(plant), [])
        self.assertFalse(self.store.photo_path(log_photo).exists())
        self.assertFalse(self.store.photo_path(ai_photo).exists())

    def test_delete_record_rejects_wrong_plant_and_linked_ai_suggestion(self):
        plant = self.store.add_plant('식물')
        other = self.store.add_plant('다른 식물')
        log_id = self.store.add_log(plant, 'observation', date.today(), photo=test_photo_bytes())
        photo = self.store.list_logs(plant)[0]['photo_path']
        with self.assertRaises(ValueError):
            self.store.delete_log(other, log_id)
        self.store.add_analysis(plant, 'test', {}, {'actions': ['상태 확인']}, {}, source_log_id=log_id)
        suggestion_id = self.store.list_suggestions(plant)[0]['id']
        self.store.add_schedule(plant, '상태 확인', 'observation', date.today(), source_suggestion_id=suggestion_id)
        with self.assertRaises(ValueError):
            self.store.delete_log(plant, log_id)
        self.assertTrue(self.store.photo_path(photo).exists())
        self.assertEqual(len(self.store.list_logs(plant)), 1)

    def test_ai_context_contains_observed_results_and_only_requested_recent_logs(self):
        plant = self.store.add_plant("식물")
        today = date.today()
        self.store.add_log(plant, "watering", today - timedelta(days=3))
        self.store.add_log(plant, "observation", today - timedelta(days=1), outcome="unchanged")
        self.store.add_log(plant, "observation", today, notes="잎이 다시 섰다", outcome="improved")
        context = build_context(self.store, plant, recent_limit=2)
        self.assertEqual(len(context["recent_care_logs"]), 2)
        self.assertEqual(context["recent_care_logs"][-1]["outcome"], "improved")
        self.assertEqual(context["last_watered"], (today - timedelta(days=3)).isoformat())

    def test_export_contains_records_and_no_photo_bytes(self):
        plant = self.store.add_plant("식물", photo=test_photo_bytes())
        self.store.add_log(plant, "observation", date.today(), notes="관찰")
        exported = self.store.export_plant(plant)
        self.assertEqual(exported["schema_version"], 2)
        self.assertEqual(exported["care_logs"][0]["notes"], "관찰")
        self.assertIsInstance(exported["plant"]["photo_path"], str)


if __name__ == "__main__":
    unittest.main()
