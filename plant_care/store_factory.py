"""저장소는 명시적으로 선택한다. 연결 실패 시 로컬로 몰래 전환하지 않는다."""
import os
from .storage import PlantStore
from .cloud_store import CloudError, CloudPlantStore


def create_store(data_root, settings=None):
    settings = settings or {}
    def option(name, default=''):
        return str(os.environ.get(name, settings.get(name, default))).strip()
    backend = option('STORAGE_BACKEND', 'local')
    if backend == 'local':
        return PlantStore(data_root)
    if backend == 'supabase':
        return CloudPlantStore(option('SUPABASE_URL'), option('SUPABASE_SECRET_KEY'))
    raise CloudError('STORAGE_BACKEND는 local 또는 supabase로 설정해 주세요.')
