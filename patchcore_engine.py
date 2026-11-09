"""
포스코 AI 해커톤 - PatchCore 비지도 이상탐지 추론 엔진
(Roth et al. CVPR 2022 Eq. 6-7 N_b(m*) Re-weighting, Offline ResNet18 SHA256 Verified Load, Unclipped Area & Mode-Synced Heatmap)
파일명: patchcore_engine.py
"""

from pathlib import Path
import io
import json
import base64
import hashlib
from PIL import Image
import numpy as np
import torch
import torch.nn.functional as F
import torchvision.models as models
import torchvision.transforms as T
from scipy.ndimage import gaussian_filter, binary_dilation
import matplotlib

from rule_engine import evaluate_defect

torch.use_deterministic_algorithms(True)

BASE_DIR = Path(__file__).parent
MODEL_PATH = BASE_DIR / "models" / "memory_bank.pt"
RESNET18_LOCAL_PATH = BASE_DIR / "models" / "resnet18_imagenet_v1.pth"
RESNET18_SHA256 = "08d627238e253b434517f2d2e3dab9d4812e708de55cc6017ecd2bd164b034af"
EVAL_REPORT_PATH = BASE_DIR / "results" / "evaluation.json"
ENGINE_VERSION = "1.2.1-eq7-stratified-offline"

_YY, _XX = np.meshgrid(np.linspace(-1.0, 1.0, 32), np.linspace(-1.0, 1.0, 32), indexing="ij")
DEFAULT_OUTER_RING_MASK_32 = (np.sqrt(_XX ** 2 + _YY ** 2) >= 0.58) & (np.sqrt(_XX ** 2 + _YY ** 2) <= 0.95)


def load_resnet18_backbone(device: torch.device | str = "cpu") -> torch.nn.Module:
    """
    오프라인 시연 안전성을 위해 로컬 state_dict(models/resnet18_imagenet_v1.pth)가 존재하면
    SHA256 해시 검증 후 weights_only=True로 즉시 로드하고, 없을 때만 torchvision 공식 가중치 다운로드 시도
    """
    dev = torch.device(device)
    if RESNET18_LOCAL_PATH.exists():
        raw_bytes = RESNET18_LOCAL_PATH.read_bytes()
        actual_hash = hashlib.sha256(raw_bytes).hexdigest()
        if actual_hash != RESNET18_SHA256:
            raise RuntimeError(
                f"로컬 ResNet18 가중치 SHA256 불일치! 기대={RESNET18_SHA256[:12]}..., 실제={actual_hash[:12]}..."
            )
        model = models.resnet18(weights=None)
        state_dict = torch.load(io.BytesIO(raw_bytes), map_location=dev, weights_only=True)
        model.load_state_dict(state_dict)
        return model.to(dev).eval()
    try:
        weights = models.ResNet18_Weights.IMAGENET1K_V1
        model = models.resnet18(weights=weights)
        return model.to(dev).eval()
    except Exception as e:
        raise RuntimeError(
            f"ResNet18 가중치 로드 실패 (오프라인 환경에서는 {RESNET18_LOCAL_PATH} 파일이 필요합니다): {e}"
        ) from e


def compute_foreground_ring_mask_32(rgb_img: Image.Image) -> tuple[np.ndarray, tuple[float, float]]:
    """
    입력 이미지에서 밝기 기반 전경(금속 너트) 무게중심(Centroid)을 추정하고,
    해당 중심을 기준으로 32x32 격자 상의 외곽 조임면/나사산 링 마스크(0.58 <= r <= 0.95)를 동적 생성.
    """
    gray_32 = np.array(rgb_img.convert("L").resize((32, 32), Image.BILINEAR), dtype=np.float32)
    fg_thresh = float(np.percentile(gray_32, 45))
    fg_weights = np.maximum(gray_32 - fg_thresh, 0.0)
    total_w = float(np.sum(fg_weights))
    if total_w > 1e-3:
        cy = float(np.clip(np.sum(_YY * fg_weights) / total_w, -0.25, 0.25))
        cx = float(np.clip(np.sum(_XX * fg_weights) / total_w, -0.25, 0.25))
    else:
        cy, cx = 0.0, 0.0
    rr = np.sqrt((_XX - cx) ** 2 + (_YY - cy) ** 2)
    ring_mask = (rr >= 0.58) & (rr <= 0.95)
    return ring_mask, (round(cy, 4), round(cx, 4))


