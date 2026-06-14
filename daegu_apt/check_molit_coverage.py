# -*- coding: utf-8 -*-
import sys; sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, json, os

BASE  = os.path.dirname(os.path.abspath(__file__))
fpath = os.path.join(BASE, r'대구부동산_수집결과_20260613\대구통합_부동산_20260613_220927.xlsx')

xl      = pd.read_excel(fpath, sheet_name=None)
summary = xl['호가_단지요약']
molit   = xl['실거래가']

# complex_aptseq_map: {단지코드 → aptSeq}
with open(os.path.join(BASE, 'complex_aptseq_map.json'), encoding='utf-8') as f:
    aptseq_map = json.load(f)

# 역방향: {aptSeq → 단지코드}
rev_seq = {}
for cid, seq in aptseq_map.items():
    rev_seq.setdefault(seq, []).append(cid)

# 호가 단지코드 집합
summary_cids = set(summary['단지코드'].astype(str).unique())

# 이 엑셀은 aptSeq 컬럼 추가 전 수집본 → (구, 아파트명)으로 aptSeq 역방향 매핑
# molit_scraper가 수집한 아파트명과 aptSeq_map의 역방향을 아파트명 기준으로 연결

# complex_molit_map: {단지코드 → MOLIT아파트명}
import re
with open(os.path.join(BASE, 'complex_molit_map.json'), encoding='utf-8') as f:
    name_map = json.load(f)

# {단지코드 → aptSeq} 이미 로드됨(aptseq_map)
# 실거래가 고유 (구, 아파트명)
molit_u = molit.drop_duplicates(['구', '아파트명'])[['구', '아파트명']].copy()
print(f'실거래가 고유 단지: {len(molit_u)}개')

# 호가 단지별 (구, MOLIT아파트명) 집합 — aptSeq 경유
def norm(s):
    return re.sub(r'[\s　]', '', str(s)).lower()

# aptSeq → [단지코드] 역방향
rev_seq = {}
for cid, seq in aptseq_map.items():
    rev_seq.setdefault(seq, []).append(cid)

# MOLIT 아파트명 → aptSeq (구별, 이름으로 역방향)
# complex_molit_map: 단지코드 → MOLIT아파트명
# aptseq_map: 단지코드 → aptSeq
# 따라서 MOLIT아파트명 → aptSeq: name_map의 단지코드를 중간에 사용
nm_to_seq = {}   # (구, norm_molit명) → aptSeq
for cid, molit_nm in name_map.items():
    seq = aptseq_map.get(cid)
    if seq:
        m = summary[summary['단지코드'].astype(str) == cid]
        gu = m['지역(구)'].iloc[0] if not m.empty else ''
        nm_to_seq[(gu, norm(molit_nm))] = seq

# 실거래가 각 (구, 아파트명) → aptSeq → 단지코드 → 호가에 있는지
matched = []
no_seq = []
no_summary = []

for _, row in molit_u.iterrows():
    gu = str(row['구'])
    nm = str(row['아파트명'])
    key = (gu, norm(nm))
    seq = nm_to_seq.get(key)
    if seq is None:
        no_seq.append(row)
        continue
    cids = rev_seq.get(seq, [])
    found = [c for c in cids if c in summary_cids]
    if found:
        matched.append(row)
    else:
        no_summary.append(row)

total = len(molit_u)
print(f'\n=== 실거래 단지 → 호가 단지 매칭 결과 (aptSeq 경유) ===')
print(f'  매칭됨:                {len(matched)}개')
print(f'  aptSeq 없음(미매핑):   {len(no_seq)}개')
print(f'  aptSeq 있으나 호가없음: {len(no_summary)}개')
print(f'\n  커버율: {len(matched)}/{total} = {len(matched)/total*100:.1f}%')

if no_seq:
    print(f'\n--- aptSeq 없는 {len(no_seq)}개 ---')
    print(pd.DataFrame(no_seq).to_string(index=False))

if no_summary:
    print(f'\n--- aptSeq 있으나 호가없는 {len(no_summary)}개 ---')
    print(pd.DataFrame(no_summary).to_string(index=False))
