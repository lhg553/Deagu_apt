# -*- coding: utf-8 -*-
"""전체 8개 구 수집 — 2개 구 동시 실행(별도 프로세스) + 구별 시간 측정.
수집 결과는 대구부동산_수집결과_YYYYMMDD/ 폴더에 저장.
완료 후 자동으로 통합본 + 엑셀_데이터_명세.md 복사.
"""
import time
import subprocess
import sys
import os
import shutil
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 동시 실행 시 부하 분산: 큰 구와 작은 구가 짝이 되도록 배치
DISTRICTS = ['달서구', '중구', '동구', '서구', '수성구', '남구', '북구', '달성군']
MAX_CONCURRENT = 2

PY = sys.executable
BASE = os.path.dirname(os.path.abspath(__file__))


def run_one(gu, out_dir):
    t0 = time.time()
    ts = datetime.now().strftime('%H%M%S')
    out = os.path.join(out_dir, f'{gu}_부동산_{datetime.now().strftime("%Y%m%d")}_{ts}.xlsx')
    log = os.path.join(out_dir, f'all_{gu}.log')
    with open(log, 'w', encoding='utf-8') as f:
        subprocess.run(
            [PY, '-u', '-X', 'utf8', 'main.py', '--district', gu, '--output', out],
            stdout=f, stderr=subprocess.STDOUT,
            env={**os.environ, 'PYTHONUNBUFFERED': '1'},
        )
    return gu, time.time() - t0, out


if __name__ == '__main__':
    date_str = datetime.now().strftime('%Y%m%d')
    out_dir = os.path.join(BASE, f'대구부동산_수집결과_{date_str}')
    os.makedirs(out_dir, exist_ok=True)

    print(f'전체 수집 시작: {", ".join(DISTRICTS)} (동시 {MAX_CONCURRENT}개)', flush=True)
    print(f'저장 폴더: {out_dir}', flush=True)
    grand0 = time.time()
    results = {}
    out_files = []

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as ex:
        futs = {ex.submit(run_one, gu, out_dir): gu for gu in DISTRICTS}
        for fut in as_completed(futs):
            gu, el, out = fut.result()
            results[gu] = el
            out_files.append(out)
            print(f'[완료] {gu}: {el:.0f}초 ({el/60:.1f}분)', flush=True)

    grand = time.time() - grand0
    print('\n=== 전체 수집 시간 ===', flush=True)
    for gu in DISTRICTS:
        if gu in results:
            print(f'  {gu}: {results[gu]:.0f}초', flush=True)
    print(f'  전체 wall-clock: {grand:.0f}초 ({grand/60:.1f}분)', flush=True)

    # 통합본 생성
    print('\n=== 통합본 생성 ===', flush=True)
    ts_combined = datetime.now().strftime('%H%M%S')
    combined = os.path.join(out_dir, f'대구통합_부동산_{date_str}_{ts_combined}.xlsx')
    try:
        from combine import combine_files
        combine_files(out_files, combined)
        print(f'통합본 저장: {combined}', flush=True)
    except Exception as e:
        print(f'통합본 생성 실패: {e}', flush=True)

    # 엑셀_데이터_명세.md 복사
    spec = os.path.join(BASE, '엑셀_데이터_명세.md')
    if os.path.exists(spec):
        shutil.copy2(spec, os.path.join(out_dir, '엑셀_데이터_명세.md'))
        print('엑셀_데이터_명세.md 복사 완료', flush=True)
