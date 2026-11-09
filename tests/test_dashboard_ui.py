"""
[Role 4] Streamlit 관제 대시보드(app.py) UI 동작 검증 (streamlit.testing AppTest, 헤드리스)
파일명: tests/test_dashboard_ui.py

FastAPI 응답은 httpx.get / httpx.post 를 테스트 더블로 교체해 재현한다 (실제 서버·외부 네트워크 불필요).
LOCAL_FALLBACK 시나리오만 실제 PatchCoreEngine 추론을 사용한다.

검증 항목
 U1. compare_model_state / get_decision_style 단위 동작
 U2. FastAPI 온라인 + 모델 일치  -> '모델 상태 동기화 정상' 배너
 U3. FastAPI 온라인 + 모델 SHA256 불일치 -> '🚨 모델 불일치 경고' 배너
 U4. FastAPI 온라인 + 검사 API 500 -> 판정 보류, 로컬 엔진 미호출(무폴백)
 U5. FastAPI 미기동 -> LOCAL_FALLBACK 경고(헤더 + 판정별) 및 실제 로컬 추론
 U6. decision=MANUAL_REVIEW -> SCRAP 배너가 아닌 2차 판정 배너, 보류 집계
 U7. decision=SCRAP & interlock=true -> 인터록 비상정지 배너
 U8. decision=PASS -> 히트맵 억제 표시 (붉은 히트맵 미강조)
 U9. 감사 로그 섹션 렌더링 및 MANUAL_REVIEW 필터 옵션 존재
"""

import ast
import base64
import io
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.chdir(BASE_DIR)
os.environ["AUDIT_LOG_DIR"] = tempfile.mkdtemp(prefix="sg_ui_audit_")
os.environ["API_BASE_URL"] = "http://127.0.0.1:8000"

import httpx  # noqa: E402
from PIL import Image  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402
import patchcore_engine  # noqa: E402

# APP_UNDER_TEST 로 다른 app 파일(예: 수정 전 원본)을 지정해 비교 실행 가능
APP = os.environ.get("APP_UNDER_TEST") or str(BASE_DIR / "app.py")
SHA_A = "a" * 64
SHA_B = "b" * 64
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + f"[{name}] {detail}")


class FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def red_png_b64():
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (255, 0, 0)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def make_inspect_payload(decision="PASS", sha=SHA_A, interlock=False, heatmap_display=None, autonomous=True):
    if heatmap_display is None:
        heatmap_display = "SUPPRESSED_BELOW_THRESHOLD" if decision == "PASS" else "ACTIVE_ANOMALY"
    return {
        "confidence_tier": "PRODUCTION_READY" if autonomous else "PILOT_LOW_CONFIDENCE",
        "autonomous_decision_allowed": autonomous,
        "inspection_id": "00000000-0000-4000-8000-000000000000",
        "model_part_id": "metal_nut_default", "part_id": "metal_nut_default",
        "model_sha256": sha, "model_version": "1.0.0", "activated_at": "2026-11-09T00:00:00+00:00",
        "structural_shape_check": "NOT_PERFORMED", "global_deformation_coverage": "LIMITED",
        "decision": decision, "decision_threshold": 0.6, "decision_basis": ["test_basis"],
        "heatmap_display": heatmap_display, "reason_code": "TEST", "anomaly_score": 0.61,
        "raw_distance": 0.45, "peak_patch_distance": 0.5, "defect_area_ratio": 0.01,
        "edge_region_ratio": None, "structural_defect_likelihood": 0.1,
        "estimated_defect_pattern": "TEST_PATTERN", "pattern_estimate": None,
        "manual_review_recommended": False, "interlock": interlock, "summary": "test summary",
        "engine_version": "test", "model_hash": "aaaaaaaaaaaa", "inference_mode": "FASTAPI_REST_SERVER",
        "heatmap_base64": red_png_b64(),
    }


