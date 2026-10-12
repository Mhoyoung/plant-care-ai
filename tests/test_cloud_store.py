from copy import deepcopy
from datetime import date
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from zipfile import ZipFile

from streamlit.testing.v1 import AppTest
from plant_care.cloud_store import CloudError, CloudPlantStore, SupabaseClient
from plant_care.gemini import analysis_context
from plant_care.snapshot import dump_store, make_backup, read_backup, TABLES
from plant_care.storage import PlantStore
from plant_care.store_factory import create_store
from test_app import APP_PATH, click_button
from test_gemini import RESULT
from test_storage import test_photo_bytes

URL = 'https://abcdefghijklmnopqrst.supabase.co'
SECRET = 'sb_secret_' + 'test-only-never-a-real-key' * 2


class FakeCloud:
    """원격 CAS·쓰기 완료 이력·비공개 사진 저장소의 계약을 모의한다."""
    def __init__(self):
        self.state = {'version': 1, 'tables': {name: [] for name in TABLES}}
        self.revision = 0
        self.writes = {}
        self.photos = {}
        self.calls = []
        self.lose_response = False
        self.fail_before_commit = False
        self.bucket_public = False

    def request(self, path, method='GET', data=None, binary=False, limit=None, upsert=False):
        self.calls.append((path, method))
        if path == '/storage/v1/bucket/plant-care-photos':
            return {'public': self.bucket_public}
        if path.startswith('/rest/v1/pc_gardens?'):
            return [{'state': deepcopy(self.state), 'revision': self.revision}]
        if path.startswith('/rest/v1/pc_garden_writes?'):
            write_id = path.split('write_id=eq.')[1].split('&')[0]
            return [{'revision': self.writes[write_id]}] if write_id in self.writes else []
        if path == '/rest/v1/rpc/pc_save_garden':
            if self.fail_before_commit:
                raise CloudError('응답 미확인')
            if data['p_expected_revision'] != self.revision:
                raise CloudError('다른 팀원이 먼저 저장했어요. 새로고침한 뒤 다시 기록해 주세요.')
            self.state = deepcopy(data['p_state'])
            self.revision += 1
            self.writes[data['p_write_id']] = self.revision
            if self.lose_response:
                self.lose_response = False
                raise CloudError('응답이 끊김')
            return self.revision
        if path.startswith('/storage/v1/object/authenticated/plant-care-photos/'):
            return self.photos[path.split('/plant-care-photos/')[1]]
        if path.startswith('/storage/v1/object/plant-care-photos/'):
            name = path.split('/plant-care-photos/')[1]
            if name in self.photos and not upsert:
                raise CloudError('existing photo')
            self.photos[name] = data
            return {'Key': name}
        raise AssertionError(path)


