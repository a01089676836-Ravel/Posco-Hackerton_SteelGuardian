"""
포스코 AI 해커톤 - 역할별 맞춤형 배포 패키지 생성 스크립트
팀원 각자에게 전달할 독립 ZIP 파일을 Downloads 폴더 및 role_packages/ 폴더에 생성합니다.

1. role_1_ai_vision.zip         (AI/비전 알고리즘 엔지니어)
2. role_2_backend_security.zip  (백엔드 및 시스템 보안 엔지니어)
3. role_3_mes_domain.zip        (공정 도메인 룰 및 MES 감사 엔지니어)
4. role_4_frontend_ui.zip       (프론트엔드 및 관제 UI/UX 엔지니어)
5. role_5_pm_presentation.zip   (PM 및 발표·지표 총괄)
"""

import os
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = Path.home() / "Downloads"
OUTPUT_DIR = BASE_DIR / "role_packages"

EXCLUDE_DIRS = {".venv", "__pycache__", ".git", ".idea", ".vscode", ".pytest_cache", "wheels", "role_packages"}
EXCLUDE_EXTS = {".pyc", ".pyo", ".pyd"}
EXCLUDE_FILES = {".env", "package_roles.py", "package_submission.py"}

ROLE_CONFIGS = {
    "role_1a_data_benchmark.zip": {
        "title": "Role 1A: 데이터 엔지니어링 & 벤치마크 평가 (김지민)",
        "guide_md": "docs/roles/ROLE_DATA_ENGINEERING_BENCHMARK.md",
        "include_items": [
            "evaluate_benchmark.py",
            "tests/test_robustness.py",
            "datasets/metal_nut",
            "results/evaluation.json",
            "results/robustness_report.json",
            "tests/scenarios.json",
            "docs/final_metrics.md",
            "docs/roles/ROLE_DATA_ENGINEERING_BENCHMARK.md",
            "docs/roles/README.md",
            "README.md",
            "requirements.txt",
            "requirements.lock.txt"
        ]
    },
    "role_1b_ai_modeling.zip": {
        "title": "Role 1B: AI 비전 모델링 & 온보딩 (차주현)",
        "guide_md": "docs/roles/ROLE_AI_VISION_MODELING.md",
        "include_items": [
            "patchcore_engine.py",
            "onboard_new_part.py",
            "models/memory_bank.pt",
            "models/memory_bank.meta.json",
            "models/resnet18_imagenet_v1.pth",
            "datasets/metal_nut",
            "tests/test_onboard.py",
            "tests/test_server.py",
            "docs/final_metrics.md",
            "docs/roles/ROLE_AI_VISION_MODELING.md",
            "docs/roles/README.md",
            "README.md",
            "requirements.txt",
            "requirements.lock.txt"
        ]
    },
    "role_1_ai_vision.zip": {
        "title": "Role 1: AI/비전 알고리즘 엔지니어 (김지민 & 차주현 통합본)",
        "guide_md": "docs/roles/ROLE_AI_VISION_ENGINEER.md",
        "include_items": [
            "patchcore_engine.py",
            "onboard_new_part.py",
            "evaluate_benchmark.py",
            "rule_engine.py",
            "audit_logger.py",
            "models/memory_bank.pt",
            "models/memory_bank.meta.json",
            "models/resnet18_imagenet_v1.pth",
            "datasets/metal_nut",
            "results/evaluation.json",
            "results/robustness_report.json",
            "tests/scenarios.json",
            "tests/test_onboard.py",
            "tests/test_robustness.py",
            "tests/test_server.py",
            "docs/final_metrics.md",
            "docs/roles/ROLE_AI_VISION_ENGINEER.md",
            "docs/roles/ROLE_DATA_ENGINEERING_BENCHMARK.md",
            "docs/roles/ROLE_AI_VISION_MODELING.md",
            "docs/roles/README.md",
            "README.md",
            "requirements.txt",
            "requirements.lock.txt"
        ]
    },
    "role_2_backend_security.zip": {
        "title": "Role 2: 백엔드 및 시스템 보안 엔지니어",
        "guide_md": "docs/roles/ROLE_BACKEND_SECURITY.md",
        "include_items": [
            "server.py",
            "patchcore_engine.py",
            "rule_engine.py",
            "audit_logger.py",
            "package_submission.py",
            "check_ports.bat",
            "setup_and_run.bat",
            "run_dashboard.bat",
            ".streamlit/config.toml",
            ".env.example",
            ".env.demo_lan.example",
            "models/memory_bank.pt",
            "models/memory_bank.meta.json",
            "models/resnet18_imagenet_v1.pth",
            "datasets/metal_nut",
            "docs/api.md",
            "docs/openapi.yaml",
            "docs/SETUP_WINDOWS.md",
            "docs/MULTI_PART_LRU_CACHE_DESIGN.md",
            "docs/roles/ROLE_BACKEND_SECURITY.md",
            "docs/roles/README.md",
            "tests/test_server.py",
            "tests/test_live_server_endpoints.py",
            "tests/test_audit.py",
            "tests/test_stress_load.py",
            "tests/test_offline_airgap.py",
            "tests/test_security_regression.py",
            "tests/test_package_submission.py",
            "docs/worklog",
            "tests/scenarios.json",
            "tests/check_zip.py",
            "results/stress_test_report.json",
            "README.md",
            "requirements.txt",
            "requirements.lock.txt"
        ]
    },
    "role_3_mes_domain.zip": {
        "title": "Role 3: 공정 도메인 룰 및 MES 감사 엔지니어",
        "guide_md": "docs/roles/ROLE_MES_DOMAIN_ENGINEER.md",
        "include_items": [
            "rule_engine.py",
            "audit_logger.py",
            "patchcore_engine.py",
            "server.py",
            "models/memory_bank.pt",
            "models/memory_bank.meta.json",
            "models/resnet18_imagenet_v1.pth",
            "datasets/metal_nut",
            "logs/README.md",
            "tests/test_audit.py",
            "tests/test_server.py",
            "tests/scenarios.json",
            "results/stress_test_report.json",
            "docs/final_metrics.md",
            "docs/api.md",
            "docs/roles/ROLE_MES_DOMAIN_ENGINEER.md",
            "docs/roles/README.md",
            ".env.example",
            "README.md",
            "requirements.txt",
            "requirements.lock.txt"
        ]
    },
    "role_4_frontend_ui.zip": {
        "title": "Role 4: 프론트엔드 및 관제 UI/UX 엔지니어",
        "guide_md": "docs/roles/ROLE_FRONTEND_UI_ENGINEER.md",
        "include_items": [
            "app.py",
            "server.py",
            "patchcore_engine.py",
            "rule_engine.py",
            "audit_logger.py",
            "run_dashboard.bat",
            ".streamlit/config.toml",
            ".env.example",
            ".env.demo_lan.example",
            "models/memory_bank.pt",
            "models/memory_bank.meta.json",
            "models/resnet18_imagenet_v1.pth",
            "datasets/metal_nut",
            "results/evaluation.json",
            "tests/scenarios.json",
            "tests/test_dashboard_ui.py",
            "tests/test_streamlit_cache.py",
            "tests/test_offline_airgap.py",
            "tests/test_server.py",
            "docs/api.md",
            "docs/roles/ROLE_FRONTEND_UI_ENGINEER.md",
            "docs/roles/README.md",
            "README.md",
            "requirements.txt",
            "requirements.lock.txt"
        ]
    },
    "role_5_pm_presentation.zip": {
        "title": "Role 5: PM 및 발표·지표 동기화 총괄",
        "guide_md": "docs/roles/ROLE_PM_PRESENTATION_LEAD.md",
        "include_items": [
            "docs/final_metrics.md",
            "docs/SETUP_WINDOWS.md",
            "docs/MULTI_PART_LRU_CACHE_DESIGN.md",
            "docs/api.md",
            "docs/openapi.yaml",
            "docs/roles",
            "results/evaluation.json",
            "results/robustness_report.json",
            "tests/scenarios.json",
            "results/stress_test_report.json",
            "results/submission_security_report.json",
            "tests/check_zip.py",
            "README.md"
        ]
    }
}

