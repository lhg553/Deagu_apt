"""
MOLIT aptSeq ↔ Naver complexNo 매핑
- Naver Land 법정동별 단지목록 API (rate limit 없음, Playwright 불필요)
- MOLIT 실거래가 아파트명·법정동으로 Naver 단지와 매칭
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import os, re, time, requests, json
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
BASE = os.path.dirname(os.path.abspath(__file__))

# 대구 시군구 cortarNo (Naver 법정동코드 앞 5자리)
DISTRICT_CORTAR = {
    '중구':   '27110',
    '동구':   '27120',
    '서구':   '27140',
    '남구':   '27155',
    '북구':   '27170',
    '수성구': '27200',
    '달서구': '27230',
}

HDR = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://m.land.naver.com/',
}

def fetch_naver_complexes(cortar_no: str) -> list[dict]:
    """Naver Land API로 시군구 전체 단지 목록 조회 (페이징 처리)."""
    url = 'https://m.land.naver.com/complex/ajax/complexList'
    complexes = []
    page = 1
    while True:
        params = {
            'cortarNo': cortar_no,
            'realEstateType': 'APT:ABYG:JGC',  # 아파트+재건축+주상복합
            'tradeType': '',
            'page': page,
            'sameAddressGroup': 'false',
        }
        try:
            r = requests.get(url, params=params, headers=HDR, timeout=10)
            data = r.json()
        except Exception as e:
            print(f'  [오류] {cortar_no} page={page}: {e}')
            break
        items = data.get('body', {}).get('list', []) if isinstance(data.get('body'), dict) else []
        if not items:
            break
        complexes.extend(items)
        total = data.get('body', {}).get('totalCount', 0)
        if len(complexes) >= total:
            break
        page += 1
        time.sleep(0.2)
    return complexes

def normalize(name: str) -> str:
    return re.sub(r'[\s　\(（].*', '', name).strip()  # 괄호 전까지만

def match_name(molit_nm: str, naver_list: list[dict]) -> dict | None:
    """MOLIT 아파트명으로 Naver 단지 퍼지 매칭."""
    norm_m = normalize(molit_nm)
    # 1순위: 정규화 후 정확 일치
    for c in naver_list:
        if normalize(c.get('complexName', '')) == norm_m:
            return c
    # 2순위: Naver명이 MOLIT명 포함 or 역방향
    for c in naver_list:
        n = normalize(c.get('complexName', ''))
        if norm_m in n or n in norm_m:
            return c
    return None

def run(districts=None):
    if districts is None:
        districts = list(DISTRICT_CORTAR.keys())

    all_mappings = []

    for dist in districts:
        cortar = DISTRICT_CORTAR.get(dist)
        if not cortar:
            continue

        # 최신 Excel 파일 찾기
        import glob
        files = sorted(glob.glob(os.path.join(BASE, f'{dist}_부동산_*.xlsx')), reverse=True)
        if not files:
            print(f'[{dist}] Excel 없음 — skip')
            continue
        xlsx = files[0]

        xl = pd.ExcelFile(xlsx)
        molit = xl.parse('실거래가')
        if '구' in molit.columns:
            molit = molit[molit['구'] == dist]
        molit_name_col = '아파트명' if '아파트명' in molit.columns else molit.columns[0]

        print(f'\n[{dist}] Naver 단지목록 조회 중... (cortarNo={cortar})')
        naver_cxs = fetch_naver_complexes(cortar)
        print(f'  → Naver 단지 {len(naver_cxs)}개')

        # MOLIT 고유 단지 목록
        molit_uniq = molit.drop_duplicates(subset=[molit_name_col])

        matched = 0
        unmatched = []
        for _, row in molit_uniq.iterrows():
            nm = str(row[molit_name_col])
            apt_seq = str(row.get('aptSeq', '')) if 'aptSeq' in molit.columns else ''
            dong = str(row.get('법정동', '')) if '법정동' in molit.columns else ''
            cx = match_name(nm, naver_cxs)
            if cx:
                all_mappings.append({
                    '구': dist,
                    'MOLIT_아파트명': nm,
                    'MOLIT_aptSeq': apt_seq,
                    'MOLIT_법정동': dong,
                    'Naver_단지명': cx.get('complexName', ''),
                    'Naver_단지코드': cx.get('complexNo', ''),
                    'Naver_주소': cx.get('address', ''),
                    '세대수': cx.get('totalHouseholdCount', ''),
                })
                matched += 1
            else:
                unmatched.append(nm)

        print(f'  매칭: {matched}/{len(molit_uniq)}')
        if unmatched:
            print(f'  미매칭: {unmatched}')

    if all_mappings:
        df = pd.DataFrame(all_mappings)
        out = os.path.join(BASE, 'molit_naver_mapping.xlsx')
        df.to_excel(out, index=False)
        print(f'\n저장: {out}  ({len(df)}건)')
        # 샘플 출력
        print(df[['구','MOLIT_아파트명','Naver_단지명','Naver_단지코드','MOLIT_aptSeq']].to_string())

if __name__ == '__main__':
    districts = sys.argv[1:] if len(sys.argv) > 1 else None
    run(districts)
