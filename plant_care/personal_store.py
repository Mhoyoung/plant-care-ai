"""One snapshot per authenticated owner; database and Storage RLS enforce ownership."""
from .auth import AuthSession, UserClient, user_id
from .cloud_store import CloudError, CloudPlantStore
from .snapshot import photo_name


class PersonalCloudPlantStore(CloudPlantStore):
    personal = True

    def __init__(self, url, publishable_key, session):
        if not isinstance(session, AuthSession):
            raise CloudError('로그인이 필요해요.')
        self.owner_id = user_id(session.owner_id)
        self._access_token = session.access_token
        super().__init__(url, publishable_key)

    def _make_client(self, url, secret):
        return UserClient(url, secret, self._access_token)

    def _load_remote(self):
        self.client.request('/rest/v1/rpc/pc_ensure_user_garden', 'POST', {})
        return self.client.request(f'/rest/v1/pc_user_gardens?owner_id=eq.{self.owner_id}&select=state,revision')

    def _save_remote(self, state, write_id):
        return self.client.request('/rest/v1/rpc/pc_save_user_garden', 'POST',
            {'p_expected_revision': self._revision, 'p_state': state, 'p_write_id': write_id})

    def _find_write(self, write_id):
        return self.client.request(f'/rest/v1/pc_user_garden_writes?owner_id=eq.{self.owner_id}&write_id=eq.{write_id}&select=revision')

    def _remote_photo(self, name):
        return self.owner_id + '/' + photo_name(name)
