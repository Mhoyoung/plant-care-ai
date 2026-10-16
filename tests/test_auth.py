"""Auth/session/privacy tests with a transport fake; SQL RLS needs separate deployment checks."""
from copy import deepcopy
from datetime import date, timedelta
from io import BytesIO
import json
import os
from pathlib import Path
from time import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from types import SimpleNamespace
from base64 import b64decode

from streamlit.testing.v1 import AppTest
from plant_care.auth import AuthClient, AuthError, AuthSession, UserClient, SESSION_KEY, clear_account_state
from plant_care.cloud_store import CloudError
from plant_care.personal_store import PersonalCloudPlantStore
from plant_care.snapshot import TABLES, make_backup, read_backup
from plant_care.store_factory import create_store, CACHE_KEY
from plant_care.private_media import photo, download
from test_app import APP_PATH, click_button
from test_storage import test_photo_bytes
from test_gemini import RESULT

URL = 'https://abcdefghijklmnopqrst.supabase.co'
KEY = 'sb_publishable_test-only-not-a-real-key'
A = '11111111-1111-4111-8111-111111111111'
B = '22222222-2222-4222-8222-222222222222'


def session(owner=A, token=None, expiry=None):
    return AuthSession(owner, 'a@example.invalid' if owner == A else 'b@example.invalid',
                       token or owner, 'refresh-' + owner, expiry or time() + 3600)


class PersonalFake:
    def __init__(self):
        self.gardens = {}
        self.writes = {}
        self.photos = {}
        self.calls = []
        self.lose_response = False

    def request(self, client, path, method='GET', data=None, **kwargs):
        owner = client._access_token
        self.calls.append((owner, path, method))
        if owner not in (A, B):
            raise CloudError('인증 필요')
        if path == '/rest/v1/rpc/pc_ensure_user_garden':
            self.gardens.setdefault(owner, {'state': {'version': 1, 'tables': {t: [] for t in TABLES}}, 'revision': 0})
            return None
        if path.startswith('/rest/v1/pc_user_gardens?'):
            self.assert_owner(path, owner)
            return [deepcopy(self.gardens[owner])]
        if path.startswith('/rest/v1/pc_user_garden_writes?'):
            self.assert_owner(path, owner)
            write = path.split('write_id=eq.')[1].split('&')[0]
            value = self.writes.get((owner, write))
            return [] if value is None else [{'revision': value}]
        if path == '/rest/v1/rpc/pc_save_user_garden':
            if set(data) != {'p_expected_revision', 'p_state', 'p_write_id'}:
                raise AssertionError('RPC must derive identity from JWT')
            garden = self.gardens[owner]
            if garden['revision'] != data['p_expected_revision']:
                raise CloudError('저장 충돌')
            garden.update(state=deepcopy(data['p_state']), revision=garden['revision'] + 1)
            self.writes[owner, data['p_write_id']] = garden['revision']
            if self.lose_response:
                self.lose_response = False
                raise CloudError('커밋 후 응답 유실')
            return garden['revision']
        if '/plant-care-photos/' in path:
            name = path.split('/plant-care-photos/')[1]
            if not name.startswith(owner + '/photos/'):
                raise CloudError('사진 접근 거부')
            if method == 'POST':
                self.photos[name] = data
                return {'Key': name}
            return self.photos[name]
        raise AssertionError(path)

    @staticmethod
    def assert_owner(path, owner):
        if 'owner_id=eq.' + owner not in path:
            raise CloudError('계정 접근 거부')


