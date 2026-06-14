"""
대구 아파트 부동산 데이터 수집기

시트 구성:
  [1] 호가_단지요약   - 단지×평형 1행씩 매매/전세/월세 최저·최고·평균·매물수 + 지하철·학교
  [2] 매물상세        - 개별 매물 가격 목록
  [3] 실거래가        - 국토교통부 실거래가 (molit-key 필요)

사용법:
  python main.py --district 수성구
  python main.py --district all --molit-key YOUR_KEY
  python main.py --district 달서구 --months 6 --molit-key YOUR_KEY
"""
import argparse
import logging
import os
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.WARNING,
    format='[%(levelname)s] %(message)s',
)

# .env 파일 로드 (python-dotenv 있을 때만)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter


# ── Excel 스타일 ───────────────────────────────────────────────────

HEADER_BLUE   = PatternFill('solid', fgColor='1F497D')
HEADER_ORANGE = PatternFill('solid', fgColor='974706')
HEADER_PURPLE = PatternFill('solid', fgColor='403151')
WHITE_FONT    = Font(color='FFFFFF', bold=True, size=10)


def _style_sheet(ws, header_fill=None, number_cols=None, pct_cols=None):
    if header_fill is None:
        header_fill = HEADER_BLUE
    for cell in ws[1]:
        cell.fill      = header_fill
        cell.font      = WHITE_FONT
        cell.alignment = Alignment(horizontal='center', vertical='center')

    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len    = max((len(str(c.value or '')) for c in col), default=8)
        ws.column_dimensions[col_letter].width = min(max_len + 4, 28)

    if number_cols:
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                col_name = ws.cell(1, cell.column).value or ''
                if any(k in col_name for k in number_cols):
                    cell.number_format = '#,##0'
                    cell.alignment     = Alignment(horizontal='right')

    if pct_cols:
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                col_name = ws.cell(1, cell.column).value or ''
                if any(k in col_name for k in pct_cols):
                    cell.number_format = '0.0"%"'

    ws.freeze_panes = 'A2'
    ws.row_dimensions[1].height = 22


def save_excel(sheet_data: dict, path: str):
    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        for sheet_name, (df, fill, num_cols, pct_cols) in sheet_data.items():
            if df is None or df.empty:
                continue
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            ws = writer.sheets[sheet_name]
            _style_sheet(ws, header_fill=fill,
                         number_cols=num_cols, pct_cols=pct_cols)

    print(f'저장 완료 → {path}')


# ── 헬퍼: 지역명을 DataFrame 첫 컬럼으로 삽입 ─────────────────────

def _add_district_col(df: pd.DataFrame, district: str) -> pd.DataFrame:
    """kakao 역지오코딩이 없을 때 fallback으로 --district 인수를 지역 컬럼에 삽입."""
    if df.empty or district == 'all' or '지역(구)' in df.columns:
        return df
    out = df.copy()
    out.insert(0, '지역', district)
    return out


def _load_complex_map() -> dict:
    """complex_molit_map.json 로드. 단지코드(str) → MOLIT 아파트명(공백제거).

    탐색 순서:
    1. EXE 옆 (사용자 수정본 우선)
    2. PyInstaller _MEIPASS (번들 기본값)
    3. 스크립트 디렉터리 (개발 환경)
    """
    import json, sys as _sys
    fname = 'complex_molit_map.json'
    candidates = []
    if getattr(_sys, 'frozen', False):
        candidates.append(os.path.join(os.path.dirname(_sys.executable), fname))
    meipass = getattr(_sys, '_MEIPASS', None)
    if meipass:
        candidates.append(os.path.join(meipass, fname))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), fname))

    for path in candidates:
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                raw = json.load(f)
            return {str(k): v.replace(' ', '') for k, v in raw.items() if v}
    return {}


