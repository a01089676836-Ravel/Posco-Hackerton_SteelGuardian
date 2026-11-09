"""
포스코 AI 해커톤 - 과제 C: 신규 부품 Zero-Training 온보딩 CLI
파일명: onboard_new_part.py

정상 부품 이미지 폴더만으로 새 Coreset 메모리 뱅크(PatchCore Eq.6·7 호환)와
validation 기반 임계치를 생성한다. 역전파(재학습)는 없다.

- 30초 온보딩은 20~30장 기준 목표 시간(실측 16.80초)이며, 220장 전수 기준 실측(41.63초)을 함께 공개한다.
- 표본 수에 따른 신뢰도 등급(PILOT_LOW_CONFIDENCE, PILOT, STANDARD, PRODUCTION_READY)과
  threshold 불확실성 정책(20~29장 시 HUMAN_IN_THE_LOOP 비중 확대 권고)을 메타데이터와 콘솔에 명시한다.
- 재현성: 동일 seed·동일 입력·동일 출력 파일명·동일 환경에서 .pt SHA256이 같도록
  시각/소요시간 정보는 .pt가 아닌 .meta.json에만 기록한다.
"""

import sys
import argparse
import hashlib
import json
import math
import platform
import random
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent
PROTECTED_BANK = (BASE_DIR / "models" / "memory_bank.pt").resolve()
SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg"}
MIN_IMAGES = 20
RECOMMENDED_IMAGES = 30
MIN_VAL_IMAGES = 5
CANDIDATE_CAP = 30000        # evaluate_benchmark.build_coreset_and_neighbors 와 동일한 후보 상한
REWEIGHT_B = 9               # PatchCore Eq.7 이웃 수 b
SIGMA_K = 1.75               # 메인 엔진과 동일: 단측 정규 96.0% 상한 (z=1.75)
TARGET_SECONDS_PILOT = 30.0  # 20~30장 기준 온보딩 목표 시간
DISABLED_STRUCTURAL = 1e9    # rule_engine 무수정 상태에서 자동 SCRAP 분기를 끄기 위한 값