class PersonalStoreTests(unittest.TestCase):
    def setUp(self):
        self.fake = PersonalFake()
        fake = self.fake
        def transport(client, *args, **kwargs):
            return fake.request(client, *args, **kwargs)
        mock = patch.object(UserClient, 'request', transport)
        mock.start()
        self.addCleanup(mock.stop)
        self.stores = []
        self.addCleanup(lambda: [s.close() for s in self.stores])

    def store(self, owner=A):
        store = PersonalCloudPlantStore(URL, KEY, session(owner))
        self.stores.append(store)
        return store

    def test_same_local_ids_have_separate_plants_logs_photos_schedules_and_backups(self):
        a, b = self.store(), self.store(B)
        pa = a.add_plant('A 전용', photo=test_photo_bytes())
        pb = b.add_plant('B 전용', photo=test_photo_bytes())
        self.assertEqual(pa, pb)
        a.add_log(pa, 'observation', date.today(), notes='A 기록')
        a.add_schedule(pa, 'A 일정', 'observation', date.today() + timedelta(days=1))
        a.add_analysis(pa, 'fake-no-network', {}, RESULT, {})
        # Full backup exercises all tables and only the owner's photo prefix.
        state_a, photos_a = read_backup(make_backup(a))
        state_b, photos_b = read_backup(make_backup(b))
        self.assertEqual(state_a['tables']['plants'][0]['name'], 'A 전용')
        self.assertEqual(state_b['tables']['plants'][0]['name'], 'B 전용')
        self.assertEqual(len(state_a['tables']['care_logs']), 1)
        self.assertEqual(len(state_a['tables']['care_schedules']), 1)
        self.assertEqual(state_b['tables']['care_logs'], [])
        self.assertEqual(state_b['tables']['care_schedules'], [])
        self.assertEqual(len(state_a['tables']['ai_analyses']), 1)
        self.assertEqual(state_b['tables']['ai_analyses'], [])
        self.assertTrue(state_a['tables']['ai_suggestions'])
        self.assertEqual(state_b['tables']['ai_suggestions'], [])
        self.assertEqual(len(photos_a), 1)
        self.assertEqual(len(photos_b), 1)
        self.assertEqual(self.store().get_plant(pa)['name'], 'A 전용')
        with self.assertRaises(ValueError):
            a.read_photo(B + '/photos/' + 'a' * 32 + '.jpg')
        self.assertTrue(all('/pc_gardens?' not in p and 'pc_save_garden' not in p for _, p, _ in self.fake.calls))
        self.assertTrue(all(n.startswith((A + '/', B + '/')) for n in self.fake.photos))

    def test_independent_revisions_same_owner_conflict_and_lost_response(self):
        a, stale_a, b = self.store(), self.store(), self.store(B)
        a.add_plant('A')
        b.add_plant('B')
        with self.assertRaises(CloudError):
            stale_a.add_plant('덮어쓰지 않기')
        self.fake.lose_response = True
        a.add_plant('유실 응답 확인')
        self.assertFalse(a._uncertain)
        self.assertEqual(len(self.store().list_plants()), 2)
        self.assertEqual(len(self.store(B).list_plants()), 1)

    def test_factory_rejects_unauthenticated_even_with_server_secret_and_changes_scope(self):
        settings = {'STORAGE_BACKEND': 'supabase', 'SUPABASE_URL': URL,
                    'SUPABASE_PUBLISHABLE_KEY': KEY, 'SUPABASE_SECRET_KEY': 'sb_secret_never-used'}
        state = {}
        with patch.dict(os.environ, {'GARDEN_MODE': 'personal'}):
            with self.assertRaises(CloudError):
                create_store(None, settings, state)
            a = create_store(None, settings, state, session())
            self.stores.append(a)
            temporary = Path(a._temporary.name)
            b = create_store(None, settings, state, session(B))
            self.stores.append(b)
            self.assertFalse(temporary.exists())
            self.assertEqual(b.owner_id, B)
            clear_account_state(state)
            self.assertFalse(Path(b._temporary.name).exists())


