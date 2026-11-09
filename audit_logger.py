"""
포스코 AI 해커톤 - 과제 B: 스마트팩토리 MES 감사 로그(Audit Trail) 모듈
파일명: audit_logger.py

핵심 기능 및 보안 정책:
1. 실시간 검사 결과를 logs/inspection_audit.csv에 영속 기록 (UTF-8 with BOM 호환 가능, 표준 UTF-8 CSV)
2. 동시 요청(Thread-safe) 보장: 프로세스 내 threading.Lock()으로 동시 20건 이상 요청 시 행 깨짐·유실 원천 차단
3. 민감 데이터 및 대용량 이미지 배제: 원본 이미지 바이트, heatmap_base64, heatmap_pil, 개인정보(PII) 절대 미저장
4. 엑셀 수식 인젝션(CSV Formula Injection) 방어: '=', '+', '-', '@', '\t', '\r'로 시작하는 문자열 앞에 작은따옴표(') 자동 프리픽스
5. 테스트용 Mock 요청(mock=True)은 운영 감사 로그 기록에서 자동 제외
"""

from pathlib import Path
import csv
import threading
import time
import os
from contextlib import contextmanager
from typing import Any

BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
AUDIT_CSV_PATH = LOG_DIR / "inspection_audit.csv"
ACTIVATION_CSV_PATH = LOG_DIR / "model_activation_audit.csv"


def get_audit_csv_path() -> Path:
    """AUDIT_LOG_DIR 환경변수가 설정된 경우(예: 자동화 테스트) 해당 격리 경로의 CSV를 반환."""
    custom_dir = os.getenv("AUDIT_LOG_DIR")
    if custom_dir:
        return Path(custom_dir) / "inspection_audit_test.csv"
    return AUDIT_CSV_PATH


def get_activation_csv_path() -> Path:
    """AUDIT_LOG_DIR 환경변수가 설정된 경우 해당 격리 경로의 모델 활성화 CSV를 반환."""
    custom_dir = os.getenv("AUDIT_LOG_DIR")
    if custom_dir:
        return Path(custom_dir) / "model_activation_audit_test.csv"
    return ACTIVATION_CSV_PATH

_AUDIT_THREAD_LOCK = threading.Lock()
_ACTIVATION_THREAD_LOCK = threading.Lock()

try:
    import msvcrt
    def _platform_lock(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

    def _platform_unlock(f):
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
except ImportError:
    try:
        import fcntl
        def _platform_lock(f):
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)

        def _platform_unlock(f):
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
    except ImportError:
        def _platform_lock(f): pass
        def _platform_unlock(f): pass