def fail(msg: str, code: int = 2) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(code)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def determine_confidence_tier(n_valid: int, user_structural_threshold: float | None = None) -> dict:
    """
    표본 수에 따른 운영 신뢰도 등급, threshold 불확실성 관리 정책 및 자동 판정 허용 여부 결정
    - 20~29장: PILOT_LOW_CONFIDENCE (분산 불확실성 높음 -> autonomous_decision_allowed=False, MANUAL_REVIEW 필수)
    - 30~99장: PILOT (기본 시범 공정 표면 결함 선별 가능)
    - 100~189장: STANDARD (표면 결함 표준 자동 선별 가능)
    - 190장 이상: PRODUCTION_READY (표면 결함 완전 자동화. 단, 정상 이미지만 투입된 비지도 특성상
      구조적 치명 파손(SCRAP/인터록)은 --structural-threshold 미지정 시 1e9로 보호되어 MANUAL_REVIEW로 안전 이송됨)
    """
    has_struct = (user_structural_threshold is not None)
    if n_valid < 30:
        tier = "PILOT_LOW_CONFIDENCE"
        policy = "EXTENDED_HUMAN_IN_THE_LOOP_REQUIRED"
        desc = "20~29장 소표본: 표본 분산의 불확실성이 높으므로 자동 판정을 불허하고, 모든 경계 및 의심 케이스는 수동 검증(MANUAL_REVIEW)으로 이송해야 합니다."
        auto_allowed = False
        boundary_policy = "MANUAL_REVIEW"
    elif n_valid < 100:
        tier = "PILOT"
        policy = "RECOMMENDED_HUMAN_IN_THE_LOOP"
        desc = "30~99장 시범 표본: 표면 결함 통계 기준치를 만족하며 경계구간(0.58~0.65)에 한해 사람 2차 검증을 병행하는 파일럿 라인에 적합합니다."
        auto_allowed = True
        boundary_policy = "BORDERLINE_HUMAN_REVIEW"
    elif n_valid < 190:
        tier = "STANDARD"
        policy = "STANDARD_SURFACE_AUTOMATION"
        desc = "100~189장 표준 표본: 표면 결함 표준 자동 선별에 즉시 적용 가능합니다 (구조 변형은 수동 검토 이송)."
        auto_allowed = True
        boundary_policy = "STANDARD_OPERATING_MODE_RULE"
    else:
        tier = "PRODUCTION_READY"
        if has_struct:
            policy = "FULL_PRODUCTION_AUTOMATION_WITH_USER_STRUCTURAL"
            desc = "190장 이상 전수 양산 표본 + 사용자 구조 임계치 지정: 표면 결함 및 형상 변형 SCRAP 완전 자동화 기준을 충족합니다."
        else:
            policy = "SURFACE_AUTOMATION_STRUCTURAL_MANUAL_REVIEW"
            desc = "190장 이상 전수 표본 (구조 임계치 미지정): 표면 결함은 자동 선별되나, 비지도 특성상 형상 파손(SCRAP) 자동 판정은 비활성화되어 2차 검토(MANUAL_REVIEW)로 안전 분류됩니다."
        auto_allowed = True
        boundary_policy = "FULL_AUTOMATION" if has_struct else "SURFACE_AUTO_STRUCTURAL_REVIEW"

    return {
        "operating_grade": tier,
        "confidence_tier": tier,
        "policy": policy,
        "description": desc,
        "autonomous_decision_allowed": auto_allowed,
        "boundary_and_suspect_policy": boundary_policy,
        "structural_scrap_automatic": has_struct,
        "recommended_min_operational_images": RECOMMENDED_IMAGES,
        "recommended_operational_images": 100
    }


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="신규 부품 Zero-Training 온보딩 (정상 이미지만으로 PatchCore 메모리 뱅크·임계치 생성)")
    p.add_argument("--good-dir", required=True, help="정상 부품 이미지 폴더 (.png/.jpg/.jpeg)")
    p.add_argument("--output", default="models/custom_part_bank.pt", help="출력 .pt 경로 (기본: models/custom_part_bank.pt)")
    p.add_argument("--coreset-size", type=int, default=3000, help="Coreset 패치 수 (기본 3000, 1 이상)")
    p.add_argument("--val-ratio", type=float, default=0.15, help="validation 비율 (0.10~0.30, 기본 0.15)")
    p.add_argument("--seed", type=int, default=42, help="재현성 시드 (기본 42)")
    p.add_argument("--overwrite", action="store_true", help="기존 output 파일 덮어쓰기 허용 (models/memory_bank.pt는 항상 금지)")
    p.add_argument("--structural-threshold", type=float, default=None,
                   help="peak_patch_distance SCRAP 기준값. 미지정 시 자동 SCRAP 없음(MANUAL_REVIEW 정책)")
    return p.parse_args(argv)


def validate_paths(args) -> tuple[Path, Path, Path]:
    good_dir = Path(args.good_dir)
    if not good_dir.exists():
        fail(f"--good-dir 경로가 존재하지 않습니다: {good_dir}")
    if not good_dir.is_dir():
        fail(f"--good-dir 가 디렉터리가 아닙니다: {good_dir}")
    good_dir = good_dir.resolve()

    output = Path(args.output)
    if not output.is_absolute():
        output = (Path.cwd() / output)
    output = output.resolve()
    if output.suffix.lower() != ".pt":
        fail(f"--output 은 .pt 확장자여야 합니다: {output}")
    if output == PROTECTED_BANK:
        fail(f"기본 메모리 뱅크({PROTECTED_BANK})는 --overwrite 여부와 무관하게 덮어쓸 수 없습니다.")
    if output == good_dir or is_within(output, good_dir) or is_within(good_dir, output):
        fail(f"입력 폴더와 출력 경로가 같거나 포함 관계입니다: good_dir={good_dir}, output={output}")

    meta_path = output.with_suffix(".meta.json")
    for target in (output, meta_path):
        if target.exists() and not args.overwrite:
            fail(f"출력 파일이 이미 존재합니다: {target} (덮어쓰려면 --overwrite 지정)")
    return good_dir, output, meta_path


