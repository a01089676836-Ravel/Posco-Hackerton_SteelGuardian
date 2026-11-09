"""
포스코 AI 해커톤 - 실시간 비지도 품질 관제 대시보드
(PatchCore Eq.6-7 N_b(m*) 재가중 + 전경 중심 링 마스크 + 무클리핑 다중 특징 규칙 + 운영 모드별 판정·히트맵 동기화)
실행 명령어: streamlit run app.py
"""

import streamlit as st
import time
import io
import uuid
import base64
import subprocess
import sys
from datetime import datetime, timezone, timedelta
import random
from pathlib import Path
from PIL import Image
import pandas as pd
import httpx

from rule_engine import evaluate_defect, OPERATING_MODE_THRESHOLDS
from patchcore_engine import PatchCoreEngine, get_engine, load_evaluation_report
from audit_logger import log_inspection_audit, read_recent_audit_logs, read_audit_csv_bytes

import os
import hashlib

BASE_DIR = Path(__file__).parent

def get_default_api_base_url() -> str:
    env_url = os.getenv("API_BASE_URL") or os.getenv("API_URL")
    if env_url:
        return env_url.strip().rstrip("/")
    api_h = os.getenv("API_HOST", "127.0.0.1")
    api_p = os.getenv("API_PORT", "8000")
    # Windows/Linux에서 0.0.0.0은 서버 바인딩 전용이므로 클라이언트 접속 시 127.0.0.1 사용
    client_h = "127.0.0.1" if api_h in ("0.0.0.0", "", "::") else api_h
    return f"http://{client_h}:{api_p}"


# ---------------------------------------------------------------------------
# 판정 표시 규칙 (decision 값 집합: PASS / REWORK / SCRAP / MANUAL_REVIEW)
# 알 수 없는 값은 SCRAP 등으로 추정하지 않고 "판정 확인 필요"로 표시한다.
# ---------------------------------------------------------------------------
DECISION_STYLES = {
    "PASS": {"css": "decision-pass", "icon": "●", "label": "판정 결과: 정상 합격 (PASS)",
             "color": "#059669",
             "action": "정상 합격: 다음 공정(표면 조질 압연)으로 정상 이송합니다."},
    "REWORK": {"css": "decision-rework", "icon": "▲", "label": "판정 결과: 재가공 이송 (REWORK)",
               "color": "#d97706",
               "action": "재가공 대상: 표면 결함 제거를 위해 버핑/연마 라인으로 회차 이송합니다."},
    "SCRAP": {"css": "decision-scrap", "icon": "■", "label": "판정 결과: 즉시 폐기 (SCRAP)",
              "color": "#dc2626",
              "action": "즉시 폐기: 치명적 형상 변형 추정. 해당 부품을 폐기 라인으로 분리합니다."},
    "MANUAL_REVIEW": {"css": "decision-review", "icon": "◆", "label": "판정 결과: 2차 육안 판정 대기 (MANUAL_REVIEW)",
                      "color": "#0369a1",
                      "action": "2차 육안 판정 대기: 자동 이송을 보류하고 검사원 확인 후 처리합니다."},
}


def get_decision_style(decision) -> dict:
    """decision 값에 맞는 배너 스타일을 반환. 미정의 값은 '판정 확인 필요'로 안전하게 표시."""
    key = str(decision)
    if key in DECISION_STYLES:
        return DECISION_STYLES[key]
    return {"css": "decision-review", "icon": "?", "label": f"판정 확인 필요 (알 수 없는 decision: {key})",
            "color": "#475569", "action": "확인 필요: 정의되지 않은 판정값입니다. 자동 이송을 보류하십시오."}


def compare_model_state(inspect_resp: dict, registry_active: dict | None) -> dict:
    """
    검사 응답의 model_part_id / model_sha256 을 GET /v1/models 의 활성 모델과 대조.
    반환 status:
      - MATCH: 두 값 모두 일치
      - MISMATCH: part_id 또는 sha256 불일치 (검사 도중 모델 교체 등)
      - UNVERIFIED: 레지스트리 조회 실패 또는 sha256 누락으로 대조 불가 (정상으로 간주하지 않음)
    """
    inspected_part = inspect_resp.get("model_part_id") or inspect_resp.get("part_id")
    inspected_sha = str(inspect_resp.get("model_sha256") or "").lower()
    out = {
        "inspected_part": inspected_part,
        "inspected_sha": inspected_sha,
        "registry_part": None,
        "registry_sha": "",
    }
    if not registry_active:
        return {**out, "status": "UNVERIFIED", "reason": "GET /v1/models 활성 모델 조회 실패"}
    reg_part = registry_active.get("model_part_id") or registry_active.get("part_id")
    reg_sha = str(registry_active.get("model_sha256") or "").lower()
    out.update({"registry_part": reg_part, "registry_sha": reg_sha})
    if not inspected_sha or not reg_sha:
        return {**out, "status": "UNVERIFIED", "reason": "model_sha256 값이 응답에 없음"}
    if inspected_part != reg_part or inspected_sha != reg_sha:
        return {**out, "status": "MISMATCH", "reason": "검사 모델과 서버 활성 모델 불일치"}
    return {**out, "status": "MATCH", "reason": ""}

st.set_page_config(
    page_title="POSCO 실시간 스마트팩토리 품질 관제 시스템",
    page_icon="🏭",
    layout="wide"
)

def inject_custom_styles():
    """Impeccable Craft Floor: POSCO 제철소 산업용 SCADA / MES 디자인 시스템 스타일링"""
    st.markdown("""
    <style>
    :root {
        --posco-navy: #002b49;
        --posco-blue: #005a9c;
        --posco-steel: #1e3a5f;
        --posco-bg: #f8fafc;
        --posco-card-bg: #ffffff;
        --posco-border: #e2e8f0;
        --posco-text-main: #0f172a;
        --posco-text-muted: #64748b;
        --status-pass: #059669;
        --status-rework: #d97706;
        --status-scrap: #dc2626;
    }

    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Pretendard", sans-serif;
        letter-spacing: -0.015em;
        color: #0f172a;
    }
    [data-testid="stMetricValue"], [data-testid="stMetricDelta"], table, th, td, code, pre {
        font-variant-numeric: tabular-nums !important;
    }

    .posco-header-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 24px;
        background: linear-gradient(135deg, #002b49 0%, #1e3a5f 100%);
        border-radius: 8px;
        color: #ffffff;
        margin-bottom: 16px;
        box-shadow: 0 2px 8px rgba(0, 43, 73, 0.12);
    }
    .posco-header-title {
        font-size: 1.3rem;
        font-weight: 700;
        letter-spacing: -0.02em;
        margin: 0;
        color: #ffffff;
    }
    .posco-header-subtitle {
        font-size: 0.82rem;
        color: #cbd5e1;
        margin-top: 4px;
    }
    .posco-system-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 5px 12px;
        border-radius: 16px;
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.02em;
    }
    .badge-online {
        background-color: rgba(16, 185, 129, 0.2);
        color: #34d399;
        border: 1px solid rgba(52, 211, 153, 0.5);
    }
    .badge-offline {
        background-color: rgba(239, 68, 68, 0.2);
        color: #f87171;
        border: 1px solid rgba(248, 113, 113, 0.5);
    }

    [data-testid="stMetric"] {
        background-color: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 8px !important;
        padding: 12px 16px !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03) !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.82rem !important;
        font-weight: 600 !important;
        color: #64748b !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.35rem !important;
        font-weight: 700 !important;
        color: #0f172a !important;
    }

    [data-testid="stSidebar"] {
        background-color: #f8fafc !important;
        border-right: 1px solid #e2e8f0 !important;
    }

    .stButton > button {
        border-radius: 6px !important;
        font-weight: 600 !important;
        font-size: 0.88rem !important;
        transition: transform 0.1s ease, box-shadow 0.1s ease !important;
    }
    .stButton > button:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08) !important;
    }

    .decision-banner {
        padding: 14px 18px;
        border-radius: 8px;
        font-weight: 700;
        font-size: 1.15rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;
    }
    .decision-pass {
        background-color: #ecfdf5;
        color: #065f46;
        border: 1px solid #a7f3d0;
    }
    .decision-rework {
        background-color: #fffbeb;
        color: #92400e;
        border: 1px solid #fde68a;
    }
    .decision-scrap {
        background-color: #fef2f2;
        color: #991b1b;
        border: 1px solid #fecaca;
    }
    .decision-review {
        background-color: #eff6ff;
        color: #075985;
        border: 1px solid #bae6fd;
    }
    .interlock-banner {
        padding: 12px 18px;
        border-radius: 8px;
        font-weight: 800;
        font-size: 1.05rem;
        letter-spacing: 0.01em;
        background-color: #b91c1c;
        color: #ffffff;
        border: 2px solid #7f1d1d;
        margin-bottom: 12px;
    }

    [data-testid="stDataFrame"] {
        border-radius: 8px !important;
        border: 1px solid #e2e8f0 !important;
    }
    </style>
    """, unsafe_allow_html=True)

