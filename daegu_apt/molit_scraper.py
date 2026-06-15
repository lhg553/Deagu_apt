"""
국토교통부 아파트 매매 실거래가 API
API 키 발급: https://www.data.go.kr → '아파트매매 실거래가 상세 자료' 검색 → 활용신청
"""
import logging
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

_log = logging.getLogger(__name__)

DAEGU_LAWD = {
    'all':   ['27110','27140','27170','27200','27230','27260','27290','27710'],
    '중구':  ['27110'],
    '동구':  ['27140'],
    '서구':  ['27170'],
    '남구':  ['27200'],
    '북구':  ['27230'],
    '수성구': ['27260'],
    '달서구': ['27290'],
    '달성군': ['27710'],
}

LAWD_NAME = {
    '27110': '중구', '27140': '동구', '27170': '서구', '27200': '남구',
    '27230': '북구', '27260': '수성구', '27290': '달서구', '27710': '달성군',
}

API_URL  = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'
SILV_URL = 'https://apis.data.go.kr/1613000/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade'


def _prev_months(n: int) -> list[str]:
    result = []
    d = datetime.today().replace(day=1)
    for _ in range(n):
        result.append(d.strftime('%Y%m'))
        d -= timedelta(days=1)
        d = d.replace(day=1)
    return result


