# -*- coding: utf-8 -*-
"""여러 구의 부동산 엑셀을 시트별로 병합해 통합 파일 1개 생성.

각 파일의 동일 시트명(호가_단지요약·매물상세·실거래가)을 concat 한다.
지역(구) 컬럼으로 구 구분이 가능하므로 별도 표시 컬럼은 추가하지 않는다.
"""
import pandas as pd

from main import save_excel, HEADER_BLUE, HEADER_ORANGE, HEADER_PURPLE

# 시트명 → (헤더색, 숫자포맷 대상 키워드, 퍼센트 대상 키워드)
_SHEET_STYLE = {
    '호가_단지요약': (HEADER_BLUE,   ['만원', '최저', '최고', '평균', '거래금액'], ['%', '비율']),
    '매물상세':      (HEADER_ORANGE, ['가격(만원)', '전용면적'], []),
    '실거래가':      (HEADER_PURPLE, ['거래금액', '전용면적'], []),
}
_SHEET_ORDER = ['호가_단지요약', '매물상세', '실거래가']

_SUMMARY_COL_ORDER = [
    '지역(구)', '지역(동)', '지역', '단지명', '건축년월', '총세대수', '전용평형(평)',
    '매매_최저(만원)', '매매_최고(만원)', '매매_평균(만원)', '매매_매물수',
    '전세_최저(만원)', '전세_최고(만원)', '전세_평균(만원)', '전세_매물수',
    '월세_매물수', '5억이하매물수(호가)',
    '단지코드', '위도', '경도',
    '근처지하철', '지하철직선도보(분)',
    '근처초등학교', '초등학교직선거리(m/분)',
    '근처중학교', '중학교직선거리(m/분)', '근처고등학교', '고등학교직선거리(m/분)',
    '인근대형마트(5km)', '인근공원(1km)', '인근어린이집(1km)',
]


def _reorder_summary(df: pd.DataFrame) -> pd.DataFrame:
    fixed = [c for c in _SUMMARY_COL_ORDER if c in df.columns]
    extra = [c for c in df.columns if c not in fixed]
    return df[fixed + extra]


def combine_files(paths, out_path):
    """paths의 엑셀들을 시트별로 병합해 out_path로 저장. 저장 경로 반환(없으면 None)."""
    bucket: dict = {}  # sheet_name -> [df, ...]
    for p in paths:
        try:
            sheets = pd.read_excel(p, sheet_name=None)
        except Exception as e:
            print(f'  [병합 경고] {p} 읽기 실패: {e}')
            continue
        for name, df in sheets.items():
            if df is not None and not df.empty:
                bucket.setdefault(name, []).append(df)

    if not bucket:
        print('  [병합] 병합할 데이터가 없습니다.')
        return None

    # 시트 순서: 알려진 순서 우선, 나머지는 뒤에
    names = [n for n in _SHEET_ORDER if n in bucket] + \
            [n for n in bucket if n not in _SHEET_ORDER]

    sheet_data = {}
    for name in names:
        df = pd.concat(bucket[name], ignore_index=True)
        if name == '호가_단지요약':
            df = _reorder_summary(df)
        fill, num_cols, pct_cols = _SHEET_STYLE.get(name, (HEADER_BLUE, [], []))
        sheet_data[name] = (df, fill, num_cols, pct_cols)
        print(f'  [병합] {name}: {len(df):,}행')

    save_excel(sheet_data, out_path)
    return out_path


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print('사용법: python combine.py 출력.xlsx 구1.xlsx 구2.xlsx ...')
        sys.exit(1)
    combine_files(sys.argv[2:], sys.argv[1])