class CloudStoreTests(unittest.TestCase):
    def setUp(self):
        self.cloud = FakeCloud()
        self.mock = patch('plant_care.cloud_store.SupabaseClient.request', side_effect=self.cloud.request)
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.stores = []
        self.addCleanup(lambda: [store._temporary.cleanup() for store in self.stores])

    def store(self):
        store = CloudPlantStore(URL, SECRET)
        self.stores.append(store)
        return store

    def test_records_photos_and_full_care_loop_survive_new_server_instance(self):
        first = self.store()
        plant = first.add_plant('몬스테라', photo=test_photo_bytes())
        first.add_log(plant, 'watering', date.today(), notes='관리 기록')
        context = analysis_context(first, plant, '상태 확인', True)
        first.add_analysis(plant, 'test-model', context, RESULT, {}, test_photo_bytes())
        suggestion = first.list_suggestions(plant)[0]['id']
        first.add_log(plant, 'observation', date.today(), notes='흙을 확인하고 관찰', suggestion_id=suggestion, link_type='execution')
        first.add_log(plant, 'observation', date.today(), notes='새 잎 확인', outcome='improved', suggestion_id=suggestion, link_type='outcome')
        first.set_weather_region(plant, 'suncheon')
        later = self.store()
        self.assertEqual(later.get_plant(plant)['name'], '몬스테라')
        self.assertEqual(later.get_weather_region(plant), 'suncheon')
        self.assertEqual(later.list_suggestions(plant)[0]['observations'][0]['outcome'], 'improved')
        self.assertEqual(later.list_analyses(plant)[0]['input'], context)
        self.assertTrue(later.read_photo(later.get_plant(plant)['photo_path']).startswith(b'\xff\xd8'))
        with self.assertRaises(CloudError):
            later.photo_path(later.get_plant(plant)['photo_path'])

    def test_stale_team_member_cannot_overwrite_another_members_record(self):
        first = self.store()
        stale = self.store()
        first.add_plant('먼저 저장한 식물')
        with self.assertRaises(CloudError):
            stale.add_plant('덮어쓰면 안 되는 식물')
        self.assertEqual(stale.list_plants(), [])
        self.assertEqual(self.store().list_plants()[0]['name'], '먼저 저장한 식물')
        with self.assertRaises(CloudError):
            stale.add_plant('다시 저장 시도')
        self.assertEqual(self.cloud.revision, 1)

    def test_lost_response_recovers_only_confirmed_write_without_resubmission(self):
        store = self.store()
        self.cloud.lose_response = True
        store.add_plant('한 번만 저장')
        self.assertEqual(len(self.store().list_plants()), 1)
        self.assertEqual(sum(path.endswith('pc_save_garden') for path, method in self.cloud.calls), 1)

    def test_uncertain_write_keeps_photo_and_does_not_commit_local_record(self):
        store = self.store()
        self.cloud.fail_before_commit = True
        with self.assertRaises(CloudError):
            store.add_plant('확인 안 된 저장', photo=test_photo_bytes())
        self.assertEqual(store.list_plants(), [])
        self.assertEqual(self.cloud.state['tables']['plants'], [])
        self.assertEqual(len(self.cloud.photos), 1)
        self.assertFalse(any(method == 'DELETE' for _, method in self.cloud.calls))

    def test_complete_backup_restores_to_empty_cloud_and_rejects_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            local = PlantStore(folder)
            plant = local.add_plant('기존 식물', photo=test_photo_bytes())
            local.add_log(plant, 'observation', date.today(), notes='기존 사진', photo=test_photo_bytes())
            local.set_weather_region(plant, 'suncheon')
            state, photos = read_backup(make_backup(local))
            cloud = self.store()
            cloud.restore_backup(state, photos)
            self.assertEqual(dump_store(self.store()), dump_store(local))
            restored_state, restored_photos = read_backup(make_backup(self.store()))
            self.assertEqual(restored_state, state)
            self.assertEqual(set(restored_photos), set(photos))
            uploads_before = sum(method == 'POST' and '/object/' in path for path, method in self.cloud.calls)
            with self.assertRaises(ValueError):
                self.store().restore_backup(state, photos)
            self.assertEqual(sum(method == 'POST' and '/object/' in path for path, method in self.cloud.calls), uploads_before)

    def test_private_bucket_and_configuration_are_required_without_local_fallback(self):
        self.cloud.bucket_public = True
        with self.assertRaises(CloudError):
            self.store()
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'STORAGE_BACKEND': 'supabase', 'SUPABASE_URL': '', 'SUPABASE_SECRET_KEY': ''}):
            with self.assertRaises(CloudError):
                create_store(folder)
            self.assertFalse((Path(folder) / 'plants.db').exists())

    def test_cloud_ui_registers_persists_photo_records_and_can_prepare_backup(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'PLANT_CARE_DATA_DIR': folder,
                'STORAGE_BACKEND': 'supabase', 'SUPABASE_URL': URL, 'SUPABASE_SECRET_KEY': SECRET}):
            app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            app.text_input(key='plant_name').set_value('팀 정원 테스트')
            click_button(app, '식물 등록')
            self.assertEqual(len(app.exception), 0)
            app.text_area(key='care_notes').set_value('팀원 관리 기록')
            click_button(app, '기록 저장')
            self.assertEqual(len(app.exception), 0)
            click_button(app, '사진 포함 전체 백업 준비')
            state, photos = read_backup(app.session_state['garden_backup'])
            self.assertEqual(state['tables']['care_logs'][0]['notes'], '팀원 관리 기록')
            relaunched = AppTest.from_file(str(APP_PATH)).run(timeout=15)
            self.assertEqual(len(relaunched.exception), 0)
            self.assertEqual(self.store().list_plants()[0]['name'], '팀 정원 테스트')


class CloudTransportTests(unittest.TestCase):
    def test_secret_is_only_in_apikey_header_and_response_errors_hide_details(self):
        with patch('plant_care.cloud_store.urlopen', return_value=BytesIO(b'[]')) as request:
            SupabaseClient(URL, SECRET).request('/rest/v1/pc_gardens')
        wire = request.call_args.args[0]
        self.assertEqual(wire.get_header('Apikey'), SECRET)
        self.assertNotIn(SECRET, wire.full_url)
        self.assertIsNone(wire.get_header('Authorization'))
        for error in (URLError('private secret ' + SECRET), HTTPError(URL, 401, SECRET, {}, None), TimeoutError(SECRET)):
            with patch('plant_care.cloud_store.urlopen', side_effect=error), self.assertRaises(CloudError) as caught:
                SupabaseClient(URL, SECRET).request('/rest/v1/pc_gardens')
            self.assertNotIn(SECRET, str(caught.exception))
        for url, key in (('http://localhost', SECRET), ('https://evil.example', SECRET), (URL, 'sb_publishable_public')):
            with self.assertRaises(CloudError):
                SupabaseClient(url, key)

    def test_backup_rejects_unexpected_files_and_path_traversal(self):
        for state, extra in (({'version': 1, 'tables': {name: [] for name in TABLES}}, '../evil.txt'),
                             ({'version': 1, 'tables': {name: ([{'photo_path': '../secret'}] if name == 'plants' else []) for name in TABLES}}, None)):
            buffer = BytesIO()
            with ZipFile(buffer, 'w') as archive:
                archive.writestr('garden.json', json.dumps(state))
                if extra:
                    archive.writestr(extra, 'not allowed')
            with self.assertRaises(ValueError):
                read_backup(buffer.getvalue())


if __name__ == '__main__':
    unittest.main()
