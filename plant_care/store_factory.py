"""저장소는 명시적으로 선택한다. 연결 실패 시 로컬로 몰래 전환하지 않는다."""
import os
from hashlib import sha256
from time import monotonic
from .storage import PlantStore
from .cloud_store import CloudError, CloudPlantStore
from .auth import AuthSession
from .personal_store import PersonalCloudPlantStore


CLOUD_READ_TTL = 15
CACHE_KEY = '_plant_store_cache'


def option(settings, name, default=''):
    return str(os.environ.get(name, (settings or {}).get(name, default))).strip()


def personal_mode(settings=None):
    return option(settings, 'STORAGE_BACKEND', 'local') == 'supabase' and option(settings, 'GARDEN_MODE', 'personal') == 'personal'


def discard_cached_store(session):
    if cached := session.pop(CACHE_KEY, None):
        cached['store'].close()


def create_store(data_root, settings=None, session=None, auth=None):
    settings = settings or {}
    backend = option(settings, 'STORAGE_BACKEND', 'local')
    if backend == 'local':
        if session is not None:
            discard_cached_store(session)
        return PlantStore(data_root)
    if backend == 'supabase':
        if option(settings, 'GARDEN_MODE', 'personal') not in ('personal', 'team'):
            raise CloudError('GARDEN_MODE는 personal 또는 team으로 설정해 주세요.')
        url = option(settings, 'SUPABASE_URL')
        if personal_mode(settings):
            if not isinstance(auth, AuthSession):
                if session is not None:
                    discard_cached_store(session)
                raise CloudError('로그인 후 내 정원을 열 수 있어요.')
            secret = option(settings, 'SUPABASE_PUBLISHABLE_KEY')
            def build():
                return PersonalCloudPlantStore(url, secret, auth)
            scope = auth.owner_id + '\0' + auth.access_token
        else:
            secret = option(settings, 'SUPABASE_SECRET_KEY')
            def build():
                return CloudPlantStore(url, secret)
            scope = 'team'
        if session is None:
            return build()
        identity = sha256((url + '\0' + secret + '\0' + scope).encode('utf-8')).hexdigest()
        cached = session.get(CACHE_KEY)
        if (cached and cached['identity'] == identity and not cached['store']._uncertain
                and monotonic() - cached['loaded_at'] < CLOUD_READ_TTL):
            return cached['store']
        discard_cached_store(session)
        store = build()
        session[CACHE_KEY] = {'identity': identity, 'store': store, 'loaded_at': monotonic()}
        return store
    if session is not None:
        discard_cached_store(session)
    raise CloudError('STORAGE_BACKEND는 local 또는 supabase로 설정해 주세요.')