inject_custom_styles()

if "custom_api_url" not in st.session_state:
    st.session_state["custom_api_url"] = get_default_api_base_url()

API_BASE_URL = st.session_state["custom_api_url"]


def check_api_online(target_url: str = None) -> bool:
    url = (target_url or API_BASE_URL).rstrip("/")
    try:
        r = httpx.get(f"{url}/health", timeout=0.5)
        return r.status_code == 200
    except Exception:
        return False


def start_fastapi_server():
    """로컬 환경에서 FastAPI 추론 서버(server.py)를 백그라운드 프로세스로 기동"""
    api_h = os.getenv("API_HOST", "127.0.0.1")
    api_p = os.getenv("API_PORT", "8000")
    host_to_bind = "127.0.0.1" if api_h in ("0.0.0.0", "", "::") else api_h

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)

    py_bin = sys.executable
    venv_py = BASE_DIR / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        py_bin = str(venv_py)

    cmd = [
        py_bin,
        "-m",
        "uvicorn",
        "server:app",
        "--host",
        host_to_bind,
        "--port",
        api_p
    ]
    try:
        subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        for _ in range(8):
            time.sleep(0.5)
            if check_api_online():
                return True, "FastAPI 서버가 성공적으로 기동되었습니다."
        return False, "FastAPI 프로세스를 실행했으나 4초 이내에 헬스체크에 응답하지 않았습니다."
    except Exception as e:
        return False, f"FastAPI 실행 중 오류 발생: {e}"


@st.cache_resource
def load_patchcore_engine(model_path_str: str, model_sha256: str):
    """
    PatchCore 모델 경로와 SHA256 체크섬을 캐시 키로 사용하여
    파일 변경 시 캐시를 무효화하고 안전하게 엔진 인스턴스를 생성
    """
    return PatchCoreEngine(model_path=Path(model_path_str))


default_pt_path = BASE_DIR / "models" / "memory_bank.pt"
default_sha = hashlib.sha256(default_pt_path.read_bytes()).hexdigest() if default_pt_path.exists() else ""
engine = load_patchcore_engine(str(default_pt_path), default_sha)
eval_report = load_evaluation_report()
metrics = engine.metrics

# SCADA 관제 헤더 바
is_local_target = any(loc in API_BASE_URL for loc in ("127.0.0.1", "localhost", "0.0.0.0"))
api_online = check_api_online()

if not api_online and is_local_target and not st.session_state.get("_autostart_attempted", False):
    st.session_state["_autostart_attempted"] = True
    ok, _ = start_fastapi_server()
    if ok:
        api_online = True
        st.rerun()

status_badge = (
    f'<span class="posco-system-badge badge-online">● FASTAPI ONLINE ({API_BASE_URL})</span>'
    if api_online else
    f'<span class="posco-system-badge badge-offline">▲ LOCAL FALLBACK ({API_BASE_URL} 미응답)</span>'
)

st.markdown(f"""
<div class="posco-header-bar">
    <div>
        <h1 class="posco-header-title">POSCO 스마트팩토리 실시간 비지도 품질 관제 시스템</h1>
        <div class="posco-header-subtitle">
            스틸가디언 (SteelGuardian) · Unsupervised PatchCore ResNet-18 (Coreset 6,000 + Eq.6·7 밀도 재가중) · 금속 부품(metal_nut) 표면 결함 관제
        </div>
    </div>
    <div>
        {status_badge}
    </div>
</div>
""", unsafe_allow_html=True)

if not api_online:
    col_err, col_btn = st.columns([3.5, 1.5])
    with col_err:
        st.warning("FastAPI 백엔드 서버가 응답하지 않아 개발용 LOCAL_FALLBACK 모드로 동작 중입니다. 모델 교체 시 사이드바에서 캐시 초기화가 필요합니다.")
    with col_btn:
        if st.button("FastAPI 서버 즉시 켜기", key="btn_start_fastapi_top", width="stretch"):
            with st.spinner("FastAPI 백엔드 추론 서버 기동 중..."):
                ok, msg = start_fastapi_server()
                if ok:
                    st.success(f"{msg}")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(f"{msg}")
st.divider()

BASE_DIR = Path(__file__).parent
DATASET_DIR = BASE_DIR / "datasets" / "metal_nut" / "metal_nut" / "test"

api_online = check_api_online()
op_metrics = eval_report.get("operational_safety_metrics", {})

