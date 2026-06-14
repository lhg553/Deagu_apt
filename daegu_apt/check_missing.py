"""
실거래가(MOLIT) vs 호가_단지요약(Naver) 교차검증 스크립트
사용법:
  python check_missing.py <구이름> <Excel파일경로>
  예) python check_missing.py 중구 중구_부동산_20260611_204635.xlsx
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import os, requests, json, glob
import pandas as pd
from dotenv import load_dotenv
from shapely.geometry import Point, shape

load_dotenv()
KAKAO_KEY = os.getenv('KAKAO_API_KEY', '')
BASE = os.path.dirname(os.path.abspath(__file__))

def find_latest_excel(district):
    pattern = os.path.join(BASE, f'{district}_부동산_*.xlsx')
    files = sorted(glob.glob(pattern), reverse=True)
    return files[0] if files else None

def kakao_search(name, district, dong=None, road=None):
    """정밀 검색: 구+법정동+도로명+단지명. 결과 없으면 None 반환."""
    url = 'https://dapi.kakao.com/v2/local/search/keyword.json'
    headers = {'Authorization': f'KakaoAK {KAKAO_KEY}'}
    parts = ['대구', district]
    if dong:
        parts.append(dong)
    if road:
        parts.append(road)
    parts.append(name)
    params = {'query': ' '.join(parts), 'size': 1}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=5)
        docs = r.json().get('documents', [])
        if docs:
            d = docs[0]
            return float(d['y']), float(d['x']), d['place_name'], d['address_name']
    except Exception:
        pass
    return None, None, None, None


def kakao_search_candidates(name, district):
    """넓은 검색(구+단지명만) → 후보 목록 반환. 정밀 검색 실패 시 fallback."""
    url = 'https://dapi.kakao.com/v2/local/search/keyword.json'
    headers = {'Authorization': f'KakaoAK {KAKAO_KEY}'}
    params = {'query': f'대구 {district} {name}', 'size': 5}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=5)
        docs = r.json().get('documents', [])
        return [(float(d['y']), float(d['x']), d['place_name'], d['address_name'])
                for d in docs]
    except Exception:
        return []


def _pick_best(candidates, poly, molit_year, summary_df):
    """폴리곤 필터 → MOLIT 건축년도 + 호가 건축년월로 최적 후보 선택."""
    from math import radians, sin, cos, sqrt, atan2

    def haversine(lat1, lon1, lat2, lon2):
        R = 6371000
        φ1, φ2 = radians(lat1), radians(lat2)
        Δφ, Δλ = radians(lat2 - lat1), radians(lon2 - lon1)
        a = sin(Δφ/2)**2 + cos(φ1)*cos(φ2)*sin(Δλ/2)**2
        return R * 2 * atan2(sqrt(a), sqrt(1 - a))

    # 1단계: 폴리곤 필터
    in_poly = [c for c in candidates
               if poly and poly.buffer(0.0005).contains(Point(c[1], c[0]))]
    if not in_poly:
        return None
    if len(in_poly) == 1:
        return in_poly[0]

    # 2단계: 여러 개 남으면 MOLIT 건축년도 vs 호가 건축년월로 매칭
    if molit_year and not summary_df.empty and '위도' in summary_df.columns:
        for lat, lon, place, addr in in_poly:
            for _, row in summary_df.iterrows():
                if pd.isna(row.get('위도')) or pd.isna(row.get('경도')):
                    continue
                if haversine(lat, lon, float(row['위도']), float(row['경도'])) > 300:
                    continue
                bym = str(row.get('건축년월', ''))
                if bym[:4] == str(molit_year):
                    return (lat, lon, place, addr)

    # 건축년도 매칭도 실패 → 결과 없음 처리
    return None

def _normalize(name: str) -> str:
    """비교용 정규화: (주상복합), (아파트) 등 접미사 제거 + 공백 제거."""
    import re
    return re.sub(r'[\s　]|\(주상복합\)|\(아파트\)', '', name).strip()

def _fuzzy_match(molit_name: str, summary_names: set) -> str | None:
    """MOLIT 단지명이 호가_단지요약에 있으면 매칭된 호가 이름 반환, 없으면 None."""
    norm_molit = _normalize(molit_name)
    for sname in summary_names:
        norm_s = _normalize(sname)
        # 정규화 후 동일하거나 한쪽이 다른 쪽을 포함
        if norm_molit == norm_s or norm_molit in norm_s or norm_s in norm_molit:
            return sname
    return None

def run(district, xlsx_path):
    print(f'\n{"="*60}')
    print(f'  교차검증: {district}  ({os.path.basename(xlsx_path)})')
    print(f'{"="*60}')

    xl = pd.ExcelFile(xlsx_path)
    summary = xl.parse('호가_단지요약')
    molit = xl.parse('실거래가')

    if '구' in molit.columns:
        molit_d = molit[molit['구'] == district]
    else:
        molit_d = molit

    molit_name_col = '아파트명' if '아파트명' in molit_d.columns else molit_d.columns[0]
    summary_names = set(summary['단지명'].dropna().unique())
    molit_names = set(molit_d[molit_name_col].dropna().unique())

    # 이름 불일치 vs 진짜 누락 분류
    exact_missing = sorted(molit_names - summary_names)
    name_mismatch = []   # 호가에 있지만 이름이 다른 것
    truly_missing = []   # 퍼지 매칭도 실패 (현재 매물 없거나 Naver 미등록)

    for name in exact_missing:
        matched = _fuzzy_match(name, summary_names)
        if matched:
            name_mismatch.append((name, matched))
        else:
            truly_missing.append(name)

    matched_count = len(molit_names) - len(exact_missing) + len(name_mismatch)
    print(f'  실거래가 단지 수 ({district}):   {len(molit_names)}')
    print(f'  호가_단지요약 단지 수:           {len(summary_names)}')
    print(f'  이름 정확 일치:                 {len(molit_names) - len(exact_missing)}')
    print(f'  이름 불일치(퍼지 매칭):          {len(name_mismatch)}  ← Naver가 (주상복합) 등 접미사 추가')
    print(f'  실질 누락(매물 없음 or 미수집):   {len(truly_missing)}')

    if name_mismatch:
        print(f'\n  [이름 불일치 — 실제 수집됨]')
        for molit_n, naver_n in name_mismatch:
            print(f'    MOLIT: {molit_n}  →  Naver: {naver_n}')

    if not truly_missing:
        print(f'\n  → 실질 누락 없음. 전 단지 수집 완료.')
        return

    # 폴리곤 로드
    poly_path = os.path.join(BASE, 'daegu_boundaries.json')
    poly = None
    if os.path.isfile(poly_path):
        with open(poly_path, encoding='utf-8') as f:
            bdry = json.load(f)
        poly = shape(bdry[district]) if district in bdry else None

    print(f'\n  [실질 누락 단지] — 현재 Naver 매물 없거나 미수집')
    print(f'  {"단지명":<32} {"건수":>4}  {"좌표":^26}  {"폴리곤"}')
    print(f'  {"-"*72}')
    for name in truly_missing:
        rows = molit_d[molit_d[molit_name_col] == name]
        cnt = len(rows)
        molit_year = int(rows['건축년도'].iloc[0]) if '건축년도' in rows.columns and not rows.empty else None
        dong = str(rows['법정동'].iloc[0]) if '법정동' in rows.columns and not rows.empty else None
        road_val = rows['도로명'].iloc[0] if '도로명' in rows.columns and not rows.empty else None
        road = str(road_val) if road_val and str(road_val) not in ('nan', 'None', '') else None

        # 1차: 정밀 검색 (구+법정동+도로명+단지명)
        lat, lon, place, addr = kakao_search(name, district, dong=dong, road=road)
        if lat is not None:
            in_poly = poly.buffer(0.0005).contains(Point(lon, lat)) if poly else '?'
            flag = '' if in_poly else ' ← 폴리곤 밖!'
            year_tag = f'[건축{molit_year}]' if molit_year else ''
            print(f'  {name:<32} {cnt:>4}건  ({lat:.5f},{lon:.5f})  {str(in_poly)}{flag}  {year_tag}')
            continue

        # 2차: 넓은 검색 fallback (구+단지명) → 폴리곤+건축년도 매칭
        candidates = kakao_search_candidates(name, district)
        best = _pick_best(candidates, poly, molit_year, summary)
        if best is None:
            print(f'  {name:<32} {cnt:>4}건  카카오 검색 실패')
            continue
        lat, lon, place, addr = best
        in_poly = poly.buffer(0.0005).contains(Point(lon, lat)) if poly else '?'
        flag = '' if in_poly else ' ← 폴리곤 밖!'
        year_tag = f'[건축{molit_year}]' if molit_year else ''
        print(f'  {name:<32} {cnt:>4}건  ({lat:.5f},{lon:.5f})  {str(in_poly)}{flag}  {year_tag} [넓은검색]')

    print(f'\n  [결론] {district}: 실질 누락 {len(truly_missing)}개')
    print(f'         → 해당 단지는 현재 Naver 매물이 없어 호가 수집 불가 (정상)')

if __name__ == '__main__':
    if len(sys.argv) >= 3:
        district_arg = sys.argv[1]
        xlsx_arg = sys.argv[2]
    elif len(sys.argv) == 2:
        district_arg = sys.argv[1]
        xlsx_arg = find_latest_excel(district_arg)
        if not xlsx_arg:
            print(f'[오류] {district_arg} 최신 Excel 파일을 찾을 수 없음')
            sys.exit(1)
    else:
        print('사용법: python check_missing.py <구이름> [Excel경로]')
        sys.exit(1)

    run(district_arg, xlsx_arg)
