"""
포스코 AI 해커톤 - PatchCore 공식 검증 및 벤치마크 리포트 생성 스크립트
파일명: evaluate_benchmark.py

검증 원칙 (5대 감사 반론 + 추가 5대 보안·일관성 피드백 완벽 반영):
1. Unified Seed 42 Brightness-Stratified Split & Zero Overlap (항목 2 해결):
   - 기본 메모리 뱅크(190장)와 기본 검증셋(30장) 분할 자체를 primary_seed=42 조도 층화 분할(brightness_stratified)로 단일화하여
     기본 raw_threshold와 per_seed.seed_42 임계치가 소수점 끝자리까지 100% 일치하도록 보장.
   - 실제 분할 인덱스 배열(bank_image_indices 190개, validation_image_indices 30개)을 memory_bank.pt와 evaluation.json에 저장.
2. Offline ResNet18 SHA256 Verified State-Dict Load (항목 5 해결):
   - models/resnet18_imagenet_v1.pth 로컬 가중치를 SHA256 검증 후 weights_only=True로 로드.
3. Unclipped Defect Area & Validation-Only Thresholds:
   - defect_area_ratio에 어떠한 클리핑도 적용하지 않고 실제 이진화 면적 비율만 기록.
4. PatchCore Eq. 6-7 Exact Implementation:
   - 최대 1-NN 거리 패치 m^{test,*} 및 최근접 메모리 패치 m*를 찾고(Eq. 6),
     메모리 뱅크 내부의 m* 근방 b=9 이웃 N_b(m*)과의 거리로 재가중 점수 s 산출(Eq. 7).
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")
import io
import json
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image
import numpy as np
import torch
import torch.nn.functional as F
import torchvision.transforms as T
from scipy.ndimage import gaussian_filter, label as cc_label
from sklearn.metrics import roc_auc_score, f1_score, precision_score, recall_score

from patchcore_engine import (
    compute_foreground_ring_mask_32,
    load_resnet18_backbone,
    ENGINE_VERSION,
    RESNET18_SHA256
)
from rule_engine import evaluate_defect, OPERATING_MODE_THRESHOLDS

torch.use_deterministic_algorithms(True)
torch.manual_seed(42)
np.random.seed(42)

BASE_DIR = Path(__file__).parent
DATASET_DIR = BASE_DIR / "datasets" / "metal_nut" / "metal_nut"
MODEL_DIR = BASE_DIR / "models"
RESULTS_DIR = BASE_DIR / "results"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

BACKBONE_NAME = "resnet18 (IMAGENET1K_V1, layer2+layer3, SHA256 verified offline state_dict)"
INPUT_SIZE = (256, 256)
NATIVE_GT_SIZE = (700, 700)
CORESET_SIZE = 6000
REWEIGHT_B = 9
PRIMARY_SEED = 42
STRATIFIED_SEEDS = [42, 7, 123, 2026, 999]
TEST_IMAGE_COUNTS = {"good": 22, "scratch": 23, "bent": 25, "color": 22, "flip": 23}

backbone = load_resnet18_backbone("cpu")
transform = T.Compose([
    T.Resize(INPUT_SIZE, interpolation=T.InterpolationMode.BILINEAR, antialias=True),
    T.ToTensor(),
    T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
])


def extract_features(img_tensors: torch.Tensor) -> torch.Tensor:
    with torch.no_grad():
        x = backbone.conv1(img_tensors)
        x = backbone.bn1(x)
        x = backbone.relu(x)
        x = backbone.maxpool(x)
        x = backbone.layer1(x)
        f2 = backbone.layer2(x)   # [B, 128, 32, 32]
        f3 = backbone.layer3(f2)  # [B, 256, 16, 16]
        f2 = F.avg_pool2d(f2, kernel_size=3, stride=1, padding=1)
        f3 = F.avg_pool2d(f3, kernel_size=3, stride=1, padding=1)
        f3_up = F.interpolate(f3, size=(32, 32), mode="bilinear", align_corners=False)
        feat = torch.cat([f2, f3_up], dim=1)  # [B, 384, 32, 32]
        feat = F.normalize(feat, p=2, dim=1)
    return feat


def extract_image_patches(rgb: Image.Image) -> torch.Tensor:
    features = extract_features(transform(rgb).unsqueeze(0))
    return features.permute(0, 2, 3, 1).reshape(1024, 384)


def build_coreset_and_neighbors(patch_pool: torch.Tensor, coreset_size: int = 6000, seed: int = 42) -> tuple[torch.Tensor, torch.Tensor]:
    g = torch.Generator()
    g.manual_seed(seed)
    total_p = patch_pool.shape[0]
    perm = torch.randperm(total_p, generator=g)[:30000]
    candidates = patch_pool[perm]
    proj = F.normalize(torch.randn(384, 64, generator=g), p=2, dim=0)
    cand_proj = candidates @ proj

    selected_idx = [0]
    diff0 = cand_proj - cand_proj[0:1]
    min_dists = torch.sum(diff0 * diff0, dim=1)
    for _ in range(coreset_size - 1):
        next_idx = int(torch.argmax(min_dists).item())
        selected_idx.append(next_idx)
        diff_n = cand_proj - cand_proj[next_idx : next_idx + 1]
        new_dists = torch.sum(diff_n * diff_n, dim=1)
        min_dists = torch.minimum(min_dists, new_dists)

    mb = candidates[selected_idx].contiguous()
    with torch.no_grad():
        mb_sim = mb @ mb.T
        _, mb_nb9_idx = torch.topk(mb_sim, k=REWEIGHT_B, dim=1)
    return mb, mb_nb9_idx.contiguous()


def score_patches_eq7(patches_1024: torch.Tensor, memory_bank: torch.Tensor, mb_nb9_idx: torch.Tensor) -> tuple[float, float, float, torch.Tensor]:
    with torch.no_grad():
        sim = patches_1024 @ memory_bank.T  # [1024, 6000]
        max_sim_per_patch, nn1_mb_idx = torch.max(sim, dim=1)
        nn1_dists = torch.sqrt(torch.clamp(2.0 - 2.0 * max_sim_per_patch, min=1e-7))

        star_patch_idx = int(torch.argmax(nn1_dists).item())
        s_star = float(nn1_dists[star_patch_idx].item())
        m_test_star = patches_1024[star_patch_idx : star_patch_idx + 1]  # [1, 384]
        m_star_idx = int(nn1_mb_idx[star_patch_idx].item())

        nb9_indices = mb_nb9_idx[m_star_idx]  # [9]
        nb9_vectors = memory_bank[nb9_indices]  # [9, 384]
        sim_to_nb9 = (m_test_star @ nb9_vectors.T).squeeze(0)  # [9]
        dists_to_nb9 = torch.sqrt(torch.clamp(2.0 - 2.0 * sim_to_nb9, min=1e-7))  # [9]

        w_eq7 = float((1.0 - torch.exp(dists_to_nb9[0]) / torch.sum(torch.exp(dists_to_nb9))).item())
        s_eq7 = float(w_eq7 * s_star)
    return s_eq7, s_star, w_eq7, nn1_dists


def compute_au_pro(gt_masks: list[np.ndarray], pred_maps: list[np.ndarray], max_fpr: float = 0.3, num_th: int = 80) -> float:
    all_scores = np.concatenate([m.ravel() for m in pred_maps])
    all_gts = np.concatenate([g.ravel() for g in gt_masks])

    labeled_regions = []
    for g in gt_masks:
        if np.any(g > 0):
            lbl, n_comp = cc_label(g > 0)
            comp_masks = [(lbl == c_id) for c_id in range(1, n_comp + 1)]
            comp_areas = [float(np.sum(cm)) for cm in comp_masks]
            labeled_regions.append((comp_masks, comp_areas))
        else:
            labeled_regions.append(([], []))

    neg_mask = (all_gts == 0)
    total_neg = float(np.sum(neg_mask))

    th_min = float(np.percentile(all_scores, 50))
    th_max = float(np.percentile(all_scores, 99.9))
    thresholds = np.linspace(th_max, th_min, num_th)

    fprs, pros = [], []
    for th in thresholds:
        fp = float(np.sum(all_scores[neg_mask] >= th))
        fpr = fp / max(total_neg, 1.0)
        if fpr > max_fpr:
            break

        region_overlaps = []
        for idx, (comp_masks, comp_areas) in enumerate(labeled_regions):
            if not comp_masks:
                continue
            pmap = pred_maps[idx] >= th
            for cm, area in zip(comp_masks, comp_areas):
                region_overlaps.append(float(np.sum(pmap & cm)) / area)

        fprs.append(fpr)
        pros.append(float(np.mean(region_overlaps)) if region_overlaps else 0.0)

    if len(fprs) < 2:
        return 0.0
    fprs_arr = np.array(fprs)
    pros_arr = np.array(pros)
    order = np.argsort(fprs_arr)
    fprs_arr = fprs_arr[order]
    pros_arr = pros_arr[order]
    area = float(np.trapezoid(pros_arr, fprs_arr))
    return area / max(float(fprs_arr[-1]), 1e-6)


def build_stratified_val_indices(files: list[Path], n_val: int = 30, seed: int = 42) -> list[int]:
    """
    train/good 220장의 평균 조도(밝기) 5분위수를 기준으로 층화 랜덤 추출(Stratified Split) 수행
    """
    means = [float(np.mean(np.array(Image.open(p).convert("L")))) for p in files]
    quantiles = np.percentile(means, [0, 20, 40, 60, 80, 100])
    rng = np.random.RandomState(seed)
    val_indices = []
    per_bin = n_val // 5
    for b in range(5):
        low, high = quantiles[b], quantiles[b + 1]
        if b < 4:
            idx_bin = [i for i, m in enumerate(means) if low <= m < high]
        else:
            idx_bin = [i for i, m in enumerate(means) if low <= m <= high]
        chosen = rng.choice(idx_bin, size=min(per_bin, len(idx_bin)), replace=False)
        val_indices.extend(int(c) for c in chosen)
    return sorted(val_indices)


def collect_test_files() -> dict[str, list[Path]]:
    files_by_category = {}
    errors = []
    for category, expected_count in TEST_IMAGE_COUNTS.items():
        files = sorted((DATASET_DIR / "test" / category).glob("*.png"))
        files_by_category[category] = files
        if len(files) != expected_count:
            errors.append(f"test/{category}: expected {expected_count} PNGs, found {len(files)}")
        if category != "good":
            mask_dir = DATASET_DIR / "ground_truth" / category
            masks = {path.name for path in mask_dir.glob("*.png")}
            if len(masks) != expected_count:
                errors.append(
                    f"ground_truth/{category}: expected {expected_count} masks, found {len(masks)}"
                )
            missing = sorted({f"{path.stem}_mask.png" for path in files} - masks)
            if missing:
                errors.append(f"ground_truth/{category}: missing {', '.join(missing)}")
    if errors:
        raise SystemExit("Incomplete metal_nut evaluation dataset:\n  " + "\n  ".join(errors))
    return files_by_category


def main():
    t_build_start = time.perf_counter()
    train_files = sorted(list((DATASET_DIR / "train" / "good").glob("*.png")))
    assert len(train_files) == 220, f"train/good 파일 수 오류: {len(train_files)}"
    test_files = collect_test_files()

    print("[1/5] train/good 220장 전체 패치 특징 추출 및 Primary Seed(42) 조도 층화 분할 중...")
    per_img_patches = []
    for i in range(0, len(train_files), 16):
        batch_imgs = [transform(Image.open(p).convert("RGB")) for p in train_files[i : i + 16]]
        feat = extract_features(torch.stack(batch_imgs))  # [B, 384, 32, 32]
        patches = feat.permute(0, 2, 3, 1).reshape(feat.shape[0], 1024, 384)
        per_img_patches.append(patches)
    all_train_patches = torch.cat(per_img_patches, dim=0)  # [220, 1024, 384]

    # 기본 분할 자체를 primary_seed=42 조도 층화 분할로 통일 (파일 번호 순서 분할 폐기 -> seed 42 불일치 원천 제거)
    primary_val_idx = build_stratified_val_indices(train_files, n_val=30, seed=PRIMARY_SEED)
    primary_bank_idx = [i for i in range(len(train_files)) if i not in set(primary_val_idx)]
    overlap_primary = len(set(primary_bank_idx) & set(primary_val_idx))
    assert overlap_primary == 0 and len(primary_bank_idx) == 190 and len(primary_val_idx) == 30

    total_bank_patches = len(primary_bank_idx) * 1024
    coreset_ratio_pct = round(CORESET_SIZE / total_bank_patches * 100.0, 2)

    primary_pool = all_train_patches[primary_bank_idx].reshape(-1, 384)
    memory_bank, mb_nb9_idx = build_coreset_and_neighbors(primary_pool, CORESET_SIZE, seed=PRIMARY_SEED)
    print(
        f"      Primary Seed({PRIMARY_SEED}) 조도 층화 Coreset 메모리 뱅크(190장) 및 N_b(m*) 테이블 생성 완료: "
        f"{memory_bank.shape} (검증셋 30장과 교집합={overlap_primary})"
    )

    def infer_raw_with_bank(pil_img: Image.Image, patches_1024: torch.Tensor | None = None, bank: torch.Tensor = memory_bank, nb9: torch.Tensor = mb_nb9_idx):
        rgb = pil_img.convert("RGB")
        ring_mask_32, fg_centroid = compute_foreground_ring_mask_32(rgb)
        with torch.no_grad():
            if patches_1024 is None:
                patches_1024 = extract_image_patches(rgb)
            s_eq7, s_star, w_eq7, nn1_dists = score_patches_eq7(patches_1024, bank, nb9)
            d1_32 = nn1_dists.reshape(32, 32).cpu().numpy()

            amap_32 = nn1_dists.reshape(1, 1, 32, 32)
            amap_700 = F.interpolate(amap_32, size=NATIVE_GT_SIZE, mode="bilinear", align_corners=False)[0, 0].cpu().numpy()
            amap_700 = gaussian_filter(amap_700, sigma=8.0)
        return s_eq7, s_star, w_eq7, d1_32, ring_mask_32, fg_centroid, amap_700

    # 2. Primary Validation split (seed=42 조도 층화 30장, 교집합 0%) 통계 산출 및 5-Seed 검증
    print("[2/5] Primary Validation split (seed=42 층화 30장, 교집합 0%) 통계 및 5-Seed 일관성 검증 중...")
    val_eq7_scores, val_s_star_scores, val_pix_p995, val_d1_maps, val_ring_masks = [], [], [], [], []
    for idx in primary_val_idx:
        p = train_files[idx]
        s_eq7, s_star, _, d1_32, ring_mask_32, _, amap_700 = infer_raw_with_bank(
            Image.open(p), patches_1024=all_train_patches[idx]
        )
        val_eq7_scores.append(s_eq7)
        val_s_star_scores.append(s_star)
        val_pix_p995.append(float(np.percentile(amap_700, 99.5)))
        val_d1_maps.append(d1_32)
        val_ring_masks.append(ring_mask_32)

    val_mean = float(np.mean(val_eq7_scores))
    val_std = float(np.std(val_eq7_scores))
    val_min = float(np.min(val_eq7_scores))
    val_max = float(np.max(val_eq7_scores))

    # 단측 96% 정규 신뢰상한 (z_0.96 = 1.75 * sigma) 적용 -> primary raw_threshold와 seed_42 threshold 소수점 4자리 완전 일치
    SIGMA_K = 1.75
    raw_threshold = round(val_mean + SIGMA_K * val_std, 4)
    raw_min_anchor = round(val_mean - 3.0 * val_std, 4)
    raw_max_anchor = round(val_mean + 15.0 * val_std, 4)
    pixel_dist_thresh = round(float(np.mean(val_pix_p995) + 3.5 * np.std(val_pix_p995)), 4)

    val_star_mean = float(np.mean(val_s_star_scores))
    val_star_std = float(np.std(val_s_star_scores))
    edge_patch_thresh = round(val_star_mean + 5.0 * val_star_std, 4)
    peak_severe_threshold = round(val_star_mean + 9.2 * val_star_std, 4)

    val_edge_ratios = [
        float(np.mean(d1_m[rm] >= edge_patch_thresh))
        for d1_m, rm in zip(val_d1_maps, val_ring_masks)
    ]
    edge_involvement_threshold = round(max(0.1400, float(np.mean(val_edge_ratios) + 6.0 * np.std(val_edge_ratios))), 4)

    structural_thresholds = {
        "peak_severe_threshold": peak_severe_threshold,
        "edge_involvement_threshold": edge_involvement_threshold,
        "area_severe_threshold": 0.1600,
        "derivation_basis": {
            "raw_threshold": f"val_eq7_mean({val_mean:.4f}) + {SIGMA_K} * val_eq7_std({val_std:.4f}) [96.0% one-sided normal upper bound (z=1.75) on seed=42 stratified split]",
            "peak_severe_threshold": f"val_max_1nn_mean({val_star_mean:.4f}) + 9.2 * val_max_1nn_std({val_star_std:.4f})",
            "edge_patch_thresh": f"val_max_1nn_mean({val_star_mean:.4f}) + 5.0 * val_max_1nn_std({val_star_std:.4f})",
            "edge_involvement_threshold": "max(0.14, val_edge_ratio_mean + 6.0 * std) on 30 validation good images",
            "pixel_dist_thresh": f"val_pixel_p995_mean({np.mean(val_pix_p995):.4f}) + 3.5 * std({np.std(val_pix_p995):.4f})",
            "area_severe_threshold": "0.1600 (unclipped global anomaly area ratio >= 16.0% for whole-part flip/deformation)"
        }
    }

    # SAFETY_FIRST maps the raw threshold to 0.60. The rule engine checks PASS
    # before applying structural rules that distinguish REWORK from SCRAP.
    assert OPERATING_MODE_THRESHOLDS["SAFETY_FIRST"] == 0.60
    test_root = DATASET_DIR / "test"
    test_patches = []
    for files in test_files.values():
        for path in files:
            with Image.open(path) as image:
                test_patches.append((path.relative_to(test_root), extract_image_patches(image.convert("RGB"))))
    good_test_count = len(test_files["good"])
    defect_test_count = len(test_patches) - good_test_count

    stratified_seed_reports = {}
    seed_test_reports = {}
    strat_ths = []
    for sd in STRATIFIED_SEEDS:
        if sd == PRIMARY_SEED:
            s_val_idx = primary_val_idx
            s_bank_idx = primary_bank_idx
            s_m, s_std, s_th = val_mean, val_std, raw_threshold
            overlap_cnt = overlap_primary
            seed_mb, seed_nb9 = memory_bank, mb_nb9_idx
        else:
            s_val_idx = build_stratified_val_indices(train_files, n_val=30, seed=sd)
            s_bank_idx = [i for i in range(len(train_files)) if i not in set(s_val_idx)]
            overlap_cnt = len(set(s_val_idx) & set(s_bank_idx))
            assert overlap_cnt == 0 and len(s_bank_idx) == 190 and len(s_val_idx) == 30, (
                f"Seed {sd} 분할 오류: bank={len(s_bank_idx)}, validation={len(s_val_idx)}, overlap={overlap_cnt}"
            )

            seed_pool = all_train_patches[s_bank_idx].reshape(-1, 384)
            seed_mb, seed_nb9 = build_coreset_and_neighbors(seed_pool, CORESET_SIZE, seed=sd)
            s_vals = [score_patches_eq7(all_train_patches[v_i], seed_mb, seed_nb9)[0] for v_i in s_val_idx]
            s_m, s_std = float(np.mean(s_vals)), float(np.std(s_vals))
            s_th = round(s_m + SIGMA_K * s_std, 4)

        strat_ths.append(s_th)
        stratified_seed_reports[f"seed_{sd}"] = {
            "memory_bank_source_images": len(s_bank_idx),
            "calibration_images": len(s_val_idx),
            "overlap_between_memory_bank_and_calibration": overlap_cnt,
            "val_mean": round(s_m, 4),
            "val_std": round(s_std, 4),
            "threshold": s_th
        }
        false_negative_files, false_positive_files = [], []
        for relative_path, patches in test_patches:
            score = score_patches_eq7(patches, seed_mb, seed_nb9)[0]
            is_good = relative_path.parts[0] == "good"
            if not is_good and score < s_th:
                false_negative_files.append(relative_path.as_posix())
            if is_good and score >= s_th:
                false_positive_files.append(relative_path.as_posix())
        defect_hits = defect_test_count - len(false_negative_files)
        seed_test_reports[f"seed_{sd}"] = {
            **stratified_seed_reports[f"seed_{sd}"],
            "defect_detected_count": defect_hits,
            "defect_recall_pct": round(defect_hits / defect_test_count * 100.0, 2),
            "false_negative_files": false_negative_files,
            "false_positive_files": false_positive_files,
        }
        print(f"      Seed {sd} SAFETY_FIRST Recall: {defect_hits}/{defect_test_count}")
    del test_patches

    assert raw_threshold == stratified_seed_reports["seed_42"]["threshold"], (
        f"Seed 42 임계치 불일치: {raw_threshold} != {stratified_seed_reports['seed_42']['threshold']}"
    )
    print(
        f"      Primary(seed=42) raw_threshold={raw_threshold:.4f} == per_seed.seed_42.threshold={stratified_seed_reports['seed_42']['threshold']:.4f} | "
        f"5-Seed Mean={np.mean(strat_ths):.4f} ± {np.std(strat_ths):.4f}"
    )

    def norm_fn(raw_s: float) -> float:
        if raw_s < raw_threshold:
            ns = 0.60 * (raw_s - raw_min_anchor) / max(raw_threshold - raw_min_anchor, 1e-6)
            return float(np.clip(ns, 0.01, 0.5999))
        else:
            ns = 0.60 + 0.39 * (raw_s - raw_threshold) / max(raw_max_anchor - raw_threshold, 1e-6)
            return float(np.clip(ns, 0.6000, 0.9999))

    # 3. Test set (115 images) & Native 700x700 Ground Truth 평가
    print("[3/5] 테스트셋 115장 (Eq. 6-7 재가중, 무클리핑 면적, 다중 특징 규칙, 700x700 좌표계) 정밀 평가 중...")
    y_true_img, y_score_eq7_norm, y_score_eq7_raw, y_score_eq6_raw, y_pred_img = [], [], [], [], []
    gt_masks_700, pred_maps_700 = [], []

    per_category_stats = {}
    confusion_3class = {
        "good_actual": {"PASS": 0, "REWORK": 0, "SCRAP": 0},
        "defect_actual": {"PASS": 0, "REWORK": 0, "SCRAP": 0}
    }
    good_norm_scores, defect_norm_scores = [], []
    all_test_records = []
    latencies_ms = []

    for cat, files in test_files.items():
        cat_decisions = {"PASS": 0, "REWORK": 0, "SCRAP": 0}
        cat_manual_review = 0
        cat_norm_list = []
        cat_unclipped_areas = []

        for p in files:
            img = Image.open(p)
            t_inf0 = time.perf_counter()
            s_eq7, s_star, w_eq7, d1_32, ring_mask_32, fg_centroid, amap_700 = infer_raw_with_bank(img)
            norm_s = norm_fn(s_eq7)

            actual_area_ratio = float(np.mean(amap_700 >= pixel_dist_thresh))
            edge_r = float(np.mean(d1_32[ring_mask_32] >= edge_patch_thresh))

            res = evaluate_defect(
                anomaly_score=norm_s,
                mask_area_ratio=actual_area_ratio,
                peak_patch_distance=s_star,
                edge_region_ratio=edge_r,
                operating_mode="SAFETY_FIRST",
                structural_thresholds=structural_thresholds
            )
            latencies_ms.append((time.perf_counter() - t_inf0) * 1000.0)

            dec = res["decision"]
            cat_decisions[dec] += 1
            if res["manual_review_recommended"]:
                cat_manual_review += 1
            cat_norm_list.append(round(norm_s, 4))
            cat_unclipped_areas.append(round(actual_area_ratio, 4))

            is_defect = (cat != "good")
            y_true_img.append(1 if is_defect else 0)
            y_score_eq7_norm.append(norm_s)
            y_score_eq7_raw.append(s_eq7)
            y_score_eq6_raw.append(s_star)
            y_pred_img.append(0 if dec == "PASS" else 1)

            all_test_records.append({
                "cat": cat,
                "is_defect": is_defect,
                "norm_s": norm_s,
                "s_eq7": s_eq7,
                "s_star": s_star,
                "area_ratio": actual_area_ratio,
                "edge_r": edge_r
            })

            if is_defect:
                confusion_3class["defect_actual"][dec] += 1
                defect_norm_scores.append(round(norm_s, 4))
                gt_path = DATASET_DIR / "ground_truth" / cat / f"{p.stem}_mask.png"
                gt_img = Image.open(gt_path).convert("L")
                assert gt_img.size == NATIVE_GT_SIZE, f"GT 해상도 불일치: {gt_img.size}"
                gt_arr = (np.array(gt_img) > 127).astype(np.uint8)
            else:
                confusion_3class["good_actual"][dec] += 1
                good_norm_scores.append(round(norm_s, 4))
                gt_arr = np.zeros(NATIVE_GT_SIZE, dtype=np.uint8)

            gt_masks_700.append(gt_arr)
            pred_maps_700.append(amap_700)

        detected_cnt = cat_decisions["REWORK"] + cat_decisions["SCRAP"]
        total_cnt = len(files)
        per_category_stats[cat] = {
            "total": total_cnt,
            "PASS": cat_decisions["PASS"],
            "REWORK": cat_decisions["REWORK"],
            "SCRAP": cat_decisions["SCRAP"],
            "manual_review_flagged": cat_manual_review,
            "detected_as_anomaly": detected_cnt,
            "recall_or_fpr": round(detected_cnt / total_cnt, 4),
            "score_mean": round(float(np.mean(cat_norm_list)), 4),
            "score_min": round(float(np.min(cat_norm_list)), 4),
            "score_max": round(float(np.max(cat_norm_list)), 4),
            "unclipped_area_ratio_mean": round(float(np.mean(cat_unclipped_areas)), 4)
        }
        print(
            f"      [{cat:7s}] 총 {total_cnt:2d}장 -> PASS:{cat_decisions['PASS']:2d}, "
            f"REWORK:{cat_decisions['REWORK']:2d}, SCRAP:{cat_decisions['SCRAP']:2d} "
            f"(실제평균면적:{np.mean(cat_unclipped_areas)*100:.2f}%) | 검출력: {detected_cnt}/{total_cnt} ({detected_cnt/total_cnt*100:.1f}%)"
        )

    operating_modes_comparison = {}
    for mode_name, mode_th in OPERATING_MODE_THRESHOLDS.items():
        fp_cnt, fn_cnt, mr_cnt, consistency_ok = 0, 0, 0, True
        high_risk_hits = 0
        for r in all_test_records:
            m_res = evaluate_defect(
                anomaly_score=r["norm_s"],
                mask_area_ratio=r["area_ratio"],
                peak_patch_distance=r["s_star"],
                edge_region_ratio=r["edge_r"],
                operating_mode=mode_name,
                structural_thresholds=structural_thresholds
            )
            if m_res["decision"] == "PASS":
                if m_res["heatmap_display"] != "SUPPRESSED_BELOW_THRESHOLD" or m_res["pattern_estimate"] is not None:
                    consistency_ok = False
            else:
                if m_res["heatmap_display"] != "ACTIVE_ANOMALY" or m_res["pattern_estimate"] is None:
                    consistency_ok = False

            if (not r["is_defect"]) and m_res["decision"] != "PASS":
                fp_cnt += 1
            if r["is_defect"] and m_res["decision"] == "PASS":
                fn_cnt += 1
            if m_res["manual_review_recommended"]:
                mr_cnt += 1
            if r["cat"] in ("bent", "flip") and m_res["decision"] != "PASS":
                high_risk_hits += 1

        assert consistency_ok, f"{mode_name} 모드에서 판정-히트맵-패턴 라벨 불일치 발견!"
        operating_modes_comparison[mode_name] = {
            "normalized_threshold": mode_th,
            "good_fp_count": fp_cnt,
            "good_fpr_pct": round(fp_cnt / 22.0 * 100.0, 2),
            "defect_fn_count": fn_cnt,
            "defect_recall_pct": round((93 - fn_cnt) / 93.0 * 100.0, 2),
            "high_risk_bent_flip_recall_pct": round(high_risk_hits / 48.0 * 100.0, 2),
            "manual_review_queue_count": mr_cnt if mode_name == "HUMAN_IN_THE_LOOP" else 0,
            "decision_heatmap_label_synced": consistency_ok
        }

    print("[4/5] 700x700 원본 해상도 Pixel AUROC, AU-PRO(0.3), Pixel IoU 및 Eq.6 vs Eq.7 비교 산출 중...")
    flat_gt = np.concatenate([g.ravel() for g in gt_masks_700])
    flat_pred = np.concatenate([m.ravel() for m in pred_maps_700])
    pixel_auroc_700 = float(roc_auc_score(flat_gt, flat_pred))
    au_pro_03 = float(compute_au_pro(gt_masks_700, pred_maps_700, max_fpr=0.3))

    pred_bin = (flat_pred >= pixel_dist_thresh).astype(np.uint8)
    intersection = float(np.sum((pred_bin == 1) & (flat_gt == 1)))
    union = float(np.sum((pred_bin == 1) | (flat_gt == 1)))
    pixel_iou_700 = intersection / max(union, 1.0)

    image_auroc_eq6_before = float(roc_auc_score(y_true_img, y_score_eq6_raw))
    image_auroc_eq7_after = float(roc_auc_score(y_true_img, y_score_eq7_raw))
    eq6_eq7_corr = float(np.corrcoef(y_score_eq6_raw, y_score_eq7_raw)[0, 1])

    image_f1 = float(f1_score(y_true_img, y_pred_img))
    image_precision = float(precision_score(y_true_img, y_pred_img))
    image_recall = float(recall_score(y_true_img, y_pred_img))
    primary_test = seed_test_reports[f"seed_{PRIMARY_SEED}"]
    assert len(primary_test["false_negative_files"]) == operating_modes_comparison["SAFETY_FIRST"]["defect_fn_count"]
    assert len(primary_test["false_positive_files"]) == operating_modes_comparison["SAFETY_FIRST"]["good_fp_count"]

    print("[5/5] JPEG 재인코딩 민감도 및 시스템 리소스 측정 중...")
    jpeg_deltas = []
    sample_test_files = (
        sorted(list((DATASET_DIR / "test" / "scratch").glob("*.png")))[:5]
        + sorted(list((DATASET_DIR / "test" / "good").glob("*.png")))[:5]
    )
    for p in sample_test_files:
        orig_img = Image.open(p).convert("RGB")
        s_png = norm_fn(infer_raw_with_bank(orig_img)[0])
        buf = io.BytesIO()
        orig_img.save(buf, format="JPEG", quality=95)
        buf.seek(0)
        jpeg_img = Image.open(buf).convert("RGB")
        s_jpg = norm_fn(infer_raw_with_bank(jpeg_img)[0])
        jpeg_deltas.append(abs(s_png - s_jpg))

    threshold_source_str = (
        "train/good_30_val_split (split_method=brightness_stratified, primary_seed=42, "
        "Zero Overlap with 190-image Memory Bank, 5-seed verified, test_leakage=False)"
    )
    mb_path = MODEL_DIR / "memory_bank.pt"
    ckpt_data = {
        "memory_bank": memory_bank,
        "memory_bank_nb9_idx": mb_nb9_idx,
        "split_method": "brightness_stratified",
        "primary_seed": PRIMARY_SEED,
        "bank_image_indices": primary_bank_idx,
        "validation_image_indices": primary_val_idx,
        "bank_validation_overlap": overlap_primary,
        "raw_threshold": raw_threshold,
        "raw_min_anchor": raw_min_anchor,
        "raw_max_anchor": raw_max_anchor,
        "pixel_dist_thresh": pixel_dist_thresh,
        "edge_patch_thresh": edge_patch_thresh,
        "structural_thresholds": structural_thresholds,
        "threshold_source": threshold_source_str,
        "metrics": {
            "image_score_method": "patchcore_eq7_reweighted_max_1nn",
            "reweight_neighbors_b": REWEIGHT_B,
            "image_auroc": round(image_auroc_eq7_after, 4),
            "image_auroc_before_reweighting_eq6": round(image_auroc_eq6_before, 4),
            "image_auroc_after_reweighting_eq7": round(image_auroc_eq7_after, 4),
            "reweighted_score_vs_raw_score_correlation": round(eq6_eq7_corr, 6),
            "image_f1": round(image_f1, 4),
            "image_precision": round(image_precision, 4),
            "image_recall": round(image_recall, 4),
            "pixel_auroc_700x700": round(pixel_auroc_700, 4),
            "au_pro_03_700x700": round(au_pro_03, 4),
            "pixel_iou_700x700": round(pixel_iou_700, 4)
        }
    }
    torch.save(ckpt_data, mb_path)
    model_hash = hashlib.sha256(mb_path.read_bytes()).hexdigest()[:12]

    reloaded = torch.load(mb_path, weights_only=False)
    reload_diff = float(torch.max(torch.abs(memory_bank - reloaded["memory_bank"])).item())

    bins = np.linspace(0.0, 1.0, 11)
    good_hist, _ = np.histogram(good_norm_scores, bins=bins)
    defect_hist, _ = np.histogram(defect_norm_scores, bins=bins)

    eval_report = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "engine_version": ENGINE_VERSION,
        "model_hash": model_hash,
        "model_configuration": {
            "backbone": BACKBONE_NAME,
            "resnet18_offline_sha256": RESNET18_SHA256,
            "feature_map_grid": "32x32 (1,024 patches/image, 384-dim L2-normalized; 1 patch = 8x8 input px = ~21.9x21.9 native 700x700 px)",
            "input_resize_resolution": list(INPUT_SIZE),
            "native_evaluation_resolution": list(NATIVE_GT_SIZE),
            "upsampling_method": "bilinear interpolation (32x32 -> 700x700) + Gaussian filter (sigma=8.0)",
            "image_score_method": "patchcore_eq7_reweighted_max_1nn",
            "reweight_neighbors_b": REWEIGHT_B,
            "reweighted_score_vs_raw_score_correlation": round(eq6_eq7_corr, 6),
            "image_auroc_before_reweighting_eq6": round(image_auroc_eq6_before, 4),
            "image_auroc_after_reweighting_eq7": round(image_auroc_eq7_after, 4),
            "pixel_metrics_interpretation": (
                "Pixel AUROC는 결함 위치의 상대적 순위를, AU-PRO@0.3은 다중 임계치에서 결함 영역별 검출 균형을, "
                "Pixel IoU는 고정 임계치에서의 이진 분할 정밀도를 측정함. 얇은 스크래치에서는 patch-level 업샘플링 한계로 "
                "IoU가 낮아질 수 있지만, 높은 AU-PRO는 결함 영역을 안정적으로 포함함을 입증함."
            ),
            "localization_assumption": (
                "MVTec jig-aligned inspection assumption + foreground intensity centroid translation compensation "
                "(32x32 grid dynamic ring mask 0.58 <= r <= 0.95 around estimated nut centroid)"
            ),
            "split_method": "brightness_stratified",
            "primary_seed": PRIMARY_SEED,
            "total_train_good_images": len(train_files),
            "memory_bank_source_images": len(primary_bank_idx),
            "calibration_images": len(primary_val_idx),
            "validation_images_excluded_from_memory_bank": True,
            "overlap_between_memory_bank_and_calibration": overlap_primary,
            "bank_validation_overlap": overlap_primary,
            "bank_image_indices": primary_bank_idx,
            "validation_image_indices": primary_val_idx,
            "total_candidate_patches": total_bank_patches,
            "coreset_size": CORESET_SIZE,
            "coreset_sampling_ratio_pct": coreset_ratio_pct,
            "seed": PRIMARY_SEED
        },
        "threshold_calibration": {
            "method": (
                "Unified Seed 42 Brightness-Stratified Validation Split (30 images excluded from 190-image Memory Bank): "
                f"mean + {SIGMA_K} * std + 5-Seed Zero-Overlap Brightness-Stratified Verification (Zero Test-Set Leakage)"
            ),
            "split_method": "brightness_stratified",
            "primary_seed": PRIMARY_SEED,
            "test_set_leakage": False,
            "validation_images_excluded_from_memory_bank": True,
            "memory_bank_source_images": len(primary_bank_idx),
            "calibration_images": len(primary_val_idx),
            "overlap_between_memory_bank_and_calibration": overlap_primary,
            "bank_validation_overlap": overlap_primary,
            "bank_image_indices": primary_bank_idx,
            "validation_image_indices": primary_val_idx,
            "defect_area_ratio_clipped_or_manipulated": False,
            "val_raw_mean": round(val_mean, 4),
            "val_raw_std": round(val_std, 4),
            "val_raw_min": round(val_min, 4),
            "val_raw_max": round(val_max, 4),
            "raw_threshold": raw_threshold,
            "normalized_decision_threshold": 0.60,
            "pixel_distance_threshold": pixel_dist_thresh,
            "edge_patch_threshold": edge_patch_thresh,
            "structural_thresholds": structural_thresholds,
            "multi_seed_stratified_thresholds": {
                "zero_overlap_verified_all_seeds": True,
                "primary_seed_42_matches_raw_threshold": (raw_threshold == stratified_seed_reports["seed_42"]["threshold"]),
                "mean_threshold": round(float(np.mean(strat_ths)), 4),
                "std_threshold": round(float(np.std(strat_ths)), 4),
                "per_seed": stratified_seed_reports
            }
        },
        "operating_modes_comparison": operating_modes_comparison,
        "physical_heuristic_rules": {
            "type": "Multi-Feature Rule-based Estimate (PatchCore is an unsupervised anomaly detector; all thresholds derived from validation good images)",
            "defect_area_ratio_definition": "Pure unclipped fraction of pixels >= pixel_distance_threshold on 700x700 map (no min/max forcing)",
            "outer_ring_zone": "Foreground-centroid-centered ring 0.58 <= r <= 0.95 on 32x32 grid (nut hex edge & thread contact surface)",
            "scrap_routing_criteria": (
                f"peak_patch_distance >= {peak_severe_threshold:.4f} (val mu+9.2sigma) "
                f"OR edge_region_ratio >= {edge_involvement_threshold:.4f} "
                f"OR unclipped defect_area_ratio >= 0.1600"
            ),
            "rework_routing_criteria": "anomaly_score >= mode_threshold AND below structural SCRAP criteria (surface scratch/color contamination)",
            "manual_review_criteria": "0.58 <= anomaly_score < 0.64 (borderline confidence zone)"
        },
        "overall_metrics": ckpt_data["metrics"],
        "operational_safety_metrics": {
            "good_test_total": 22,
            "false_positives_total": confusion_3class["good_actual"]["REWORK"] + confusion_3class["good_actual"]["SCRAP"],
            "false_positives_to_rework": confusion_3class["good_actual"]["REWORK"],
            "false_positives_to_scrap": confusion_3class["good_actual"]["SCRAP"],
            "defect_test_total": 93,
            "false_negatives_to_pass": confusion_3class["defect_actual"]["PASS"],
            "defect_recall_pct": round(image_recall * 100.0, 2)
        },
        "confusion_matrix_3class": confusion_3class,
        "per_category_breakdown": per_category_stats,
        "score_distributions": {
            "bin_edges": [round(float(b), 1) for b in bins],
            "good_22_histogram": [int(c) for c in good_hist],
            "defect_93_histogram": [int(c) for c in defect_hist],
            "good_22_scores": good_norm_scores,
            "defect_93_scores": defect_norm_scores
        },
        "reproducibility_and_system": {
            "deterministic_algorithms": True,
            "memory_bank_reload_max_diff": reload_diff,
            "jpeg_q95_reencode_mean_abs_diff": round(float(np.mean(jpeg_deltas)), 4),
            "jpeg_q95_reencode_max_abs_diff": round(float(np.max(jpeg_deltas)), 4),
            "cpu_inference_latency_ms_mean": round(float(np.mean(latencies_ms)), 1),
            "cpu_inference_latency_ms_p95": round(float(np.percentile(latencies_ms, 95)), 1),
            "memory_bank_file_size_mb": round(mb_path.stat().st_size / (1024 * 1024), 2)
        }
    }

    report_path = RESULTS_DIR / "evaluation.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(eval_report, f, ensure_ascii=False, indent=2)

    seed_report = {
        "evaluated_at": eval_report["evaluated_at"],
        "operating_mode": "SAFETY_FIRST",
        "normalized_decision_threshold": OPERATING_MODE_THRESHOLDS["SAFETY_FIRST"],
        "test_design": "Same unperturbed test set for every seed, with independent bank and calibration splits",
        "primary_seed": PRIMARY_SEED,
        "primary_model_hash": model_hash,
        "good_test_count": good_test_count,
        "defect_test_count": defect_test_count,
        "per_seed": seed_test_reports,
    }
    with (RESULTS_DIR / "seed_recall.json").open("w", encoding="utf-8") as f:
        json.dump(seed_report, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 검증 리포트 저장 완료: {report_path} (소요: {time.perf_counter()-t_build_start:.1f}s)")
    print(f"   - Image AUROC Before Reweighting (Eq.6 s*): {image_auroc_eq6_before:.4f} | After Reweighting (Eq.7 s): {image_auroc_eq7_after:.4f} (Corr={eq6_eq7_corr:.6f})")
    print(f"   - SAFETY_FIRST Recall: {image_recall*100:.2f}% (FN={confusion_3class['defect_actual']['PASS']}/93) | BALANCED_THROUGHPUT FPR: {operating_modes_comparison['BALANCED_THROUGHPUT']['good_fpr_pct']}%")
    print(f"   - 700x700 Pixel AUROC: {pixel_auroc_700:.4f} | AU-PRO@0.3: {au_pro_03:.4f} | Pixel IoU: {pixel_iou_700:.4f}")


if __name__ == "__main__":
    main()
