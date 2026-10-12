"""Supabase의 비공개 팀 정원. 저장 버전 비교로 동시 수정 덮어쓰기를 막는다."""
from contextlib import contextmanager
import json
import re
import sqlite3
import weakref
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from .media import MAX_PHOTO_BYTES, prepare_photo
from .snapshot import MAX_STATE_BYTES, dump_connection, photo_name, restore_connection
from .storage import PlantStore


class CloudError(OSError):
    """키·URL·서버 원문을 포함하지 않는 저장소 오류."""


class SupabaseClient:
    def __init__(self, url, secret):
        if not re.fullmatch(r'https://[a-z0-9]{10,40}\.supabase\.co', url.rstrip('/')):
            raise CloudError('Supabase 프로젝트 URL을 확인해 주세요.')
        if not isinstance(secret, str) or not secret.startswith('sb_secret_') or len(secret) < 25:
            raise CloudError('서버용 Supabase Secret key를 설정해 주세요. Publishable key는 사용할 수 없어요.')
        self._url = url.rstrip('/')
        self._secret = secret

    def request(self, path, method='GET', data=None, binary=False, limit=MAX_STATE_BYTES + 1024, upsert=False):
        headers = {'apikey': self._secret, 'User-Agent': 'PlantCareAI/server', 'Accept': 'application/json'}
        if isinstance(data, bytes):
            headers.update({'Content-Type': 'image/jpeg', 'x-upsert': 'true' if upsert else 'false'})
        elif data is not None:
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if data is not None and len(data) > MAX_STATE_BYTES:
            raise CloudError('정원 데이터가 커서 저장하지 못했어요. 전체 백업을 준비해 관리자에게 알려 주세요.')
        request = Request(self._url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read(limit + 1)
            if len(raw) > limit:
                raise CloudError('저장소 응답이 너무 커서 읽지 못했어요.')
            return raw if binary else (json.loads(raw) if raw else None)
        except HTTPError as error:
            if error.code == 409:
                raise CloudError('다른 팀원이 먼저 저장했어요. 새로고침한 뒤 다시 기록해 주세요.') from None
            if error.code in (401, 403):
                raise CloudError('저장소 접근 설정을 확인해 주세요. 키와 SQL 초기 설정이 필요해요.') from None
            if error.code == 404:
                raise CloudError('저장소가 준비되지 않았어요. Supabase SQL 초기 설정을 확인해 주세요.') from None
            raise CloudError('저장소 요청을 완료하지 못했어요. 설정·용량과 프로젝트 일시정지 여부를 확인해 주세요.') from None
        except (URLError, TimeoutError, OSError):
            raise CloudError('저장소 응답을 확인하지 못했어요. 새로고침해 저장 여부를 먼저 확인해 주세요.') from None
        except (ValueError, TypeError, KeyError):
            raise CloudError('저장소 응답 형식을 확인할 수 없어요.') from None


class CloudPlantStore(PlantStore):
    """요청마다 원격 정원을 복원해 기존 검증을 사용하고, 변경만 원자적으로 저장한다."""
    backend = 'supabase'

    def __init__(self, url, secret):
        self.client = SupabaseClient(url, secret)
        self._ready = False
        self._uncertain = False
        self._photo_cache = {}
        bucket = self.client.request('/storage/v1/bucket/plant-care-photos')
        if not isinstance(bucket, dict) or bucket.get('public') is not False:
            raise CloudError('사진 저장소를 비공개로 설정해 주세요.')
        rows = self.client.request('/rest/v1/pc_gardens?id=eq.team-garden&select=state,revision')
        if not isinstance(rows, list) or len(rows) != 1 or type(rows[0].get('revision')) is not int:
            raise CloudError('정원 저장소를 초기화해 주세요. SQL 설정 파일을 실행해야 해요.')
        self._revision = rows[0]['revision']
        self._temporary = TemporaryDirectory(prefix='plant-care-session-')
        self._cleanup = weakref.finalize(self, self._temporary.cleanup)
        try:
            super().__init__(self._temporary.name)
            with self._connection() as connection:
                restore_connection(connection, rows[0]['state'])
        except (ValueError, KeyError, TypeError, sqlite3.Error):
            self._temporary.cleanup()
            raise CloudError('저장된 정원 형식을 확인할 수 없어요. 원격 데이터는 변경하지 않았어요.') from None
        self._ready = True

    def close(self):
        if temporary := getattr(self, '_temporary', None):
            temporary.cleanup()

    def __del__(self):
        try:
            self.close()
        except OSError:
            pass

    @contextmanager
    def _connection(self):
        with super()._connection() as connection:
            before = connection.total_changes
            yield connection
            if self._ready and connection.total_changes != before:
                if self._uncertain:
                    raise CloudError('저장 결과 확인이 필요해요. 새로고침한 뒤 계속해 주세요.')
                state = dump_connection(connection)
                write_id = str(uuid4())
                try:
                    revision = self.client.request('/rest/v1/rpc/pc_save_garden', 'POST',
                                                   {'p_expected_revision': self._revision, 'p_state': state, 'p_write_id': write_id})
                except CloudError as error:
                    # 응답이 끊긴 뒤에도 서버에서 커밋됐을 수 있다. 같은 쓰기의 완료만 조회한다.
                    try:
                        records = self.client.request(f'/rest/v1/pc_garden_writes?write_id=eq.{write_id}&select=revision')
                    except CloudError:
                        records = None
                    if records and len(records) == 1 and type(records[0].get('revision')) is int:
                        revision = records[0]['revision']
                    else:
                        self._uncertain = True
                        raise error from None
                if type(revision) is not int or revision != self._revision + 1:
                    self._uncertain = True
                    raise CloudError('저장 결과를 확인할 수 없어요. 새로고침해 먼저 확인해 주세요.')
                self._revision = revision

    def _save_photo(self, photo):
        if self._uncertain:
            raise CloudError('저장 결과 확인이 필요해요. 새로고침한 뒤 계속해 주세요.')
        if photo is None:
            return None
        prepared = prepare_photo(photo)
        name = f'photos/{uuid4().hex}.jpg'
        self.client.request('/storage/v1/object/plant-care-photos/' + name, 'POST', prepared)
        self._photo_cache[name] = prepared
        return name

    def _remove_photo(self, relative):
        # 커밋 결과가 불확실할 때 실제 저장된 기록의 사진을 삭제하지 않는다.
        # 참조되지 않는 업로드는 관리자 백업/정리 절차로 다룬다.
        pass

    def read_photo(self, relative):
        relative = photo_name(relative)
        if relative not in self._photo_cache:
            self._photo_cache[relative] = self.client.request('/storage/v1/object/authenticated/plant-care-photos/' + relative,
                                                            binary=True, limit=MAX_PHOTO_BYTES)
        return self._photo_cache[relative]

    def photo_path(self, relative):
        raise CloudError('외부 저장소의 사진은 파일 경로 대신 read_photo로 읽어 주세요.')

    def restore_backup(self, state, photos):
        # SQL 검증을 통과하고 현재 정원이 비어 있을 때만 사진을 업로드한다.
        with self._connection() as connection:
            restore_connection(connection, state)
            for name, data in photos.items():
                photo_name(name)
                prepared = prepare_photo(data)
                # UUID를 새로 만들지 않아 기존 기록의 연결을 그대로 유지한다.
                self.client.request('/storage/v1/object/plant-care-photos/' + name, 'POST', prepared, upsert=True)
