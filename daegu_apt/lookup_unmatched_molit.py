"""
미매칭 Naver 단지에 대해 MOLIT 실거래가 API로 후보 검색
- complex_molit_map_review.xlsx 의 '미매칭' 시트 읽기
- 구별 MOLIT 전체 단지 목록(최근 12개월) 빌드
- 각 미매칭 단지: 같은 동 내 MOLIT 단지 퍼지 매칭 → 원인 분류
- 결과: complex_molit_unmatched_analysis.xlsx
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import os, re, time
import requests
import xml.etree.ElementTree as ET
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))
API_KEY = os.getenv('MOLIT_API_KEY', '')
API_URL = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'

DAEGU_LAWD = {
    '중구':  '27110',
    '동구':  '27140',
    '서구':  '27170',
    '남구':  '27200',
    '북구':  '27230',
    '수성구': '27260',
    '달서구': '27290',
    '달성군': '27710',
}

def prev_months(n=12):
    result = []
    d = datetime.today().replace(day=1)
    for _ in range(n):
        result.append(d.strftime('%Y%m'))
        d -= timedelta(days=1)
        d = d.replace(day=1)
    return result

def fetch_molit(lawd_cd, deal_ymd):
    url = (f'{API_URL}?serviceKey={API_KEY}'
           f'&LAWD_CD={lawd_cd}&DEAL_YMD={deal_ymd}&numOfRows=1000&pageNo=1')
    try:
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        result_code = root.findtext('.//resultCode', '')
        if result_code and result_code not in ('00', '000'):
            return []
        rows = []
        for item in root.findall('.//item'):
            def g(tag):
                el = item.find(tag)
                return el.text.strip() if el is not None and el.text else ''
            rows.append({
                '아파트명': g('aptNm'),
                '법정동': g('umdNm'),
                '건축년도': g('buildYear'),
                '거래년도': g('dealYear'),
                '거래월': g('dealMonth'),
                '전용면적': g('excluUseAr'),
                '거래금액': g('dealAmount'),
            })
        return rows
    except Exception:
        return []

def normalize(name):
    """괄호·공백·특수문자 제거 후 소문자"""
    name = re.sub(r'[\s　]', '', name)
    name = re.sub(r'[(\(（].*', '', name)
    return name.lower()

def fuzzy_score(naver_nm, molit_nm):
    """0.0~1.0 유사도 (포함관계 기반)"""
    n = normalize(naver_nm)
    m = normalize(molit_nm)
    if n == m:
        return 1.0
    if n in m or m in n:
        return 0.8
    # 공통 prefix 길이
    shorter = min(len(n), len(m))
    if shorter == 0:
        return 0.0
    prefix = sum(1 for a, b in zip(n, m) if a == b)
    return prefix / shorter * 0.5

# ── 1. 미매칭 목록 로드 ──────────────────────────────────────────
print('미매칭 목록 로드...')
df_unmatched = pd.read_excel(
    os.path.join(BASE, 'complex_molit_map_review.xlsx'),
    sheet_name='미매칭'
)
print(f'  → {len(df_unmatched)}개 단지')

# ── 2. 구별 MOLIT 전체 단지 수집 (최근 12개월) ──────────────────
print('\nMOLIT API 조회 중 (최근 12개월)...')
deal_ymds = prev_months(12)
molit_all = []  # [{'구','아파트명','법정동','건축년도','거래수'}]

districts_needed = df_unmatched['구'].unique()
for dist in districts_needed:
    lawd = DAEGU_LAWD.get(dist)
    if not lawd:
        continue
    rows_dist = []
    for ymd in deal_ymds:
        rows = fetch_molit(lawd, ymd)
        rows_dist.extend(rows)
        time.sleep(0.1)
    # 구 내 고유 단지명+동 집계
    tmp = pd.DataFrame(rows_dist)
    if tmp.empty:
        print(f'  [{dist}] 데이터 없음')
        continue
    grouped = (tmp.groupby(['아파트명', '법정동', '건축년도'])
                  .size()
                  .reset_index(name='거래건수'))
    grouped['구'] = dist
    molit_all.append(grouped)
    print(f'  [{dist}] {len(grouped)}개 고유 단지 (12개월 거래 있음)')

df_molit = pd.concat(molit_all, ignore_index=True) if molit_all else pd.DataFrame()

# ── 3. 미매칭 단지별 원인 분류 ──────────────────────────────────
print('\n원인 분석 중...')

REASON_NO_TRADE = '해당동 최근12개월 거래없음'
REASON_EXACT    = '이름 달라 정확매칭'
REASON_FUZZY    = '퍼지 후보 있음'
REASON_NO_MATCH = '동내 거래있으나 이름 불일치'

results = []
for _, row in df_unmatched.iterrows():
    naver_nm = str(row['Naver단지명'])
    dist     = str(row['구'])
    dong     = str(row['동'])
    year     = row.get('건축년도', '')

    # 같은 구+동의 MOLIT 단지
    if df_molit.empty:
        same_dong = pd.DataFrame()
    else:
        same_dong = df_molit[
            (df_molit['구'] == dist) &
            (df_molit['법정동'] == dong)
        ]

    if same_dong.empty:
        reason = REASON_NO_TRADE
        candidates = ''
    else:
        # 점수 계산
        scores = same_dong['아파트명'].apply(lambda m: fuzzy_score(naver_nm, m))
        best_idx = scores.idxmax()
        best_score = scores[best_idx]
        best_molit = same_dong.loc[best_idx, '아파트명']
        best_cnt   = same_dong.loc[best_idx, '거래건수']

        if best_score == 1.0:
            reason = REASON_EXACT
            candidates = best_molit
        elif best_score >= 0.8:
            reason = REASON_FUZZY
            # 상위 후보 최대 3개
            top = same_dong.assign(score=scores).nlargest(3, 'score')
            candidates = ' | '.join(
                f"{r['아파트명']}({r['거래건수']}건)" for _, r in top.iterrows()
            )
        else:
            reason = REASON_NO_MATCH
            # 같은 동 전체 목록
            candidates = ' | '.join(
                f"{r['아파트명']}({r['거래건수']}건)"
                for _, r in same_dong.sort_values('거래건수', ascending=False).head(5).iterrows()
            )

    results.append({
        '단지코드':     row['단지코드'],
        'Naver단지명':  naver_nm,
        '구':           dist,
        '동':           dong,
        '건축년도':     year,
        '원인분류':     reason,
        'MOLIT후보':    candidates,
    })

df_result = pd.DataFrame(results)

# ── 4. 원인 요약 출력 ─────────────────────────────────────────────
print('\n=== 원인 분류 요약 ===')
print(df_result['원인분류'].value_counts().to_string())

# ── 5. Excel 저장 ────────────────────────────────────────────────
out_path = os.path.join(BASE, 'complex_molit_unmatched_analysis.xlsx')
with pd.ExcelWriter(out_path, engine='openpyxl') as writer:
    df_result.to_excel(writer, sheet_name='미매칭원인분석', index=False)

    # 퍼지 후보 있는 것만 별도 시트 (수동 매칭 참고용)
    df_fuzzy = df_result[df_result['원인분류'].isin([REASON_EXACT, REASON_FUZZY])].copy()
    df_fuzzy['MOLIT아파트명(매핑)'] = ''  # 사람이 채울 컬럼
    df_fuzzy.to_excel(writer, sheet_name='후보있음_수동매칭', index=False)

    # MOLIT 전체 단지 참고
    if not df_molit.empty:
        df_molit.to_excel(writer, sheet_name='MOLIT단지목록(12개월)', index=False)

print(f'\n저장: {out_path}')
print(f'  미매칭원인분석: {len(df_result)}행')
print(f'  후보있음_수동매칭: {len(df_fuzzy)}행')
