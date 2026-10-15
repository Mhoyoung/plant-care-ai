"""Short topic labels and lossless details from already saved AI suggestions."""


def short_proposal_title(text):
    # Topic labels invite checking; they never turn a conditional suggestion into an instruction.
    topics = [
        (('비료', '시비', '양분'), '비료 사용 조건 확인'),
        (('흙', '수분', '물주', '물을', '급수'), '흙 상태·물주기 조건 확인'),
        (('분갈', '뿌리'), '뿌리·분갈이 상태 확인'),
        (('배수', '받침', '고인 물'), '배수·받침대 확인'),
        (('잎',), '잎 상태 확인'),
        (('통풍', '창가', '광량', '햇빛', '직사광', '온도'), '키우는 환경 확인'),
    ]
    return next((title for words, title in topics if any(word in text for word in words)), 'AI 관리 제안 확인')


def ai_schedule_description(action, checks, uncertainty):
    return '\n\n'.join([
        '[AI 제안]\n' + action,
        '[먼저 확인할 것]\n' + ('\n'.join('• ' + check for check in checks) or '저장된 확인 조건이 없습니다. 실행 전에 현재 상태를 확인해 주세요.'),
        '[분석의 한계]\n' + uncertainty,
    ])