def _add_turnover(summary_df: pd.DataFrame, molit_df: pd.DataFrame, months: int,
                  silv_df: pd.DataFrame = None) -> pd.DataFrame:
    """MOLIT 실거래 건수 / 총세대수 → 회전률 컬럼 추가.
    silv_df(분양권) 있으면 분양권거래수 컬럼 + 회전율주의 컬럼도 추가.
    """
    if molit_df.empty or '아파트명' not in molit_df.columns or '총세대수' not in summary_df.columns:
        return summary_df

    # 해제된 거래 제외, 이름 정규화(공백 제거)
    df = molit_df[molit_df['해제여부'].fillna('') == ''].copy() if '해제여부' in molit_df.columns else molit_df.copy()
    df['_name'] = df['아파트명'].str.replace(' ', '', regex=False)

    # 구 컬럼 있으면 (단지명+구) 기준으로 집계, 없으면 단지명만
    gu_col = next((c for c in ('구', '지역(구)', '지역') if c in df.columns), None)
    if gu_col:
        cnt = df.groupby(['_name', gu_col]).size().reset_index(name='_cnt')
        cnt.rename(columns={gu_col: '_gu'}, inplace=True)
    else:
        cnt = df.groupby('_name').size().reset_index(name='_cnt')

    # 단지코드 → MOLIT 아파트명 매핑 (complex_molit_map.json)
    cmap = _load_complex_map()

    out = summary_df.copy()
    # 매핑 파일에 있으면 해당 MOLIT 이름 사용, 없으면 Naver 단지명 정규화 fallback
    if cmap and '단지코드' in out.columns:
        out['_name'] = out['단지코드'].astype(str).map(cmap).fillna(
            out['단지명'].str.replace(' ', '', regex=False)
        )
    else:
        out['_name'] = out['단지명'].str.replace(' ', '', regex=False)

    gu_col_s = next((c for c in ('지역(구)', '지역') if c in out.columns), None)
    if gu_col and gu_col_s:
        out['_gu'] = out[gu_col_s]
        out = out.merge(cnt, on=['_name', '_gu'], how='left').drop(columns=['_gu'])
    else:
        out = out.merge(cnt, on='_name', how='left')

    total = pd.to_numeric(out['총세대수'], errors='coerce')
    out[f'회전률({months}개월%)'] = (out['_cnt'] / total * 100).round(1)
    out = out.drop(columns=['_name', '_cnt'], errors='ignore')

    # ── 분양권 거래수 + 회전율 주의 컬럼 ──────────────────────────
    if silv_df is not None and not silv_df.empty and '아파트명' in silv_df.columns:
        sdf = silv_df[silv_df['해제여부'].fillna('') == ''].copy() if '해제여부' in silv_df.columns else silv_df.copy()
        sdf['_name'] = sdf['아파트명'].str.replace(' ', '', regex=False)
        gu_col_s2 = next((c for c in ('구', '지역(구)', '지역') if c in sdf.columns), None)
        if gu_col_s2:
            scnt = sdf.groupby(['_name', gu_col_s2]).size().reset_index(name='_scnt')
            scnt.rename(columns={gu_col_s2: '_gu'}, inplace=True)
        else:
            scnt = sdf.groupby('_name').size().reset_index(name='_scnt')

        if cmap and '단지코드' in out.columns:
            out['_name'] = out['단지코드'].astype(str).map(cmap).fillna(
                out['단지명'].str.replace(' ', '', regex=False)
            )
        else:
            out['_name'] = out['단지명'].str.replace(' ', '', regex=False)

        if gu_col_s2 and gu_col_s:
            out['_gu'] = out[gu_col_s]
            out = out.merge(scnt, on=['_name', '_gu'], how='left').drop(columns=['_gu'])
        else:
            out = out.merge(scnt, on='_name', how='left')

        out[f'분양권거래수({months}개월)'] = out['_scnt'].fillna(0).astype(int)
        out['⚠️회전율주의'] = out[f'분양권거래수({months}개월)'].apply(
            lambda x: '분양권포함-회전율과대평가주의' if x > 0 else ''
        )
        out = out.drop(columns=['_name', '_scnt'], errors='ignore')

    return out