REGISTRY = {
    "active_model": {"part_id": "metal_nut_default", "model_part_id": "metal_nut_default",
                     "model_file": "memory_bank.pt", "model_hash": "aaaaaaaaaaaa", "model_sha256": SHA_A,
                     "model_version": "1.0.0", "activated_at": "2026-11-09T00:00:00+00:00", "raw_threshold": 0.4362,
                     "confidence_tier": "PRODUCTION_READY", "autonomous_decision_allowed": True},
    "available_models": [
        {"part_id": "memory_bank", "is_active": True, "confidence_tier": "PRODUCTION_READY", "sha256": SHA_A},
        {"part_id": "metal_nut_fg", "is_active": False, "confidence_tier": "PRODUCTION_READY", "sha256": SHA_B},
    ],
}


@contextmanager
def fake_api(online=True, inspect_status=200, inspect_payload=None):
    orig_get, orig_post = httpx.get, httpx.post
    calls = {"inspect": 0}

    def _get(url, *a, **k):
        if not online:
            raise httpx.ConnectError("offline (test double)")
        if url.endswith("/health"):
            return FakeResp(200, {"status": "healthy"})
        if url.endswith("/v1/models"):
            return FakeResp(200, REGISTRY)
        return FakeResp(404, {"detail": "not found"})

    def _post(url, *a, **k):
        if not online:
            raise httpx.ConnectError("offline (test double)")
        if url.endswith("/v1/defects/inspect"):
            calls["inspect"] += 1
            return FakeResp(inspect_status, inspect_payload if inspect_payload is not None else {"detail": "server error"})
        return FakeResp(404, {"detail": "not found"})

    httpx.get, httpx.post = _get, _post
    try:
        yield calls
    finally:
        httpx.get, httpx.post = orig_get, orig_post


@contextmanager
def count_local_predict():
    orig = patchcore_engine.PatchCoreEngine.predict
    counter = {"n": 0}

    def wrapped(self, *a, **k):
        counter["n"] += 1
        return orig(self, *a, **k)

    patchcore_engine.PatchCoreEngine.predict = wrapped
    try:
        yield counter
    finally:
        patchcore_engine.PatchCoreEngine.predict = orig


def run_conveyor(batch=7):
    at = AppTest.from_file(APP, default_timeout=240)
    at.session_state["_autostart_attempted"] = True  # 테스트 중 uvicorn 자동 기동 방지
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    at.select_slider[0].set_value(batch)
    at.slider[0].set_value(0.2)
    btn = [b for b in at.button if b.label.startswith("▶")][0]
    btn.click().run()
    return at


def image_captions(at):
    """st.image 캡션은 AppTest에서 일반 텍스트 요소로 잡히지 않으므로 proto에서 직접 수집"""
    caps = []
    try:
        for el in at.get("imgs"):
            for im in getattr(el.proto, "imgs", []):
                caps.append(str(getattr(im, "caption", "")))
    except Exception as e:
        caps.append(f"(caption 수집 실패: {e})")
    return caps


def texts(at):
    out = []
    for coll in (at.error, at.warning, at.success, at.info, at.markdown, at.caption):
        out += [str(e.value) for e in coll]
    out += image_captions(at)
    return "\n".join(out)


def dump(at, label):
    print(f"   --- {label} 디버그: error={[str(e.value)[:90] for e in at.error]}")
    print(f"   --- warning={[str(e.value)[:90] for e in at.warning]}")
    print(f"   --- success={[str(e.value)[:90] for e in at.success]}")
    print(f"   --- image captions={image_captions(at)[:4]}")
    print(f"   --- exceptions={[str(e.value)[:200] for e in at.exception]}")


def metric_value(at, label):
    for m in at.metric:
        if m.label == label:
            return m.value
    return None


