# mortgage 프로젝트

대구광역시 아파트 부동산 데이터 수집·분석 도구.

**메인 도구**: `daegu_apt/` — 상세 가이드: [daegu_apt/CLAUDE.md](daegu_apt/CLAUDE.md)

**웹 앱**: `web/` — FastAPI 백엔드 + React 프론트엔드 + Ollama LLM

---

## 웹 앱 실행 방법

### 사전 조건

- Python 3.10 이상
- Node.js 18 이상
- [Ollama](https://ollama.com) 설치 및 모델 pull 완료
  ```powershell
  ollama pull qwen2.5:14b   # 한국어 품질 우수 (9GB)
  ollama pull llama3.1:8b   # 가벼운 대안 (5GB)
  ```
- `daegu_apt/대구부동산_수집결과_*/대구통합_부동산_*.xlsx` 파일 존재 (수집 선행 필요)

### 1단계 — 백엔드 패키지 설치 (최초 1회)

```powershell
cd web\backend
pip install -r requirements.txt
```

### 2단계 — 프론트엔드 패키지 설치 (최초 1회)

```powershell
cd web\frontend
npm install
```

### 3단계 — 서버 실행 (터미널 2개)

**터미널 A — 백엔드:**
```powershell
$env:PYTHONIOENCODING = "utf-8"
cd web\backend
uvicorn main:app --reload --port 8000
```

**터미널 B — 프론트엔드:**
```powershell
cd web\frontend
npm run dev
```

### 4단계 — 브라우저 접속

```
http://localhost:5173
```

### 주요 기능

| 기능 | 설명 |
|------|------|
| 지도 | Leaflet + CartoDB, 가격대별 색상 마커, 클러스터링 |
| 단지명 검색 | 왼쪽 필터 패널 상단 검색창에서 실시간 필터링 |
| 필터 | 구·매매가·평형 범위 조건 |
| AI 채팅 | Ollama 로컬 LLM (qwen2.5:14b 기본) |
| AI → 지도 | AI 응답의 단지명 클릭 시 해당 마커로 지도 자동 이동 |

### 구조

```
web/
├── backend/
│   ├── main.py          FastAPI 서버 (데이터 API + Ollama SSE 스트리밍)
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── App.jsx
    │   └── components/
    │       ├── MapView.jsx    Leaflet 지도 (flyTo 외부 노출)
    │       ├── ChatPanel.jsx  Ollama 채팅 + 단지명 클릭 링크
    │       └── FilterBar.jsx  필터 + 단지명 검색
    ├── package.json
    └── vite.config.js   /api → localhost:8000 프록시
```
