"""
Naver 단지코드 ↔ MOLIT 아파트명 매핑 파일 생성 도구.

사용법:
  python make_complex_map.py <excel파일>
      → 자동 매핑 분석, complex_molit_map.json + complex_molit_map_review.xlsx 생성

  python make_complex_map.py <excel파일> --update
      → 기존 매핑 유지하고 신규 단지만 추가

  python make_complex_map.py --from-review
      → complex_molit_map_review.xlsx 의 수동 수정사항을 complex_molit_map.json 에 반영

수동 검토 방법:
  1. complex_molit_map_review.xlsx → '수동검토' 시트 열기
  2. 'MOLIT아파트명(매핑)' 컬럼에 올바른 아파트명 입력 (없으면 비워두기)
  3. python make_complex_map.py --from-review 실행
"""
import argparse, json, os, re, difflib
import pandas as pd


MAP_FILE = os.path.join(os.path.dirname(__file__), 'complex_molit_map.json')
REVIEW_FILE = os.path.join(os.path.dirname(__file__), 'complex_molit_map_review.xlsx')


def _strip_suffix(s: str) -> str:
    """(주상복합), (도시형), (오피스텔) 등 괄호 suffix 제거."""
    return re.sub(r'\s*\([^)]*\)', '', str(s)).strip()


def _normalize(s: str) -> str:
    return str(s).replace(' ', '').strip()


def _extract_ordinal(s: str) -> set:
    """이름에서 차수/동호/단지/지구 번호 추출. ex) '1차' '2차' 'A동' '3단지' '2지구'"""
    found = set()
    found.update(re.findall(r'\d+차', s))
    found.update(re.findall(r'[A-Z]동', s))
    found.update(re.findall(r'\d+지구', s))
    found.update(re.findall(r'\d+블록', s))
    found.update(re.findall(r'\d+단지', s))
    return found


def _ordinal_compatible(a: str, b: str) -> bool:
    """a, b 이름의 차수/동/지구 번호가 충돌하지 않으면 True."""
    ords_a = _extract_ordinal(a)
    ords_b = _extract_ordinal(b)
    if not ords_a or not ords_b:
        return True
    return bool(ords_a & ords_b)


def build_map(fpath: str, existing_map: dict | None = None) -> dict:
    summary = pd.read_excel(fpath, sheet_name='호가_단지요약')
    molit = pd.read_excel(fpath, sheet_name='실거래가')

    # 고유 단지 (단지코드 기준) — 건축년월 포함
    sum_cols = ['단지코드', '단지명', '지역(구)', '지역(동)']
    if '건축년월' in summary.columns:
        sum_cols.append('건축년월')
    complexes = summary[sum_cols].drop_duplicates('단지코드').copy()
    complexes['_name'] = complexes['단지명'].apply(_normalize)
    complexes['_name_s'] = complexes['_name'].apply(_strip_suffix)
    complexes['단지코드'] = complexes['단지코드'].astype(str)
    # 건축년도 (앞 4자리)
    if '건축년월' in complexes.columns:
        complexes['_year'] = pd.to_numeric(complexes['건축년월'], errors='coerce') \
                               .apply(lambda x: int(str(int(x))[:4]) if pd.notna(x) else None)
    else:
        complexes['_year'] = None

    # 실거래가 고유 단지
    molit_cols = ['구', '법정동', '아파트명']
    if '건축년도' in molit.columns:
        molit_cols.append('건축년도')
    molit_u = molit[molit_cols].drop_duplicates().copy()
    molit_u['_name'] = molit_u['아파트명'].apply(_normalize)

    # 구별, 구+동별, 구+건축년도별 lookup dict
    gu_map: dict[str, dict] = {}
    gu_dong_map: dict[tuple, dict] = {}
    gu_year_map: dict[tuple, dict] = {}
    for _, r in molit_u.iterrows():
        gu_map.setdefault(r['구'], {})[r['_name']] = r['아파트명']
        gu_dong_map.setdefault((r['구'], r['법정동']), {})[r['_name']] = r['아파트명']
        if '건축년도' in molit_u.columns and pd.notna(r.get('건축년도')):
            key = (r['구'], int(r['건축년도']))
            gu_year_map.setdefault(key, {})[r['_name']] = r['아파트명']

    result_map = dict(existing_map) if existing_map else {}
    rows = []  # review용

    for _, row in complexes.iterrows():
        code = row['단지코드']
        gu = row['지역(구)']
        dong = row['지역(동)']
        name = row['_name']
        name_s = row['_name_s']
        year = row.get('_year')
        molit_gu = gu_map.get(gu, {})
        molit_dong = gu_dong_map.get((gu, dong), {})
        molit_year = gu_year_map.get((gu, int(year)), {}) if year else {}

        # 기존 매핑 있으면 유지
        if code in result_map:
            rows.append({
                '단지코드': code, 'Naver단지명': row['단지명'],
                '구': gu, '동': dong, '건축년도': year,
                'MOLIT아파트명(매핑)': result_map[code],
                '매칭방식': 'existing',
                '검토필요': '',
            })
            continue

        molit_name = None
        match_type = None

        # 1단계: 정확 매칭 (공백 제거 후)
        if name in molit_gu:
            molit_name = molit_gu[name]
            match_type = 'exact'

        # 2단계: suffix 제거 후 매칭
        elif name_s and name_s in molit_gu:
            molit_name = molit_gu[name_s]
            match_type = 'strip_suffix'

        # 3단계: 같은 구+동 내 fuzzy 매칭 (cutoff 0.78)
        # ordinal 체크는 suffix 제거 전 원본(name)으로 → (A동), (B동) 구분
        elif molit_dong:
            candidates = list(molit_dong.keys())
            matches = difflib.get_close_matches(name_s or name, candidates, n=3, cutoff=0.78)
            for cand in matches:
                if _ordinal_compatible(name, cand):
                    molit_name = molit_dong[cand]
                    match_type = 'fuzzy_dong'
                    break

        # 4단계: 같은 구+건축년도 내 fuzzy 매칭 (cutoff 0.65, 연도로 범위 좁힘)
        if molit_name is None and molit_year:
            candidates = list(molit_year.keys())
            matches = difflib.get_close_matches(name_s or name, candidates, n=3, cutoff=0.65)
            for cand in matches:
                if _ordinal_compatible(name, cand):
                    molit_name = molit_year[cand]
                    match_type = 'fuzzy_year'
                    break

        if molit_name:
            result_map[code] = molit_name

        if match_type in ('fuzzy_dong', 'fuzzy_year'):
            review_flag = '★ 확인필요'
        elif molit_name is None:
            review_flag = '✗ 미매칭'
        else:
            review_flag = ''

        rows.append({
            '단지코드': code, 'Naver단지명': row['단지명'],
            '구': gu, '동': dong, '건축년도': year,
            'MOLIT아파트명(매핑)': molit_name or '',
            '매칭방식': match_type or '',
            '검토필요': review_flag,
        })

    # 검토 Excel 저장
    review_df = pd.DataFrame(rows)
    with pd.ExcelWriter(REVIEW_FILE, engine='openpyxl') as writer:
        review_df.to_excel(writer, index=False, sheet_name='전체매핑')
        manual = review_df[review_df['검토필요'] != ''].copy()
        manual.to_excel(writer, index=False, sheet_name='수동검토')
        unmatched = review_df[review_df['매칭방식'].fillna('') == ''].copy()
        unmatched.to_excel(writer, index=False, sheet_name='미매칭')

    return result_map