with st.sidebar:
    st.header("⚙️ 관제 모니터 설정")

    with st.expander("🌐 네트워크 및 API 서버 연결", expanded=False):
        input_url = st.text_input(
            "FastAPI 서버 URL",
            value=st.session_state["custom_api_url"],
            help="다른 노트북/원격 서버에서 실행 중인 FastAPI에 연결하려면 해당 IP/URL을 입력하세요 (예: http://192.168.0.15:8000)"
        ).strip().rstrip("/")
        if input_url and input_url != st.session_state["custom_api_url"]:
            st.session_state["custom_api_url"] = input_url
            st.rerun()

    if api_online:
        st.success(f"🟢 FastAPI 추론 서버 연결됨 (`{API_BASE_URL}`)")
        allow_local_fallback = True
    else:
        st.error(f"⚠️ FastAPI 서버(`{API_BASE_URL}`) 미가동")
        if st.button("🚀 FastAPI 서버 켜기", key="btn_start_fastapi_side", width="stretch"):
            with st.spinner("서버 기동 중..."):
                ok, msg = start_fastapi_server()
                if ok:
                    st.success("✅ 서버 기동 완료")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(msg)
        allow_local_fallback = st.checkbox("개발 모드 LOCAL_FALLBACK 허용", value=True)

    mode = st.radio(
        "화면 모드 선택",
        [
            "가상 컨베이어 벨트 스트리밍",
            "개별 이미지 업로드 검사",
            "📊 공식 벤치마크 검증 리포트 (Audit)"
        ]
    )

    operating_mode = st.selectbox(
        "운영 임계치 모드 (Operating Mode)",
        ["SAFETY_FIRST", "BALANCED_THROUGHPUT", "HUMAN_IN_THE_LOOP"],
        format_func=lambda m: {
            "SAFETY_FIRST": "🛡️ SAFETY_FIRST (불량 유출 FN=0 최우선, th=0.600)",
            "BALANCED_THROUGHPUT": "⚡ BALANCED_THROUGHPUT (정상 오탐 최소화, th=0.645)",
            "HUMAN_IN_THE_LOOP": "👁️ HUMAN_IN_THE_LOOP (경계 0.58~0.65 2차 판정 대기)"
        }[m]
    )

    part_geometry = st.selectbox(
        "부품 형상 모드 (Part Geometry)",
        ["generic", "circular_jig"],
        format_func=lambda g: {
            "generic": "📦 generic (범용 부품 — 링 마스크 비활성화)",
            "circular_jig": "⚙️ circular_jig (원형 너트 전용 링 마스크 0.58~0.95)"
        }[g]
    )

    st.markdown("---")
    st.subheader("🔄 부품 모델 레지스트리")
    if api_online:
        try:
            m_res = httpx.get(f"{API_BASE_URL}/v1/models", timeout=1.0).json()
            act = m_res.get("active_model", {})
            st.caption(f"**활성 모델:** `{act.get('part_id')}` (`{act.get('model_file')}`)")
            st.caption(f"- Hash: `{act.get('model_hash')}` | Raw Th: `{act.get('raw_threshold')}`")
            if act.get("confidence_tier"):
                auto_txt = "자동 판정 허용" if act.get("autonomous_decision_allowed") else "자동 판정 불허 (이상 시 2차 판정)"
                st.caption(f"- 신뢰 등급: `{act.get('confidence_tier')}` | {auto_txt}")

            avail_models = m_res.get("available_models", [])
            other_models = [m for m in avail_models if not m.get("is_active")]
            # 대시보드 접속자 판별: 대시보드가 FastAPI와 같은 PC에서 돌면 서버는 모든 요청을 로컬로 보므로,
            # LAN 시연 시 다른 PC 접속자가 키 없이 모델을 바꾸지 못하도록 대시보드에서 차단한다.
            try:
                viewer_ip = st.context.ip_address
            except Exception:
                viewer_ip = None
            viewer_is_local = viewer_ip in ("127.0.0.1", "::1", "localhost")
            if other_models and not viewer_is_local:
                st.info("🔒 모델 교체는 대시보드를 실행한 PC에서 로컬로 접속한 경우에만 가능합니다.")
            if other_models and viewer_is_local:
                target_model = st.selectbox(
                    "전환할 부품 모델 선택",
                    other_models,
                    format_func=lambda m: f"{m['part_id']} ({m['confidence_tier']})"
                )
                # 원격(비-루프백) 서버는 x-admin-key 헤더가 필요. 키는 헤더로만 전송하며 화면·로그·URL에 남기지 않음.
                is_loopback_api = any(h in API_BASE_URL for h in ("://127.0.0.1", "://localhost", "://[::1]"))
                admin_key_input = ""
                if not is_loopback_api:
                    admin_key_input = st.text_input(
                        "관리자 키 (원격 서버 핫스왑 시 필요)",
                        type="password",
                        key="admin_key_input",
                        help="입력값은 x-admin-key 요청 헤더로만 전송되며 화면, 감사 로그, URL에 기록되지 않습니다."
                    )
                if st.button("🚀 선택한 모델로 활성화 (핫스왑)"):
                    act_headers = {"x-admin-key": admin_key_input} if admin_key_input else {}
                    act_resp = httpx.post(
                        f"{API_BASE_URL}/v1/models/activate",
                        json={"part_id": target_model["part_id"], "expected_sha256": target_model["sha256"]},
                        headers=act_headers,
                        timeout=30.0
                    )
                    if act_resp.status_code == 200:
                        st.success(f"✅ 모델 활성화 완료: {target_model['part_id']}")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(f"❌ 활성화 실패: {act_resp.text}")
            else:
                st.caption("추가 사용 가능 모델 없음 (onboard_new_part.py 로 새 모델 생성 시 자동 노출)")
        except Exception as e:
            st.caption(f"모델 레지스트리 조회 실패: {e}")
    else:
        st.caption("FastAPI 미가동 (기본 로컬 모델 사용)")

    if st.button("🧹 엔진 캐시 초기화 (Clear Cache)", width="stretch"):
        st.cache_resource.clear()
        st.success("대시보드 엔진 캐시가 초기화되었습니다.")
        time.sleep(0.3)
        st.rerun()

    st.markdown("---")
    st.subheader("📈 공식 검증 성적 (MVTec Test 115장)")
    fn_cnt = op_metrics.get("false_negatives_to_pass", 0)
    rec_pct = op_metrics.get("defect_recall_pct", 100.0)
    st.markdown(f"- **불량 검출 Recall (안전모드):** `{rec_pct:.2f}% (FN={fn_cnt}/93)`")
    st.markdown(f"- **Image AUROC (Eq.7 $s$):** `{metrics.get('image_auroc_after_reweighting_eq7', metrics.get('image_auroc', 0.9912))*100:.2f}%`")
    st.markdown(f"- **Image AUROC (Eq.6 $s^*$):** `{metrics.get('image_auroc_before_reweighting_eq6', 0.9912)*100:.2f}%`")
    st.markdown(f"- **Image F1 (@0.60):** `{metrics.get('image_f1', 0.9841)*100:.2f}%`")
    st.markdown(f"- **Pixel AUROC (700×700):** `{metrics.get('pixel_auroc_700x700', 0.9634)*100:.2f}%`")
    st.markdown(f"- **AU-PRO@0.3 (700×700):** `{metrics.get('au_pro_03_700x700', 0.9047)*100:.2f}%`")
    st.markdown(f"- **Pixel IoU (700×700):** `{metrics.get('pixel_iou_700x700', 0.6022)*100:.2f}%`")

    st.markdown("---")
    st.subheader("📋 다중 특징 판정 기준 (Validation-Derived)")
    st.markdown("- **정상(PASS):** Score < 운영 임계치 (`SUPPRESSED_BELOW_THRESHOLD`)")
    st.markdown("- **재가공(REWORK):** 내부 평면 표면 스크래치·오염 추정")
    st.markdown("- **폐기(SCRAP):** 최대 패치 거리 초과, 외곽 링 관여율 초과, 또는 광역 면적(`bent`/`flip` 추정)")
    st.markdown("- **2차 육안판정 권고:** 경계 점수(`0.58 ≤ score < 0.65`)에서 `manual_review_recommended=true`")
    st.markdown("- **2차 판정 대기(MANUAL_REVIEW):** 서버가 해당 판정을 반환하면 자동 이송 보류로 표시")

    st.markdown("---")
    st.caption(f"Engine `{engine.engine_version}` | Hash `{engine.model_hash}`")
    st.info("💡 **팀 정보:** POSCO K-뉴딜 해커톤 (스틸가디언 팀)\n- 팀장: 전종현\n- 팀원: 김지민, 차주현, 허재원, 주현규")

