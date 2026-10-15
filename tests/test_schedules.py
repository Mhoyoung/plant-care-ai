from copy import deepcopy
from datetime import date, timedelta
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from streamlit.testing.v1 import AppTest
from plant_care.storage import PlantStore
from plant_care.snapshot import dump_store, restore_connection, make_backup, read_backup, LEGACY_TABLES
from plant_care.calendar_export import calendar_ics, google_calendar_url
from plant_care.gemini import analysis_context
from plant_care.time_utils import today_in_seoul
from plant_care.cloud_store import CloudError
from test_app import APP_PATH, click_button
import test_cloud_store as cloud_tests


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = PlantStore(self.folder.name)
        self.plant = self.store.add_plant('테스트 식물')

    def add(self, **kwargs):
        return self.store.add_schedule(self.plant, **dict(title='흙 확인', kind='observation',
            due_on=today_in_seoul(), due_time='09:00', **kwargs))

    def test_plan_is_not_observation_completion_is_atomic_and_only_once(self):
        before = analysis_context(self.store, self.plant, '같은 질문', False)
        sid = self.add()
        self.assertEqual(analysis_context(self.store, self.plant, '같은 질문', False), before)
        self.assertEqual(self.store.list_logs(self.plant), [])
        self.assertIsNone(self.store.last_watered(self.plant))
        with self.assertRaises(ValueError):
            self.store.complete_schedule(sid, 'watering', today_in_seoul() + timedelta(days=1), '미래')
        with self.assertRaises(ValueError):
            self.store.complete_schedule(sid, 'watering', today_in_seoul(), '')
        self.assertEqual(self.store.list_logs(self.plant), [])
        log = self.store.complete_schedule(sid, 'observation', today_in_seoul(), '흙이 젖어 물을 주지 않음')
        self.assertEqual(self.store.list_schedules()[0]['completed_log_id'], log)
        self.assertEqual(len(self.store.list_logs(self.plant)), 1)
        self.assertIsNone(self.store.last_watered(self.plant))
        with self.assertRaises(ValueError):
            self.store.complete_schedule(sid, 'watering', today_in_seoul(), '중복')
        self.assertEqual(len(self.store.list_logs(self.plant)), 1)

    def test_reschedule_cancel_and_legacy_backup_preserve_existing_data(self):
        sid = self.add()
        uid = self.store.list_schedules()[0]['calendar_uid']
        self.store.update_schedule(sid, '다음에 확인', 'observation', date(2026, 10, 20), '10:30', '메모')
        changed = self.store.list_schedules()[0]
        self.assertEqual((changed['calendar_uid'], changed['revision']), (uid, 1))
        state, _ = read_backup(make_backup(self.store))
        with tempfile.TemporaryDirectory() as target:
            restored = PlantStore(target)
            with restored._connection() as connection:
                restore_connection(connection, state)
            self.assertEqual(restored.list_schedules(), self.store.list_schedules())
        legacy = deepcopy(state)
        legacy['tables'] = {key: legacy['tables'][key] for key in LEGACY_TABLES}
        with tempfile.TemporaryDirectory() as target:
            restored = PlantStore(target)
            with restored._connection() as connection:
                restore_connection(connection, legacy)
            self.assertEqual(restored.get_plant(self.plant)['name'], '테스트 식물')
            self.assertEqual(restored.list_schedules(), [])
        self.store.cancel_schedule(sid)
        self.assertEqual(self.store.list_schedules()[0]['status'], 'cancelled')
        self.assertEqual(self.store.list_logs(self.plant), [])
        with self.assertRaises(ValueError):
            self.store.complete_schedule(sid, 'observation', today_in_seoul(), '취소된 일정')

    def test_invalid_schedule_and_missing_plant_leave_no_rows(self):
        for values in [dict(title=''), dict(due_on='bad-date'), dict(due_time='13:00+09:00'), dict(kind='unknown')]:
            options = dict(title='할 일', kind='observation', due_on=date(2026, 10, 20), due_time='09:00')
            options.update(values)
            with self.assertRaises(ValueError):
                self.store.add_schedule(self.plant, **options)
        with self.assertRaises(ValueError):
            self.store.add_schedule(999, '할 일', 'observation', date(2026, 10, 20))
        self.assertEqual(self.store.list_schedules(), [])

    def test_calendar_timezone_alarm_unicode_folding_and_injection(self):
        sid = self.store.add_schedule(self.plant, '한글' * 40 + '\nBEGIN:VEVENT', 'observation',
                                      date(2026, 10, 20), '09:30', '확인;물,빛\\메모\r\nEND:VEVENT')
        item = self.store.list_schedules()[0]
        raw = calendar_ics(item)
        self.assertTrue(all(len(line) <= 75 for line in raw.split(b'\r\n')))
        unfolded = raw.decode('utf-8').replace('\r\n ', '')
        self.assertIn('DTSTART:20261020T003000Z', unfolded)
        self.assertIn('TRIGGER:-PT10M', unfolded)
        self.assertEqual(unfolded.count('\r\nBEGIN:VEVENT\r\n'), 1)
        self.assertEqual(unfolded.count('\r\nEND:VEVENT\r\n'), 1)
        self.assertIn('\\nEND:VEVENT', unfolded)
        query = parse_qs(urlparse(google_calendar_url(item)).query)
        self.assertEqual(query['dates'], ['20261020T003000Z/20261020T004500Z'])
        self.assertEqual(query['ctz'], ['Asia/Seoul'])
        self.store.cancel_schedule(sid)
        with self.assertRaises(ValueError):
            calendar_ics(self.store.list_schedules()[0])

    def test_ui_add_validation_complete_and_cancel_without_ai_requests(self):
        with patch.dict(os.environ, {'PLANT_CARE_DATA_DIR': self.folder.name, 'STORAGE_BACKEND': 'local'}), \
                patch('plant_care.ai_ui.analyze') as ai, patch('plant_care.comparison.analyze') as comparison:
            app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
            app.selectbox(key='selected_plant').select(self.plant).run()
            self.assertEqual(len(app.exception), 0)
            click_button(app, '일정 추가')
            self.assertEqual(self.store.list_schedules(), [])
            app.text_input(key=f'schedule_new_{self.plant}_0_title').set_value('흙 확인')
            click_button(app, '일정 추가')
            self.assertEqual(len(app.exception), 0)
            sid = self.store.list_schedules()[0]['id']
            self.assertEqual(self.store.list_logs(self.plant), [])
            self.assertEqual(app.text_input(key=f'schedule_new_{self.plant}_1_title').value, '')
            click_button(app, '완료하고 관리 기록 저장')
            self.assertEqual(self.store.list_logs(self.plant), [])
            app.text_area(key=f'schedule_{sid}_actual_notes').set_value('흙을 만져 상태를 확인함')
            click_button(app, '완료하고 관리 기록 저장')
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(self.store.list_schedules()[0]['status'], 'completed')
            self.assertEqual(len(self.store.list_logs(self.plant)), 1)
            app.text_input(key=f'schedule_new_{self.plant}_1_title').set_value('취소할 일정')
            click_button(app, '일정 추가')
            click_button(app, '일정 취소')
            self.assertEqual(self.store.list_schedules()[1]['status'], 'pending')
            sid2 = self.store.list_schedules()[1]['id']
            app.checkbox(key=f'schedule_{sid2}_cancel_confirm').check()
            click_button(app, '일정 취소')
            self.assertEqual(self.store.list_schedules()[1]['status'], 'cancelled')
            ai.assert_not_called()
            comparison.assert_not_called()


