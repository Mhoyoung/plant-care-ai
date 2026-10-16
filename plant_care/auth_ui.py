"""Email/password gate, before any garden/AI/backup UI is rendered."""
import streamlit as st
from .auth import AuthClient, AuthError, SESSION_KEY, clear_account_state
from .cloud_store import CloudError
from .store_factory import option


def _submit(client, action):
    email = str(st.session_state.get('_login_email', '')).strip()
    password = st.session_state.get('_login_password', '')
    try:
        if not email or '@' not in email or len(email) > 320:
            raise ValueError('이메일 주소를 확인해 주세요.')
        if len(password) < 8 or len(password) > 128:
            raise ValueError('비밀번호는 8~128자로 입력해 주세요.')
        if action == 'signup':
            if password != st.session_state.get('_login_confirm', ''):
                raise ValueError('비밀번호 확인이 일치하지 않아요.')
            client.sign_up(email, password)
            clear_account_state(st.session_state, notice='가입 요청을 보냈어요. 이메일의 인증 링크를 누른 뒤 로그인해 주세요. 이미 가입한 주소라면 기존 비밀번호로 로그인하세요.')
        else:
            session = client.sign_in(email, password)
            clear_account_state(st.session_state, session, '로그인했어요. 나만의 정원을 시작해 보세요.')
    except (CloudError, ValueError) as error:
        clear_account_state(st.session_state)
        st.session_state['_auth_error'] = str(error)


def logout(client, session):
    notice = '로그아웃했어요.'
    try:
        client.sign_out(session)
    except CloudError:
        notice = '이 기기에서 로그아웃했어요. 서버 연결이 끊겨 세션 해지는 확인하지 못했어요.'
    finally:
        clear_account_state(st.session_state, notice=notice)


def require_account(settings):
    try:
        client = AuthClient(option(settings, 'SUPABASE_URL'), option(settings, 'SUPABASE_PUBLISHABLE_KEY'))
    except CloudError as error:
        clear_account_state(st.session_state)
        st.error(str(error))
        st.info('개인 정원 연결을 준비하고 있어요. 관리자가 로그인 설정과 supabase/personal.sql을 적용해야 해요.')
        st.stop()
    if session := st.session_state.get(SESSION_KEY):
        try:
            verified = client.verify(session)
        except AuthError as error:
            if error.invalid_session:
                clear_account_state(st.session_state)
                st.session_state['_auth_error'] = '로그인이 만료됐어요. 다시 로그인해 주세요.'
            else:
                st.error(str(error))
                st.button('로그인 연결 다시 확인')
                st.button('로그아웃', on_click=logout, args=(client, session))
                st.stop()
        except CloudError as error:
            # Fail closed on verification outages, but allow a later refresh to recover.
            st.error(str(error))
            st.button('로그인 연결 다시 확인')
            st.button('로그아웃', on_click=logout, args=(client, session))
            st.stop()
        else:
            st.session_state[SESSION_KEY] = verified
            return verified, client
    with st.container(key='account_gate'):
        st.html('<style>.st-key-account_gate{max-width:480px;margin-inline:auto;padding-top:1rem}</style>')
        _render_login(client)
    st.stop()


def _render_login(client):
    st.title('🌿 나만의 식물 정원')
    st.write('로그인하면 내 식물과 사진, 관리 기록, 케어 일정을 이어서 사용할 수 있어요.')
    st.caption('Android 시험 앱에서도 같은 이메일 계정을 사용할 수 있도록 준비하고 있어요.')
    if notice := st.session_state.pop('_auth_notice', None):
        st.success(notice)
    if error := st.session_state.pop('_auth_error', None):
        st.error(error)
    action = st.radio('계정', ['로그인', '회원가입'], horizontal=True, key='_auth_action')
    with st.form('account_form'):
        st.text_input('이메일', max_chars=320, key='_login_email', autocomplete='email')
        st.text_input('비밀번호', type='password', max_chars=128, key='_login_password',
                      autocomplete='current-password' if action == '로그인' else 'new-password')
        if action == '회원가입':
            st.text_input('비밀번호 확인', type='password', max_chars=128, key='_login_confirm', autocomplete='new-password')
            st.caption('8자 이상으로 설정하고, 가입 후 이메일 인증을 완료해 주세요.')
        st.form_submit_button(action, type='primary', width='stretch', on_click=_submit,
                              args=(client, 'signin' if action == '로그인' else 'signup'))
    st.caption('다른 사람의 정원은 볼 수 없어요. AI 요청은 공용 Gemini 한도를 사용해요. 공용 기기에서는 사용 후 로그아웃해 주세요.')
    st.caption('인증 메일은 스팸함도 확인해 주세요. 브라우저를 새로 열거나 세션이 종료되면 다시 로그인해야 할 수 있어요.')
    st.stop()
