"""Supabase Auth REST: passwords are sent only to Auth; garden requests use user JWTs."""
from dataclasses import dataclass, field
import base64
import json
import math
import re
from time import time
from uuid import UUID

from .cloud_store import CloudError, SupabaseClient

SESSION_KEY = '_auth_session'


class AuthError(CloudError):
    def __init__(self, message, invalid_session=False):
        super().__init__(message)
        self.invalid_session = invalid_session


def user_id(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise AuthError('계정 정보를 확인할 수 없어요. 다시 로그인해 주세요.', True) from None


@dataclass(frozen=True)
class AuthSession:
    owner_id: str
    email: str
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: float


class UserClient(SupabaseClient):
    """Publishable key + verified user access token. Never accepts a server secret."""
    def __init__(self, url, publishable_key, access_token=''):
        if not re.fullmatch(r'https://[a-z0-9]{10,40}\.supabase\.co', url.rstrip('/')):
            raise CloudError('Supabase 프로젝트 URL을 확인해 주세요.')
        legacy_anon = False
        try:
            payload = publishable_key.split('.')[1]
            legacy_anon = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4))).get('role') == 'anon'
        except (ValueError, IndexError, TypeError, AttributeError):
            pass
        if not (isinstance(publishable_key, str) and
                ((publishable_key.startswith('sb_publishable_') and len(publishable_key) >= 25) or legacy_anon)):
            raise CloudError('SUPABASE_PUBLISHABLE_KEY를 설정해 주세요. 서버용 Secret key를 넣지 마세요.')
        if not isinstance(access_token, str) or '\n' in access_token or '\r' in access_token:
            raise AuthError('로그인 정보를 확인할 수 없어요.', True)
        self._url = url.rstrip('/')
        self._secret = publishable_key
        self._access_token = access_token

    def _headers(self):
        headers = super()._headers()
        if self._access_token:
            headers['Authorization'] = 'Bearer ' + self._access_token
        return headers


class AuthClient(UserClient):
    def _network_error(self):
        # Auth outages do not imply an uncertain garden write or an invalid password.
        return AuthError('로그인 서버에 연결하지 못했어요. 잠시 뒤 다시 시도하고, 계속되면 관리자에게 알려 주세요.')

    def _http_error(self, error):
        # Parse only an allowlisted machine code. Never echo server text or request credentials.
        try:
            code = json.loads(error.read(8192)).get('code')
        except (ValueError, TypeError, AttributeError, OSError):
            code = None
        if code == 'email_address_not_authorized':
            return AuthError('인증 메일 발송 설정이 필요해요. 관리자에게 Custom SMTP 설정을 요청해 주세요.')
        if code == 'over_email_send_rate_limit':
            return AuthError('인증 메일 발송 한도에 도달했어요. 반복 가입하지 말고 잠시 뒤 다시 시도해 주세요.')
        if code == 'signup_disabled':
            return AuthError('회원가입이 닫혀 있어요. 관리자에게 알려 주세요.')
        if code == 'email_not_confirmed':
            return AuthError('이메일의 인증 링크를 먼저 누른 뒤 로그인해 주세요.', True)
        if code == 'weak_password':
            return AuthError('더 강한 비밀번호를 사용해 주세요. 관리자 설정의 길이·문자 조건을 확인해 주세요.')
        if error.code == 429:
            return AuthError('요청이 많아 잠시 제한됐어요. 잠시 뒤 다시 시도해 주세요.')
        if error.code in (400, 401, 403, 422):
            return AuthError('이메일·비밀번호와 이메일 인증 여부를 확인해 주세요. 인증 링크가 만료됐다면 다시 가입을 시도해 주세요.', True)
        return AuthError('로그인 서버에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.')

    def _auth_request(self, path, method='GET', data=None):
        return self.request('/auth/v1/' + path, method, data, limit=65536)

    def _session(self, payload):
        try:
            access = payload['access_token']
            refresh = payload['refresh_token']
            expires = float(payload.get('expires_at') or time() + float(payload['expires_in']))
            if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh or not math.isfinite(expires) or expires <= time():
                raise ValueError()
            # Do not authorize from decoded JWT claims or the unverified login response.
            verified = AuthClient(self._url, self._secret, access)._auth_request('user')
            owner = user_id(verified['id'])
            email = str(verified.get('email') or '')[:320]
            if not verified.get('email_confirmed_at'):
                raise AuthError('이메일 인증을 완료한 뒤 로그인해 주세요.', True)
            return AuthSession(owner, email, access, refresh, expires)
        except (KeyError, TypeError, ValueError, OverflowError):
            raise AuthError('로그인 응답을 확인할 수 없어요. 다시 로그인해 주세요.', True) from None

    def sign_in(self, email, password):
        return self._session(self._auth_request('token?grant_type=password', 'POST', {'email': email, 'password': password}))

    def sign_up(self, email, password):
        # Always return to sign-in; even auto-confirm projects must verify /user there.
        self._auth_request('signup', 'POST', {'email': email, 'password': password})

    def verify(self, session):
        if not isinstance(session, AuthSession):
            raise AuthError('다시 로그인해 주세요.', True)
        if session.expires_at <= time() + 60:
            updated = self._session(self._auth_request('token?grant_type=refresh_token', 'POST', {'refresh_token': session.refresh_token}))
        else:
            verified = AuthClient(self._url, self._secret, session.access_token)._auth_request('user')
            if not isinstance(verified, dict) or not verified.get('email_confirmed_at'):
                raise AuthError('이메일 인증 후 다시 로그인해 주세요.', True)
            updated = AuthSession(user_id(verified.get('id')), str(verified.get('email') or '')[:320],
                                  session.access_token, session.refresh_token, session.expires_at)
        if updated.owner_id != session.owner_id:
            raise AuthError('계정이 변경됐어요. 다시 로그인해 주세요.', True)
        return updated

    def sign_out(self, session):
        AuthClient(self._url, self._secret, session.access_token)._auth_request('logout?scope=local', 'POST')


def clear_account_state(state, session=None, notice=None):
    """No cached bytes/forms/backups/comparison results may cross account boundaries."""
    from .store_factory import discard_cached_store
    discard_cached_store(state)
    state.clear()
    if session is not None:
        state[SESSION_KEY] = session
    if notice:
        state['_auth_notice'] = notice