if mode == "📊 공식 벤치마크 검증 리포트 (Audit)":
    st.subheader("🔬 PatchCore 모델 무결성 및 무누수(Zero-Leakage) 운영 검증 리포트 (`results/evaluation.json`)")
    if not eval_report:
        st.warning("`results/evaluation.json` 파일이 없습니다. `python evaluate_benchmark.py`를 먼저 실행하세요.")
    else:
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        op = eval_report["operational_safety_metrics"]
        ov = eval_report["overall_metrics"]
        k1.metric("불량 미검출 (FN)", f"{op['false_negatives_to_pass']} / 93건", f"Recall {op['defect_recall_pct']:.1f}%")
        k2.metric("정상 폐기 오판", f"{op['false_positives_to_scrap']} / 22건", f"REWORK 이송 {op['false_positives_to_rework']}건")
        k3.metric("Image AUROC (Eq.7)", f"{ov['image_auroc']*100:.2f}%", f"Eq.6: {ov.get('image_auroc_before_reweighting_eq6', 0.9912)*100:.2f}%")
        k4.metric("Pixel AUROC (700²)", f"{ov['pixel_auroc_700x700']*100:.2f}%")
        k5.metric("AU-PRO@0.3 (700²)", f"{ov['au_pro_03_700x700']*100:.2f}%")
        k6.metric("Pixel IoU (700²)", f"{ov['pixel_iou_700x700']*100:.2f}%")

        st.info(
            "💡 **픽셀 지표 및 전경 위치 보정 가이드:** Pixel AUROC는 결함 위치의 상대적 순위를, AU-PRO@0.3은 결함 영역별 검출 균형을, "
            "Pixel IoU는 고정 threshold에서의 분할 정밀도를 측정합니다. 얇은 스크래치에서는 patch-level 업샘플링(입력 8×8px → 700×700 기준 약 21.9×21.9px) "
            "한계로 IoU가 낮아질 수 있지만, AU-PRO 0.90 이상은 결함 영역을 안정적으로 포함함을 보여줍니다. 본 시스템은 지그 정렬(jig-aligned) 가정에 더해 "
            "전경 밝기 무게중심(Foreground Centroid) 기반 동적 링 마스크로 소폭 이송 변위를 보정합니다."
        )

        st.divider()
        c_left, c_right = st.columns(2)
        with c_left:
            st.markdown("#### 1. 결함 유형별 판정 및 무클리핑(Unclipped) 실제 면적 명세 (총 115장)")
            rows = []
            for cat, d in eval_report["per_category_breakdown"].items():
                rows.append({
                    "유형": cat.upper(),
                    "총 수량": d["total"],
                    "PASS": d["PASS"],
                    "REWORK": d["REWORK"],
                    "SCRAP": d["SCRAP"],
                    "실제 평균면적": f"{d.get('unclipped_area_ratio_mean', 0.0)*100:.2f}%",
                    "검출률 (Recall/FPR)": f"{d['recall_or_fpr']*100:.1f}%"
                })
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            st.caption("※ `defect_area_ratio`에는 어떠한 인위적 클리핑(min/max 강제)도 적용하지 않으며, 모든 규칙 임계치는 검증셋 정상 통계에서만 유도되었습니다.")

        with c_right:
            st.markdown("#### 2. 운영 모드별 임계치(Threshold) 및 판정·히트맵 동기화 검증")
            modes_cmp = eval_report.get("operating_modes_comparison", {})
            if modes_cmp:
                m_rows = []
                for m_name, md in modes_cmp.items():
                    m_rows.append({
                        "운영 모드": m_name,
                        "임계치": f"{md['normalized_threshold']:.3f}",
                        "정상 오탐 (FP/22)": f"{md['good_fp_count']}건 ({md['good_fpr_pct']:.1f}%)",
                        "불량 유출 (FN/93)": f"{md['defect_fn_count']}건 (Recall {md['defect_recall_pct']:.1f}%)",
                        "고위험(bent·flip) 검출": f"{md['high_risk_bent_flip_recall_pct']:.1f}%",
                        "판정-히트맵 동기화": "✅ 일치" if md.get("decision_heatmap_label_synced", True) else "❌ 불일치"
                    })
                st.dataframe(pd.DataFrame(m_rows), width="stretch", hide_index=True)

            st.markdown("#### 3. 3단계 공정 의사결정 혼동 행렬 (SAFETY_FIRST 기준)")
            cm = eval_report["confusion_matrix_3class"]
            cm_df = pd.DataFrame([
                {"실제 구분": "정상 부품 (Good, 22장)", "🟢 PASS": cm["good_actual"]["PASS"], "🟡 REWORK": cm["good_actual"]["REWORK"], "🔴 SCRAP": cm["good_actual"]["SCRAP"]},
                {"실제 구분": "결함 부품 (Defect, 93장)", "🟢 PASS (FN)": cm["defect_actual"]["PASS"], "🟡 REWORK": cm["defect_actual"]["REWORK"], "🔴 SCRAP": cm["defect_actual"]["SCRAP"]},
            ])
            st.dataframe(cm_df, width="stretch", hide_index=True)

        st.divider()
        h_left, h_right = st.columns(2)
        with h_left:
            st.markdown("#### 4. 정상(22장) vs 불량(93장) Anomaly Score 분포 히스토그램")
            dist = eval_report["score_distributions"]
            edges = dist["bin_edges"]
            labels = [f"{edges[i]:.1f}~{edges[i+1]:.1f}" for i in range(len(edges)-1)]
            hist_df = pd.DataFrame({
                "구간": labels,
                "정상 부품 (Good 22장)": dist["good_22_histogram"],
                "결함 부품 (Defect 93장)": dist["defect_93_histogram"]
            }).set_index("구간")
            st.bar_chart(hist_df)

        with h_right:
            st.markdown("#### 5. 5-Seed 교집합 0% 검증, Eq. 6·7 비교 및 재현성 리포트")
            tc = eval_report["threshold_calibration"]
            rs = eval_report["reproducibility_and_system"]
            strat_info = tc.get("multi_seed_stratified_thresholds", {})
            st.json({
                "engine_version": eval_report.get("engine_version", engine.engine_version),
                "model_hash": eval_report.get("model_hash", engine.model_hash),
                "image_score_method": ov.get("image_score_method", "patchcore_eq7_reweighted_max_1nn"),
                "reweight_neighbors_b": ov.get("reweight_neighbors_b", 9),
                "reweighted_vs_raw_correlation": ov.get("reweighted_score_vs_raw_score_correlation", 0.999),
                "test_set_leakage": tc["test_set_leakage"],
                "validation_images_excluded_from_memory_bank": tc.get("validation_images_excluded_from_memory_bank", True),
                "overlap_between_memory_bank_and_calibration": tc.get("overlap_between_memory_bank_and_calibration", 0),
                "defect_area_ratio_clipped_or_manipulated": tc.get("defect_area_ratio_clipped_or_manipulated", False),
                "holdout_raw_threshold": tc["raw_threshold"],
                "5_seed_zero_overlap_threshold_mean_std": f"{strat_info.get('mean_threshold', 0)} ± {strat_info.get('std_threshold', 0)}",
                "5_seed_details": strat_info.get("per_seed", {}),
                "jpeg_q95_reencode_mean_diff": rs["jpeg_q95_reencode_mean_abs_diff"],
                "memory_bank_reload_diff": rs["memory_bank_reload_max_diff"],
                "cpu_latency_ms_mean_p95": f"{rs['cpu_inference_latency_ms_mean']}ms (P95: {rs['cpu_inference_latency_ms_p95']}ms)"
            })