class ScheduleCloudTests(unittest.TestCase):
    setUp = cloud_tests.CloudStoreTests.setUp
    store = cloud_tests.CloudStoreTests.store

    def test_schedule_completion_is_single_cloud_write_and_stale_writer_rolls_back(self):
        first = self.store()
        plant = first.add_plant('팀 식물')
        sid = first.add_schedule(plant, '확인', 'observation', today_in_seoul())
        stale = self.store()
        revision = self.cloud.revision
        first.complete_schedule(sid, 'observation', today_in_seoul(), '실제 확인')
        self.assertEqual(self.cloud.revision, revision + 1)
        with self.assertRaises(CloudError):
            stale.complete_schedule(sid, 'watering', today_in_seoul(), '동시 완료')
        self.assertEqual(stale.list_logs(plant), [])
        fresh = self.store()
        self.assertEqual(len(fresh.list_logs(plant)), 1)
        self.assertEqual(fresh.list_schedules()[0]['status'], 'completed')
        with self.assertRaises(ValueError):
            fresh.complete_schedule(sid, 'watering', today_in_seoul(), '중복 완료')

    def test_old_cloud_snapshot_loads_and_schedule_survives_restart_and_lost_response(self):
        self.cloud.state['tables'].pop('care_schedules')
        first = self.store()
        plant = first.add_plant('기존 정원')
        sid = first.add_schedule(plant, '확인', 'observation', today_in_seoul())
        self.cloud.lose_response = True
        first.complete_schedule(sid, 'observation', today_in_seoul(), '확인했음')
        fresh = self.store()
        self.assertEqual(fresh.list_schedules()[0]['status'], 'completed')
        self.assertEqual(len(fresh.list_logs(plant)), 1)