def load_pure_functions():
    """app.py에서 순수 함수(compare_model_state, get_decision_style, DECISION_STYLES)만 추출해 실행"""
    tree = ast.parse(Path(APP).read_text(encoding="utf-8"))
    keep = [n for n in tree.body if
            (isinstance(n, ast.FunctionDef) and n.name in ("compare_model_state", "get_decision_style")) or
            (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "DECISION_STYLES" for t in n.targets))]
    ns = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "app_pure", "exec"), ns)
    return ns


def main():
    # U1 ---------------------------------------------------------------
    print(f"APP_UNDER_TEST = {Path(APP).name}")
    ns = load_pure_functions()
    if "compare_model_state" not in ns or "get_decision_style" not in ns:
        check("U1 순수 함수 존재", False, "compare_model_state/get_decision_style 없음")
        cms = lambda *a, **k: {"status": None}  # noqa: E731
        gds = lambda d: {"label": ""}  # noqa: E731
    else:
        cms, gds = ns["compare_model_state"], ns["get_decision_style"]
    reg = REGISTRY["active_model"]
    check("U1a 모델 일치=MATCH", cms({"model_part_id": "metal_nut_default", "model_sha256": SHA_A}, reg)["status"] == "MATCH")
    check("U1b SHA 불일치=MISMATCH", cms({"model_part_id": "metal_nut_default", "model_sha256": SHA_B}, reg)["status"] == "MISMATCH")
    check("U1c part 불일치=MISMATCH", cms({"model_part_id": "other", "model_sha256": SHA_A}, reg)["status"] == "MISMATCH")
    check("U1d 레지스트리 실패=UNVERIFIED", cms({"model_part_id": "x", "model_sha256": SHA_A}, None)["status"] == "UNVERIFIED")
    check("U1e SHA 누락=UNVERIFIED", cms({"model_part_id": "metal_nut_default"}, reg)["status"] == "UNVERIFIED")
    check("U1f MANUAL_REVIEW 스타일", "MANUAL_REVIEW" in gds("MANUAL_REVIEW")["label"] and "SCRAP" not in gds("MANUAL_REVIEW")["label"])
    check("U1g 미정의 판정=확인 필요", "판정 확인 필요" in gds("WEIRD")["label"])

    # U2 ---------------------------------------------------------------
    with fake_api(online=True, inspect_payload=make_inspect_payload("PASS", SHA_A)) as calls, count_local_predict() as lp:
        at = run_conveyor()
        t = texts(at)
        check("U2 FastAPI 온라인 표시", "FastAPI 추론 서버 연결됨" in t and "FASTAPI ONLINE" in t)
        check("U2 모델 일치 배너", "모델 상태 동기화 정상" in t and "모델 불일치 경고" not in t, f"inspect 호출 {calls['inspect']}회")
        check("U2 로컬 엔진 미사용", lp["n"] == 0, f"local predict={lp['n']}")
        # U8: PASS 히트맵 억제
        caps = image_captions(at)
        if not caps:
            # Streamlit 1.66 AppTest는 st.image 캡션을 노출하지 않음 → 실제 브라우저 화면에서 별도 확인
            print("SKIP [U8 PASS 히트맵 억제 표시] AppTest가 이미지 캡션을 노출하지 않아 자동 판정 불가 (실화면 확인 항목)")
        else:
            check("U8 PASS 히트맵 억제 표시", any("히트맵 억제" in c for c in caps), f"captions={caps[:2]}")

    # U3 ---------------------------------------------------------------
    with fake_api(online=True, inspect_payload=make_inspect_payload("REWORK", SHA_B)):
        at = run_conveyor()
        t = texts(at)
        ok3 = "모델 불일치 경고" in t and "metal_nut_default" in t
        check("U3 모델 불일치 경고 배너", ok3)
        if not ok3:
            dump(at, "U3")

    # U4 ---------------------------------------------------------------
    with fake_api(online=True, inspect_status=500) as calls, count_local_predict() as lp:
        at = run_conveyor()
        t = texts(at)
        check("U4 검사 실패 시 판정 보류 배너", "FastAPI 검사 요청 실패" in t and "판정 보류" in t)
        check("U4 로컬 엔진 자동 대체 안 함", lp["n"] == 0 and "LOCAL_FALLBACK 판정" not in t, f"local predict={lp['n']}")
        check("U4 보류 집계(SCRAP 오집계 없음)", metric_value(at, "폐기 (SCRAP)") == "0개" and metric_value(at, "판정 보류 / 2차 판정") == "7개",
              f"SCRAP={metric_value(at, '폐기 (SCRAP)')}, 보류={metric_value(at, '판정 보류 / 2차 판정')}")

    # U5 ---------------------------------------------------------------
    os.environ["API_BASE_URL"] = "http://127.0.0.1:8000"
    with fake_api(online=False), count_local_predict() as lp:
        at = run_conveyor()
        t = texts(at)
        check("U5 헤더 LOCAL_FALLBACK 경고", "LOCAL_FALLBACK" in t and "캐시 초기화" in t)
        check("U5 판정별 LOCAL_FALLBACK 경고", "LOCAL_FALLBACK 판정" in t)
        check("U5 실제 로컬 추론 수행", lp["n"] == 7, f"local predict={lp['n']}")

    # U6 ---------------------------------------------------------------
    with fake_api(online=True, inspect_payload=make_inspect_payload("MANUAL_REVIEW", SHA_A)):
        at = run_conveyor()
        t = texts(at)
        check("U6 MANUAL_REVIEW 배너", "2차 육안 판정 대기 (MANUAL_REVIEW)" in t and "즉시 폐기 (SCRAP)" not in t)
        check("U6 MANUAL_REVIEW를 SCRAP으로 집계 안 함", metric_value(at, "폐기 (SCRAP)") == "0개",
              f"SCRAP={metric_value(at, '폐기 (SCRAP)')}")

    # U7 ---------------------------------------------------------------
    with fake_api(online=True, inspect_payload=make_inspect_payload("SCRAP", SHA_A, interlock=True)):
        at = run_conveyor()
        t = texts(at)
        check("U7 인터록 비상정지 배너", "설비 인터록 ON" in t and "즉시 폐기 (SCRAP)" in t)

    # U10 --------------------------------------------------------------
    with fake_api(online=True, inspect_payload=make_inspect_payload("MANUAL_REVIEW", SHA_A, autonomous=False)):
        at10 = run_conveyor()
        t10 = texts(at10)
        check("U10 자동 판정 불허 모델 안내", "자동 판정 불허 모델" in t10 and "PILOT_LOW_CONFIDENCE" in t10)
        check("U10 사이드바 신뢰 등급 표시", "신뢰 등급" in t10)

    # U11 --------------------------------------------------------------
    # AppTest 세션은 접속자 IP가 없음(= 로컬 접속 아님) → 핫스왑 버튼이 숨겨지고 안내만 보여야 함
    with fake_api(online=True, inspect_payload=make_inspect_payload("PASS", SHA_A)):
        at11 = AppTest.from_file(APP, default_timeout=240)
        at11.session_state["_autostart_attempted"] = True
        at11.run()
        t11 = texts(at11)
        hot_btns = [b for b in at11.button if "핫스왑" in b.label]
        check("U11 원격 접속자 핫스왑 버튼 숨김", not hot_btns and "로컬로 접속한 경우에만" in t11,
              f"hot-swap buttons={len(hot_btns)}")

    # U9 ---------------------------------------------------------------
    subs = [s.value for s in at.subheader]
    ms = [m for m in at.multiselect if m.label == "판정 결과 필터"]
    check("U9 감사 로그 섹션 렌더링", any("감사 로그" in s for s in subs))
    check("U9 MANUAL_REVIEW 필터 옵션", bool(ms) and "MANUAL_REVIEW" in ms[0].options)

    failed = [r for r in RESULTS if not r[1]]
    print(f"\nTOTAL {len(RESULTS)}  PASS {len(RESULTS) - len(failed)}  FAIL {len(failed)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
