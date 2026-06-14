# -*- coding: utf-8 -*-
"""
수집 결과 정합성 검증: 기준(이전) 엑셀과 신규 엑셀 비교 + 신규 파일 내부 일관성 검사.

사용법:
  python verify_run.py 기준파일.xlsx 신규파일.xlsx
"""
import sys

import pandas as pd


def load(path):
    sheets = pd.read_excel(path, sheet_name=None)
    return sheets


def fill_rate(df, col):
    if col not in df.columns:
        return None
    s = df[col].astype(str).str.strip()
    return (s.ne('') & s.ne('nan')).mean() * 100


def main(old_path, new_path):
    old, new = load(old_path), load(new_path)
    print(f'기준: {old_path}')
    print(f'신규: {new_path}\n')

    issues = []

    # ── 1. 시트 구성 ──────────────────────────────────────────
    print('=== 시트 구성 ===')
    for name in old:
        mark = 'OK' if name in new else '누락!'
        if name not in new:
            issues.append(f'시트 누락: {name}')
        print(f'  {name}: 기준 {len(old[name])}행 → 신규 {len(new[name]) if name in new else "-"}행 [{mark}]')
    for name in new:
        if name not in old:
            print(f'  {name}: 신규에만 존재 ({len(new[name])}행)')
    print()

    so, sn = old.get('호가_단지요약'), new.get('호가_단지요약')
    ao, an = old.get('매물상세'), new.get('매물상세')

    # ── 2. 단지 집합 비교 ─────────────────────────────────────
    if so is not None and sn is not None and '단지코드' in so.columns and '단지코드' in sn.columns:
        cs_o = set(so['단지코드'].astype(str))
        cs_n = set(sn['단지코드'].astype(str))
        only_o, only_n = cs_o - cs_n, cs_n - cs_o
        print('=== 단지 집합 (호가_단지요약) ===')
        print(f'  기준 {len(cs_o)}개 / 신규 {len(cs_n)}개 / 공통 {len(cs_o & cs_n)}개')
        print(f'  기준에만: {len(only_o)}개 / 신규에만: {len(only_n)}개')
        if only_o:
            miss_rate = len(only_o) / len(cs_o) * 100
            names = so[so['단지코드'].astype(str).isin(only_o)]['단지명'].unique()[:10]
            print(f'  기준에만 있는 단지(상위 10): {", ".join(map(str, names))}')
            if miss_rate > 3:
                issues.append(f'단지 누락률 {miss_rate:.1f}% (>3%) — {len(only_o)}개')
        print()

        # 공통 단지 가격 드리프트 (매매_최저 기준, 단지 단위 min)
        common = cs_o & cs_n
        if common and '매매_최저(만원)' in so.columns and '매매_최저(만원)' in sn.columns:
            po = so.groupby(so['단지코드'].astype(str))['매매_최저(만원)'].apply(
                lambda s: pd.to_numeric(s, errors='coerce').min())
            pn = sn.groupby(sn['단지코드'].astype(str))['매매_최저(만원)'].apply(
                lambda s: pd.to_numeric(s, errors='coerce').min())
            both = pd.DataFrame({'o': po, 'n': pn}).dropna()
            both = both[both.index.isin(common)]
            both = both[both['o'] > 0]
            if len(both):
                drift = ((both['n'] - both['o']).abs() / both['o'])
                big = (drift > 0.2).sum()
                print(f'=== 가격 드리프트 (공통 단지 매매_최저) ===')
                print(f'  비교 가능 {len(both)}개 / 20% 초과 변동 {big}개 ({big/len(both)*100:.1f}%)')
                if big / len(both) > 0.05:
                    issues.append(f'가격 20%+ 변동 단지 {big}개 ({big/len(both)*100:.1f}%) — 데이터 오염 의심')
                print()

    # ── 3. 매물상세 비교 ──────────────────────────────────────
    if ao is not None and an is not None:
        print('=== 매물상세 ===')
        for trade in ('매매', '전세', '월세'):
            co = (ao['거래유형'] == trade).sum() if '거래유형' in ao.columns else 0
            cn = (an['거래유형'] == trade).sum() if '거래유형' in an.columns else 0
            delta = (cn - co) / co * 100 if co else 0
            print(f'  {trade}: 기준 {co}건 → 신규 {cn}건 ({delta:+.1f}%)')
        new_cols = set(an.columns) - set(ao.columns)
        if new_cols:
            print(f'  신규 컬럼: {sorted(new_cols)}')
        lost_cols = set(ao.columns) - set(an.columns)
        if lost_cols:
            print(f'  사라진 컬럼: {sorted(lost_cols)}')
            issues.append(f'매물상세 컬럼 사라짐: {sorted(lost_cols)}')
        print()

    # ── 4. 신규 파일 내부 일관성 ───────────────────────────────
    if sn is not None and an is not None:
        print('=== 신규 파일 내부 일관성 ===')
        # 4-1. 요약 매매_매물수 합 == 매물상세 매매 행수 (단지별)
        if all(c in sn.columns for c in ('단지코드', '매매_매물수')) and \
           all(c in an.columns for c in ('단지코드', '거래유형')):
            sum_cnt = sn.groupby(sn['단지코드'].astype(str))['매매_매물수'].apply(
                lambda s: pd.to_numeric(s, errors='coerce').fillna(0).sum())
            art_cnt = an[an['거래유형'] == '매매'].groupby(
                an[an['거래유형'] == '매매']['단지코드'].astype(str)).size()
            merged = pd.DataFrame({'s': sum_cnt, 'a': art_cnt}).fillna(0)
            mismatch = merged[merged['s'] != merged['a']]
            print(f'  단지별 매매_매물수(요약) vs 매물상세 행수: '
                  f'{len(merged)-len(mismatch)}/{len(merged)} 일치')
            if len(mismatch):
                issues.append(f'요약-상세 매물수 불일치 {len(mismatch)}개 단지')
                print(f'  불일치 예시:\n{mismatch.head(5)}')

        # 4-2. 가격 양수 검사
        if '가격(만원)' in an.columns:
            bad = (pd.to_numeric(an['가격(만원)'], errors='coerce').fillna(0) <= 0).sum()
            print(f'  가격 0 이하 매물: {bad}건')
            if bad:
                issues.append(f'가격 0 이하 매물 {bad}건')

        # 4-3. 위치 정보 채움률
        for col in ('지역(구)', '근처지하철', '근처초등학교', '인근대형마트(5km)'):
            r = fill_rate(sn, col)
            if r is not None:
                print(f'  {col} 채움률: {r:.1f}%')
                if col in ('지역(구)', '근처지하철') and r < 95:
                    issues.append(f'{col} 채움률 {r:.1f}% (<95%)')

        # 4-4. 참고 컬럼 존재 확인
        for col in ('중개사명(참고)', '중개사_코멘트(참고)', '태그(참고)'):
            ok = col in an.columns
            print(f'  매물상세 {col}: {"있음" if ok else "없음!"}')
            if not ok:
                issues.append(f'매물상세에 {col} 컬럼 없음')
        print()

    # ── 결과 ─────────────────────────────────────────────────
    print('=' * 50)
    if issues:
        print(f'[검증 실패] 문제 {len(issues)}건:')
        for it in issues:
            print(f'  - {it}')
        sys.exit(1)
    print('[검증 통과] 정합성 문제 없음')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