def apply_review(review_path: str, existing_map: dict) -> dict:
    """수동검토 시트에서 사용자가 수정한 매핑을 JSON에 반영."""
    df = pd.read_excel(review_path, sheet_name='수동검토')
    updated = dict(existing_map)
    count = 0
    for _, r in df.iterrows():
        code = str(r['단지코드'])
        molit_name = r['MOLIT아파트명(매핑)']
        if pd.notna(molit_name) and str(molit_name).strip():
            new_val = str(molit_name).strip()
            if updated.get(code) != new_val:
                updated[code] = new_val
                count += 1
        else:
            # 빈 값이면 매핑 제거 (미매칭으로 두기)
            if code in updated:
                del updated[code]
                count += 1
    return updated, count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('excel', nargs='?', help='대구통합_부동산_*.xlsx 경로')
    parser.add_argument('--update', action='store_true', help='기존 매핑 유지하고 신규 단지만 추가')
    parser.add_argument('--from-review', action='store_true', help='수동검토 Excel → JSON 업데이트')
    args = parser.parse_args()

    existing = {}
    if os.path.exists(MAP_FILE):
        with open(MAP_FILE, encoding='utf-8') as f:
            existing = json.load(f)

    if args.from_review:
        if not os.path.exists(REVIEW_FILE):
            print(f'검토 파일 없음: {REVIEW_FILE}')
            return
        result, count = apply_review(REVIEW_FILE, existing)
        with open(MAP_FILE, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f'수동 수정 반영: {count}건 업데이트')
        print(f'총 매핑: {len(result)}개')
        return

    if not args.excel:
        parser.error('excel 파일 경로가 필요합니다')

    if args.update:
        print(f'기존 매핑 로드: {len(existing)}개')
        result = build_map(args.excel, existing)
    else:
        result = build_map(args.excel, None)

    with open(MAP_FILE, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'매핑 저장: {MAP_FILE}')
    print(f'매핑된 단지: {len(result)}개')

    review_df = pd.read_excel(REVIEW_FILE, sheet_name='전체매핑')
    print()
    print('[매칭 결과]')
    vc = review_df['매칭방식'].fillna('').value_counts()
    for mt, cnt in vc.items():
        label = {
            'exact': '정확 매칭',
            'strip_suffix': 'suffix 제거 후 매칭',
            'fuzzy_dong': 'fuzzy 매칭-구+동 (★ 검토필요)',
            'fuzzy_year': 'fuzzy 매칭-구+건축년도 (★ 검토필요)',
            'existing': '기존 매핑 유지',
            '': '미매칭 (실거래 없거나 이름 상이)',
        }.get(mt, mt)
        print(f'  {label}: {cnt}개')
    print()
    print(f'검토 파일: {REVIEW_FILE}')
    fuzzy_cnt = review_df['매칭방식'].fillna('').isin(['fuzzy_dong', 'fuzzy_year']).sum()
    unmatch_cnt = (review_df['매칭방식'].fillna('') == '').sum()
    print(f'  └ 수동검토 시트: fuzzy {fuzzy_cnt}개 + 미매칭 {unmatch_cnt}개')
    print()
    print('수동 수정 후: python make_complex_map.py --from-review')


if __name__ == '__main__':
    main()