class AuthTests(unittest.TestCase):
    def test_personal_photos_are_data_uris_instead_of_shared_media_files(self):
        data = test_photo_bytes()
        with patch('plant_care.private_media.st.image') as image:
            photo(data, personal=True)
            source = image.call_args.args[0]
            self.assertTrue(source.startswith('data:image/jpeg;base64,'))
            self.assertEqual(b64decode(source.split(',', 1)[1]), data)
            photo(data, personal=False)
            self.assertEqual(image.call_args.args[0], data)

    def test_personal_download_never_registers_public_download_url(self):
        with patch('plant_care.private_media.st.download_button') as public_download, \
             patch('plant_care.private_media.st.iframe') as inline:
            download(SimpleNamespace(personal=True), '내 백업', b'private-test-bytes',
                     file_name='garden.zip', mime='application/zip')
            public_download.assert_not_called()
            html = inline.call_args.args[0]
            self.assertIn('download="garden.zip"', html)
            encoded = html.split('base64,', 1)[1].split('"', 1)[0]
            self.assertEqual(b64decode(encoded), b'private-test-bytes')
            self.assertNotIn('/media/', html)

    def test_user_transport_uses_publishable_plus_bearer_and_rejects_service_keys(self):
        client = UserClient(URL, KEY, 'user-token')
        with patch('plant_care.cloud_store.urlopen') as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = b'[]'
            self.assertEqual(client.request('/rest/v1/pc_user_gardens'), [])
            request = open_url.call_args.args[0]
            self.assertEqual(request.get_header('Apikey'), KEY)
            self.assertEqual(request.get_header('Authorization'), 'Bearer user-token')
        for bad in ('sb_secret_test-key-must-not-work', '', 'not-a-key'):
            with self.assertRaises(CloudError):
                UserClient(URL, bad)

    def test_login_requires_server_verified_confirmed_identity_and_hides_tokens(self):
        payload = {'access_token': 'secret-access', 'refresh_token': 'secret-refresh', 'expires_in': 3600,
                   'user': {'id': B}}
        with patch.object(AuthClient, '_auth_request', side_effect=[payload, {'id': A, 'email': 'a@example.invalid', 'email_confirmed_at': 'yes'}]) as api:
            signed = AuthClient(URL, KEY).sign_in('a@example.invalid', 'not-a-real-password')
            self.assertEqual(signed.owner_id, A)
            self.assertNotIn('secret-access', repr(signed))
            self.assertNotIn('secret-refresh', repr(signed))
            self.assertEqual(api.call_args_list[1].args, ('user',))
        with patch.object(AuthClient, '_auth_request', side_effect=[payload, {'id': A}]):
            with self.assertRaises(AuthError):
                AuthClient(URL, KEY).sign_in('a@example.invalid', 'not-a-real-password')

    def test_expiry_refresh_validates_user_and_cannot_switch_owner(self):
        payload = {'access_token': 'fresh-access', 'refresh_token': 'fresh-refresh', 'expires_in': 3600}
        with patch.object(AuthClient, '_auth_request', side_effect=[payload, {'id': A, 'email_confirmed_at': 'yes'}]) as api:
            updated = AuthClient(URL, KEY).verify(session(expiry=time() + 5))
            self.assertEqual(updated.access_token, 'fresh-access')
            self.assertIn('grant_type=refresh_token', api.call_args_list[0].args[0])
        with patch.object(AuthClient, '_auth_request', return_value={'id': B, 'email_confirmed_at': 'yes'}):
            with self.assertRaises(AuthError):
                AuthClient(URL, KEY).verify(session())

    def test_auth_errors_never_show_response_body_or_credentials(self):
        for status in (400, 401, 403, 422, 429, 500):
            error = HTTPError(URL, status, 'secret-server-error', {}, BytesIO(b'{"secret":"do-not-echo"}'))
            with patch('plant_care.cloud_store.urlopen', side_effect=error):
                with self.assertRaises(CloudError) as raised:
                    AuthClient(URL, KEY).sign_in('private@example.invalid', 'private-password')
            self.assertNotIn('do-not-echo', str(raised.exception))
            self.assertNotIn('private', str(raised.exception))

    def test_account_clear_destroys_all_forms_ai_photos_backup_and_old_store(self):
        class Cached:
            closed = False
            def close(self):
                self.closed = True
        cached = Cached()
        state = {CACHE_KEY: {'store': cached}, 'garden_backup': b'private', 'comparison_question': 'private',
                 'plant_photo_0': b'private', 'selected_plant': 1, '_login_password': 'private'}
        clear_account_state(state, session(B))
        self.assertTrue(cached.closed)
        self.assertEqual(set(state), {SESSION_KEY})
        self.assertEqual(state[SESSION_KEY].owner_id, B)