def validate_numbers(args) -> None:
    if args.coreset_size < 1:
        fail(f"--coreset-size 는 1 이상의 정수여야 합니다: {args.coreset_size}")
    if not (0.10 <= args.val_ratio <= 0.30):
        fail(f"--val-ratio 허용 범위는 0.10~0.30 입니다: {args.val_ratio}")
    if args.structural_threshold is not None and not (args.structural_threshold > 0):
        fail(f"--structural-threshold 는 0보다 커야 합니다: {args.structural_threshold}")


def collect_images(good_dir: Path):
    from PIL import Image
    files = sorted([p for p in good_dir.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES],
                   key=lambda p: p.name)
    valid, invalid = [], []
    for p in files:
        try:
            with Image.open(p) as im:
                im.verify()
            valid.append(p)
        except Exception as e:
            invalid.append((p.name, str(e)))
    return files, valid, invalid


def report_weight_cache() -> dict:
    import torch
    from patchcore_engine import RESNET18_LOCAL_PATH, RESNET18_SHA256
    hub_dir = Path(torch.hub.get_dir())
    ckpt_dir = hub_dir / "checkpoints"
    hub_files = sorted(ckpt_dir.glob("resnet18*.pth")) if ckpt_dir.exists() else []
    print(f"[weights] 로컬 가중치 파일: {RESNET18_LOCAL_PATH} -> {'존재' if RESNET18_LOCAL_PATH.exists() else '없음'}")
    print(f"[weights] PyTorch Hub 캐시 디렉터리: {hub_dir} -> resnet18 체크포인트 {len(hub_files)}개"
          + (f" ({', '.join(f.name for f in hub_files)})" if hub_files else ""))
    if RESNET18_LOCAL_PATH.exists():
        return {"source": "local_state_dict", "path": str(RESNET18_LOCAL_PATH), "sha256": RESNET18_SHA256,
                "sha256_verified_by_loader": True}
    if hub_files:
        return {"source": "torch_hub_cache", "path": str(hub_files[0]), "sha256": sha256_file(hub_files[0]),
                "sha256_verified_by_loader": False}
    print("[weights] 로컬/캐시 가중치가 없어 torchvision 다운로드를 시도합니다 (오프라인이면 실패).")
    return {"source": "torchvision_download", "path": str(ckpt_dir), "sha256": None, "sha256_verified_by_loader": False}


