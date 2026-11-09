"""
포스코 AI 해커톤 - 배포 ZIP 패키징 및 보안 감사 스크립트
1. code_lightweight.zip: 20MB 이하 경량 패키지 (check_zip.py 0 FAIL, 0 WARN)
2. code.zip: ResNet18 로컬 가중치 포함 오프라인 올인원 패키지
3. submission_security_report.json: 비밀키, 개인 식별정보, Base64 이미지, 미인가 파일 누출 검사 보고서
"""

import os
import sys
import re
import json
import zipfile
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = Path.home() / "Downloads"

EXCLUDE_DIRS = {".venv", "__pycache__", ".git", ".idea", ".vscode", ".pytest_cache", ".cache", "role_packages", "worklog"}
# 데이터셋의 test/scratch 불량 이미지까지 제외되지 않도록 프로젝트 최상위에서만 적용한다.
ROOT_ONLY_EXCLUDE_DIRS = {"scratch"}
EXCLUDE_EXTS = {".pyc", ".pyo", ".pyd"}
EXCLUDE_FILES = {"package_submission.py", ".env"}
LIGHTWEIGHT_MAX_BYTES = 20_000_000

SECRET_PATTERNS = [
    (r"sk-[A-Za-z0-9_\-]{20,}", "OpenAI API Key 패턴"),
    (r"ghp_[A-Za-z0-9]{36}", "GitHub Personal Access Token 패턴"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key 패턴"),
    (r"(admin[_-]?api[_-]?key|admin[_-]?key|secret[_-]?key)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]", "하드코딩된 ADMIN_KEY/SECRET_KEY 패턴"),
    (r"(?m)^\s*(?:ADMIN_API_KEY|ADMIN_KEY)\s*=\s*(\S{8,})", ".env 형식 관리자 키 값 패턴"),
]

BASE64_IMAGE_PATTERN = re.compile(r"data:image\/(?:png|jpeg|jpg|webp);base64,[A-Za-z0-9+\/=]{100,}", re.I)
PERSONAL_PATH_PATTERN = re.compile(r"([A-Za-z]:[\\\/]Users[\\\/][a-zA-Z0-9_-]+|[\\\/]Users[\\\/][a-zA-Z0-9_-]+|[\\\/]home[\\\/][a-zA-Z0-9_-]+)", re.I)

TEXT_EXTENSIONS = {
    ".py", ".bat", ".env", ".example", ".md", ".txt", ".json", ".yaml", ".yml",
    ".csv", ".sh", ".toml", ".ini", ".cfg"
}

def should_exclude(rel_path: Path, is_lightweight: bool) -> bool:
    if rel_path.name in EXCLUDE_FILES:
        return True
    # .env 파일 제외 (단, .example 파일은 템플릿으로 포함)
    if rel_path.name == ".env" or (rel_path.name.startswith(".env.") and not rel_path.name.endswith(".example")):
        return True

    parts = rel_path.parts
    if parts[0] in ROOT_ONLY_EXCLUDE_DIRS:
        return True
    for p in parts:
        if p in EXCLUDE_DIRS or p.startswith(".venv"):
            return True
    if rel_path.suffix.lower() in EXCLUDE_EXTS:
        return True

    # logs 폴더 내부의 모든 csv/log/tmp 및 하위 디렉터리(test, backup) 제외 (설명용 README만 유지)
    if len(parts) >= 2 and parts[0] == "logs":
        if len(parts) > 2 or rel_path.suffix.lower() in (".csv", ".log", ".tmp"):
            return True

    # lightweight 버전에서는 wheels 폴더, 데이터셋 및 대용량 백본 가중치 제외
    if is_lightweight:
        if parts[0] in ("wheels", "datasets") or rel_path.name == "resnet18_imagenet_v1.pth":
            return True

    return False

def audit_zip_security(zip_path: Path, is_lightweight: bool = True) -> dict:
    print(f"\n🛡️ [{zip_path.name}] 보안 및 개인정보 누출 전수 검증 시작...")
    report = {
        "zip_file": zip_path.name,
        "zip_size_bytes": zip_path.stat().st_size,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_files": 0,
        "prohibited_files_found": [],
        "secrets_found": [],
        "base64_images_found": [],
        "personal_paths_found": [],
        "size_limit_exceeded": False,
        "security_verdict": "PASS"
    }

    if is_lightweight:
        prohibited_name_re = re.compile(r"(^|/)\.env$|\.pyc$|(^|/)(__pycache__|\.venv)/|^(wheels|datasets|scratch)/|(^|/)logs/[^/]+\.csv$")
        report["size_limit_exceeded"] = report["zip_size_bytes"] > LIGHTWEIGHT_MAX_BYTES
    else:
        prohibited_name_re = re.compile(r"(^|/)\.env$|\.pyc$|(^|/)(__pycache__|\.venv)/|^scratch/|(^|/)logs/[^/]+\.csv$")

    with zipfile.ZipFile(zip_path, "r") as zf:
        infolist = zf.infolist()
        report["total_files"] = len(infolist)

        for info in infolist:
            fname = info.filename.replace("\\", "/")
            if prohibited_name_re.search(fname):
                report["prohibited_files_found"].append(fname)

            # 텍스트 파일 내용 검사
            ext = Path(fname).suffix.lower()
            if ext in TEXT_EXTENSIONS and info.file_size < 5_000_000:
                try:
                    content = zf.read(info).decode("utf-8", errors="replace")
                except Exception:
                    continue

                # 1. 시크릿 및 ADMIN_API_KEY 검사
                for pat, desc in SECRET_PATTERNS:
                    # 예시 파일도 실제 키가 들어가면 그대로 배포되므로 검사 대상에 포함한다 (자리표시자만 제외).
                    matches = re.findall(pat, content, re.I)
                    for m in matches:
                        match_str = m if isinstance(m, str) else m[0]
                        if "your-secure-admin" in match_str:
                            continue
                        # 리포트에 키 원문이 남지 않도록 값은 기록하지 않는다.
                        report["secrets_found"].append({"file": fname, "type": desc})

                # 2. Base64 이미지 인라인 삽입 검사 (JSON이나 소스 내 거대 이미지 누출 방지)
                b64_matches = BASE64_IMAGE_PATTERN.findall(content)
                if b64_matches:
                    report["base64_images_found"].append({"file": fname, "count": len(b64_matches)})

                # 3. 개인 로컬 절대 경로 노출 검사
                # 보안 감사 리포트 자체의 진단 스니펫은 제외
                if not fname.endswith("submission_security_report.json"):
                    path_matches = PERSONAL_PATH_PATTERN.findall(content)
                    for p_match in path_matches:
                        if any(ign in p_match.lower() for ign in ["<내_ip>", "<서버_ip>", "<pid>"]):
                            continue
                        report["personal_paths_found"].append({"file": fname, "path_snippet": p_match})

    if (report["prohibited_files_found"] or report["secrets_found"] or
        report["base64_images_found"] or report["personal_paths_found"] or
        report["size_limit_exceeded"]):
        report["security_verdict"] = "FAIL"

    print(f"  - 총 검사 파일 수: {report['total_files']}개")
    if is_lightweight:
        print(f"  - 크기: {report['zip_size_bytes'] / 1_000_000:.1f} MB (한도 {LIGHTWEIGHT_MAX_BYTES / 1_000_000:.0f} MB)")
    print(f"  - 금지 파일 감지: {len(report['prohibited_files_found'])}건")
    print(f"  - 비밀키(API Key) 감지: {len(report['secrets_found'])}건")
    print(f"  - Base64 인라인 이미지 감지: {len(report['base64_images_found'])}건")
    print(f"  - 개인 PC 절대경로 감지: {len(report['personal_paths_found'])}건")
    print(f"  - 최종 보안 판정: {report['security_verdict']}")

    return report

def build_zip(zip_path: Path, is_lightweight: bool):
    print(f"\n📦 [{zip_path.name}] 패키징 시작 (is_lightweight={is_lightweight})...")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        count = 0
        total_size = 0
        for root, dirs, files in os.walk(BASE_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".venv")]
            for f in files:
                full_p = Path(root) / f
                rel_p = full_p.relative_to(BASE_DIR)
                if should_exclude(rel_p, is_lightweight):
                    continue
                arcname = str(rel_p).replace("\\", "/")
                zf.write(full_p, arcname=arcname)
                count += 1
                total_size += full_p.stat().st_size
    print(f"✅ [{zip_path.name}] 패키징 완료: {count}개 파일, 압축 해제 {total_size / 1_000_000:.1f} MB, zip 크기 {zip_path.stat().st_size / 1_000_000:.1f} MB")

