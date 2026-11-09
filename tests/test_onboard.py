"""
포스코 AI 해커톤 - 과제 C 검증: onboard_new_part.py
파일명: tests/test_onboard.py

실제 CLI를 subprocess로 실행하고, 콘솔 출력·종료 코드·생성 파일만 근거로 판정한다.
임시 입력/출력은 시스템 임시 폴더에 만들고 종료 시 삭제한다.
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
CLI = BASE_DIR / "onboard_new_part.py"
TRAIN_GOOD = BASE_DIR / "datasets" / "metal_nut" / "metal_nut" / "train" / "good"
TEST_DIR = BASE_DIR / "datasets" / "metal_nut" / "metal_nut" / "test"
PROTECTED = BASE_DIR / "models" / "memory_bank.pt"
VENV_PY = BASE_DIR / ".venv" / "Scripts" / "python.exe"

RESULTS: list[tuple[str, str, str]] = []


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_cli(*args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(CLI), *args]
    return subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace")


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, "PASS" if ok else "FAIL", detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} — {detail}")


def make_subset(root: Path, name: str, count: int) -> Path:
    d = root / name
    d.mkdir(parents=True)
    for p in sorted(TRAIN_GOOD.glob("*.png"))[:count]:
        shutil.copy2(p, d / p.name)
    return d


def main() -> int:
    protected_before = sha256(PROTECTED)
    tmp = Path(tempfile.mkdtemp(prefix="onboard_test_"))
    try:
        good20 = make_subset(tmp, "good20", 20)
        good24 = make_subset(tmp, "good24", 24)
        good19 = make_subset(tmp, "good19", 19)

        # 1 & 3. 20장 입력 성공 + validation 최소 5장 보장 + 신뢰도 등급/불확실성 정책 검증
        out1 = tmp / "run1" / "bank.pt"
        r = run_cli("--good-dir", str(good20), "--output", str(out1), "--seed", "42")
        meta1 = json.loads(out1.with_suffix(".meta.json").read_text(encoding="utf-8")) if out1.exists() else {}
        record("1. 20장 입력 CLI 실행 성공", r.returncode == 0 and out1.exists(),
               f"exit={r.returncode}, pt={'생성' if out1.exists() else '없음'}")
        n_val = meta1.get("split", {}).get("validation_images", -1)
        record("3. validation 최소 5장 보장", n_val >= 5 and "자동 조정" in r.stdout,
               f"validation={n_val}장, 자동 조정 메시지={'있음' if '자동 조정' in r.stdout else '없음'}")

        # 3b. 신뢰도 등급 및 threshold 불확실성 정책 검증 (20장 -> PILOT_LOW_CONFIDENCE, 수동검증 확대)
        tier1 = meta1.get("confidence_tier")
        hitl_rec = meta1.get("threshold_uncertainty_policy", {}).get("human_in_the_loop_extended_recommended")
        t_meta = meta1.get("timing_sec", {})
        has_targets = ("onboarding_target_seconds" in t_meta and "measured_total_seconds" in t_meta and "target_met" in t_meta)
        record("3b. 신뢰도 등급 및 불확실성 메타데이터", tier1 == "PILOT_LOW_CONFIDENCE" and hitl_rec is True and has_targets,
               f"tier={tier1}, HITL 확대={hitl_rec}, 목표시간 메타={'있음' if has_targets else '없음'}")

        # 3c. 20장 온보딩 운영 등급(operating_grade) 및 자동판정 불허(autonomous_decision_allowed=False) 정책 검증
        op_grade = meta1.get("operating_grade")
        auto_allowed = meta1.get("autonomous_decision_allowed")
        boundary_pol = meta1.get("boundary_and_suspect_policy")
        record("3c. 20장 온보딩 운영 등급 및 자동판정 불허 정책",
               op_grade == "PILOT_LOW_CONFIDENCE" and auto_allowed is False and boundary_pol == "MANUAL_REVIEW",
               f"operating_grade={op_grade}, autonomous_decision_allowed={auto_allowed}, boundary_policy={boundary_pol}")

        # 1b. 19장 → 실패해야 함
        r19 = run_cli("--good-dir", str(good19), "--output", str(tmp / "r19" / "bank.pt"))
        record("1b. 19장 입력 시 중단", r19.returncode != 0 and not (tmp / "r19" / "bank.pt").exists(),
               f"exit={r19.returncode}")

        # 2. 교집합 0% (meta와 .pt 양쪽)
        import torch
        ck1 = torch.load(out1, map_location="cpu", weights_only=False) if out1.exists() else {}
        b, v = set(ck1.get("bank_image_indices", [])), set(ck1.get("validation_image_indices", []))
        record("2. bank/validation 교집합 0%", len(b) > 0 and len(b & v) == 0 and len(b) + len(v) == 20
               and meta1["split"]["bank_validation_overlap"] == 0,
               f"bank={len(b)}, val={len(v)}, 교집합={len(b & v)}")

        # 4. 동일 seed·입력 2회 → threshold·인덱스·SHA256 동일 (파일명은 같고 폴더만 다르게)
        outA, outB = tmp / "repA" / "bank.pt", tmp / "repB" / "bank.pt"
        rA = run_cli("--good-dir", str(good24), "--output", str(outA), "--seed", "42")
        rB = run_cli("--good-dir", str(good24), "--output", str(outB), "--seed", "42")
        ok4 = rA.returncode == 0 and rB.returncode == 0
        if ok4:
            mA = json.loads(outA.with_suffix(".meta.json").read_text(encoding="utf-8"))
            mB = json.loads(outB.with_suffix(".meta.json").read_text(encoding="utf-8"))
            same_th = mA["calibration"]["raw_threshold"] == mB["calibration"]["raw_threshold"]
            same_idx = (mA["split"]["bank_image_indices"] == mB["split"]["bank_image_indices"]
                        and mA["split"]["validation_image_indices"] == mB["split"]["validation_image_indices"])
            shaA, shaB = sha256(outA), sha256(outB)
            ok4 = same_th and same_idx and shaA == shaB
            detail4 = (f"threshold {mA['calibration']['raw_threshold']} vs {mB['calibration']['raw_threshold']}, "
                       f"인덱스 동일={same_idx}, SHA256 {shaA[:12]} vs {shaB[:12]}")
        else:
            detail4 = f"exit A={rA.returncode}, B={rB.returncode}"
        record("4. 동일 seed 재실행 재현성", ok4, detail4)

        # 5. coreset clamp (20장 → bank 15장 = 15360 패치)
        out5 = tmp / "clamp" / "bank.pt"
        r5 = run_cli("--good-dir", str(good20), "--output", str(out5), "--coreset-size", "10000000")
        if r5.returncode == 0:
            m5 = json.loads(out5.with_suffix(".meta.json").read_text(encoding="utf-8"))["coreset"]
            ok5 = (m5["clamped"] and m5["applied_coreset_size"] == min(m5["total_patches"], m5["candidate_pool"])
                   and "clamp" in r5.stdout)
            detail5 = f"요청 {m5['requested_coreset_size']} → 적용 {m5['applied_coreset_size']} (전체 패치 {m5['total_patches']})"
        else:
            ok5, detail5 = False, f"exit={r5.returncode} {r5.stderr[-300:]}"
        record("5. coreset 자동 clamp", ok5, detail5)

        # 7. 기존 출력 존재 시 --overwrite 없이 실패, 있으면 성공
        r7a = run_cli("--good-dir", str(good20), "--output", str(out1))
        r7b = run_cli("--good-dir", str(good20), "--output", str(out1), "--overwrite")
        record("7. --overwrite 없이 덮어쓰기 거부", r7a.returncode != 0 and r7b.returncode == 0,
               f"overwrite 없음 exit={r7a.returncode}, overwrite 지정 exit={r7b.returncode}")

        # 7b. 출력이 입력 폴더 안이면 거부
        r7c = run_cli("--good-dir", str(good20), "--output", str(good20 / "bank.pt"))
        record("7b. 입력 폴더 내부 출력 거부", r7c.returncode != 0 and not (good20 / "bank.pt").exists(),
               f"exit={r7c.returncode}")

        # 6. models/memory_bank.pt 보호 (--overwrite 지정해도 거부) + 해시 불변
        r6 = run_cli("--good-dir", str(good20), "--output", str(PROTECTED), "--overwrite")
        protected_after = sha256(PROTECTED)
        record("6. 기본 memory_bank.pt 불변", r6.returncode != 0 and protected_before == protected_after,
               f"보호 경로 쓰기 exit={r6.returncode}, SHA256 {protected_before[:12]} → {protected_after[:12]}")

        # 8. custom bank 로 실제 이미지 추론
        from patchcore_engine import PatchCoreEngine
        from PIL import Image
        eng = PatchCoreEngine(model_path=outA)
        preds = {}
        for cat in ("good", "flip"):
            img = Image.open(sorted((TEST_DIR / cat).glob("*.png"))[0]).convert("RGB")
            preds[cat] = eng.predict(img, include_heatmap=False, operating_mode="SAFETY_FIRST")
        ok8 = all(p["decision"] in ("PASS", "REWORK", "SCRAP", "MANUAL_REVIEW") for p in preds.values())
        no_auto_scrap = all(p["decision"] != "SCRAP" for p in preds.values())
        record("8. custom bank 실제 추론", ok8,
               "; ".join(f"{c}/000.png → {p['decision']} (score {p['anomaly_score']})" for c, p in preds.items())
               + f"; MANUAL_REVIEW 정책상 SCRAP 없음={no_auto_scrap}")

        # 10. 청크 coreset == evaluate_benchmark 원본 함수 (소형 풀) — 원본 스크립트가 배포본에 없으면 검증 불가로 표기
        import importlib.util
        import onboard_new_part as onb
        if importlib.util.find_spec("evaluate_benchmark") is None:
            RESULTS.append(("10. 청크 coreset = 원본 함수", "NOT VERIFIED", "evaluate_benchmark.py 없음"))
            print("[NOT VERIFIED] 10. 청크 coreset — evaluate_benchmark.py 없음")
        else:
            import evaluate_benchmark as eb
            g = torch.Generator().manual_seed(0)
            pool = torch.nn.functional.normalize(torch.randn(5000, 384, generator=g), dim=1)
            mb_ref, nb_ref = eb.build_coreset_and_neighbors(pool, 500, seed=42)
            mb_new, nb_new = onb.build_coreset_and_neighbors_chunked(pool, 500, seed=42, chunk=128)
            same_mb = torch.equal(mb_ref, mb_new)
            nb_match = float((nb_ref == nb_new).float().mean().item())
            record("10. 청크 coreset = 원본 함수", same_mb and nb_match == 1.0,
                   f"memory bank 동일={same_mb}, N_b 인덱스 일치율={nb_match * 100:.2f}%")

        # 11. 전경 마스크 채점: 신규 뱅크는 마스크 캘리브레이션 플래그를 갖고, 기존 뱅크는 마스크를 쓰지 않아야 함(동작 불변)
        ckpt = torch.load(out1, weights_only=False)
        legacy = PatchCoreEngine(PROTECTED)
        record("11. 전경 마스크 플래그", ckpt.get("foreground_masked_scoring") is True and not legacy.foreground_masked_scoring,
               f"신규 뱅크={ckpt.get('foreground_masked_scoring')}, 기존 memory_bank.pt={legacy.foreground_masked_scoring}")

        # 9. tests/test_server.py (fastapi 필요 → .venv 인터프리터)
        if VENV_PY.exists():
            r9 = subprocess.run([str(VENV_PY), "tests/test_server.py"], cwd=BASE_DIR, capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
            record("9. tests/test_server.py 회귀", r9.returncode == 0, f"exit={r9.returncode} (.venv)")
            if r9.returncode != 0:
                print(r9.stdout[-1500:], r9.stderr[-1500:])
        else:
            RESULTS.append(("9. tests/test_server.py 회귀", "NOT VERIFIED", ".venv 없음"))
            print("[NOT VERIFIED] 9. tests/test_server.py — .venv 없음")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n| 항목 | 결과 | 근거 |\n| :--- | :---: | :--- |")
    for name, status, detail in RESULTS:
        print(f"| {name} | {status} | {detail} |")
    failed = [r for r in RESULTS if r[1] == "FAIL"]
    print(f"\n총 {len(RESULTS)}개 중 FAIL {len(failed)}개")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