class MolitScraper:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def _fetch_page(self, lawd_cd: str, deal_ymd: str, page: int) -> tuple[list, int]:
        """단일 페이지 조회. (rows, totalCount) 반환."""
        url = (f'{API_URL}?serviceKey={self.api_key}'
               f'&LAWD_CD={lawd_cd}&DEAL_YMD={deal_ymd}'
               f'&numOfRows=1000&pageNo={page}')
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            _log.warning('MOLIT HTTP %d (%s %s p%d): %s', r.status_code, lawd_cd, deal_ymd, page, r.text[:200])
            return [], 0
        root = ET.fromstring(r.content)
        result_code = root.findtext('.//resultCode', '')
        if result_code and result_code not in ('00', '000'):
            msg = root.findtext('.//resultMsg', '')
            _log.warning('MOLIT API 오류 %s: %s (%s %s)', result_code, msg, lawd_cd, deal_ymd)
            return [], 0
        total = int(root.findtext('.//totalCount', '0') or 0)
        gu = LAWD_NAME.get(lawd_cd, lawd_cd)
        rows = []
        for item in root.findall('.//item'):
            def g(tag, _item=item):
                el = _item.find(tag)
                return el.text.strip() if el is not None and el.text else ''
            rows.append({
                'aptSeq':         g('aptSeq'),
                '구':             gu,
                '법정동':         g('umdNm'),
                '도로명':         g('roadNm'),
                '아파트명':       g('aptNm'),
                '동':             g('aptDong'),
                '건축년도':       g('buildYear'),
                '전용면적㎡':     g('excluUseAr'),
                '층':             g('floor'),
                '거래금액(만원)': g('dealAmount').replace(',', '').strip(),
                '거래유형':       g('dealingGbn'),
                '매수자':         g('buyerGbn'),
                '매도자':         g('slerGbn'),
                '거래년도':       g('dealYear'),
                '거래월':         g('dealMonth'),
                '거래일':         g('dealDay'),
                '등기일자':       g('rgstDate'),
                '해제여부':       g('cdealType'),
                '해제사유발생일': g('cdealDay'),
            })
        return rows, total

    def _fetch(self, lawd_cd: str, deal_ymd: str) -> list:
        try:
            rows, total = self._fetch_page(lawd_cd, deal_ymd, page=1)
            if total > 1000:
                import math
                n_pages = math.ceil(total / 1000)
                _log.info('MOLIT 페이징 (%s %s): 총 %d건 → %d페이지', lawd_cd, deal_ymd, total, n_pages)
                for p in range(2, n_pages + 1):
                    extra, _ = self._fetch_page(lawd_cd, deal_ymd, page=p)
                    rows.extend(extra)
            return rows
        except Exception as e:
            _log.warning('MOLIT 요청 실패 (%s %s): %s', lawd_cd, deal_ymd, e)
            return []

    def _fetch_silv_page(self, lawd_cd: str, deal_ymd: str, page: int) -> tuple[list, int]:
        """분양권·입주권 단일 페이지 조회."""
        url = (f'{SILV_URL}?serviceKey={self.api_key}'
               f'&LAWD_CD={lawd_cd}&DEAL_YMD={deal_ymd}'
               f'&numOfRows=1000&pageNo={page}')
        r = requests.get(url, timeout=20)
        if r.status_code in (401, 403) or (r.status_code == 500 and 'Unexpected errors' in r.text):
            raise PermissionError('분양권 API 미승인 — data.go.kr에서 "아파트 분양·입주권 거래 신고 내역" 활용신청 후 승인 대기 중')
        if r.status_code != 200:
            _log.warning('MOLIT 분양권 HTTP %d (%s %s p%d)', r.status_code, lawd_cd, deal_ymd, page)
            return [], 0
        root = ET.fromstring(r.content)
        result_code = root.findtext('.//resultCode', '')
        if result_code and result_code not in ('00', '000'):
            return [], 0
        total = int(root.findtext('.//totalCount', '0') or 0)
        gu = LAWD_NAME.get(lawd_cd, lawd_cd)
        rows = []
        for item in root.findall('.//item'):
            def g(tag, _i=item):
                el = _i.find(tag)
                return el.text.strip() if el is not None and el.text else ''
            rows.append({
                '구':             gu,
                '법정동':         g('umdNm'),
                '지번':           g('jibun'),
                '아파트명':       g('aptNm'),
                '거래방법':       g('dealingGbn'),   # 중개거래 / 직거래
                '전용면적㎡':     g('excluUseAr'),
                '층':             g('floor'),
                '거래금액(만원)': g('dealAmount').replace(',', '').strip(),
                '매수자':         g('buyerGbn'),
                '매도자':         g('slerGbn'),
                '거래년도':       g('dealYear'),
                '거래월':         g('dealMonth'),
                '거래일':         g('dealDay'),
                '해제여부':       g('cdealType'),
                '해제사유발생일': g('cdealDay'),
            })
        return rows, total

    def _fetch_silv(self, lawd_cd: str, deal_ymd: str) -> list:
        import math
        rows, total = self._fetch_silv_page(lawd_cd, deal_ymd, 1)
        if total > 1000:
            for p in range(2, math.ceil(total / 1000) + 1):
                extra, _ = self._fetch_silv_page(lawd_cd, deal_ymd, p)
                rows.extend(extra)
        return rows

    def collect_silv(self, district: str = 'all', months: int = 3,
                     lawd_codes: list = None) -> pd.DataFrame:
        """분양권·입주권 실거래 수집.
        API 미승인 시 빈 DataFrame 반환 (경고 출력).
        """
        lawd_list = lawd_codes if lawd_codes else DAEGU_LAWD.get(district, DAEGU_LAWD['all'])
        deal_ymds = _prev_months(months)
        rows = []
        for lawd_cd in lawd_list:
            gu = LAWD_NAME.get(lawd_cd, lawd_cd)
            for ymd in deal_ymds:
                print(f'  [{gu}] {ymd[:4]}년 {ymd[4:]}월 분양권 조회 중...')
                try:
                    rows.extend(self._fetch_silv(lawd_cd, ymd))
                except PermissionError as e:
                    print(f'  [건너뜀] {e}')
                    return pd.DataFrame()
                except Exception as e:
                    _log.warning('MOLIT 분양권 요청 실패 (%s %s): %s', lawd_cd, ymd, e)
        return pd.DataFrame(rows)

    def collect(self, district: str = 'all', months: int = 3,
                lawd_codes: list = None) -> pd.DataFrame:
        """lawd_codes 지정 시 해당 코드만 조회 (Naver 결과 기반 동적 구성)."""
        lawd_list = lawd_codes if lawd_codes else DAEGU_LAWD.get(district, DAEGU_LAWD['all'])
        deal_ymds = _prev_months(months)
        rows = []

        for lawd_cd in lawd_list:
            gu = LAWD_NAME.get(lawd_cd, lawd_cd)
            for ymd in deal_ymds:
                print(f'  [{gu}] {ymd[:4]}년 {ymd[4:]}월 실거래 조회 중...')
                rows.extend(self._fetch(lawd_cd, ymd))

        return pd.DataFrame(rows)