def _build_pyeong_summary(summary_df: pd.DataFrame, articles_df: pd.DataFrame) -> pd.DataFrame:
    """단지 수준 summary + 매물 상세 articles → 단지×평형 1행씩 생성.

    단지 공통 정보(위치·학교·지하철 등)는 각 평형 행에 복사.
    평형별 매매/전세 통계는 articles_df에서 집계.
    articles 없는 단지는 summary_df 단지 수준 통계를 그대로 사용.
    """
    if summary_df.empty:
        return summary_df

    COMPLEX_COLS = [
        '단지명', '건축년월', '총세대수', '단지코드', '위도', '경도',
        '근처지하철', '지하철직선도보(분)', '근처초등학교', '초등학교직선거리(m/분)',
        '근처중학교', '중학교직선거리(m/분)', '근처고등학교', '고등학교직선거리(m/분)',
        '인근대형마트(5km)', '인근공원(1km)', '인근어린이집(1km)',
        '지역(구)', '지역(동)', '지역',
    ]

    has_arts = not articles_df.empty and '전용평형' in articles_df.columns
    if has_arts:
        _dedup = ['단지코드', '거래유형', '가격(만원)', '층', '방향']
        art_stats = articles_df.drop_duplicates(
            subset=[k for k in _dedup if k in articles_df.columns], keep='first'
        )
    else:
        art_stats = pd.DataFrame()

    def _price_stats(sub):
        prices = pd.to_numeric(sub['가격(만원)'], errors='coerce').dropna()
        if len(prices) == 0:
            return None, None, None, 0
        return int(prices.min()), int(prices.max()), int(prices.mean().round()), len(prices)

    rows = []
    for _, cplx in summary_df.iterrows():
        cid = cplx.get('단지코드', '')

        if has_arts and cid:
            cid_all   = articles_df[articles_df['단지코드'] == cid]
            cid_stats = art_stats[art_stats['단지코드'] == cid]
            pyeong_vals = sorted(
                {p for p in cid_all['전용평형'] if p and str(p).strip() not in ('', 'nan')},
                key=lambda x: int(x) if str(x).isdigit() else 0
            )
        else:
            cid_all = cid_stats = pd.DataFrame()
            pyeong_vals = []

        def _make_row(pyeong):
            base = {}
            for c in COMPLEX_COLS:
                if c in cplx.index:
                    base[c] = cplx[c]
            base['전용평형(평)'] = pyeong if pyeong is not None else ''

            if has_arts and cid and pyeong is not None:
                deal  = cid_stats[(cid_stats['거래유형'] == '매매') & (cid_stats['전용평형'] == pyeong)]
                lease = cid_stats[(cid_stats['거래유형'] == '전세') & (cid_stats['전용평형'] == pyeong)]
                rent  = cid_stats[(cid_stats['거래유형'] == '월세') & (cid_stats['전용평형'] == pyeong)]

                mn_d, mx_d, avg_d, cnt_d = _price_stats(deal)
                mn_l, mx_l, avg_l, cnt_l = _price_stats(lease)
                _, _, _, cnt_r = _price_stats(rent)

                base['매매_최저(만원)'] = mn_d or ''
                base['매매_최고(만원)'] = mx_d or ''
                base['매매_평균(만원)'] = avg_d or ''
                base['매매_매물수']     = cnt_d
                base['전세_최저(만원)'] = mn_l or ''
                base['전세_최고(만원)'] = mx_l or ''
                base['전세_평균(만원)'] = avg_l or ''
                base['전세_매물수']     = cnt_l
                base['월세_매물수']     = cnt_r

                didi = deal[deal['가격(만원)'] <= 50000]
                if '전용면적㎡' in didi.columns:
                    didi = didi[pd.to_numeric(didi['전용면적㎡'], errors='coerce').fillna(999) <= 85]
                base['5억이하매물수(호가)'] = len(didi) if len(didi) > 0 else ''
            else:
                for c in ['매매_최저(만원)', '매매_최고(만원)', '매매_평균(만원)', '매매_매물수',
                          '전세_최저(만원)', '전세_최고(만원)', '전세_평균(만원)', '전세_매물수',
                          '월세_매물수', '5억이하매물수(호가)']:
                    if c in cplx.index:
                        base[c] = cplx[c]
            return base

        if not pyeong_vals:
            rows.append(_make_row(None))
        else:
            for p in pyeong_vals:
                rows.append(_make_row(p))

    result = pd.DataFrame(rows)

    lead_cols = [c for c in ('지역(구)', '지역(동)', '지역') if c in result.columns]
    ordered = (
        lead_cols +
        ['단지명', '건축년월', '총세대수', '전용평형(평)',
         '매매_최저(만원)', '매매_최고(만원)', '매매_평균(만원)', '매매_매물수',
         '전세_최저(만원)', '전세_최고(만원)', '전세_평균(만원)', '전세_매물수',
         '월세_매물수', '5억이하매물수(호가)',
         '단지코드', '위도', '경도',
         '근처지하철', '지하철직선도보(분)',
         '근처초등학교', '초등학교직선거리(m/분)',
         '근처중학교', '중학교직선거리(m/분)', '근처고등학교', '고등학교직선거리(m/분)',
         '인근대형마트(5km)', '인근공원(1km)', '인근어린이집(1km)']
    )
    final_cols = [c for c in ordered if c in result.columns]
    extra_cols = [c for c in result.columns if c not in final_cols]
    return result[final_cols + extra_cols]


