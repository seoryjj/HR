"""
Confluence 페이지 내용 → goals.json 자동 갱신 스크립트
GitHub Actions에서 실행됨
"""
import os, json, re, requests, datetime
from base64 import b64encode

# ── 환경변수 ─────────────────────────────────────-
CONFLUENCE_URL     = os.environ['CONFLUENCE_URL'].rstrip('/')
CONFLUENCE_TOKEN   = os.environ['CONFLUENCE_TOKEN']
CONFLUENCE_EMAIL   = os.environ['CONFLUENCE_EMAIL']
CONFLUENCE_PAGE_ID = os.environ['CONFLUENCE_PAGE_ID']

# ── Confluence API 인증 ───────────────────────────
def get_auth():
    token = b64encode(f"{CONFLUENCE_EMAIL}:{CONFLUENCE_TOKEN}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

# ── 페이지 내용 가져오기 ──────────────────────────
def fetch_page():
    url = f"{CONFLUENCE_URL}/rest/api/content/{CONFLUENCE_PAGE_ID}"
    params = {"expand": "body.storage,version"}
    resp = requests.get(url, headers=get_auth(), params=params)
    resp.raise_for_status()
    data = resp.json()
    # storage format (XML) → plain text 추출
    storage = data['body']['storage']['value']
    version = data['version']['number']
    title   = data['title']
    print(f"✅ 페이지 가져오기 성공: '{title}' (v{version})")
    return storage, title

# ── Confluence storage XML → 텍스트 파싱 ─────────
def parse_storage(xml_content):
    """
    Confluence storage format에서 섹션별 목표 파싱
    h2 태그 = 본부 섹션
    h3 태그 = 역할 섹션
    li 태그 = 목표 항목
    """
    # HTML 태그 제거 헬퍼
    def strip_tags(s):
        return re.sub(r'<[^>]+>', '', s).strip()

    # 전사공통 / 본부별 파싱
    common_goals = []
    dept_data = {}   # {dept_name: {role_name: [goals]}}

    # h2 섹션 분리
    sections = re.split(r'<h2[^>]*>', xml_content)
    current_dept = None

    for section in sections[1:]:  # 첫 번째는 헤더 이전
        # 섹션 제목
        title_match = re.match(r'(.*?)</h2>', section, re.DOTALL)
        if not title_match:
            continue
        raw_title = strip_tags(title_match.group(1))
        title = raw_title.replace('📌 수정 방법 안내', '').strip()

        # 전사 공통
        if '전사 공통' in title:
            items = re.findall(r'<li[^>]*>(.*?)</li>', section, re.DOTALL)
            common_goals = [strip_tags(i) for i in items if strip_tags(i)]
            continue

        # 본부 섹션 (🏢 포함)
        if '🏢' in raw_title or any(kw in raw_title for kw in ['본부', '연구센터', '사업부']):
            # 본부 이름 정리
            dept_name = re.sub(r'[🏢*_]', '', raw_title).strip()
            if not dept_name or '수정 방법' in dept_name:
                continue
            current_dept = dept_name
            dept_data[current_dept] = {}

            # h3 역할 섹션 분리
            roles_section = section[title_match.end():]
            role_sections = re.split(r'<h3[^>]*>', roles_section)

            for role_sec in role_sections[1:]:
                role_title_m = re.match(r'(.*?)</h3>', role_sec, re.DOTALL)
                if not role_title_m:
                    continue
                role_name = strip_tags(role_title_m.group(1))
                # [ ] 괄호 제거
                role_name = re.sub(r'[\[\]]', '', role_name).strip()

                # 목표 항목 추출
                items = re.findall(r'<li[^>]*>(.*?)</li>', role_sec, re.DOTALL)
                goals = [strip_tags(i) for i in items if strip_tags(i)]
                if goals:
                    dept_data[current_dept][role_name] = goals

    return common_goals, dept_data

# ── goals.json 갱신 ───────────────────────────────
def update_goals_json(common_goals, dept_data):
    with open('goals.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    changed = []

    # 전사 공통 갱신
    if common_goals:
        old = data['common']['goals']
        if old != common_goals:
            data['common']['goals'] = common_goals
            changed.append("전사 공통")

    # 본부별 갱신
    for dept in data['depts']:
        dname = dept['name']
        # dept_data 키와 매칭 (부분 일치 허용)
        matched_key = next(
            (k for k in dept_data if k in dname or dname in k), None
        )
        if not matched_key:
            continue

        for role in dept['roles']:
            rname = role['name']
            matched_role = next(
                (k for k in dept_data[matched_key] if k in rname or rname in k), None
            )
            if not matched_role:
                continue
            new_goals = dept_data[matched_key][matched_role]
            if new_goals and role['goals'] != new_goals:
                role['goals'] = new_goals
                changed.append(f"{dname} / {rname}")

    if changed:
        data['meta']['updated'] = datetime.date.today().strftime('%Y-%m-%d')
        with open('goals.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✅ goals.json 갱신 완료")
        print(f"   변경된 섹션: {', '.join(changed)}")
    else:
        print("ℹ️  변경사항 없음 — goals.json 그대로 유지")

# ── 실행 ─────────────────────────────────────────
if __name__ == '__main__':
    storage_xml, _ = fetch_page()
    common_goals, dept_data = parse_storage(storage_xml)

    print(f"\n파싱 결과:")
    print(f"  전사 공통: {len(common_goals)}개")
    for d, roles in dept_data.items():
        total = sum(len(g) for g in roles.values())
        print(f"  {d}: {total}개 ({', '.join(roles.keys())})")

    update_goals_json(common_goals, dept_data)