@contextmanager
def interprocess_file_lock(
    csv_path: Path,
    timeout: float = 3.0,
    poll_interval: float = 0.02,
    hard_timeout: float = 15.0
):
    """
    멀티 프로세스(FastAPI 서버 + Streamlit 대시보드 동시 실행 환경) 파일 쓰기 유실 방지.
    스레드 락과 OS 레벨 파일 락을 결합하여 동시 다중 프로세스 쓰기 충돌을 원천 차단함.
    hard_timeout 안에 락을 얻지 못하면 락 없이 진행하지 않고 TimeoutError를 발생시킴.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file_path = csv_path.with_suffix(".lock")
    start_t = time.perf_counter()
    acquired = False

    while not acquired:
        try:
            # 원자적 배타 생성 (O_CREAT | O_EXCL)
            fd = os.open(str(lock_file_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            acquired = True
        except (FileExistsError, PermissionError):
            # Windows는 다른 프로세스가 락 파일을 삭제하는 중이면 PermissionError를 낸다. 경합과 동일하게 대기한다.
            waited = time.perf_counter() - start_t
            if waited > hard_timeout:
                raise TimeoutError(f"감사 로그 락 획득 실패: {lock_file_path.name}")
            if waited > timeout:
                # 타임아웃 시 오래된 락 파일 정리 후 진입 시도
                try:
                    if lock_file_path.exists() and (time.time() - lock_file_path.stat().st_mtime > 5.0):
                        lock_file_path.unlink(missing_ok=True)
                except Exception:
                    pass
            time.sleep(poll_interval)

    try:
        yield
    finally:
        if acquired:
            try:
                os.close(fd)
                lock_file_path.unlink(missing_ok=True)
            except Exception:
                pass

AUDIT_COLUMNS = [
    "timestamp",
    "inspection_id",
    "camera_id",
    "part_id",
    "operating_mode",
    "decision",
    "decision_threshold",
    "anomaly_score",
    "raw_distance",
    "peak_patch_distance",
    "defect_area_ratio",
    "edge_region_ratio",
    "structural_defect_likelihood",
    "reason_code",
    "interlock",
    "manual_review_recommended",
    "estimated_defect_pattern",
    "engine_version",
    "model_hash",
    "inference_mode"
]

ACTIVATION_COLUMNS = [
    "timestamp",
    "part_id",
    "status",
    "reason",
    "expected_sha256",
    "actual_sha256",
    "model_hash"
]

FORBIDDEN_KEYS = {"heatmap_base64", "heatmap_pil", "file", "image", "raw_bytes"}
FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_value(val: Any) -> str | float | int | bool:
    """
    CSV 수식 인젝션(Formula Injection) 방지 및 개행 문자 정제:
    문자열이 '=', '+', '-', '@', '\t', '\r'로 시작할 경우 앞에 작은따옴표(')를 추가하여
    Excel/스프레드시트에서 수식으로 실행되지 않도록 차단.
    """
    if val is None:
        return ""
    if isinstance(val, (bool, int, float)):
        return val
    s = str(val).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    if s.startswith(FORMULA_INJECTION_PREFIXES):
        return "'" + s
    return s


def log_inspection_audit(payload: dict[str, Any], csv_path: Path | None = None) -> bool:
    """
    단일 검사 응답(payload)을 감사 로그 CSV에 기록.
    - mock 요청(payload.get("mock") is True 또는 inference_mode == "MOCK_TEST_OVERRIDE")은 기록하지 않고 False 반환.
    - 이미지·Base64 데이터는 절대 저장하지 않음.
    """
    if csv_path is None:
        csv_path = get_audit_csv_path()
    if payload.get("mock") is True or payload.get("inference_mode") == "MOCK_TEST_OVERRIDE":
        return False

    row_dict = {}
    for col in AUDIT_COLUMNS:
        if col in FORBIDDEN_KEYS:
            continue
        row_dict[col] = sanitize_csv_value(payload.get(col, ""))

    with _AUDIT_THREAD_LOCK:
        with interprocess_file_lock(csv_path):
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            file_exists = csv_path.exists() and csv_path.stat().st_size > 0
            with open(csv_path, mode="a", encoding="utf-8", newline="") as f:
                _platform_lock(f)
                try:
                    writer = csv.DictWriter(f, fieldnames=AUDIT_COLUMNS)
                    if not file_exists:
                        writer.writeheader()
                    writer.writerow(row_dict)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    _platform_unlock(f)
    return True


def read_recent_audit_logs(limit: int = 50, csv_path: Path | None = None) -> list[dict[str, str]]:
    """
    감사 로그 CSV에서 최근 limit건(기본 50건)을 최신순(역순)으로 반환.
    limit <= 0이면 전체를 반환한다. 대시보드(app.py)가 전체 조회에 사용하므로 동작을 바꾸려면 Role 4와 협의한다.
    """
    if csv_path is None:
        csv_path = get_audit_csv_path()
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []
    with _AUDIT_THREAD_LOCK:
        with interprocess_file_lock(csv_path):
            with open(csv_path, mode="r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
    if limit <= 0:
        return list(reversed(rows))
    return list(reversed(rows[-limit:]))


def read_audit_csv_bytes(csv_path: Path | None = None) -> bytes:
    """
    대시보드 다운로드 버튼용 전체 CSV 바이트(UTF-8 with BOM) 반환.
    """
    if csv_path is None:
        csv_path = get_audit_csv_path()
    if not csv_path.exists():
        return b""
    with _AUDIT_THREAD_LOCK:
        with interprocess_file_lock(csv_path):
            raw_text = csv_path.read_text(encoding="utf-8")
    return raw_text.encode("utf-8-sig")


def log_model_activation_audit(
    part_id: str,
    status: str,
    reason: str,
    expected_sha256: str = "",
    actual_sha256: str = "",
    model_hash: str = "",
    csv_path: Path | None = None
) -> None:
    """
    부품 모델 활성화(Activate) 성공/실패 이벤트를 model_activation_audit.csv에 안전하게 영속 기록.
    """
    if csv_path is None:
        csv_path = get_activation_csv_path()
    from datetime import datetime, timezone
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "part_id": sanitize_csv_value(part_id),
        "status": sanitize_csv_value(status),
        "reason": sanitize_csv_value(reason),
        "expected_sha256": sanitize_csv_value(expected_sha256),
        "actual_sha256": sanitize_csv_value(actual_sha256),
        "model_hash": sanitize_csv_value(model_hash)
    }
    with _ACTIVATION_THREAD_LOCK:
        with interprocess_file_lock(csv_path):
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            file_exists = csv_path.exists() and csv_path.stat().st_size > 0
            with open(csv_path, mode="a", encoding="utf-8", newline="") as f:
                _platform_lock(f)
                try:
                    writer = csv.DictWriter(f, fieldnames=ACTIVATION_COLUMNS)
                    if not file_exists:
                        writer.writeheader()
                    writer.writerow(row)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    _platform_unlock(f)
