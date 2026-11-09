"""
포스코 AI 해커톤 - 실시간 비지도 결함 검사 REST API 서버
(모델 레지스트리, 핫스왑 활성화, 무클리핑 다중 특징 판정, MES 감사 로그 연동)
파일명: server.py
"""

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from pathlib import Path
import hmac
import io
import logging
import os
import re
import uuid
import json
import hashlib
import threading
import torch
from PIL import Image

from rule_engine import evaluate_defect, OPERATING_MODE_THRESHOLDS
from patchcore_engine import PatchCoreEngine, get_engine, load_evaluation_report
from audit_logger import log_inspection_audit, log_model_activation_audit

app = FastAPI(
    title="POSCO Smart Factory AI Defect Inspection API",
    version="1.3.0",
    description="비지도 이상탐지(PatchCore Eq.6-7 N_b(m*) 재가중 + 모델 레지스트리 동적 핫스왑) 기반 금속 부품 결함 실시간 검사 및 공정 제어 API"
)

# CORS 최소화: allow_origins=["*"] 금지, 명시적 로컬 origin만 허용 (credentials 지원)
default_cors_origins = [
    "http://127.0.0.1:8501",
    "http://localhost:8501",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]
env_cors = os.getenv("CORS_ALLOWED_ORIGINS")
if env_cors:
    allowed_origins = [orig.strip() for orig in env_cors.split(",") if orig.strip()]
else:
    allowed_origins = default_cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent
MODELS_DIR = BASE_DIR / "models"
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
ALLOWED_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "testclient"}
SUPPORTED_PART_GEOMETRIES = {"generic", "circular_jig"}
CAMERA_ID_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{1,64}")

# 현장 카메라 해상도·장비 성능에 맞춰 환경변수로 조정한다.
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
MAX_IMAGE_PIXELS = int(os.getenv("MAX_IMAGE_PIXELS", "16000000"))
INFERENCE_WAIT_SEC = float(os.getenv("INFERENCE_WAIT_SEC", "30"))
# ponytail: 대기 요청이 워커 스레드를 점유한다. 동시 40건을 넘는 부하가 생기면 대기열을 별도로 둔다.
_INFERENCE_SLOTS = threading.BoundedSemaphore(int(os.getenv("MAX_CONCURRENT_INFERENCES", "1")))

logger = logging.getLogger("uvicorn.error")


def _apply_model_policy(engine: PatchCoreEngine, meta: dict) -> tuple[str, bool]:
    """모델 메타의 자동 판정 정책을 엔진에 적용하고 (신뢰 등급, 자동 판정 허용 여부)를 반환한다."""
    autonomous = meta.get("autonomous_decision_allowed") is True
    # engine.predict가 이 dict를 evaluate_defect에 그대로 넘기므로, 엔진 수정 없이 룰 엔진까지 정책이 전달된다.
    engine.structural_thresholds = {**engine.structural_thresholds, "autonomous_decision_allowed": autonomous}
    return str(meta.get("confidence_tier", "UNKNOWN")), autonomous


def _read_meta_or_empty(meta_file: Path) -> dict:
    """읽을 수 없는 메타는 빈 dict로 처리해 자동 판정이 불허되도록 한다."""
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


_ENGINE_LOCK = threading.RLock()
_ACTIVE_PART_ID: str = "metal_nut_default"
_ACTIVE_MODEL_PATH: Path = MODELS_DIR / "memory_bank.pt"
_ACTIVE_ENGINE: PatchCoreEngine = get_engine()
_ACTIVE_ACTIVATED_AT: str = datetime.now(timezone.utc).isoformat()
_ACTIVE_MODEL_SHA256: str = hashlib.sha256(_ACTIVE_MODEL_PATH.read_bytes()).hexdigest() if _ACTIVE_MODEL_PATH.exists() else ""
_ACTIVE_MODEL_VERSION: str = "1.0.0"
_ACTIVE_CONFIDENCE_TIER, _ACTIVE_AUTONOMOUS = _apply_model_policy(_ACTIVE_ENGINE, _read_meta_or_empty(_ACTIVE_MODEL_PATH.with_suffix(".meta.json")))