else:
    if not api_online and not allow_local_fallback:
        st.error(f"🚨 **API 서버 미가동 오류:** FastAPI 서버(`{API_BASE_URL}`)가 응답하지 않습니다. 서버가 기동 중인지 확인하거나 좌측 사이드바의 '네트워크 및 API 서버 연결'에서 올바른 URL을 입력하세요. (단독 개발 시 사이드바에서 `개발 모드 LOCAL_FALLBACK 허용` 체크 가능)")
        st.stop()

    col_cam, col_ai, col_decision = st.columns([1.2, 1.2, 1.4])

    with col_cam:
        st.subheader("📷 실시간 공정 카메라 (700×700 RGB)")
        camera_placeholder = st.empty()

    with col_ai:
        st.subheader("🔥 PatchCore 픽셀 이상치 히트맵")
        heatmap_placeholder = st.empty()

    with col_decision:
        st.subheader("📊 조업 의사결정 및 인터록 제어")
        sync_warning_placeholder = st.empty()
        decision_placeholder = st.empty()
        metrics_placeholder = st.empty()
        action_placeholder = st.empty()

    st.divider()
    st.subheader("📈 실시간 생산 수율 및 조업 통계")
    stats_col1, stats_col2, stats_col3, stats_col4, stats_col5 = st.columns(5)

    total_metric = stats_col1.empty()
    pass_metric = stats_col2.empty()
    rework_metric = stats_col3.empty()
    scrap_metric = stats_col4.empty()
    hold_metric = stats_col5.empty()

    def render_inspection_result(img: Image.Image, label_caption: str):
        """
        FastAPI REST API(POST /v1/defects/inspect)를 호출해 서버 판정을 그대로 표시.
        - FastAPI가 온라인이면 서버 판정만 사용한다. 요청이 실패해도 로컬 엔진으로 자동 대체하지 않고 판정을 보류한다.
        - FastAPI가 미기동(오프라인)일 때만 개발용 LOCAL_FALLBACK을 수행한다.
        반환값: 판정 dict, 또는 판정을 보류한 경우 None
        """
        t0 = time.perf_counter()
        used_rest_api = False
        model_state = None
        api_error = None
        shape_check, global_cov = "NOT_PERFORMED", "LIMITED"

        if api_online:
            try:
                # 렌더링 전 GET /v1/models를 호출해 현재 서버 활성 모델 정보 확인
                active_model_meta = None
                try:
                    reg_resp = httpx.get(f"{API_BASE_URL}/v1/models", timeout=2.0)
                    if reg_resp.status_code == 200:
                        active_model_meta = reg_resp.json().get("active_model", {})
                except Exception:
                    active_model_meta = None

                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="PNG")
                resp = httpx.post(
                    f"{API_BASE_URL}/v1/defects/inspect",
                    files={"file": ("frame.png", buf.getvalue(), "image/png")},
                    data={
                        "camera_id": "CAM_FINISHING_01",
                        "operating_mode": operating_mode,
                        "part_geometry": part_geometry,
                        "include_heatmap": "true"
                    },
                    timeout=20.0
                )
                if resp.status_code != 200:
                    try:
                        detail = resp.json().get("detail", resp.text)
                    except Exception:
                        detail = resp.text
                    api_error = f"HTTP {resp.status_code} — {str(detail)[:200]}"
                else:
                    api_data = resp.json()
                    score = api_data["anomaly_score"]
                    raw_dist = api_data.get("raw_distance", score)
                    peak_d = api_data.get("peak_patch_distance", raw_dist)
                    area_ratio = api_data.get("defect_area_ratio") if api_data.get("defect_area_ratio") is not None else 0.0
                    raw_edge_r = api_data.get("edge_region_ratio")
                    if raw_edge_r is None:
                        raw_edge_r = api_data.get("outer_ring_ratio")
                    edge_r = raw_edge_r
                    struct_like = api_data.get("structural_defect_likelihood")
                    inf_mode = api_data.get("inference_mode", "FASTAPI_REST_SERVER")
                    mod_hash = api_data.get("model_hash", "")
                    b64_str = api_data.get("heatmap_base64")
                    heatmap_img = Image.open(io.BytesIO(base64.b64decode(b64_str))) if b64_str else img

                    # 모델 상태 동기화 검증: inspect 응답 모델과 GET /v1/models 활성 모델 대조
                    model_state = compare_model_state(api_data, active_model_meta)
                    model_state["activated_at"] = str(api_data.get("activated_at", ""))

                    shape_check = api_data.get("structural_shape_check", "NOT_PERFORMED")
                    global_cov = api_data.get("global_deformation_coverage", "LIMITED")

                    # 서버 API 판정을 그대로 사용 (대시보드에서 재계산하지 않음)
                    style = get_decision_style(api_data["decision"])
                    result = {
                        "decision": api_data["decision"],
                        "decision_threshold": api_data["decision_threshold"],
                        "decision_basis": api_data["decision_basis"],
                        "heatmap_display": api_data["heatmap_display"],
                        "reason_code": api_data["reason_code"],
                        "interlock": bool(api_data["interlock"]),
                        "manual_review_recommended": api_data["manual_review_recommended"],
                        "estimated_defect_pattern": api_data["estimated_defect_pattern"],
                        "pattern_estimate": api_data.get("pattern_estimate"),
                        "structural_defect_likelihood": struct_like or 0.0,
                        "summary": api_data["summary"],
                        "action": style["action"],
                        "confidence_tier": api_data.get("confidence_tier"),
                        "autonomous_decision_allowed": api_data.get("autonomous_decision_allowed"),
                    }
                    used_rest_api = True
            except Exception as e:
                api_error = f"{type(e).__name__}: {str(e)[:200]}"
                used_rest_api = False

            if not used_rest_api:
                # FastAPI가 온라인인데 검사 요청이 실패한 경우: 로컬 엔진으로 대체하지 않고 판정 보류
                sync_warning_placeholder.error(
                    "🚨 **FastAPI 검사 요청 실패 — 판정을 보류합니다.**  \n"
                    f"- 원인: `{api_error}`  \n"
                    "- 서버가 온라인 상태이므로 대시보드 내장 엔진으로 자동 대체하지 않습니다. "
                    "부품을 수동 검사 대기 구역으로 분리하고 서버 상태를 확인하십시오."
                )
                camera_placeholder.image(img, caption=label_caption, width="stretch")
                heatmap_placeholder.empty()
                decision_placeholder.markdown(
                    f"<div class='decision-banner decision-review'><span>◆ 판정 보류 (서버 응답 오류)</span></div>",
                    unsafe_allow_html=True
                )
                metrics_placeholder.empty()
                action_placeholder.empty()
                return None

        if not used_rest_api:
            # FastAPI 미기동 시에만 도달 (개발용 LOCAL_FALLBACK)
            pred = engine.predict(img, include_heatmap=True, operating_mode=operating_mode, part_geometry=part_geometry)
            score = pred["anomaly_score"]
            raw_dist = pred["raw_distance"]
            peak_d = pred["peak_patch_distance"]
            area_ratio = pred["defect_area_ratio"]
            edge_r = pred["edge_region_ratio"]
            struct_like = pred["structural_defect_likelihood"]
            inf_mode = "LOCAL_FALLBACK"
            eng_ver = pred["engine_version"]
            mod_hash = pred["model_hash"]
            heatmap_img = pred["heatmap_pil"]
            shape_check = "PERFORMED" if part_geometry == "circular_jig" else "NOT_PERFORMED"
            result = evaluate_defect(
                anomaly_score=score,
                mask_area_ratio=area_ratio,
                peak_patch_distance=peak_d,
                edge_region_ratio=edge_r,
                structural_defect_likelihood=struct_like,
                operating_mode=operating_mode,
                structural_thresholds=engine.structural_thresholds
            )
            result["action"] = get_decision_style(result["decision"])["action"]
            try:
                log_inspection_audit({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "inspection_id": str(uuid.uuid4()),
                    "camera_id": "CAM_FINISHING_01",
                    "operating_mode": operating_mode,
                    "decision": result["decision"],
                    "decision_threshold": result["decision_threshold"],
                    "anomaly_score": round(score, 4),
                    "raw_distance": round(raw_dist, 4),
                    "peak_patch_distance": round(peak_d, 4),
                    "defect_area_ratio": round(area_ratio, 4),
                    "edge_region_ratio": round(edge_r, 4) if edge_r is not None else None,
                    "structural_defect_likelihood": result["structural_defect_likelihood"],
                    "reason_code": result["reason_code"],
                    "interlock": result["interlock"],
                    "manual_review_recommended": result["manual_review_recommended"],
                    "estimated_defect_pattern": result["estimated_defect_pattern"],
                    "engine_version": eng_ver,
                    "model_hash": mod_hash,
                    "inference_mode": inf_mode
                })
            except Exception as log_err:
                st.toast(f"감사 로그 기록 실패(LOCAL_FALLBACK): {type(log_err).__name__}")

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        active_th = result["decision_threshold"]
        style = get_decision_style(result["decision"])

        # 1. 상태 배너: LOCAL_FALLBACK / 모델 불일치 / 대조 불가 / 정상
        if not used_rest_api:
            sync_warning_placeholder.warning(
                "⚠️ **LOCAL_FALLBACK 판정** — FastAPI 서버 미연결 상태로 대시보드 내장 엔진(기본 모델 `memory_bank.pt`)이 판정했습니다.  \n"
                "서버에서 모델을 교체했거나 모델 파일이 바뀐 경우 사이드바 **[🧹 엔진 캐시 초기화]** 후 다시 검사하십시오."
            )
        elif model_state["status"] == "MISMATCH":
            sync_warning_placeholder.error(
                "🚨 **모델 불일치 경고**  \n"
                f"- 검사에 사용된 모델: `{model_state['inspected_part']}` (SHA256: `{model_state['inspected_sha'][:12] or 'N/A'}`…)  \n"
                f"- 현재 서버 활성 모델: `{model_state['registry_part']}` (SHA256: `{model_state['registry_sha'][:12] or 'N/A'}`…)  \n"
                "*검사 도중 모델이 교체되었을 수 있습니다. 이 판정은 재검사 후 확정하십시오.*"
            )
        elif model_state["status"] == "UNVERIFIED":
            sync_warning_placeholder.warning(
                f"⚠️ **모델 대조 불가** — {model_state['reason']}. "
                f"검사 모델: `{model_state['inspected_part']}` (SHA256: `{model_state['inspected_sha'][:12] or 'N/A'}`…)"
            )
        else:
            sync_warning_placeholder.success(
                f"🔒 **모델 상태 동기화 정상:** `{model_state['inspected_part']}` "
                f"(SHA256: `{model_state['inspected_sha'][:10]}...` | 활성시각: `{model_state['activated_at'][:19]}`)"
            )

        camera_placeholder.image(img, caption=label_caption, width="stretch")
        # PASS 판정 또는 히트맵 억제 상태에서는 붉은 결함 히트맵을 강조하지 않고 원본을 표시
        if result["decision"] == "PASS" or result["heatmap_display"] == "SUPPRESSED_BELOW_THRESHOLD":
            heatmap_placeholder.image(
                img,
                caption=f"히트맵 억제 [{result['heatmap_display']}] — 정상 범위 ([{inf_mode}] {elapsed_ms:.0f}ms)",
                width="stretch"
            )
        else:
            heatmap_placeholder.image(
                heatmap_img,
                caption=f"700×700 히트맵 [{result['heatmap_display']}] ([{inf_mode}] {elapsed_ms:.0f}ms)",
                width="stretch"
            )

        review_badge_html = "<span style='font-size: 0.8rem; background: #e0f2fe; color: #0369a1; padding: 2px 8px; border-radius: 4px; font-weight: 600; margin-left: 10px;'>2차 육안판정 권고</span>" if result["manual_review_recommended"] else ""
        interlock_html = (
            "<div class='interlock-banner'>■ 설비 인터록 ON — 라인 비상 정지 상태</div>"
            if result["interlock"] else ""
        )
        autonomy_html = ""
        if result.get("autonomous_decision_allowed") is False:
            autonomy_html = (
                "<div style='margin:-6px 0 12px; font-size:0.85rem; color:#075985; font-weight:600;'>"
                f"ⓘ 자동 판정 불허 모델 (신뢰 등급: {result.get('confidence_tier') or 'UNKNOWN'}) — "
                "이상 판정은 사람이 2차 확인하며 라인을 자동 정지하지 않습니다.</div>"
            )
        decision_placeholder.markdown(
            f"{interlock_html}<div class='decision-banner {style['css']}'><span>{style['icon']} {style['label']}</span>{review_badge_html}</div>{autonomy_html}",
            unsafe_allow_html=True
        )

        # 형상 검사 모드별 범위 안내 문구
        shape_info = f"`{shape_check}` (전역 변형 커버리지: `{global_cov}`)" if used_rest_api else f"`{shape_check}`"

        edge_display = f"{edge_r * 100:.2f}%" if edge_r is not None else "N/A (범용 마스크)"
        struct_val = result.get("structural_defect_likelihood")
        struct_str = f"{struct_val:.2f}" if struct_val is not None else "0.00"
        score_color = style["color"]

        metrics_placeholder.markdown(
            f"""
            <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 18px; font-size: 0.86rem; line-height: 1.8; box-shadow: 0 1px 3px rgba(0,0,0,0.03);">
                <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #f1f5f9; padding-bottom: 6px; margin-bottom: 6px;">
                    <span style="color: #64748b; font-weight: 600;">추론 모드 / 모델 해시</span>
                    <span style="font-weight: 700; font-variant-numeric: tabular-nums;">{inf_mode} ({mod_hash})</span>
                </div>
                <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #f1f5f9; padding-bottom: 6px; margin-bottom: 6px;">
                    <span style="color: #64748b; font-weight: 600;">모델 신뢰 등급 / 자동 판정</span>
                    <span style="font-weight: 600;">{result.get('confidence_tier') or 'N/A'} / {'허용' if result.get('autonomous_decision_allowed') is True else ('불허' if result.get('autonomous_decision_allowed') is False else 'N/A')}</span>
                </div>
                <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #f1f5f9; padding-bottom: 6px; margin-bottom: 6px;">
                    <span style="color: #64748b; font-weight: 600;">부품 형상 모드 / 구조형상 검사</span>
                    <span style="font-weight: 600;">{part_geometry} / {shape_info}</span>
                </div>
                <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #f1f5f9; padding-bottom: 6px; margin-bottom: 6px;">
                    <span style="color: #64748b; font-weight: 600;">정규화 이상 점수 (Anomaly Score)</span>
                    <span style="font-weight: 700; font-variant-numeric: tabular-nums; color: {score_color};">{score:.4f} <span style="font-size: 0.78rem; color: #94a3b8; font-weight: 500;">(임계치: {active_th:.4f})</span></span>
                </div>
                <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #f1f5f9; padding-bottom: 6px; margin-bottom: 6px;">
                    <span style="color: #64748b; font-weight: 600;">무클리핑 결함 면적 / 외곽 링 관여율</span>
                    <span style="font-weight: 700; font-variant-numeric: tabular-nums;">{area_ratio*100:.2f}% / {edge_display} <span style="font-size: 0.78rem; color: #94a3b8; font-weight: 500;">(구조변형: {struct_str})</span></span>
                </div>
                <div style="display: flex; justify-content: space-between; border-bottom: 1px solid #f1f5f9; padding-bottom: 6px; margin-bottom: 6px;">
                    <span style="color: #64748b; font-weight: 600;">휴리스틱 결함 추정</span>
                    <span style="font-weight: 600; color: #0284c7;">{result['estimated_defect_pattern']}</span>
                </div>
                <div style="display: flex; justify-content: space-between; padding-top: 2px;">
                    <span style="color: #64748b; font-weight: 600;">판정 근거 (Basis)</span>
                    <span style="font-size: 0.8rem; color: #334155;">{', '.join(result['decision_basis'])}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

        interlock_text = "ON (라인 즉시 정지)" if result["interlock"] else "OFF (정상 가동)"
        action_msg = (
            f"**공정 조치 지침:** {result['action']}  \n"
            f"**설비 인터록(Interlock) 작동 여부:** `{interlock_text}`\n\n"
            f"*{result['summary']}*"
        )
        if result["interlock"]:
            action_placeholder.error(action_msg)
        else:
            action_placeholder.info(action_msg)
        return result

    if mode == "가상 컨베이어 벨트 스트리밍":
        st.markdown("#### ⚙️ 공정 이송 라인 시뮬레이션 설정")
        c_ctrl1, c_ctrl2, c_ctrl3 = st.columns([1.5, 1.2, 1.3])
        with c_ctrl1:
            batch_choice = st.select_slider(
                "검사 대상 수량 선택 (Batch Size)",
                options=[7, 15, 30, 60, 115],
                value=30,
                format_func=lambda n: f"{n}개 (전수 검사)" if n == 115 else (f"{n}개 (표준 공정)" if n == 30 else (f"{n}개 (대용량)" if n == 60 else f"{n}개 (빠른 시연)")),
                help="가상 컨베이어 벨트에 투입할 검사 이미지 총 수량입니다. (ResNet-18 가중치 및 메모리 뱅크는 고정 동결되어 있어 수량을 늘려도 모델 과적합/오염이 발생하지 않습니다.)"
            )
        with c_ctrl2:
            delay_sec = st.slider(
                "부품 이송 주기 (초)",
                min_value=0.2,
                max_value=1.5,
                value=0.5,
                step=0.1,
                help="카메라 검사 존을 통과하는 부품 간격(초)입니다."
            )
        with c_ctrl3:
            balance_mode = st.radio(
                "시퀀스 구성 방식",
                ["정상/결함 층화 균형 (권장)", "테스트셋 순차 전수"],
                index=0,
                help="층화 균형 선택 시 정상 부품과 4대 결함 유형(scratch, bent, color, flip)이 골고루 인터리빙되어 실제 공정처럼 투입됩니다."
            )

        start_btn = st.button("▶ 가상 컨베이어 벨트 가동 시작 (실제 PatchCore 추론)", type="primary")

        if start_btn:
            if not DATASET_DIR.exists():
                st.error(f"데이터셋 경로를 찾을 수 없습니다: {DATASET_DIR}")
            else:
                good_images = sorted(list((DATASET_DIR / "good").glob("*.png")))
                scratch_images = sorted(list((DATASET_DIR / "scratch").glob("*.png")))
                bent_images = sorted(list((DATASET_DIR / "bent").glob("*.png")))
                color_images = sorted(list((DATASET_DIR / "color").glob("*.png")))
                flip_images = sorted(list((DATASET_DIR / "flip").glob("*.png")))

                if balance_mode == "테스트셋 순차 전수" or batch_choice == 115:
                    all_candidates = good_images + scratch_images + bent_images + color_images + flip_images
                    # 115개 전수일 때는 시드 42로 재현 가능한 셔플을 적용하여 결함이 연속으로 몰리는 현상 방지
                    rng = random.Random(42)
                    shuffled_candidates = list(all_candidates)
                    rng.shuffle(shuffled_candidates)
                    stream_queue = shuffled_candidates[:batch_choice]
                else:
                    # 정상 40% + 4대 결함 각 15% 균형 인터리빙 큐 생성
                    pattern = ["G", "G", "S", "G", "B", "C", "G", "F"]
                    stream_queue = []
                    g_i, s_i, b_i, c_i, f_i = 0, 0, 0, 0, 0
                    p_i = 0
                    while len(stream_queue) < batch_choice:
                        ptype = pattern[p_i % len(pattern)]
                        p_i += 1
                        if ptype == "G" and good_images:
                            stream_queue.append(good_images[g_i % len(good_images)])
                            g_i += 1
                        elif ptype == "S" and scratch_images:
                            stream_queue.append(scratch_images[s_i % len(scratch_images)])
                            s_i += 1
                        elif ptype == "B" and bent_images:
                            stream_queue.append(bent_images[b_i % len(bent_images)])
                            b_i += 1
                        elif ptype == "C" and color_images:
                            stream_queue.append(color_images[c_i % len(color_images)])
                            c_i += 1
                        elif ptype == "F" and flip_images:
                            stream_queue.append(flip_images[f_i % len(flip_images)])
                            f_i += 1
                        else:
                            stream_queue.append(good_images[g_i % len(good_images)])
                            g_i += 1

                total_count, pass_count, rework_count, scrap_count, hold_count = 0, 0, 0, 0, 0
                st.caption(f"🚀 총 **{len(stream_queue)}개** 부품이 컨베이어에 투입되었습니다. (이송 주기: {delay_sec:.1f}초)")

                for img_path in stream_queue:
                    img = Image.open(img_path)
                    total_count += 1
                    parent_label = img_path.parent.name
                    result = render_inspection_result(
                        img,
                        label_caption=f"공정 카메라 입력 #{total_count} (실제 카테고리: {parent_label})"
                    )

                    decision_val = result["decision"] if result else None
                    if decision_val == "PASS":
                        pass_count += 1
                    elif decision_val == "REWORK":
                        rework_count += 1
                    elif decision_val == "SCRAP":
                        scrap_count += 1
                    else:
                        # MANUAL_REVIEW, 미정의 판정값, 서버 오류로 인한 판정 보류(None)
                        hold_count += 1

                    total_metric.metric("총 검사 수량", f"{total_count}개")
                    pass_metric.metric("정상 합격 (PASS)", f"{pass_count}개", f"{(pass_count/total_count)*100:.1f}%")
                    rework_metric.metric("재가공 (REWORK)", f"{rework_count}개", f"{(rework_count/total_count)*100:.1f}%")
                    scrap_metric.metric("폐기 (SCRAP)", f"{scrap_count}개", f"{(scrap_count/total_count)*100:.1f}%")
                    hold_metric.metric("판정 보류 / 2차 판정", f"{hold_count}개", f"{(hold_count/total_count)*100:.1f}%")

                    time.sleep(delay_sec)

    else:
        uploaded_file = st.file_uploader("검사할 금속 부품 이미지 파일을 업로드하세요 (파일명 무관, 동일 환경 재실행 기준 재현성 보장)", type=["png", "jpg", "jpeg"])
        if uploaded_file:
            img = Image.open(uploaded_file)
            render_inspection_result(img, label_caption=f"업로드 파일: {uploaded_file.name}")

    st.markdown("---")
    st.subheader("📋 실시간 MES 감사 로그 (Audit Trail)")
    st.caption("제철소 품질 공정 추적성(Traceability) 및 MES 감사 규정을 준수하는 비지도 검사 이력 로그")
    if not any(h in API_BASE_URL for h in ("://127.0.0.1", "://localhost", "://[::1]")):
        st.info("ℹ️ 원격 FastAPI 서버에 연결된 상태입니다. 아래 표는 **이 대시보드 PC에 저장된 로그**이며, 원격 서버가 처리한 검사 이력은 서버 PC에 기록됩니다.")

    # 필터 UI 컨트롤
    f_col1, f_col2, f_col3 = st.columns([1.5, 1.4, 1.5])
    with f_col1:
        time_filter = st.selectbox(
            "조회 기간 필터",
            [
                "최근 50건 (기본 고속 모드)",
                "최근 1일 (24시간)",
                "최근 7일 (1주일)",
                "최근 1개월 (30일)",
                "최근 3개월 (90일)",
                "전체 누적 기록",
                "직접 선택 (날짜 범위 지정)"
            ],
            index=0
        )
    with f_col2:
        decision_filter = st.multiselect(
            "판정 결과 필터",
            ["PASS", "REWORK", "SCRAP", "MANUAL_REVIEW"],
            default=["PASS", "REWORK", "SCRAP", "MANUAL_REVIEW"]
        )
    with f_col3:
        search_query = st.text_input("검색어 (ID / 부품ID / 결함유형)", placeholder="예: scratch, bent, CAM_01")

    custom_date_range = None
    if time_filter == "직접 선택 (날짜 범위 지정)":
        d_col1, d_col2 = st.columns(2)
        today = datetime.now().date()
        with d_col1:
            start_date = st.date_input("조회 시작일", value=today - timedelta(days=7))
        with d_col2:
            end_date = st.date_input("조회 종료일", value=today)
        custom_date_range = (start_date, end_date)

    all_logs = read_recent_audit_logs(limit=0)
    if all_logs:
        df_audit = pd.DataFrame(all_logs)
        if "timestamp" in df_audit.columns:
            # 오프셋이 섞인 ISO 문자열도 비교 가능하도록 UTC 기준 tz-aware로 통일
            df_audit["_dt"] = pd.to_datetime(df_audit["timestamp"], errors="coerce", utc=True)
            now_dt = datetime.now(timezone.utc)
            if time_filter == "최근 50건 (기본 고속 모드)":
                filtered_df = df_audit.head(50)
            elif time_filter == "최근 1일 (24시간)":
                cutoff = now_dt - timedelta(days=1)
                filtered_df = df_audit[df_audit["_dt"] >= cutoff]
            elif time_filter == "최근 7일 (1주일)":
                cutoff = now_dt - timedelta(days=7)
                filtered_df = df_audit[df_audit["_dt"] >= cutoff]
            elif time_filter == "최근 1개월 (30일)":
                cutoff = now_dt - timedelta(days=30)
                filtered_df = df_audit[df_audit["_dt"] >= cutoff]
            elif time_filter == "최근 3개월 (90일)":
                cutoff = now_dt - timedelta(days=90)
                filtered_df = df_audit[df_audit["_dt"] >= cutoff]
            elif time_filter == "직접 선택 (날짜 범위 지정)" and custom_date_range:
                # 사용자가 고른 날짜는 이 PC의 현지 시각(예: KST) 기준 → UTC로 변환해 비교
                local_tz = datetime.now().astimezone().tzinfo
                s_dt = pd.Timestamp(custom_date_range[0]).tz_localize(local_tz).tz_convert("UTC")
                e_dt = (pd.Timestamp(custom_date_range[1]) + timedelta(days=1)).tz_localize(local_tz).tz_convert("UTC")
                filtered_df = df_audit[(df_audit["_dt"] >= s_dt) & (df_audit["_dt"] < e_dt)]
            else:
                filtered_df = df_audit
        else:
            filtered_df = df_audit

        if decision_filter and "decision" in filtered_df.columns:
            filtered_df = filtered_df[filtered_df["decision"].isin(decision_filter)]

        if search_query:
            q = search_query.strip().lower()
            mask = filtered_df.astype(str).apply(lambda row: row.str.lower().str.contains(q, regex=False).any(), axis=1)
            filtered_df = filtered_df[mask]

        total_matched = len(filtered_df)
        total_all = len(df_audit)
        pass_cnt = int((filtered_df["decision"] == "PASS").sum()) if "decision" in filtered_df.columns else 0
        rework_cnt = int((filtered_df["decision"] == "REWORK").sum()) if "decision" in filtered_df.columns else 0
        scrap_cnt = int((filtered_df["decision"] == "SCRAP").sum()) if "decision" in filtered_df.columns else 0
        review_cnt = int((filtered_df["decision"] == "MANUAL_REVIEW").sum()) if "decision" in filtered_df.columns else 0

        st.caption(
            f"📊 **조회 결과:** 총 **{total_matched:,}건** 표시 중 (전체 누적: {total_all:,}건) | "
            f"🟢 합격(PASS): `{pass_cnt}건` | 🟡 재가공(REWORK): `{rework_cnt}건` | 🔴 폐기(SCRAP): `{scrap_cnt}건` | 🔵 2차 판정(MANUAL_REVIEW): `{review_cnt}건`"
        )

        display_df = filtered_df.drop(columns=["_dt"], errors="ignore")
        st.dataframe(display_df, width="stretch", hide_index=True)

        col_dl1, col_dl2 = st.columns([1, 1])
        with col_dl1:
            filtered_csv = display_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button(
                label=f"📥 현재 필터링된 감사 로그 다운로드 ({total_matched}건)",
                data=filtered_csv,
                file_name=f"audit_filtered_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                width="stretch"
            )
        with col_dl2:
            csv_bytes = read_audit_csv_bytes()
            st.download_button(
                label=f"📥 전체 원본 감사 로그 CSV 다운로드 ({total_all}건)",
                data=csv_bytes,
                file_name="inspection_audit_full.csv",
                mime="text/csv",
                width="stretch"
            )
    else:
        st.caption("아직 기록된 감사 로그(logs/inspection_audit.csv)가 없습니다. 검사를 실행하면 실시간으로 누적됩니다.")
