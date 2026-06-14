# -*- coding: utf-8 -*-
"""
지정 구 목록을 단일 Python 프로세스 안에서 순차 수집.
bash 세션 타임아웃 없이 장시간 실행 가능.

사용법:
  python run_districts.py 달서구 동구 달성군
  python run_districts.py 달서구 동구 달성군 >> collect_log.txt 2>&1
"""
import argparse
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from main import run

VALID = ['중구', '동구', '서구', '남구', '북구', '수성구', '달서구', '달성군']


class Args:
    def __init__(self, district):
        self.district  = district
        self.source    = 'both'
        self.months    = 12
        self.molit_key = os.environ.get('MOLIT_API_KEY', '')
        self.kakao_key = os.environ.get('KAKAO_API_KEY', '')
        self.output    = ''
        self.test      = False


if __name__ == '__main__':
    districts = sys.argv[1:]
    if not districts:
        print(f'사용법: python run_districts.py 구1 구2 ...')
        print(f'선택 가능: {", ".join(VALID)}')
        sys.exit(1)

    invalid = [d for d in districts if d not in VALID]
    if invalid:
        print(f'알 수 없는 구: {invalid}')
        sys.exit(1)

    print(f'수집 대상: {" → ".join(districts)}')
    for district in districts:
        print(f'\n{"="*50}')
        print(f'[시작] {district}')
        print('='*50)
        try:
            run(Args(district))
        except Exception as e:
            print(f'[오류] {district} 수집 실패: {e}')
            import traceback
            traceback.print_exc()
            print(f'→ 다음 구로 계속 진행...')

    print(f'\n{"="*50}')
    print(f'전체 완료: {" ".join(districts)}')
