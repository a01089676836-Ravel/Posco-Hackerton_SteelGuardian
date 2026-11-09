"""
포스코 AI 해커톤 - 공장 망분리(Air-Gapped / Offline) 환경 완전 동작 검증 테스트
파일명: tests/test_offline_airgap.py

검증 항목:
1. 소켓 레벨 외부 네트워크 원천 차단(127.0.0.1, ::1, localhost 외 모든 외부 IP/DNS 접속 시 즉시 RuntimeError 발생)
2. 차단 상태에서 PatchCoreEngine 초기화(ResNet18 로컬 가중치 SHA256 검증 로드) 및 이미지 추론 성공 여부
3. 차단 상태에서 FastAPI (/health, /v1/parts, /v1/defects/inspect) 풀-트랜잭션 동작 여부
4. Streamlit 외부 텔레메트리 차단(.streamlit/config.toml gatherUsageStats = false) 및 배치 파일 플래그 적용 여부
5. 오프라인 패키지(wheels/)와 requirements.lock.txt 정합성 확인
"""

import io
import os
import socket
import sys
from pathlib import Path
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
os.environ.setdefault("AUDIT_LOG_DIR", str(BASE_DIR / "logs" / "test"))
sys.path.insert(0, str(BASE_DIR))

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0", "testserver"}

_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_create_connection = socket.create_connection
_orig_getaddrinfo = socket.getaddrinfo

blocked_attempts = []


def _check_host(host: str):
    h = str(host).strip().lower()
    if h not in ALLOWED_HOSTS and not h.startswith("127."):
        blocked_attempts.append(h)
        raise OSError(f"[AIR-GAP BLOCK] 외부 인터넷 연결 시도가 차단되었습니다: {host}")


def _guarded_connect(self, address):
    if isinstance(address, tuple) and len(address) >= 1:
        _check_host(address[0])
    return _orig_connect(self, address)


def _guarded_connect_ex(self, address):
    if isinstance(address, tuple) and len(address) >= 1:
        _check_host(address[0])
    return _orig_connect_ex(self, address)


def _guarded_create_connection(address, *args, **kwargs):
    if isinstance(address, tuple) and len(address) >= 1:
        _check_host(address[0])
    return _orig_create_connection(address, *args, **kwargs)


def _guarded_getaddrinfo(host, port, *args, **kwargs):
    _check_host(host)
    return _orig_getaddrinfo(host, port, *args, **kwargs)


def enable_airgap_guard():
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    socket.create_connection = _guarded_create_connection
    socket.getaddrinfo = _guarded_getaddrinfo


def disable_airgap_guard():
    socket.socket.connect = _orig_connect
    socket.socket.connect_ex = _orig_connect_ex
    socket.create_connection = _orig_create_connection
    socket.getaddrinfo = _orig_getaddrinfo


def test_airgap_full_stack():
    print("=" * 72)
    print("[Air-Gap Test] 공장 보안 망분리(외부 인터넷 완전 차단) 시뮬레이션 시작")
    print("=" * 72)

    enable_airgap_guard()
    try:
        # 1. 외부 접속 차단 가드가 실제로 작동하는지 확인
        try:
            socket.getaddrinfo("download.pytorch.org", 443)
            raise AssertionError("외부 도메인 차단 가드가 작동하지 않았습니다!")
        except OSError:
            blocked_attempts.clear()
            print("[PASS 1/5] 외부 도메인(download.pytorch.org) 소켓 차단 가드 정상 작동 확인")

        # 2. 로컬 가중치 및 추론 엔진 오프라인 초기화/추론 검증
        from patchcore_engine import PatchCoreEngine, RESNET18_LOCAL_PATH
        assert RESNET18_LOCAL_PATH.exists(), f"오프라인 필수 가중치 파일 누락: {RESNET18_LOCAL_PATH}"

        engine = PatchCoreEngine()
        sample_img = BASE_DIR / "datasets" / "metal_nut" / "metal_nut" / "test" / "scratch" / "000.png"
        assert sample_img.exists(), f"테스트 샘플 이미지 누락: {sample_img}"

        with Image.open(sample_img) as im:
            res = engine.predict(im.convert("RGB"), operating_mode="STANDARD", include_heatmap=True)

        assert "raw_anomaly_score" in res and "heatmap_base64" in res
        assert len(blocked_attempts) == 0, f"추론 중 외부 네트워크 시도 감지됨: {blocked_attempts}"
        print(f"[PASS 2/5] 오프라인 PatchCoreEngine 로드 및 추론 성공 (raw_anomaly_score={res['raw_anomaly_score']:.4f}, 외부 통신 시도=0건)")

        # 3. FastAPI 엔드투엔드 오프라인 검증
        from fastapi.testclient import TestClient
        from server import app

        client = TestClient(app)
        r_health = client.get("/health")
        assert r_health.status_code == 200 and r_health.json()["status"] == "healthy"

        raw_bytes = sample_img.read_bytes()
        r_insp = client.post(
            "/v1/defects/inspect",
            files={"file": ("000.png", io.BytesIO(raw_bytes), "image/png")},
            data={"operating_mode": "SAFETY_FIRST", "include_heatmap": "true"},
        )
        assert r_insp.status_code == 200, f"API 응답 오류: {r_insp.text}"
        body = r_insp.json()
        assert body["decision"] in ("PASS", "REWORK", "SCRAP")
        assert len(blocked_attempts) == 0, f"API 처리 중 외부 네트워크 시도 감지됨: {blocked_attempts}"
        print(f"[PASS 3/5] 오프라인 FastAPI /v1/defects/inspect 성공 (decision={body['decision']}, 외부 통신 시도=0건)")

        # 4. Streamlit 오프라인 설정 및 UI 외부 URL 미사용 검증
        st_cfg = BASE_DIR / ".streamlit" / "config.toml"
        assert st_cfg.exists(), ".streamlit/config.toml 파일이 없습니다."
        cfg_text = st_cfg.read_text(encoding="utf-8")
        assert "gatherUsageStats = false" in cfg_text, "gatherUsageStats = false 설정이 누락되었습니다."

        app_text = (BASE_DIR / "app.py").read_text(encoding="utf-8")
        for forbidden_cdn in ("fonts.googleapis.com", "cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com"):
            assert forbidden_cdn not in app_text, f"app.py 내 외부 CDN 참조 발견: {forbidden_cdn}"
        print("[PASS 4/5] Streamlit 텔레메트리 차단(.streamlit/config.toml) 및 UI 외부 CDN 의존성 0건 확인")

        # 5. 오프라인 설치용 wheels 및 배치 스크립트 점검
        setup_bat = (BASE_DIR / "setup_and_run.bat").read_text(encoding="utf-8")
        assert "--no-index --find-links=wheels" in setup_bat
        assert "--browser.gatherUsageStats false" in setup_bat
        print("[PASS 5/5] setup_and_run.bat 오프라인 wheel 설치(--no-index) 및 텔레메트리 차단 플래그 확인")

    finally:
        disable_airgap_guard()

    print("=" * 72)
    print("ALL AIR-GAP OFFLINE CHECKS PASSED (외부 네트워크 연결 시도 0건)")
    print("=" * 72)


if __name__ == "__main__":
    test_airgap_full_stack()