class AuthUITests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'STORAGE_BACKEND': 'supabase', 'GARDEN_MODE': 'personal',
            'SUPABASE_URL': URL, 'SUPABASE_PUBLISHABLE_KEY': KEY})
        env.start()
        self.addCleanup(env.stop)

    def test_logged_out_and_bad_config_never_read_garden_or_call_ai(self):
        with patch('plant_care.store_factory.create_store') as factory, \
             patch('plant_care.ai_ui.analyze') as ai:
            app = AppTest.from_file(str(APP_PATH)).run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual([f.label for f in app.text_input], ['이메일', '비밀번호'])
            self.assertFalse(any(b.label == '식물 등록' for b in app.button))
            factory.assert_not_called()
            ai.assert_not_called()
            with patch.dict(os.environ, {'SUPABASE_PUBLISHABLE_KEY': ''}):
                app.run()
                self.assertTrue(len(app.error))
                factory.assert_not_called()

    def test_login_then_logout_clears_credentials_and_previous_private_content(self):
        fake = PersonalFake()
        def transport(client, *args, **kwargs):
            return fake.request(client, *args, **kwargs)
        with patch.object(UserClient, 'request', transport), \
             patch.object(AuthClient, 'sign_in', return_value=session()), \
             patch.object(AuthClient, 'verify', side_effect=lambda s: s), \
             patch.object(AuthClient, 'sign_out', side_effect=CloudError('offline')):
            app = AppTest.from_file(str(APP_PATH)).run()
            app.text_input(key='_login_email').set_value('a@example.invalid')
            app.text_input(key='_login_password').set_value('not-a-real-password')
            click_button(app, '로그인')
            self.assertEqual(len(app.exception), 0)
            self.assertFalse('_login_password' in app.session_state)
            app.session_state['garden_backup'] = b'private'
            app.session_state['comparison_question'] = 'private'
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertFalse(app.get('download_button'))
            frames = app.get('iframe')
            self.assertTrue(any('download="plant-care-garden.zip"' in f.proto.srcdoc for f in frames))
            click_button(app, '로그아웃')
            self.assertEqual(len(app.exception), 0)
            self.assertFalse('garden_backup' in app.session_state)
            self.assertFalse('comparison_question' in app.session_state)
            self.assertFalse(SESSION_KEY in app.session_state)
            self.assertEqual(app.text_input(key='_login_password').value, '')

    def test_expired_revoked_session_clears_cached_private_state_before_render(self):
        with patch.object(AuthClient, 'verify', side_effect=AuthError('expired', True)), \
             patch('plant_care.store_factory.create_store') as factory:
            app = AppTest.from_file(str(APP_PATH))
            app.session_state[SESSION_KEY] = session()
            app.session_state['garden_backup'] = b'private'
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertFalse('garden_backup' in app.session_state)
            factory.assert_not_called()

    def test_verification_outage_blocks_data_even_with_existing_session(self):
        with patch.object(AuthClient, 'verify', side_effect=CloudError('temporary outage')), \
             patch('plant_care.store_factory.create_store') as factory:
            app = AppTest.from_file(str(APP_PATH))
            app.session_state[SESSION_KEY] = session()
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(app.error)
            factory.assert_not_called()
            self.assertFalse(any(b.label == '식물 등록' for b in app.button))
