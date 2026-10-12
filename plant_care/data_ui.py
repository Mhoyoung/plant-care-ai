"""요청할 때만 사진을 포함한 정원 백업을 준비한다."""
import json
import sqlite3
from zipfile import BadZipFile
import streamlit as st
from .cloud_store import CloudError
from .snapshot import make_backup, read_backup


def data_tools(store):
    with st.expander('기록 보관과 백업'):
        st.caption('기록과 사진을 외부 저장소에 보관하고 있어요.' if store.backend == 'supabase'
                   else '현재 실행 중인 서버에 기록을 보관하고 있어요. 팀원용 외부 저장소는 아직 연결되지 않았어요.')
        st.caption('전체 정원 백업에는 식물·기록·분석·지역 설정과 사진이 포함됩니다. 개인 자료이므로 공개 저장소에 올리지 마세요.')
        if st.button('사진 포함 전체 백업 준비', key='prepare_garden_backup'):
            try:
                with st.spinner('정원과 사진을 백업하고 있어요…'):
                    st.session_state['garden_backup'] = make_backup(store)
            except (ValueError, OSError, sqlite3.Error):
                st.session_state.pop('garden_backup', None)
                st.error('전체 백업을 준비하지 못했어요. 사진 연결과 저장소 상태를 확인해 주세요.')
        if backup := st.session_state.get('garden_backup'):
            st.download_button('정원 전체 백업 내려받기', data=backup, file_name='plant-care-garden.zip',
                               mime='application/zip', key='download_garden_backup')
            st.caption('백업 준비 버튼을 누른 시점의 파일입니다. 이후 기록은 다시 백업해 주세요.')
        if store.backend == 'supabase' and not store.list_plants():
            st.caption('외부 정원이 비어 있을 때 기존 앱에서 내려받은 전체 백업을 가져올 수 있어요.')
            uploaded = st.file_uploader('기존 정원 전체 백업', type=['zip'], max_upload_size=100, key='restore_garden_file')
            consent = st.checkbox('백업의 식물 기록과 사진을 연결한 Supabase 저장소로 옮깁니다.', key='restore_garden_consent')
            if st.button('기존 정원 가져오기', disabled=uploaded is None, key='restore_garden'):
                if not consent:
                    st.error('백업 전송 안내를 확인해 주세요.')
                else:
                    try:
                        with st.spinner('기록과 사진을 옮기고 있어요…'):
                            state, photos = read_backup(uploaded.getvalue())
                            store.restore_backup(state, photos)
                    except CloudError as error:
                        st.error(str(error))
                    except (ValueError, KeyError, TypeError, BadZipFile, OSError, sqlite3.Error, json.JSONDecodeError):
                        st.error('정원 백업을 가져오지 못했어요. 파일 형식과 사진을 확인해 주세요.')
                    else:
                        st.session_state.pop('garden_backup', None)
                        st.session_state['_select_after_save'] = -1
                        st.session_state['_notice'] = '기존 정원과 사진을 외부 저장소로 옮겼어요.'
                        st.rerun()