def compute_foreground_mask_32(rgb_img: Image.Image) -> np.ndarray:
    """
    Otsu 밝기 임계로 부품 전경을 32x32 격자에서 분리하고 1칸 팽창(외곽·탭 경계 유지).
    배경(지그 바닥)의 먼지·반사 패치가 이상 점수를 끌어올리는 정상품 오탐을 막는다.
    ponytail: 배경보다 밝은 부품 가정(metal_nut 지그). 결손으로 사라진 부위는 배경으로 보여 채점 제외됨 →
    결손형 결함이 중요한 부품이면 기준 정상 이미지의 전경 마스크를 합집합으로 쓰는 방식으로 교체.
    """
    g = np.array(rgb_img.convert("L").resize((32, 32), Image.BILINEAR), dtype=np.float32)
    hist, edges = np.histogram(g, bins=64)
    c = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    s0 = np.cumsum(hist * c)
    m0 = s0 / np.maximum(w0, 1)
    m1 = (s0[-1] - s0) / np.maximum(w1, 1)
    t = c[np.argmax(w0 * w1 * (m0 - m1) ** 2)]
    return binary_dilation(g > t, iterations=1)


def build_transform(input_size: int = 256) -> T.Compose:
    return T.Compose([
        T.Resize((input_size, input_size), interpolation=T.InterpolationMode.BILINEAR, antialias=True),
        T.ToTensor(),
        T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    ])


def extract_features(backbone: torch.nn.Module, img_tensor: torch.Tensor) -> torch.Tensor:
    """layer2 + layer3(업샘플) 결합 384채널 패치 특징. 256 입력 기준 [N, 384, 32, 32]."""
    with torch.no_grad():
        x = backbone.maxpool(backbone.relu(backbone.bn1(backbone.conv1(img_tensor))))
        f2 = backbone.layer2(backbone.layer1(x))
        f3 = backbone.layer3(f2)
        f2 = F.avg_pool2d(f2, kernel_size=3, stride=1, padding=1)
        f3 = F.avg_pool2d(f3, kernel_size=3, stride=1, padding=1)
        f3_up = F.interpolate(f3, size=f2.shape[-2:], mode="bilinear", align_corners=False)
        return F.normalize(torch.cat([f2, f3_up], dim=1), p=2, dim=1)


def score_patches_eq7(patches: torch.Tensor, memory_bank: torch.Tensor, mb_nb9_idx: torch.Tensor,
                      fg_mask: np.ndarray | None = None):
    """
    PatchCore Eq.6(최대 1-NN 거리) + Eq.7(N_b 재가중). 반환: (s_eq7, s_star, w_eq7, nn1_dists[P]).
    fg_mask(32x32 bool)가 주어지면 전경 패치만 채점하고 배경 패치 거리는 0으로 둔다(히트맵에도 반영).
    """
    if fg_mask is not None and fg_mask.any():
        keep = torch.from_numpy(fg_mask.ravel())
        s_eq7, s_star, w_eq7, d_fg = score_patches_eq7(patches[keep], memory_bank, mb_nb9_idx)
        nn1_dists = torch.zeros(patches.shape[0], dtype=d_fg.dtype)
        nn1_dists[keep] = d_fg
        return s_eq7, s_star, w_eq7, nn1_dists
    with torch.no_grad():
        max_sim, nn1_idx = torch.max(patches @ memory_bank.T, dim=1)
        nn1_dists = torch.sqrt(torch.clamp(2.0 - 2.0 * max_sim, min=1e-7))
        star = int(torch.argmax(nn1_dists).item())
        s_star = float(nn1_dists[star].item())
        nb9 = memory_bank[mb_nb9_idx[int(nn1_idx[star].item())]]
        d_nb9 = torch.sqrt(torch.clamp(2.0 - 2.0 * (patches[star:star + 1] @ nb9.T).squeeze(0), min=1e-7))
        w_eq7 = float((1.0 - torch.exp(d_nb9[0]) / torch.sum(torch.exp(d_nb9))).item())
    return w_eq7 * s_star, s_star, w_eq7, nn1_dists