@app.middleware("http")
async def reject_oversized_body(request: Request, call_next):
    """Content-Length가 한도를 넘으면 본문을 읽기 전에 거부한다."""
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_UPLOAD_BYTES:
        return JSONResponse(status_code=413, content={"detail": "PAYLOAD_TOO_LARGE: 요청 크기가 허용 한도를 초과했습니다."})
    return await call_next(request)


def _admin_key_matches(provided: str, expected: str) -> bool:
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


class ModelActivationRequest(BaseModel):
    part_id: str = Field(..., description="활성화할 부품 모델 식별자 (예: custom_part_bank 또는 memory_bank)")
    expected_sha256: str = Field(..., description="활성화 대상 .pt 파일의 기대 SHA256 체크섬 (소문자)")


@app.get("/health")
async def health_check():
    """서버 상태 및 현재 활성화된 PatchCore 모델 가용성·해시 점검"""
    with _ENGINE_LOCK:
        eng = _ACTIVE_ENGINE
        part_id = _ACTIVE_PART_ID
        path_str = str(_ACTIVE_MODEL_PATH.name)
        confidence_tier = _ACTIVE_CONFIDENCE_TIER
        autonomous = _ACTIVE_AUTONOMOUS
    return {
        "status": "healthy",
        "active_part_id": part_id,
        "active_model_file": path_str,
        "confidence_tier": confidence_tier,
        "autonomous_decision_allowed": autonomous,
        "model": "PatchCore-ResNet18-Coreset-Eq7",
        "engine_version": eng.engine_version,
        "model_hash": eng.model_hash,
        "threshold_source": eng.threshold_source,
        "raw_threshold": eng.raw_threshold,
        "version": "1.3.0",
        "device": "cpu",
        "benchmark_metrics": eng.metrics,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/v1/models")
def get_model_registry():
    """현재 활성화된 모델 정보 및 models 디렉터리 내 사용 가능 모델 목록 반환"""
    with _ENGINE_LOCK:
        active_info = {
            "part_id": _ACTIVE_PART_ID,
            "model_part_id": _ACTIVE_PART_ID,
            "model_file": _ACTIVE_MODEL_PATH.name,
            "model_hash": _ACTIVE_ENGINE.model_hash,
            "model_sha256": _ACTIVE_MODEL_SHA256,
            "model_version": _ACTIVE_MODEL_VERSION,
            "activated_at": _ACTIVE_ACTIVATED_AT,
            "confidence_tier": _ACTIVE_CONFIDENCE_TIER,
            "autonomous_decision_allowed": _ACTIVE_AUTONOMOUS,
            "raw_threshold": _ACTIVE_ENGINE.raw_threshold,
            "engine_version": _ACTIVE_ENGINE.engine_version,
            "threshold_source": _ACTIVE_ENGINE.threshold_source,
            "device": "cpu"
        }

    available = []
    if MODELS_DIR.exists():
        for pt_file in sorted(MODELS_DIR.glob("*.pt")):
            meta_file = pt_file.with_suffix(".meta.json")
            sha256_hash = hashlib.sha256(pt_file.read_bytes()).hexdigest()
            meta_data = {}
            if meta_file.exists():
                try:
                    meta_data = json.loads(meta_file.read_text(encoding="utf-8"))
                except Exception:
                    meta_data = {}
            part_stem = pt_file.stem
            is_active = (part_stem == _ACTIVE_PART_ID or (pt_file.name == "memory_bank.pt" and _ACTIVE_PART_ID in ("metal_nut_default", "memory_bank")))
            available.append({
                "part_id": part_stem,
                "filename": pt_file.name,
                "sha256": sha256_hash,
                "size_bytes": pt_file.stat().st_size,
                "has_meta_json": meta_file.exists(),
                "confidence_tier": meta_data.get("confidence_tier", "PRODUCTION_READY" if pt_file.name == "memory_bank.pt" else "UNKNOWN"),
                "is_active": is_active,
                "split_overlap": meta_data.get("split", {}).get("bank_validation_overlap", 0 if pt_file.name == "memory_bank.pt" else None)
            })

    return {
        "active_model": active_info,
        "available_models": available,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.post("/v1/models/activate")
def activate_model(payload: ModelActivationRequest, request: Request):
    """
    신규 부품 모델을 검증(경로 순회 방지, SHA256, meta.json 필수, 교집합 0%, 로드 무결성) 후
    스레드 안전 락을 통해 실시간으로 활성화(핫스왑 교체).
    보안 정책:
    - part_id는 영문, 숫자, 밑줄, 하이픈만 허용하며 절대경로 및 상위 디렉터리 접근(..)을 원천 차단.
    - models 디렉터리 내부 파일만 활성화 가능.
    - .meta.json 파일이 반드시 존재해야 하며, 검증셋 교집합(leakage) 0%여야 함.
    - 외부 네트워크 호출 차단 (로컬 루프백 호스트 또는 X-Admin-Key 인증 필요).
    """
    # x-forwarded-for는 클라이언트가 위조할 수 있으므로 인가 판단에 직접 사용하지 않는다.
    # 신뢰할 프록시 처리는 uvicorn의 --forwarded-allow-ips 설정에 맡긴다.
    client_host = request.client.host if request.client else ""

    admin_key_hdr = request.headers.get("x-admin-key")
    expected_admin_key = os.getenv("ADMIN_API_KEY") or os.getenv("ADMIN_KEY")
    allow_remote = os.getenv("ALLOW_REMOTE_ACTIVATION", "0").lower() in ("1", "true", "yes")

    part_id = payload.part_id.strip()
    expected_sha = payload.expected_sha256.strip().lower()

    def audit(status: str, reason: str, **fields) -> None:
        # 검증 전 입력도 기록되므로 길이를 제한하고, CSV 스키마 변경 없이 호출자를 reason에 남긴다.
        log_model_activation_audit(
            part_id=part_id[:128],
            status=status,
            reason=f"{reason}|client={client_host[:64]}",
            expected_sha256=expected_sha[:64],
            **fields
        )

    # 원격 모델 활성화 인증 및 권한 검증 (세부 에러 메시지 분기 및 감사 로그 기록)
    if client_host not in ALLOWED_LOOPBACK_HOSTS:
        if not allow_remote:
            audit("FAILED","REMOTE_ACTIVATION_DISABLED")
            raise HTTPException(
                status_code=403,
                detail="FORBIDDEN: REMOTE_ACTIVATION_DISABLED - 원격 모델 활성화가 비활성화되어 있습니다 (ALLOW_REMOTE_ACTIVATION=0)."
            )
        if not expected_admin_key:
            audit("FAILED","ADMIN_KEY_NOT_CONFIGURED")
            raise HTTPException(
                status_code=403,
                detail="FORBIDDEN: ADMIN_KEY_NOT_CONFIGURED - 서버에 ADMIN_API_KEY 환경변수가 설정되지 않아 원격 활성화가 차단되었습니다."
            )
        if not admin_key_hdr:
            audit("FAILED","ADMIN_KEY_REQUIRED")
            raise HTTPException(
                status_code=403,
                detail="FORBIDDEN: ADMIN_KEY_REQUIRED - 원격 모델 활성화를 위해 x-admin-key 헤더가 필요합니다."
            )
        if not _admin_key_matches(admin_key_hdr, expected_admin_key):
            audit("FAILED","ADMIN_KEY_MISMATCH")
            raise HTTPException(
                status_code=403,
                detail="FORBIDDEN: ADMIN_KEY_MISMATCH - 유효하지 않은 x-admin-key 헤더입니다."
            )
    else:
        # 로컬 루프백 호출: ADMIN_API_KEY가 설정되어 있고 헤더를 보냈을 때 불일치 시 차단
        if expected_admin_key and admin_key_hdr and not _admin_key_matches(admin_key_hdr, expected_admin_key):
            audit("FAILED","ADMIN_KEY_MISMATCH")
            raise HTTPException(
                status_code=403,
                detail="FORBIDDEN: ADMIN_KEY_MISMATCH - 유효하지 않은 x-admin-key 헤더입니다."
            )

    if not part_id:
        audit("FAILED","EMPTY_PART_ID")
        raise HTTPException(status_code=400, detail="EMPTY_PART_ID: part_id를 지정해야 합니다.")

    # 1. 경로 순회(Path Traversal) 공격 방지 (영문, 숫자, 밑줄, 하이픈만 허용)
    clean_id = part_id[:-3] if part_id.endswith(".pt") else part_id
    if not re.fullmatch(r"^[A-Za-z0-9_-]+$", clean_id):
        audit("FAILED","INVALID_PART_ID_CHARACTERS")
        raise HTTPException(status_code=400, detail="INVALID_PART_ID: part_id는 영문자, 숫자, 밑줄(_), 하이픈(-)만 포함할 수 있습니다.")
    part_id = clean_id

    target_pt = (MODELS_DIR / f"{clean_id}.pt").resolve()
    # models 디렉터리 내부 경로인지 엄격 검증
    if target_pt.parent != MODELS_DIR.resolve():
        audit("FAILED","PATH_TRAVERSAL_ATTEMPT")
        raise HTTPException(status_code=400, detail="PATH_TRAVERSAL_DETECTED: models 디렉터리 외부의 파일은 활성화할 수 없습니다.")

    if not target_pt.exists():
        audit("FAILED","MODEL_FILE_NOT_FOUND")
        raise HTTPException(status_code=400, detail=f"MODEL_FILE_NOT_FOUND: models 디렉터리에 {target_pt.name} 파일이 존재하지 않습니다.")

    # 2. meta.json 필수 검증 및 Zero-Leakage (overlap 0%) 검증
    meta_file = target_pt.with_suffix(".meta.json")
    if not meta_file.exists():
        audit("FAILED","MISSING_META_JSON")
        raise HTTPException(status_code=400, detail=f"MISSING_META_JSON: 모델 메타데이터 파일({meta_file.name})이 존재하지 않아 활성화가 거부되었습니다.")

    try:
        meta_data = json.loads(meta_file.read_text(encoding="utf-8"))
        overlap = meta_data["split"]["bank_validation_overlap"]
        meta_sha = str(meta_data["output"]["pt_sha256"]).lower()
    except Exception as e:
        # 필드가 없으면 무누수를 입증할 수 없으므로 통과시키지 않는다.
        audit("FAILED", f"INVALID_META_JSON_{type(e).__name__}")
        raise HTTPException(status_code=400, detail="INVALID_META_JSON: meta.json을 읽을 수 없거나 필수 필드(split.bank_validation_overlap, output.pt_sha256)가 없습니다.")

    if overlap != 0:
        audit("FAILED", f"DATASET_LEAKAGE_OVERLAP_{overlap}")
        raise HTTPException(
            status_code=409,
            detail=f"DATASET_LEAKAGE_OVERLAP_DETECTED: 검증셋과 메모리뱅크 간 교집합({overlap}건)이 감지되어 활성화가 거부되었습니다."
        )

    # 3. SHA256 체크섬 검증 (불일치 시 409 Conflict 반환)
    model_bytes = target_pt.read_bytes()
    actual_sha = hashlib.sha256(model_bytes).hexdigest().lower()
    if actual_sha != expected_sha:
        audit("FAILED", "SHA256_MISMATCH", actual_sha256=actual_sha)
        raise HTTPException(
            status_code=409,
            detail=f"SHA256_MISMATCH: 체크섬이 일치하지 않습니다 (기대: {expected_sha}, 실제: {actual_sha})"
        )
    if meta_sha != actual_sha:
        audit("FAILED", "META_MODEL_SHA_MISMATCH", actual_sha256=actual_sha)
        raise HTTPException(status_code=409, detail="META_MODEL_SHA_MISMATCH: meta.json이 가리키는 모델과 실제 파일의 체크섬이 다릅니다.")

    # 3-1. 코드 실행이 가능한 pickle 객체가 든 체크포인트를 엔진 로드 전에 거부한다.
    # expected_sha256은 호출자가 주는 값이라 변조 방어가 되지 못한다.
    try:
        torch.load(io.BytesIO(model_bytes), map_location="cpu", weights_only=True)
    except Exception as e:
        audit("FAILED", f"UNSAFE_CHECKPOINT_{type(e).__name__}", actual_sha256=actual_sha)
        raise HTTPException(status_code=400, detail="MODEL_LOAD_FAILED: 안전하게 로드할 수 없는 체크포인트입니다.")

    # 3-2. 신규 모델 로드 무결성 사전 검증 (기존 모델 영향 없이 별도 인스턴스로 먼저 생성)
    try:
        new_engine = PatchCoreEngine(model_path=target_pt)
    except Exception as e:
        audit("FAILED", f"LOAD_EXCEPTION_{type(e).__name__}", actual_sha256=actual_sha)
        raise HTTPException(status_code=400, detail="MODEL_LOAD_FAILED: 모델 체크포인트 로드에 실패했습니다.")

    # 3-3. 검증한 파일과 로드된 파일이 같은지, 체크포인트의 실제 인덱스에 누수가 없는지 확인한다.
    if new_engine.model_hash != actual_sha[:12]:
        audit("FAILED", "MODEL_CHANGED_DURING_ACTIVATION", actual_sha256=actual_sha)
        raise HTTPException(status_code=409, detail="MODEL_CHANGED_DURING_ACTIVATION: 검증 중 모델 파일이 변경되었습니다.")
    real_overlap = len(set(new_engine.bank_image_indices) & set(new_engine.validation_image_indices))
    if real_overlap != 0:
        audit("FAILED", f"DATASET_LEAKAGE_OVERLAP_{real_overlap}", actual_sha256=actual_sha)
        raise HTTPException(
            status_code=409,
            detail=f"DATASET_LEAKAGE_OVERLAP_DETECTED: 체크포인트 인덱스에서 교집합({real_overlap}건)이 감지되어 활성화가 거부되었습니다."
        )

    # 4. 검증 통과 완료 -> 락 획득 후 안전하게 원자적(Atomic) 교체
    now_iso = datetime.now(timezone.utc).isoformat()
    parsed_ver = meta_data.get("engine_version_compat", meta_data.get("version", "1.0.0")) if meta_file.exists() else "1.0.0"
    confidence_tier, autonomous = _apply_model_policy(new_engine, meta_data)
    with _ENGINE_LOCK:
        global _ACTIVE_ENGINE, _ACTIVE_PART_ID, _ACTIVE_MODEL_PATH, _ACTIVE_MODEL_SHA256, _ACTIVE_MODEL_VERSION, _ACTIVE_ACTIVATED_AT, _ACTIVE_CONFIDENCE_TIER, _ACTIVE_AUTONOMOUS
        _ACTIVE_ENGINE = new_engine
        _ACTIVE_CONFIDENCE_TIER = confidence_tier
        _ACTIVE_AUTONOMOUS = autonomous
        _ACTIVE_PART_ID = part_id
        _ACTIVE_MODEL_PATH = target_pt
        _ACTIVE_MODEL_SHA256 = actual_sha
        _ACTIVE_MODEL_VERSION = parsed_ver
        _ACTIVE_ACTIVATED_AT = now_iso

    audit("SUCCESS", "ACTIVATED_SAFELY", actual_sha256=actual_sha, model_hash=new_engine.model_hash)

    return {
        "status": "activated",
        "part_id": part_id,
        "model_part_id": part_id,
        "model_file": target_pt.name,
        "model_hash": new_engine.model_hash,
        "model_sha256": actual_sha,
        "model_version": parsed_ver,
        "raw_threshold": new_engine.raw_threshold,
        "threshold_source": new_engine.threshold_source,
        "confidence_tier": confidence_tier,
        "autonomous_decision_allowed": autonomous,
        "activated_at": now_iso
    }


@app.get("/v1/defects/evaluation")
def get_evaluation_report():
    """공식 벤치마크 검증 리포트(results/evaluation.json) 반환"""
    report = load_evaluation_report()
    if not report:
        raise HTTPException(status_code=404, detail="EVALUATION_REPORT_NOT_FOUND")
    return report


@app.post("/v1/defects/inspect")
def inspect_defect(
    request: Request,
    file: UploadFile = File(...),
    camera_id: str = Form("CAM_FINISHING_01"),
    operating_mode: str = Form("SAFETY_FIRST"),
    part_geometry: str = Form("generic"),
    include_heatmap: bool = Form(True)
):
    """
    금속 부품 이미지를 전송받아 PatchCore Eq. 6-7(N_b(m*) 이웃 밀도 재가중) 및
    무클리핑 다중 특징 규칙 엔진으로 결함 검사 및 공정 조치 판정 수행.
    (보안 정책: x-mock-score 헤더는 운영 환경에서 403 MOCK_DISABLED로 즉시 차단됨)
    """
    mock_score_hdr = request.headers.get("x-mock-score")
    mock_area_hdr = request.headers.get("x-mock-area")
    is_mock_request = (mock_score_hdr is not None)

    if is_mock_request:
        client_host = request.client.host if request.client else ""
        if os.getenv("ALLOW_MOCK") != "1" or client_host not in ALLOWED_LOOPBACK_HOSTS:
            raise HTTPException(
                status_code=403,
                detail="MOCK_DISABLED: Production API rejects x-mock-score header."
            )

    # 입력값이 그대로 응답과 감사 로그에 남으므로 허용 값만 받는다.
    if operating_mode not in OPERATING_MODE_THRESHOLDS:
        raise HTTPException(status_code=400, detail="INVALID_OPERATING_MODE: 지원하지 않는 운영 모드입니다.")
    if part_geometry not in SUPPORTED_PART_GEOMETRIES:
        raise HTTPException(status_code=400, detail="INVALID_PART_GEOMETRY: 지원하지 않는 부품 기하 모드입니다.")
    if not CAMERA_ID_PATTERN.fullmatch(camera_id):
        raise HTTPException(status_code=400, detail="INVALID_CAMERA_ID: camera_id는 영문, 숫자, _ . : - 조합 64자 이내여야 합니다.")

    # 1. 파일 확장자 검증
    filename = file.filename or "unknown.png"
    ext = "." + filename.split(".")[-1].lower() if "." in filename else ""
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"UNSUPPORTED_MEDIA_TYPE: 지원하지 않는 파일 형식입니다 ({ext})"
        )

    # 2. 파일 바이트 읽기 및 크기 검증
    # ponytail: Content-Length 없는 chunked 업로드는 임시 파일로 먼저 저장된 뒤 여기서 거부된다.
    # 외부에 직접 노출하면 앞단 프록시에서 본문 크기를 제한한다.
    contents = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="EMPTY_FILE: 빈 파일이 전송되었습니다.")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="PAYLOAD_TOO_LARGE: 이미지 파일 크기가 허용 한도를 초과했습니다.")

    # 3. 이미지 무결성 검증 (PIL 디코딩)
    try:
        image = Image.open(io.BytesIO(contents))
        image.verify()
        image = Image.open(io.BytesIO(contents))
    except Exception:
        raise HTTPException(status_code=400, detail="CORRUPTED_IMAGE: 유효하지 않거나 손상된 이미지 파일입니다.")
    # 작은 파일도 해상도가 크면 히트맵 연산이 수십 초 걸리므로 디코딩 전에 거부한다.
    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise HTTPException(status_code=413, detail="IMAGE_TOO_LARGE: 이미지 해상도가 허용 한도를 초과했습니다.")

    # 4. 실제 PatchCore 비지도 이상탐지 추론 (활성 엔진 스레드 안전 참조)
    with _ENGINE_LOCK:
        engine = _ACTIVE_ENGINE
        cur_part_id = _ACTIVE_PART_ID
        cur_model_sha256 = _ACTIVE_MODEL_SHA256
        cur_model_version = _ACTIVE_MODEL_VERSION
        cur_activated_at = _ACTIVE_ACTIVATED_AT
        cur_confidence_tier = _ACTIVE_CONFIDENCE_TIER
        cur_autonomous = _ACTIVE_AUTONOMOUS

    if is_mock_request:
        anomaly_score = float(mock_score_hdr)
        raw_distance = float(mock_score_hdr)
        raw_top1_eq6 = float(mock_score_hdr)
        peak_patch_distance = 0.0
        defect_area_ratio = float(mock_area_hdr) if mock_area_hdr is not None else 0.0
        edge_region_ratio = None if part_geometry != "circular_jig" else 0.0
        edge_metric_status = "NOT_APPLICABLE_FOR_GENERIC_PART" if part_geometry != "circular_jig" else "CALCULATED_CIRCULAR_JIG"
        structural_shape_check = "NOT_PERFORMED" if part_geometry != "circular_jig" else "PERFORMED"
        global_deformation_coverage = "LIMITED" if part_geometry != "circular_jig" else "SUPPORTED_RING_ONLY"
        heatmap_b64 = None
        rule_res = evaluate_defect(
            anomaly_score=anomaly_score,
            mask_area_ratio=defect_area_ratio,
            peak_patch_distance=peak_patch_distance,
            edge_region_ratio=0.0,
            operating_mode=operating_mode,
            # 테스트 시나리오의 mock 면적 기준(ALLOW_MOCK=1 로컬 전용). 실제 판정에는 쓰이지 않는다.
            structural_thresholds={**engine.structural_thresholds, "area_severe_threshold": 0.03}
        )
        fg_centroid_yx = None
    else:
        if not _INFERENCE_SLOTS.acquire(timeout=INFERENCE_WAIT_SEC):
            raise HTTPException(status_code=503, detail="SERVER_BUSY: 추론 대기 시간이 초과되었습니다. 잠시 후 다시 시도하십시오.")
        try:
            pred = engine.predict(
                image,
                include_heatmap=include_heatmap,
                operating_mode=operating_mode,
                part_geometry=part_geometry
            )
        finally:
            _INFERENCE_SLOTS.release()
        anomaly_score = pred["anomaly_score"]
        raw_distance = pred["raw_distance"]
        raw_top1_eq6 = pred["raw_top1_eq6"]
        peak_patch_distance = pred["peak_patch_distance"]
        defect_area_ratio = pred["defect_area_ratio"]
        edge_region_ratio = pred["edge_region_ratio"]
        edge_metric_status = pred["edge_metric_status"]
        structural_shape_check = pred.get("structural_shape_check", "NOT_PERFORMED" if part_geometry != "circular_jig" else "PERFORMED")
        global_deformation_coverage = pred.get("global_deformation_coverage", "LIMITED" if part_geometry != "circular_jig" else "SUPPORTED_RING_ONLY")
        fg_centroid_yx = pred["foreground_centroid_yx"]
        heatmap_b64 = pred["heatmap_base64"]
        rule_res = pred

    inspection_id = str(uuid.uuid4())
    ts_now = datetime.now(timezone.utc).isoformat()
    response_payload = {
        "inspection_id": inspection_id,
        "timestamp": ts_now,
        "camera_id": camera_id,
        "part_id": cur_part_id,
        "model_part_id": cur_part_id,
        "model_sha256": cur_model_sha256,
        "model_version": cur_model_version,
        "activated_at": cur_activated_at,
        "confidence_tier": cur_confidence_tier,
        "autonomous_decision_allowed": cur_autonomous,
        "part_geometry": part_geometry,
        "structural_shape_check": structural_shape_check,
        "global_deformation_coverage": global_deformation_coverage,
        "mock": is_mock_request,
        "decision": rule_res["decision"],
        "decision_threshold": rule_res["decision_threshold"],
        "decision_basis": rule_res["decision_basis"],
        "heatmap_display": rule_res["heatmap_display"],
        "reason_code": rule_res["reason_code"],
        "anomaly_score": round(anomaly_score, 4),
        "normalized_anomaly_score": round(anomaly_score, 4),
        "raw_anomaly_score": round(raw_distance, 4),
        "raw_distance": round(raw_distance, 4),
        "raw_max_1nn_score": round(raw_top1_eq6, 4),
        "raw_top1_eq6": round(raw_top1_eq6, 4),
        "peak_patch_distance": round(peak_patch_distance, 4),
        "defect_area_ratio": round(defect_area_ratio, 4),
        "edge_region_ratio": edge_region_ratio,
        "outer_ring_ratio": edge_region_ratio,
        "edge_metric_status": edge_metric_status,
        "foreground_centroid_yx": fg_centroid_yx,
        "structural_defect_likelihood": rule_res["structural_defect_likelihood"],
        "estimated_defect_pattern": rule_res["estimated_defect_pattern"],
        "pattern_estimate": rule_res["pattern_estimate"],
        "manual_review_recommended": rule_res["manual_review_recommended"],
        "operating_mode": rule_res["operating_mode"],
        "interlock": rule_res["interlock"],
        "summary": rule_res["summary"],
        "engine_version": engine.engine_version,
        "model_hash": engine.model_hash,
        "threshold_source": engine.threshold_source,
        "inference_mode": "MOCK_TEST_OVERRIDE" if is_mock_request else "FASTAPI_REST_SERVER",
        "heatmap_base64": heatmap_b64
    }
    # 기록되지 않은 판정을 내보내면 추적이 불가능하므로 판정을 반환하지 않고 재검사를 요구한다.
    try:
        log_inspection_audit(response_payload)
    except Exception:
        logger.exception("감사 로그 기록 실패 (inspection_id=%s)", inspection_id)
        raise HTTPException(status_code=503, detail="AUDIT_WRITE_FAILED: 감사 로그 기록에 실패해 판정을 반환하지 않습니다. 재검사가 필요합니다.")
    return response_payload


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
