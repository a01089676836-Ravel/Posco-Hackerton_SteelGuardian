"""
포스코 AI 해커톤 - 스마트팩토리 비지도 결함 검사 규칙 엔진
(단일 진입점 의사결정, 운영 모드별 임계치 동기화, 검증셋 통계 기반 다중 특징 조합 판정)
파일명: rule_engine.py
"""

OPERATING_MODE_THRESHOLDS = {
    "SAFETY_FIRST": 0.6000,         # 안전 우선 모드: 불량 유출 방지 최우선
    "BALANCED_THROUGHPUT": 0.6450,  # 처리량 우선 모드: 정상 부품 재검 최소화
    "HUMAN_IN_THE_LOOP": 0.6000     # 사람 검증 연계 모드: 경계 구간(0.58~0.65)은 MANUAL_REVIEW로 판정
}
# 모드별 성능 수치는 results/evaluation.json을 기준으로 한다.

# 기본 모델(memory_bank.pt)의 구조적 결함 기준값. 실제 판정은 모델 체크포인트의 값을 사용한다.
DEFAULT_STRUCTURAL_THRESHOLDS = {
    "peak_severe_threshold": 0.6486,      # 검증셋 정상 최대 패치 거리(mu + 9.2*sigma)
    "edge_involvement_threshold": 0.1400, # 전경 중심 기준 외곽 조임면/나사산 링 이상 비율 한계
    "area_severe_threshold": 0.1600       # 무보정 실제 이상 픽셀 면적 비율 광역 한계 (16.0%)
}

# onboard_new_part.py가 구조 임계치 미지정 모델에 넣는 비활성화 값과 같아야 한다.
DISABLED_STRUCTURAL = 1e9


def get_mode_threshold(operating_mode: str = "SAFETY_FIRST") -> float:
    """운영 모드에 대응하는 정규화 의사결정 임계치 반환"""
    return float(OPERATING_MODE_THRESHOLDS.get(operating_mode, 0.6000))


