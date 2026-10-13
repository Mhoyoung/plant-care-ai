"""저장소는 명시적으로 선택한다. 연결 실패 시 로컬로 몰래 전환하지 않는다."""
import os
from hashlib import sha256
from time import monotonic
from .storage import PlantStore
from .cloud_store import CloudError, CloudPlantStore


CLOUD_READ_TTL = 15
CACHE_KEY = '_plant_store_cache'


def discard_cached_store(session):
    if cached := session.pop(CACHE_KEY, None):
        cached['store'].close()


def create_store(data_root, settings=None, session=None):
    settings = settings or {}
    def option(name, default=''):
        return str(os.environ.get(name, settings.get(name, default))).strip()
    backend = option('STORAGE_BACKEND', 'local')
    if backend == 'local':
        if session is not None:
            discard_cached_store(session)
        return PlantStore(data_root)
    if backend == 'supabase':
        url, secret = option('SUPABASE_URL'), option('SUPABASE_SECRET_KEY')
        if session is None:
            return CloudPlantStore(url, secret)
        identity = sha256((url + '\0' + secret).encode('utf-8')).hexdigest()
        cached = session.get(CACHE_KEY)
        if (cached and cached['identity'] == identity and not cached['store']._uncertain
                and monotonic() - cached['loaded_at'] < CLOUD_READ_TTL):
            return cached['store']
        discard_cached_store(session)
        store = CloudPlantStore(url, secret)
        session[CACHE_KEY] = {'identity': identity, 'store': store, 'loaded_at': monotonic()}
        return store
    if session is not None:
        discard_cached_store(session)
    raise CloudError('STORAGE_BACKEND는 local 또는 supabase로 설정해 주세요.')