def collect_files(include_items):
    matched_files = set()
    for item in include_items:
        p = BASE_DIR / item
        if not p.exists():
            continue
        if p.is_file():
            matched_files.add(p)
        elif p.is_dir():
            for root, dirs, files in os.walk(p):
                # 루트 레벨의 임시 scratch 디렉터리만 배제하고 데이터셋 내부의 scratch 결함 폴더는 보존
                dirs[:] = [
                    d for d in dirs 
                    if d not in EXCLUDE_DIRS 
                    and not d.startswith(".venv")
                    and not (Path(root) == BASE_DIR and d == "scratch")
                ]
                for f in files:
                    fp = Path(root) / f
                    if fp.name in EXCLUDE_FILES or fp.suffix.lower() in EXCLUDE_EXTS:
                        continue
                    if fp.suffix.lower() == ".csv" and "logs" in fp.parts:
                        continue
                    matched_files.add(fp)
    return sorted(list(matched_files))

def create_role_zip(zip_name, config, target_dirs):
    print(f"\n📦 [{zip_name}] {config['title']} 패키징 생성 중...")
    files = collect_files(config["include_items"])
    guide_path = BASE_DIR / config["guide_md"]

    for tdir in target_dirs:
        tdir.mkdir(parents=True, exist_ok=True)
        out_zip = tdir / zip_name
        with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            # 1. 루트에 ROLE_GUIDE.md로 메인 인스트럭션 포함
            if guide_path.exists():
                zf.write(guide_path, arcname="ROLE_GUIDE.md")

            # 2. 역할별 소스 파일들 패키징
            for fp in files:
                rel_path = fp.relative_to(BASE_DIR)
                arcname = str(rel_path).replace("\\", "/")
                zf.write(fp, arcname=arcname)

        print(f"  -> 생성 완료: {out_zip} ({len(files) + 1}개 파일, {out_zip.stat().st_size / 1_000_000:.1f} MB)")

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    print("================================================================================")
    print("🚀 POSCO AI 해커톤 역할별 독립 배포 ZIP 패키징 시작")
    print("================================================================================")

    for zip_name, config in ROLE_CONFIGS.items():
        create_role_zip(zip_name, config, [DOWNLOADS_DIR, OUTPUT_DIR])

    print("\n================================================================================")
    print("🎉 5대 역할별 독립 ZIP 패키지 생성 완료!")
    print(f"  - 다운로드 폴더: {DOWNLOADS_DIR}")
    print(f"  - 프로젝트 폴더: {OUTPUT_DIR}")
    print("================================================================================")

if __name__ == "__main__":
    main()
