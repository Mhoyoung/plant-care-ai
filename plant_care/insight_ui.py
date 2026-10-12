"""저장된 AI 답변을 안내·확인 카드·원문으로 나누어 표시한다."""
from html import escape
from base64 import b64encode

import streamlit as st

SPROUT = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<circle cx="32" cy="32" r="31" fill="#e8f0dd"/>
<path d="M32 36C16 36 13 25 14 18c13-1 22 5 18 18Z" fill="#7fa865"/>
<path d="M32 32C30 15 43 10 51 12c1 14-7 21-19 20Z" fill="#3e704b"/>
<path d="M32 29v16" stroke="#345f40" stroke-width="3" stroke-linecap="round"/>
<path d="M20 40h24l-4 17H24Z" fill="#d5aa81"/>
<circle cx="28" cy="46" r="1.5" fill="#34513c"/><circle cx="37" cy="46" r="1.5" fill="#34513c"/>
<path d="M29 50q3 3 6 0" fill="none" stroke="#34513c" stroke-width="1.5" stroke-linecap="round"/>
</svg>'''


def partner_note(summary, context, first_check=None):
    labels = ["가상 사례" if context.get("evaluation_demo") else "기록 기반 안내"]
    labels.append("사진 포함" if context.get("has_photo") else "사진 없음")
    lead = (f"먼저 {check_title(first_check, 1)}부터 살펴볼까요?\n확인한 상태에 맞춰 다음 관리를 선택해요."
            if first_check else summary)
    icon = b64encode(SPROUT.encode('utf-8')).decode('ascii')
    st.html('<div class="partner-note"><div class="partner-avatar">'
            f'<img src="data:image/svg+xml;base64,{icon}" alt="" aria-hidden="true"></div>'
            '<div class="partner-bubble"><div class="partner-label">AI 식물 파트너</div>'
            f'<p>{escape(lead)}</p><span class="partner-meta">{escape(" · ".join(labels))}</span></div></div>')


def check_title(text, index):
    # 제목은 탐색을 돕는 표지이며, 판단·조건은 아래의 원문을 그대로 표시한다.
    for words, title in ((("배수", "받침", "고인 물"), "배수와 받침대"),
                         (("무게", "가벼", "무거", "묵직"), "화분 무게"),
                         (("흙", "수분"), "흙 상태"),
                         (("뿌리", "밑동"), "뿌리 상태"),
                         (("광량", "직사광", "창가", "온도", "통풍"), "키우는 환경"),
                         (("종류", "품종", "종을"), "식물 종류")):
        if any(word in text for word in words):
            return title
    return f"확인할 사항 {index}"


def check_card(text, index):
    st.html(f'<div class="insight-check"><span class="insight-number">{index:02}</span>'
            f'<div><h4>{escape(check_title(text, index))}</h4><p>{escape(text)}</p></div></div>')


def original_result(result):
    for field, label in (("summary", "상태 요약"), ("observations", "참고한 관찰"), ("checks", "먼저 확인할 것"),
                         ("actions", "다음 관리 제안"), ("uncertainty", "분석의 한계")):
        st.write(f"**{label}**")
        values = result[field] if isinstance(result[field], list) else [result[field]]
        for value in values:
            st.html(f'<div class="insight-original">{escape(value)}</div>')


def render_insight(result, context, prefix, *, store=None, suggestions=None):
    """두 비교 조건과 실제 분석에서 같은 표시 규칙을 사용한다. 외부 호출 없음."""
    with st.container(key=f"insight_{prefix}"):
        partner_note(result["summary"], context, result['checks'][0] if result['checks'] else None)
        st.html('<div class="insight-section">먼저, 이것부터 확인해요</div>')
        checks = result["checks"]
        if not checks:
            st.caption("이 응답에는 별도의 확인 항목이 없어요. 전체 분석과 한계를 확인해 주세요.")
        for index, text in enumerate(checks[:3], 1):
            check_card(text, index)
        if len(checks) > 3:
            with st.expander(f"확인할 사항 {len(checks) - 3}개 더 보기"):
                for index, text in enumerate(checks[3:], 4):
                    check_card(text, index)
        st.caption("확인한 상태가 제안의 조건에 맞는지 살펴본 뒤 관리해 주세요.")
        with st.expander(f"확인 후 할 수 있는 관리 · {len(result['actions'])}개"):
            if store is not None and suggestions is not None:
                from .care_ui import suggestion_card
                for suggestion in suggestions:
                    suggestion_card(store, suggestion, "analysis")
            else:
                for index, text in enumerate(result["actions"], 1):
                    st.html(f'<div class="insight-action"><b>관리 제안 {index:02}</b><p>{escape(text)}</p></div>')
        with st.expander("분석의 한계 · 꼭 확인해 주세요"):
            st.html(f'<div class="insight-original">{escape(result["uncertainty"])}</div>')
        with st.expander("이렇게 제안한 이유 · 전체 분석 보기"):
            original_result(result)