# ── 메인 로직 ─────────────────────────────────────────────────────

def run(args):
    """수집 실행 (GUI·CLI 공용). args는 argparse.Namespace 또는 동등한 객체."""

    # ── 파일명: 구 지정 시 파일명에 명시 ──────────────────────────
    ts          = datetime.now().strftime('%Y%m%d_%H%M%S')
    region_tag  = args.district if args.district != 'all' else '대구전체'
    output_path = args.output or f'{region_tag}_부동산_{ts}.xlsx'

    NUM_COLS = ['만원', '최저', '최고', '평균', '거래금액']
    PCT_COLS = ['%', '비율']

    sheets: dict = {}
    summary_df = pd.DataFrame()  # 회전률 계산을 위해 scope 유지

    # ── [1][2][3] 네이버 호가 ──────────────────────────────────────
    if args.source in ('both', 'naver'):
        print(f'=== [네이버 부동산] {region_tag} 호가 수집 ===')
        from naver_scraper import NaverLandScraper
        summary_df, articles_df, naver_meta = NaverLandScraper().collect(
            district=args.district,
            test_limit=10 if args.test else 0,
        )

        if naver_meta.get('rate_limited'):
            print('[중단] Rate limit 감지 — 수집 불완전, rate_limit 파일로 저장 후 종료합니다.')
            rl_path = output_path.replace('.xlsx', '_rate_limit.xlsx')
            if not summary_df.empty:
                from location_enricher import enrich_dataframe
                summary_df = enrich_dataframe(summary_df, kakao_key=args.kakao_key)
                summary_df = _add_district_col(summary_df, args.district)
                rl_pyeong = _build_pyeong_summary(summary_df, articles_df)
                save_excel({
                    '호가_단지요약(미완)': (rl_pyeong, HEADER_BLUE, NUM_COLS, PCT_COLS),
                    '매물상세(미완)': (articles_df, HEADER_ORANGE, ['가격(만원)', '전용면적'], []),
                }, rl_path)
                print(f'[저장] {rl_path}')
            import sys; sys.exit(2)

        if not summary_df.empty:
            print(f'  단지 {len(summary_df)}개 수집')

            # ── 위치 정보 보강 (지하철·학교) — 단지 수준에서만 수행 ─────
            from location_enricher import enrich_dataframe
            summary_df = enrich_dataframe(summary_df, kakao_key=args.kakao_key)

            # ── 지역명 컬럼 삽입 ───────────────────────────────────
            summary_df = _add_district_col(summary_df, args.district)

            # ── 평형별 요약 생성 ────────────────────────────────────
            pyeong_summary_df = _build_pyeong_summary(summary_df, articles_df)

            # [1] 호가_단지요약 (평형별 1행)
            sum_sorted = pyeong_summary_df.sort_values(
                ['단지명', '전용평형(평)'],
                ascending=[True, True],
                na_position='last'
            )
            sheets['호가_단지요약'] = (sum_sorted, HEADER_BLUE, NUM_COLS, PCT_COLS)

        # [3] 매물상세
        if not articles_df.empty:
            art = _add_district_col(
                articles_df.sort_values(['거래유형', '단지명', '가격(만원)']),
                args.district
            )
            print(f'  매물상세: {len(art)}건')
            sheets['매물상세'] = (art, HEADER_ORANGE, ['가격(만원)', '전용면적'], [])

    # ── [4] 국토교통부 실거래가 ────────────────────────────────────
    if args.source in ('both', 'molit'):
        if not args.molit_key:
            print('\n[안내] --molit-key 또는 환경변수 MOLIT_API_KEY를 설정하면')
            print('       실거래가 시트가 추가됩니다.')
            print('       발급: https://www.data.go.kr → "아파트매매 실거래가 상세자료"')
        else:
            molit_months = 1 if args.test else args.months

            from molit_scraper import MolitScraper, LAWD_NAME
            _name_to_lawd = {v: k for k, v in LAWD_NAME.items()}
            if args.district != 'all':
                # 특정 구 지정 시 해당 구만 조회
                lawd_codes = [_name_to_lawd[args.district]] if args.district in _name_to_lawd else None
                _label = args.district
            else:
                # 전체 수집 시 Naver 결과에서 발견된 구만 조회
                _gu_col = next((c for c in ('지역(구)', '지역') if c in summary_df.columns), None)
                if _gu_col and not summary_df.empty:
                    _found_gus = summary_df[_gu_col].dropna().unique()
                    lawd_codes = [_name_to_lawd[g] for g in _found_gus if g in _name_to_lawd]
                    _label = '+'.join(sorted({LAWD_NAME[c] for c in lawd_codes}))
                else:
                    lawd_codes = None
                    _label = region_tag

            scraper = MolitScraper(args.molit_key)
            suffix = ' (TEST: 1개월)' if args.test else ''

            print(f'\n=== [국토교통부] {_label} 실거래가 수집{suffix} ===')
            molit_df = scraper.collect(
                district=args.district, months=molit_months, lawd_codes=lawd_codes
            )
            if not molit_df.empty:
                molit_df.insert(0, '지역', '대구')
                molit_sorted = molit_df.sort_values(
                    ['거래년도', '거래월', '거래일'], ascending=False
                )
                print(f'  실거래가: {len(molit_sorted)}건')
                sheets['실거래가'] = (molit_sorted, HEADER_PURPLE,
                                     ['거래금액', '전용면적'], [])

            print(f'\n=== [국토교통부] {_label} 분양권·입주권 수집{suffix} ===')
            silv_df = scraper.collect_silv(
                district=args.district, months=molit_months, lawd_codes=lawd_codes
            )
            if not silv_df.empty:
                silv_df.insert(0, '지역', '대구')
                silv_sorted = silv_df.sort_values(
                    ['거래년도', '거래월', '거래일'], ascending=False
                )
                print(f'  분양권·입주권: {len(silv_sorted)}건')
                sheets['분양권실거래'] = (silv_sorted, HEADER_PURPLE,
                                        ['거래금액', '전용면적'], [])
            else:
                silv_df = pd.DataFrame()

            # 회전률 계산 → 호가_단지요약 시트 갱신
            if '호가_단지요약' in sheets and not molit_df.empty:
                cur_df  = sheets['호가_단지요약'][0]
                updated = _add_turnover(cur_df, molit_df, args.months,
                                        silv_df=silv_df if not silv_df.empty else None)
                re_sorted = updated.sort_values(
                    ['단지명', '전용평형(평)'] if '전용평형(평)' in updated.columns else ['단지명'],
                    ascending=True, na_position='last'
                )
                sheets['호가_단지요약'] = (re_sorted, HEADER_BLUE, NUM_COLS, PCT_COLS)
                print(f'  회전률({args.months}개월) 계산 완료')

    # ── 저장 ──────────────────────────────────────────────────────
    if not sheets:
        print('\n수집된 데이터가 없습니다.')
        sys.exit(1)

    save_excel(sheets, output_path)

    print('\n--- 수집 요약 ---')
    for name, (df, *_) in sheets.items():
        if df is not None and not df.empty:
            print(f'  [{name}] {len(df):,}건')
    print(f'  파일: {os.path.abspath(output_path)}')


# ── CLI 진입점 ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='대구 아파트 부동산 수집기',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--district', default='all',
                        choices=['all', '중구', '동구', '서구', '남구', '북구',
                                 '수성구', '달서구', '달성군'],
                        help='수집 지역 (기본: all)')
    parser.add_argument('--source', default='both',
                        choices=['both', 'naver', 'molit'],
                        help='데이터 소스 (기본: both)')
    parser.add_argument('--months', type=int, default=12,
                        help='실거래가 최근 N개월 (기본: 12)')
    parser.add_argument('--molit-key', default=os.environ.get('MOLIT_API_KEY', ''),
                        help='국토교통부 API 키 (data.go.kr 발급)')
    parser.add_argument('--kakao-key', default=os.environ.get('KAKAO_API_KEY', ''),
                        help='카카오 REST API 키 (지하철·학교 위치 조회)')
    parser.add_argument('--output', default='',
                        help='출력 파일명 (기본: {지역}_부동산_YYYYMMDD.xlsx)')
    parser.add_argument('--test', action='store_true',
                        help='테스트 모드: 매물 많은 순 10개 단지만 수집')
    run(parser.parse_args())


if __name__ == '__main__':
    main()
