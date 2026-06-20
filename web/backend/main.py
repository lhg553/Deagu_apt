import glob
import json
import math
import os

import httpx
import pandas as pd
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="대구 부동산 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# web/backend/ 기준으로 두 단계 위가 mortgage/ 루트
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_latest_excel() -> pd.DataFrame:
    pattern = os.path.join(
        BASE_DIR, "daegu_apt", "대구부동산_수집결과_*", "대구통합_부동산_*.xlsx"
    )
    files = sorted(glob.glob(pattern))
    if not files:
        print("[경고] 대구통합_부동산_*.xlsx 파일을 찾을 수 없습니다.")
        return pd.DataFrame()
    latest = files[-1]
    print(f"[데이터] 로드: {os.path.basename(latest)}")
    df = pd.read_excel(latest, sheet_name="호가_단지요약")
    df = df.where(pd.notnull(df), None)
    return df


df_all: pd.DataFrame = load_latest_excel()


def clean_val(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def clean_record(record: dict) -> dict:
    return {k: clean_val(v) for k, v in record.items()}


# ─── 아파트 목록 ─────────────────────────────────────────────────────────────

@app.get("/api/apartments")
async def get_apartments(
    district: str = Query(None),
    min_price: int = Query(None),
    max_price: int = Query(None),
    min_size: float = Query(None),
    max_size: float = Query(None),
):
    df = df_all.copy()

    if district and district != "전체":
        df = df[df["지역(구)"] == district]
    if min_price is not None:
        df = df[df["매매_최저(만원)"].fillna(0) >= min_price]
    if max_price is not None:
        df = df[df["매매_최저(만원)"].fillna(0) <= max_price]
    if min_size is not None:
        df = df[df["전용평형(평)"].fillna(0) >= min_size]
    if max_size is not None:
        df = df[df["전용평형(평)"].fillna(999) <= max_size]

    # 좌표 없는 항목 제외
    df = df[df["위도"].notna() & df["경도"].notna()]

    # 단지코드 기준 중복 제거 (평형별 여러 행 → 지도 마커는 단지당 1개)
    df_map = df.drop_duplicates(subset=["단지코드"], keep="first")

    records = [clean_record(r) for r in df_map.to_dict(orient="records")]
    return records


@app.get("/api/districts")
async def get_districts():
    if df_all.empty:
        return []
    districts = sorted(df_all["지역(구)"].dropna().unique().tolist())
    return ["전체"] + districts


# ─── Ollama 모델 목록 ─────────────────────────────────────────────────────────

@app.get("/api/models")
async def get_models():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("http://localhost:11434/api/tags")
            data = r.json()
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


# ─── LLM 채팅 (SSE 스트리밍) ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    model: str = "qwen2.5:14b"
    district: str = None
    max_price: int = None
    history: list = []


@app.post("/api/chat")
async def chat(req: ChatRequest):
    df = df_all.copy()

    # 메시지 안 구 이름 자동 감지
    districts_in_msg = [
        d for d in df["지역(구)"].dropna().unique() if d in req.message
    ]
    if req.district and req.district != "전체":
        df = df[df["지역(구)"] == req.district]
    elif districts_in_msg:
        df = df[df["지역(구)"].isin(districts_in_msg)]

    if req.max_price:
        df = df[df["매매_최저(만원)"].fillna(0) <= req.max_price]

    # 매물 있는 단지 우선, 최대 60개
    df_ctx = (
        df[df["매매_매물수"].fillna(0) > 0]
        .drop_duplicates(subset=["단지코드"])
        .head(60)
    )

    lines = []
    for _, r in df_ctx.iterrows():
        low = r.get("매매_최저(만원)")
        high = r.get("매매_최고(만원)")
        price_str = (
            f"{int(low):,}~{int(high):,}만원" if low and high else "가격정보없음"
        )
        line = (
            f"- {r.get('단지명','')} ({r.get('지역(구)','')} {r.get('지역(동)','')}): "
            f"{r.get('전용평형(평)','')}평, 매매 {price_str}, "
            f"{r.get('총세대수','')}세대, 건축 {r.get('건축년월','')}"
        )
        if r.get("지하철직선도보(분)"):
            line += f", 지하철 {r.get('근처지하철','')} {r.get('지하철직선도보(분)')}분"
        if r.get("근처초등학교"):
            line += f", 초등 {r.get('근처초등학교','')} {r.get('초등학교직선거리(m/분)','')}"
        lines.append(line)

    apt_context = "\n".join(lines) if lines else "해당 조건의 매물 데이터가 없습니다."

    system_prompt = f"""당신은 대구광역시 아파트 부동산 데이터 분석 도우미입니다.
아래 데이터는 네이버 부동산 호가 및 국토교통부 실거래가를 기반으로 수집된 정보입니다.

[현재 조회 데이터]
{apt_context}

답변 규칙:
- 위 데이터에 근거해서만 답변하세요. 데이터에 없는 단지는 "데이터 없음"이라고 하세요.
- 가격 단위는 만원 또는 억원으로 자연스럽게 표현하세요 (예: 35,000만원 → 3억 5천만원).
- 투자 권유는 하지 말고 사실 기반 정보만 제공하세요.
- 모든 답변은 한국어로 작성하세요."""

    messages = [{"role": "system", "content": system_prompt}]
    for h in req.history[-6:]:  # 최근 3턴만 히스토리로
        messages.append(h)
    messages.append({"role": "user", "content": req.message})

    async def generate():
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    "http://localhost:11434/api/chat",
                    json={"model": req.model, "messages": messages, "stream": True},
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            if content:
                                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
                            if data.get("done"):
                                yield f"data: {json.dumps({'done': True})}\n\n"
                                break
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