class PatchCoreEngine:
    def __init__(self, model_path: Path = MODEL_PATH):
        self.device = torch.device("cpu")
        self.engine_version = ENGINE_VERSION
        self.backbone = load_resnet18_backbone(self.device)
        self.transform = build_transform(256)

        if not model_path.exists():
            raise FileNotFoundError(f"메모리 뱅크 파일을 찾을 수 없습니다: {model_path}")

        raw_bytes = model_path.read_bytes()
        self.model_hash = hashlib.sha256(raw_bytes).hexdigest()[:12]

        ckpt = torch.load(io.BytesIO(raw_bytes), map_location=self.device, weights_only=True)
        self.memory_bank = ckpt["memory_bank"].to(self.device)

        if "memory_bank_nb9_idx" in ckpt:
            self.mb_nb9_idx = ckpt["memory_bank_nb9_idx"].to(self.device)
        else:
            with torch.no_grad():
                mb_sim = self.memory_bank @ self.memory_bank.T
                _, self.mb_nb9_idx = torch.topk(mb_sim, k=9, dim=1)

        self.bank_image_indices = list(ckpt.get("bank_image_indices", []))
        self.validation_image_indices = list(ckpt.get("validation_image_indices", []))
        self.split_method = str(ckpt.get("split_method", "brightness_stratified"))
        self.primary_seed = int(ckpt.get("primary_seed", 42))

        self.raw_threshold = float(ckpt.get("raw_threshold", 0.4606))
        self.raw_min_anchor = float(ckpt.get("raw_min_anchor", 0.3500))
        self.raw_max_anchor = float(ckpt.get("raw_max_anchor", 0.6500))
        self.pixel_dist_thresh = float(ckpt.get("pixel_dist_thresh", 0.4648))
        self.edge_patch_thresh = float(ckpt.get("edge_patch_thresh", 0.5602))
        self.structural_thresholds = ckpt.get("structural_thresholds", {
            "peak_severe_threshold": 0.6487,
            "edge_involvement_threshold": 0.1400,
            "area_severe_threshold": 0.1600
        })
        self.threshold_source = str(
            ckpt.get(
                "threshold_source",
                "train/good_30_val_split (seed=42 brightness_stratified, Zero Overlap with 190-image Memory Bank, test_leakage=False)"
            )
        )
        self.metrics = ckpt.get("metrics", {})
        # 전경 마스크 채점은 그 방식으로 임계치를 캘리브레이션한 뱅크에서만 켠다(기존 뱅크 동작 불변).
        self.foreground_masked_scoring = bool(ckpt.get("foreground_masked_scoring", False))

    def extract_features(self, img_tensor: torch.Tensor) -> torch.Tensor:
        return extract_features(self.backbone, img_tensor)

    def raw_to_norm_score(self, raw_s: float) -> float:
        if raw_s < self.raw_threshold:
            ns = 0.60 * (raw_s - self.raw_min_anchor) / max(self.raw_threshold - self.raw_min_anchor, 1e-6)
            return float(np.clip(ns, 0.01, 0.5999))
        else:
            ns = 0.60 + 0.39 * (raw_s - self.raw_threshold) / max(self.raw_max_anchor - self.raw_threshold, 1e-6)
            return float(np.clip(ns, 0.6000, 0.9999))

    def predict(
        self,
        pil_img: Image.Image,
        include_heatmap: bool = True,
        operating_mode: str = "SAFETY_FIRST",
        part_geometry: str = "generic"
    ) -> dict:
        rgb_img = pil_img.convert("RGB")
        orig_w, orig_h = rgb_img.size
        target_h, target_w = max(orig_h, 256), max(orig_w, 256)

        with torch.no_grad():
            x = self.transform(rgb_img).unsqueeze(0).to(self.device)
            feat = self.extract_features(x)  # [1, 384, 32, 32]
            patches = feat.permute(0, 2, 3, 1).reshape(-1, 384)  # [1024, 384]

            fg_mask = compute_foreground_mask_32(rgb_img) if self.foreground_masked_scoring else None
            s_eq7, s_star, w_eq7, nn1_dists = score_patches_eq7(patches, self.memory_bank, self.mb_nb9_idx, fg_mask)

            d1_32 = nn1_dists.reshape(32, 32).cpu().numpy()
            peak_d1 = s_star

            if part_geometry == "circular_jig":
                ring_mask_32, fg_centroid = compute_foreground_ring_mask_32(rgb_img)
                calc_edge_ratio = float(np.mean(d1_32[ring_mask_32] >= self.edge_patch_thresh))
                outer_ring_ratio = round(calc_edge_ratio, 4)
                edge_region_ratio = round(calc_edge_ratio, 4)
                edge_metric_status = "CALCULATED_CIRCULAR_JIG"
                structural_shape_check = "PERFORMED"
                global_deformation_coverage = "SUPPORTED_RING_ONLY"
                rule_edge_ratio = calc_edge_ratio
                fg_centroid_yx = list(fg_centroid)
            else:
                outer_ring_ratio = None
                edge_region_ratio = None
                edge_metric_status = "NOT_APPLICABLE_FOR_GENERIC_PART"
                structural_shape_check = "NOT_PERFORMED"
                global_deformation_coverage = "LIMITED"
                rule_edge_ratio = 0.0
                fg_centroid_yx = None

            amap_32 = nn1_dists.reshape(1, 1, 32, 32)
            amap_native = F.interpolate(
                amap_32,
                size=(target_h, target_w),
                mode="bilinear",
                align_corners=False
            )[0, 0].cpu().numpy()
            sigma_scaled = 8.0 * (target_h / 700.0)
            amap_smooth = gaussian_filter(amap_native, sigma=sigma_scaled)

        norm_score = self.raw_to_norm_score(s_eq7)
        actual_defect_area_ratio = float(np.mean(amap_smooth >= self.pixel_dist_thresh))

        rule_res = evaluate_defect(
            anomaly_score=norm_score,
            mask_area_ratio=actual_defect_area_ratio,
            peak_patch_distance=peak_d1,
            edge_region_ratio=rule_edge_ratio,
            operating_mode=operating_mode,
            structural_thresholds=self.structural_thresholds
        )

        heatmap_pil = None
        heatmap_b64 = None
        if include_heatmap:
            suppress_overlay = (rule_res["heatmap_display"] == "SUPPRESSED_BELOW_THRESHOLD")
            heatmap_pil = self.render_heatmap_overlay(rgb_img, amap_smooth, suppress_overlay=suppress_overlay)
            buf = io.BytesIO()
            heatmap_pil.save(buf, format="PNG")
            heatmap_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return {
            "part_geometry": part_geometry,
            "structural_shape_check": structural_shape_check,
            "global_deformation_coverage": global_deformation_coverage,
            "anomaly_score": round(norm_score, 4),
            "normalized_anomaly_score": round(norm_score, 4),
            "raw_anomaly_score": round(s_eq7, 4),
            "raw_distance": round(s_eq7, 4),
            "raw_max_1nn_score": round(s_star, 4),
            "raw_top1_eq6": round(s_star, 4),
            "eq7_reweight_factor": round(w_eq7, 4),
            "peak_patch_distance": round(peak_d1, 4),
            "edge_region_ratio": edge_region_ratio,
            "outer_ring_ratio": outer_ring_ratio,
            "edge_metric_status": edge_metric_status,
            "defect_area_ratio": round(actual_defect_area_ratio, 4),
            "structural_defect_likelihood": rule_res["structural_defect_likelihood"],
            "foreground_centroid_yx": fg_centroid_yx,
            "decision": rule_res["decision"],
            "reason_code": rule_res["reason_code"],
            "decision_threshold": rule_res["decision_threshold"],
            "decision_basis": rule_res["decision_basis"],
            "heatmap_display": rule_res["heatmap_display"],
            "estimated_defect_pattern": rule_res["estimated_defect_pattern"],
            "pattern_estimate": rule_res["pattern_estimate"],
            "operating_mode": operating_mode,
            "manual_review_recommended": rule_res["manual_review_recommended"],
            "interlock": rule_res["interlock"],
            "summary": rule_res["summary"],
            "engine_version": self.engine_version,
            "model_hash": self.model_hash,
            "threshold_source": self.threshold_source,
            "heatmap_pil": heatmap_pil,
            "heatmap_base64": heatmap_b64
        }

    def render_heatmap_overlay(
        self,
        rgb_img: Image.Image,
        amap_native: np.ndarray,
        suppress_overlay: bool = False
    ) -> Image.Image:
        if suppress_overlay:
            return rgb_img

        orig_w, orig_h = rgb_img.size
        if amap_native.shape != (orig_h, orig_w):
            amap_pil = Image.fromarray(amap_native).resize((orig_w, orig_h), Image.BILINEAR)
            amap_full = np.array(amap_pil, dtype=np.float32)
        else:
            amap_full = amap_native.astype(np.float32)

        base_arr = np.array(rgb_img, dtype=np.float32)
        low_th = self.pixel_dist_thresh - 0.02
        high_th = self.pixel_dist_thresh + 0.18
        norm_map = np.clip((amap_full - low_th) / max(high_th - low_th, 1e-5), 0.0, 1.0)
        jet_rgba = matplotlib.colormaps["jet"](norm_map)
        jet_rgb = jet_rgba[:, :, :3] * 255.0

        alpha = (norm_map ** 1.2)[..., None] * 0.65
        blended = base_arr * (1.0 - alpha) + jet_rgb * alpha
        return Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8))


_ENGINE_INSTANCE: PatchCoreEngine | None = None


def get_engine() -> PatchCoreEngine:
    global _ENGINE_INSTANCE
    if _ENGINE_INSTANCE is None:
        _ENGINE_INSTANCE = PatchCoreEngine()
    return _ENGINE_INSTANCE


def load_evaluation_report() -> dict:
    if EVAL_REPORT_PATH.exists():
        with open(EVAL_REPORT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