def main():
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    zip_light = DOWNLOADS_DIR / "code_lightweight.zip"
    zip_full = DOWNLOADS_DIR / "code.zip"

    build_zip(zip_light, is_lightweight=True)
    build_zip(zip_full, is_lightweight=False)

    report_light = audit_zip_security(zip_light, is_lightweight=True)
    report_full = audit_zip_security(zip_full, is_lightweight=False)

    final_report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": "POSCO Hackathon Submission Security Audit Report",
        "code_lightweight": report_light,
        "code_full": report_full
    }

    # 리포트 저장 (프로젝트 results 및 Downloads 디렉터리)
    res_dir = BASE_DIR / "results"
    res_dir.mkdir(parents=True, exist_ok=True)
    report_path_project = res_dir / "submission_security_report.json"
    report_path_downloads = DOWNLOADS_DIR / "submission_security_report.json"

    formatted_json = json.dumps(final_report, indent=2, ensure_ascii=False)
    report_path_project.write_text(formatted_json, encoding="utf-8")
    report_path_downloads.write_text(formatted_json, encoding="utf-8")

    print(f"\n📄 보안 검사 리포트 저장 완료: {report_path_project}")
    print(f"📄 다운로드 폴더 리포트 저장 완료: {report_path_downloads}")

    passed = report_light["security_verdict"] == "PASS" and report_full["security_verdict"] == "PASS"
    print(f"\n최종 판정: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1

if __name__ == "__main__":
    sys.exit(main())