def evaluate_defect(
    anomaly_score: float,
    mask_area_ratio: float = 0.0,
    peak_patch_distance: float = 0.0,
    edge_region_ratio: float | None = 0.0,
    structural_defect_likelihood: float | None = None,
    operating_mode: str = "SAFETY_FIRST",
    structural_thresholds: dict | None = None
) -> dict:
    """
    단일 의사결정 진입점(Single Source of Truth):
    - anomaly_score (정규화 이상 점수)와 mode별 decision_threshold를 비교하여 PASS 여부 결정
    - PASS일 경우 히트맵 표시를 SUPPRESSED_BELOW_THRESHOLD로 동기화하고 패턴 추정을 NORMAL_WITHIN_SPEC으로 고정
    - 이상 감지 시 강제 클리핑 없는 실제 면적(mask_area_ratio), 최대 패치 거리(peak_patch_distance),
      외곽 조임면/나사산 관여율(edge_region_ratio)의 다중 특징 조합(decision_basis)으로 REWORK vs SCRAP 결정
    - 자동 판정 불허 모델, HUMAN_IN_THE_LOOP 경계 구간, 구조 검사 비활성 모델의 이상 의심은 MANUAL_REVIEW로 분리
      (structural_thresholds의 autonomous_decision_allowed는 서버가 모델 메타데이터에서 주입)
    """
    decision_threshold = get_mode_threshold(operating_mode)
    st_cfg = structural_thresholds or DEFAULT_STRUCTURAL_THRESHOLDS
    peak_th = float(st_cfg.get("peak_severe_threshold", DEFAULT_STRUCTURAL_THRESHOLDS["peak_severe_threshold"]))
    edge_th = float(st_cfg.get("edge_involvement_threshold", DEFAULT_STRUCTURAL_THRESHOLDS["edge_involvement_threshold"]))
    area_th = float(st_cfg.get("area_severe_threshold", DEFAULT_STRUCTURAL_THRESHOLDS["area_severe_threshold"]))
    safe_edge_ratio = float(edge_region_ratio or 0.0)

    # 경계 구간(0.58 <= score < 0.65) 여부: 사람 2차 검증(MANUAL REVIEW) 권고 플래그
    manual_review_recommended = (0.5800 <= anomaly_score < 0.6500)

    # 구조적 변형 가능도(0.0 ~ 1.0) 산출 (외부 주입이 없을 경우 다중 특징 비율로 계산)
    if structural_defect_likelihood is None:
        p_ratio = min(1.0, max(0.0, (peak_patch_distance - 0.44) / max(peak_th - 0.44, 1e-4)))
        e_ratio = min(1.0, safe_edge_ratio / max(edge_th, 1e-4))
        a_ratio = min(1.0, mask_area_ratio / max(area_th, 1e-4))
        structural_defect_likelihood = round(float(max(p_ratio * 0.65 + e_ratio * 0.35, e_ratio * 0.75, a_ratio * 0.80)), 4)

    # 다중 특징 기반 구조적 변형 근거
    structural_reasons = []
    if peak_patch_distance >= peak_th:
        structural_reasons.append("extreme_peak_patch_distance")
    if safe_edge_ratio >= edge_th:
        structural_reasons.append("edge_region_thread_involvement")
    if mask_area_ratio >= area_th:
        structural_reasons.append("large_contiguous_defect_area")

    def manual_review(decision_basis: list[str]) -> dict:
        return {
            "decision": "MANUAL_REVIEW",
            "reason_code": "MANUAL_REVIEW_REQUIRED",
            "decision_threshold": round(decision_threshold, 4),
            "decision_basis": decision_basis,
            "heatmap_display": "ACTIVE_ANOMALY",  # 검토자가 이상 위치를 확인해야 한다.
            "action": "자동 이송 보류 및 2차 육안 판정 대기 (Manual Review Required)",
            "severity": "REVIEW",
            "color": "blue",
            "interlock": False,
            "operating_mode": operating_mode,
            "manual_review_recommended": True,
            "estimated_defect_pattern": "MANUAL_REVIEW_PENDING",
            "pattern_estimate": None,
            "outer_ring_ratio": round(safe_edge_ratio, 4) if edge_region_ratio is not None else None,
            "edge_region_ratio": round(safe_edge_ratio, 4) if edge_region_ratio is not None else None,
            "structural_defect_likelihood": round(float(structural_defect_likelihood), 4),
            "summary": f"이상 점수 {anomaly_score:.4f}로 자동 판정을 보류합니다. 2차 육안 판정을 대기합니다. (근거: {', '.join(decision_basis)})"
        }

    # 자동 판정 불허 모델: 이상 의심은 폐기·라인 정지 없이 전부 사람이 판정한다.
    if not st_cfg.get("autonomous_decision_allowed", True) and anomaly_score >= 0.5800:
        return manual_review(["autonomous_decision_not_allowed"] + structural_reasons)

    # 사람 연계 모드의 경계 구간: 임계치 이상의 구조 근거가 있으면 안전을 우선해 아래 SCRAP 경로로 보낸다.
    if operating_mode == "HUMAN_IN_THE_LOOP" and manual_review_recommended:
        if anomaly_score < decision_threshold or not structural_reasons:
            return manual_review(["borderline_confidence_zone", "human_review_required"] + structural_reasons)

    # 1. 정상 판정 (현재 운영 모드 임계치 미만) -> 히트맵 및 패턴 라벨 완전 동기화
    if anomaly_score < decision_threshold:
        decision_basis = ["score_below_operating_threshold"]
        if manual_review_recommended:
            decision_basis.append("borderline_confidence_zone")
        return {
            "decision": "PASS",
            "reason_code": "NORMAL_SURFACE",
            "decision_threshold": round(decision_threshold, 4),
            "decision_basis": decision_basis,
            "heatmap_display": "SUPPRESSED_BELOW_THRESHOLD",
            "action": "정상 통과 (Quality Checked)" + (" — [경계점수: 2차 육안확인 권고]" if manual_review_recommended else ""),
            "severity": "NORMAL",
            "color": "green",
            "interlock": False,
            "operating_mode": operating_mode,
            "manual_review_recommended": manual_review_recommended,
            "estimated_defect_pattern": "NORMAL_WITHIN_SPEC",
            "pattern_estimate": None,
            "outer_ring_ratio": round(safe_edge_ratio, 4) if edge_region_ratio is not None else None,
            "edge_region_ratio": round(safe_edge_ratio, 4) if edge_region_ratio is not None else None,
            "structural_defect_likelihood": round(float(structural_defect_likelihood), 4),
            "summary": f"운영 모드({operating_mode}) 임계치({decision_threshold:.3f}) 미만 정상 제품입니다. 후속 공정으로 자동 이송합니다."
        }

    # 구조 임계치 없이 온보딩한 모델은 표면 결함과 형상 파손을 구분할 수 없어 자동 REWORK로 보내지 않는다.
    if peak_th >= DISABLED_STRUCTURAL:
        return manual_review(["structural_check_disabled", "surface_vs_structural_not_determined"])

    # 2. 이상 감지 시 다중 특징 기반 구조적 변형(SCRAP) vs 표면 결함(REWORK) 분기
    if len(structural_reasons) == 0:
        decision_basis = [
            "anomaly_score_above_threshold",
            "surface_flaw_within_rework_limits"
        ]
        if manual_review_recommended:
            decision_basis.append("borderline_manual_review_recommended")
        pattern_label = "SURFACE_FLAW_ESTIMATE (rule-based: scratch/color)"
        return {
            "decision": "REWORK",
            "reason_code": "EXCESSIVE_SCRATCH_AREA",
            "decision_threshold": round(decision_threshold, 4),
            "decision_basis": decision_basis,
            "heatmap_display": "ACTIVE_ANOMALY",
            "action": "사상(연마) 라인 재작업 이송 (Rework / Manual Review)" if manual_review_recommended else "사상(연마) 라인 재작업 이송 (Rework Required)",
            "severity": "WARNING",
            "color": "orange",
            "interlock": False,
            "operating_mode": operating_mode,
            "manual_review_recommended": manual_review_recommended,
            "estimated_defect_pattern": pattern_label,
            "pattern_estimate": pattern_label,
            "outer_ring_ratio": round(safe_edge_ratio, 4) if edge_region_ratio is not None else None,
            "edge_region_ratio": round(safe_edge_ratio, 4) if edge_region_ratio is not None else None,
            "structural_defect_likelihood": round(float(structural_defect_likelihood), 4),
            "summary": (
                f"표면 결함 추정({pattern_label}, 실제 이상점유율 {mask_area_ratio*100:.2f}%, "
                f"외곽관여율 {safe_edge_ratio*100:.1f}%)이 감지되어 사상 연마/재검 공정으로 라우팅합니다."
            )
        }
    else:
        pattern_label = "STRUCTURAL_DEFORMATION_ESTIMATE (rule-based: bent/flip/outer-thread)"
        return {
            "decision": "SCRAP",
            "reason_code": "CRITICAL_SHAPE_DEFORMATION",
            "decision_threshold": round(decision_threshold, 4),
            "decision_basis": structural_reasons,
            "heatmap_display": "ACTIVE_ANOMALY",
            "action": "즉시 폐기 및 라인 비상 정지 (Interlock Triggered)",
            "severity": "CRITICAL",
            "color": "red",
            "interlock": True,
            "operating_mode": operating_mode,
            "manual_review_recommended": manual_review_recommended,
            "estimated_defect_pattern": pattern_label,
            "pattern_estimate": pattern_label,
            "outer_ring_ratio": round(safe_edge_ratio, 4) if edge_region_ratio is not None else None,
            "edge_region_ratio": round(safe_edge_ratio, 4) if edge_region_ratio is not None else None,
            "structural_defect_likelihood": round(float(structural_defect_likelihood), 4),
            "summary": (
                f"치명적 구조/외곽 변형 추정({pattern_label}, 근거: {', '.join(structural_reasons)}, "
                f"실제 이상점유율 {mask_area_ratio*100:.2f}%) 감지! 비상 인터록을 발령하고 즉시 폐기 처리합니다."
            )
        }