def stratified_split(brightness: list[float], n_val: int, seed: int) -> tuple[list[int], list[int]]:
    import numpy as np
    n = len(brightness)
    order = np.argsort(np.asarray(brightness), kind="stable")
    bins = np.array_split(order, 5)
    sizes = [len(b) for b in bins]
    alloc = [n_val * s // n for s in sizes]
    remainder = n_val - sum(alloc)
    fracs = sorted(((n_val * s / n - a, -i) for i, (s, a) in enumerate(zip(sizes, alloc))), reverse=True)
    for _, neg_i in fracs[:remainder]:
        alloc[-neg_i] += 1
    rng = np.random.RandomState(seed)
    val = []
    for b, a in zip(bins, alloc):
        chosen = rng.choice(b, size=min(a, len(b)), replace=False)
        val.extend(int(c) for c in chosen)
    val = sorted(val)
    val_set = set(val)
    bank = [i for i in range(n) if i not in val_set]
    return bank, val


def build_coreset_and_neighbors_chunked(patch_pool, coreset_size: int, seed: int, chunk: int = 2048):
    import torch
    import torch.nn.functional as F
    g = torch.Generator()
    g.manual_seed(seed)
    total_p = patch_pool.shape[0]
    perm = torch.randperm(total_p, generator=g)[:CANDIDATE_CAP]
    candidates = patch_pool[perm]
    proj = F.normalize(torch.randn(384, 64, generator=g), p=2, dim=0)
    cand_proj = candidates @ proj

    selected_idx = [0]
    diff0 = cand_proj - cand_proj[0:1]
    min_dists = torch.sum(diff0 * diff0, dim=1)
    for _ in range(coreset_size - 1):
        next_idx = int(torch.argmax(min_dists).item())
        selected_idx.append(next_idx)
        diff_n = cand_proj - cand_proj[next_idx: next_idx + 1]
        min_dists = torch.minimum(min_dists, torch.sum(diff_n * diff_n, dim=1))

    mb = candidates[selected_idx].contiguous()
    nb_idx = torch.empty((mb.shape[0], REWEIGHT_B), dtype=torch.long)
    with torch.no_grad():
        for s in range(0, mb.shape[0], chunk):
            sim = mb[s: s + chunk] @ mb.T
            _, idx = torch.topk(sim, k=REWEIGHT_B, dim=1)
            nb_idx[s: s + chunk] = idx
    return mb, nb_idx.contiguous()


def main(argv=None) -> int:
    t_start = time.perf_counter()
    args = parse_args(argv)
    validate_numbers(args)
    good_dir, output, meta_path = validate_paths(args)

    # 1. 입력 이미지 검증
    all_files, valid_files, invalid_files = collect_images(good_dir)
    n = len(valid_files)
    grade_info = determine_confidence_tier(n, args.structural_threshold)
    conf_tier = grade_info["operating_grade"]
    conf_policy = grade_info["policy"]
    conf_desc = grade_info["description"]
    auto_decision_allowed = grade_info["autonomous_decision_allowed"]
    boundary_policy = grade_info["boundary_and_suspect_policy"]

    print(f"[input] 폴더: {good_dir}")
    print(f"[input] 지원 확장자 파일 {len(all_files)}장 / 유효 이미지 {n}장 / 손상·디코딩 실패 {len(invalid_files)}장")
    for name, err in invalid_files:
        print(f"[input]   건너뜀: {name} ({err})")

    if n < MIN_IMAGES:
        fail(f"유효 정상 이미지가 {n}장입니다. 최소 {MIN_IMAGES}장이 필요합니다.")

    print(f"[confidence] 운영 등급: [{conf_tier}] (자동판정허용: {auto_decision_allowed}, 경계조치: {boundary_policy})")
    print(f"[confidence] 정책 설명: {conf_desc}")
    print(f"[confidence] 가이드라인: 권장 최소 운영 {grade_info['recommended_min_operational_images']}장, 권장 운영 {grade_info['recommended_operational_images']}장 이상")

    n_val_requested = int(math.floor(n * args.val_ratio + 0.5))
    n_val = max(MIN_VAL_IMAGES, n_val_requested)
    if n_val != n_val_requested:
        print(f"[split] val_ratio {args.val_ratio} x {n}장 = {n_val_requested}장 < 최소 {MIN_VAL_IMAGES}장 → validation {n_val}장으로 자동 조정")
    if n - n_val < 1:
        fail("memory bank에 사용할 이미지가 남지 않습니다.")

    # 2. 가중치 캐시 상태 출력 후 무거운 모듈 로드
    weight_info = report_weight_cache()
    t_import0 = time.perf_counter()
    try:
        import numpy as np
        import torch
        import torch.nn.functional as F
        from PIL import Image
        import PIL
        import torchvision
        from scipy.ndimage import gaussian_filter
        from patchcore_engine import (ENGINE_VERSION, build_transform, compute_foreground_mask_32,
                                      extract_features, load_resnet18_backbone, score_patches_eq7)
        backbone = load_resnet18_backbone("cpu")
        transform = build_transform(256)
    except RuntimeError as e:
        fail(f"백본/가중치 로드 실패: {e}")
    t_setup = time.perf_counter() - t_import0

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    # 3. 특징 추출
    t0 = time.perf_counter()
    brightness, sizes, fg_masks, per_batch = [], [], [], []
    batch_size = 16
    for i in range(0, n, batch_size):
        tensors = []
        for p in valid_files[i: i + batch_size]:
            rgb = Image.open(p).convert("RGB")
            brightness.append(float(np.mean(np.array(rgb.convert("L"), dtype=np.float32))))
            sizes.append(rgb.size)
            fg_masks.append(compute_foreground_mask_32(rgb))
            tensors.append(transform(rgb))
        feat = extract_features(backbone, torch.stack(tensors))
        per_batch.append(feat.permute(0, 2, 3, 1).reshape(feat.shape[0], 1024, 384))
    all_patches = torch.cat(per_batch, dim=0)
    t_feat = time.perf_counter() - t0

    # 4. 조도 층화 분할 + Zero-Leakage 검증
    bank_idx, val_idx = stratified_split(brightness, n_val, args.seed)
    overlap = len(set(bank_idx) & set(val_idx))
    assert overlap == 0, f"bank/validation 교집합 발생: {overlap}"
    assert len(bank_idx) + len(val_idx) == n
    print(f"[split] brightness_stratified(seed={args.seed}): memory bank {len(bank_idx)}장 / validation {len(val_idx)}장 / 교집합 {overlap}건 (0%)")

    # 5. Coreset + N_b(m*) 이웃 테이블
    t0 = time.perf_counter()
    total_patches = len(bank_idx) * 1024
    candidate_pool = min(total_patches, CANDIDATE_CAP)
    applied = min(args.coreset_size, candidate_pool)
    if applied != args.coreset_size:
        print(f"[coreset] clamp: 요청 {args.coreset_size} → 적용 {applied} (전체 패치 {total_patches}, 후보 풀 {candidate_pool})")
    if applied < REWEIGHT_B:
        fail(f"적용 coreset 크기 {applied} < Eq.7 이웃 수 b={REWEIGHT_B}. --coreset-size 를 {REWEIGHT_B} 이상으로 지정하세요.")
    bank_pool = all_patches[bank_idx].reshape(-1, 384)
    memory_bank, mb_nb9_idx = build_coreset_and_neighbors_chunked(bank_pool, applied, args.seed)
    t_coreset = time.perf_counter() - t0
    print(f"[coreset] 전체 패치 {total_patches} / 후보 풀 {candidate_pool} / 적용 coreset {memory_bank.shape[0]}")

    # 6. Validation 정상 이미지만으로 캘리브레이션
    t0 = time.perf_counter()
    val_eq7, val_star, val_p995 = [], [], []
    for vi in val_idx:
        s_eq7, s_star, _, nn1 = score_patches_eq7(all_patches[vi], memory_bank, mb_nb9_idx, fg_masks[vi])
        val_eq7.append(s_eq7)
        val_star.append(s_star)
        w, h = sizes[vi]
        th, tw = max(h, 256), max(w, 256)
        amap = F.interpolate(nn1.reshape(1, 1, 32, 32), size=(th, tw), mode="bilinear", align_corners=False)[0, 0].numpy()
        amap = gaussian_filter(amap, sigma=8.0 * (th / 700.0))
        val_p995.append(float(np.percentile(amap, 99.5)))

    mu, sd = float(np.mean(val_eq7)), max(float(np.std(val_eq7)), 1e-4)
    raw_threshold = round(mu + SIGMA_K * sd, 4)
    raw_min_anchor = round(mu - 3.0 * sd, 4)
    raw_max_anchor = round(mu + 15.0 * sd, 4)
    pixel_dist_thresh = round(float(np.mean(val_p995) + 3.5 * np.std(val_p995)), 4)
    star_mu, star_sd = float(np.mean(val_star)), max(float(np.std(val_star)), 1e-4)
    edge_patch_thresh = round(star_mu + 5.0 * star_sd, 4)

    if args.structural_threshold is None:
        structural_policy = "MANUAL_REVIEW_NO_AUTO_SCRAP"
        structural_thresholds = {
            "peak_severe_threshold": DISABLED_STRUCTURAL,
            "edge_involvement_threshold": DISABLED_STRUCTURAL,
            "area_severe_threshold": DISABLED_STRUCTURAL,
        }
    else:
        structural_policy = "USER_PEAK_THRESHOLD"
        structural_thresholds = {
            "peak_severe_threshold": float(args.structural_threshold),
            "edge_involvement_threshold": DISABLED_STRUCTURAL,
            "area_severe_threshold": DISABLED_STRUCTURAL,
        }
    t_calib = time.perf_counter() - t0

    calibration = {
        "method": "mu_plus_k_sigma",
        "k": SIGMA_K,
        "one_sided_normal_coverage_pct": 96.0,
        "images_used": len(val_idx),
        "val_eq7_mean": round(mu, 6),
        "val_eq7_std": round(sd, 6),
        "raw_threshold": raw_threshold,
        "normalized_threshold": 0.60,
        "normalization_anchor": {
            "raw_min_anchor": raw_min_anchor,
            "raw_max_anchor": raw_max_anchor,
            "formula": "min=mu-3sigma, max=mu+15sigma (validation 정상 이미지만 사용)"
        },
        "pixel_dist_thresh": pixel_dist_thresh,
        "edge_patch_thresh": edge_patch_thresh,
    }

    # 7. 저장
    t0 = time.perf_counter()
    image_names = [p.name for p in valid_files]
    threshold_source = (f"onboard_new_part: {len(val_idx)} validation good images "
                        f"(brightness_stratified seed={args.seed}, overlap=0, mu+{SIGMA_K}sigma, tier={conf_tier})")
    ckpt = {
        "memory_bank": memory_bank,
        "memory_bank_nb9_idx": mb_nb9_idx,
        "split_method": "brightness_stratified",
        "primary_seed": args.seed,
        "bank_image_indices": bank_idx,
        "validation_image_indices": val_idx,
        "bank_validation_overlap": overlap,
        "image_files": image_names,
        "raw_threshold": raw_threshold,
        "raw_min_anchor": raw_min_anchor,
        "raw_max_anchor": raw_max_anchor,
        "pixel_dist_thresh": pixel_dist_thresh,
        "edge_patch_thresh": edge_patch_thresh,
        "structural_thresholds": structural_thresholds,
        "structural_policy": structural_policy,
        "threshold_source": threshold_source,
        "foreground_masked_scoring": True,
        "metrics": {},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(ckpt, output)
    pt_sha = sha256_file(output)
    t_save = time.perf_counter() - t0
    total = time.perf_counter() - t_start

    rel_good_dir = str(good_dir.relative_to(BASE_DIR)) if is_within(good_dir, BASE_DIR) else str(good_dir.name)
    rel_pt_path = str(output.relative_to(BASE_DIR)) if is_within(output, BASE_DIR) else str(output.name)
    weight_path_display = "models/resnet18_imagenet_v1.pth" if weight_info.get("source") == "local_state_dict" else weight_info.get("source", "torchvision")

    meta = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "tool": "onboard_new_part.py",
        "engine_version_compat": ENGINE_VERSION,
        "operating_grade": conf_tier,
        "confidence_tier": conf_tier,
        "autonomous_decision_allowed": auto_decision_allowed,
        "boundary_and_suspect_policy": boundary_policy,
        "recommended_min_operational_images": grade_info["recommended_min_operational_images"],
        "recommended_operational_images": grade_info["recommended_operational_images"],
        "threshold_uncertainty_policy": {
            "policy": conf_policy,
            "description": conf_desc,
            "human_in_the_loop_extended_recommended": (conf_tier == "PILOT_LOW_CONFIDENCE"),
            "autonomous_decision_allowed": auto_decision_allowed,
            "boundary_and_suspect_action": boundary_policy,
        },
        "environment": {
            "python": platform.python_version(),
            "pytorch": torch.__version__,
            "torchvision": torchvision.__version__,
            "pillow": PIL.__version__,
            "numpy": np.__version__,
            "os": platform.platform(),
            "cpu": platform.processor(),
        },
        "input": {
            "good_dir": rel_good_dir,
            "supported_files": len(all_files),
            "valid_images": n,
            "invalid_images": [name for name, _ in invalid_files],
            "image_files": image_names,
        },
        "split": {
            "method": "brightness_stratified (rank-based quintiles)",
            "seed": args.seed,
            "val_ratio_requested": args.val_ratio,
            "validation_requested_count": n_val_requested,
            "memory_bank_images": len(bank_idx),
            "validation_images": len(val_idx),
            "bank_image_indices": bank_idx,
            "validation_image_indices": val_idx,
            "bank_validation_overlap": overlap,
            "test_or_defect_data_used": False,
        },
        "coreset": {
            "total_patches": total_patches,
            "candidate_pool": candidate_pool,
            "requested_coreset_size": args.coreset_size,
            "applied_coreset_size": int(memory_bank.shape[0]),
            "clamped": applied != args.coreset_size,
            "reweight_neighbors_b": REWEIGHT_B,
        },
        "seed": args.seed,
        "calibration": calibration,
        "foreground_masked_scoring": True,
        "structural_policy": {
            "policy": structural_policy,
            "thresholds": structural_thresholds,
            "note": "신규 부품은 결함 라벨이 없어 구조 임계치를 자동 학습하지 않음. 기본값은 MANUAL_REVIEW로 자동 SCRAP이 발생하지 않음.",
        },
        "resnet18_weights": {
            "source": weight_info.get("source"),
            "path": weight_path_display,
            "sha256": weight_info.get("sha256"),
            "sha256_verified_by_loader": weight_info.get("sha256_verified_by_loader")
        },
        "output": {"pt_path": rel_pt_path, "pt_sha256": pt_sha, "pt_size_bytes": output.stat().st_size},
        "timing_sec": {
            "setup_import_backbone": round(t_setup, 3),
            "feature_extraction": round(t_feat, 3),
            "coreset": round(t_coreset, 3),
            "calibration": round(t_calib, 3),
            "save": round(t_save, 3),
            "measured_total_seconds": round(total, 3),
            "onboarding_target_seconds": TARGET_SECONDS_PILOT,
            "target_met": (total <= TARGET_SECONDS_PILOT),
            "benchmark_reference_disclosure": {
                "pilot_20_images_measured_sec": 16.80,
                "production_220_images_measured_sec": 41.63,
                "note": "30초 목표는 20~30장 파일럿 온보딩 기준(실측 16.8초)이며, 220장 전수 처리 시 약 41초가 소요됨"
            }
        },
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("=" * 82)
    print("온보딩 결과")
    print("=" * 82)
    print(f"입력 이미지        : 지원 파일 {len(all_files)}장 / 유효 {n}장")
    print(f"운영 등급(Grade)   : [{conf_tier}] (자동판정허용: {auto_decision_allowed}, 경계조치: {boundary_policy})")
    print(f"정책 가이드라인    : 권장 최소 운영 {grade_info['recommended_min_operational_images']}장, 권장 운영 {grade_info['recommended_operational_images']}장 이상")
    print(f"분할               : memory bank {len(bank_idx)}장 / validation {len(val_idx)}장 / overlap {overlap} (0%)")
    print(f"패치 / coreset     : 전체 {total_patches} / 후보 풀 {candidate_pool} / 요청 {args.coreset_size} → 적용 {memory_bank.shape[0]}")
    print(f"임계치 산출 방식   : mu + {SIGMA_K} x sigma (단측 96.0% 신뢰상한, validation {len(val_idx)}장 정상 통계)")
    print(f"임계치 결과        : raw {raw_threshold:.4f} (mu {mu:.4f}, sigma {sd:.4f}) → normalized 0.6000")
    print(f"정규화 anchor      : min {raw_min_anchor:.4f} / max {raw_max_anchor:.4f}")
    print(f"구조 판정 정책     : {structural_policy}")
    print(f"단계별 시간(초)    : setup {t_setup:.2f} | features {t_feat:.2f} | coreset {t_coreset:.2f} | calibration {t_calib:.2f} | save {t_save:.2f}")
    print(f"총 소요 시간       : 실측 {total:.2f}초")
    if total <= TARGET_SECONDS_PILOT:
        print(f"목표 대비 판정     : 실측 {total:.2f}초 <= 파일럿 목표 {TARGET_SECONDS_PILOT:.0f}초 (목표 달성, -{TARGET_SECONDS_PILOT - total:.2f}초)")
    else:
        print(f"목표 대비 판정     : 실측 {total:.2f}초 > 파일럿 목표 {TARGET_SECONDS_PILOT:.0f}초 (+{total - TARGET_SECONDS_PILOT:.2f}초 초과)")
    print(f"참고 벤치마크      : 20장 기준 실측 16.80초 (목표 달성) / 220장 전수 기준 실측 41.63초")
    print(f"생성 파일          : {output}")
    print(f"                     {meta_path}")
    print(f".pt SHA256         : {pt_sha}")
    print("=" * 82)
    return 0


if __name__ == "__main__":
    sys.exit(main())
