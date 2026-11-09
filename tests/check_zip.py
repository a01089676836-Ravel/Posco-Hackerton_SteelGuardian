"""Pre-submission checker for a hackathon code.zip (stdlib only).
Usage: python -I check_zip.py <code.zip>
Exit code: 0 = no FAIL, 1 = at least one FAIL, 2 = cannot open zip.
"""
import re
import sys
import zipfile

if len(sys.argv) != 2:
    print(__doc__)
    sys.exit(2)

try:
    zf = zipfile.ZipFile(sys.argv[1])
except (OSError, zipfile.BadZipFile) as e:
    print(f"FAIL  cannot open zip: {e}")
    sys.exit(2)

infos = [i for i in zf.infolist() if not i.is_dir()]
names = [i.filename.replace("\\", "/") for i in infos]
lower = [n.lower() for n in names]
results = []  # (level, message)


def add(level, msg):
    results.append((level, msg))


def base(n):
    return n.rsplit("/", 1)[-1]


def any_name(pattern):
    return [n for n, l in zip(names, lower) if re.search(pattern, l)]


# 1. README with run instructions
readmes = [n for n in names if re.fullmatch(r"readme(\.(md|txt|rst))?", base(n).lower())]
if not readmes:
    add("FAIL", "README not found (judges need install + run steps)")
else:
    text = zf.read(readmes[0]).decode("utf-8", "replace").lower()
    keys = ["install", "run", "실행", "설치", "pip ", "npm ", "python ", "docker", "uvicorn", "gradle", "make"]
    if not any(k in text for k in keys):
        add("WARN", f"{readmes[0]}: no install/run instructions found")
    if not re.search(r"api|endpoint|openapi|swagger|엔드포인트", text):
        add("WARN", f"{readmes[0]}: does not mention the API (explain why it is designed this way)")
    add("PASS", f"README: {readmes[0]}")

# 2. Dependency file
deps = any_name(r"(^|/)(requirements[^/]*\.txt|pyproject\.toml|pipfile|package\.json|pom\.xml|build\.gradle(\.kts)?|cmakelists\.txt|go\.mod|cargo\.toml|dockerfile|environment\.ya?ml)$")
add("PASS" if deps else "FAIL", f"dependency file: {', '.join(deps[:3])}" if deps else "no dependency file (requirements.txt / package.json / ...)")

# 3. API contract
api = any_name(r"(openapi|swagger)[^/]*\.(ya?ml|json)$|(^|/)docs?/api[^/]*\.md$|(^|/)api\.md$")
add("PASS" if api else "WARN", f"API contract: {', '.join(api[:3])}" if api else "no API contract (openapi.yaml or docs/api.md)")

# 4. Tests / scenarios
tests = any_name(r"(^|/)tests?/|(^|/)test_[^/]+\.py$|[^/]+_test\.(py|go)$|\.(test|spec)\.[jt]sx?$|scenarios?[^/]*\.(json|ya?ml|csv)$")
add("PASS" if tests else "WARN", f"tests/scenarios: {len(tests)} file(s)" if tests else "no tests or scenario files (judges try other inputs)")

# 5. Secrets
envs = [n for n in names if re.fullmatch(r"\.env(\..+)?", base(n)) and not base(n).endswith((".example", ".sample", ".template"))]
if envs:
    add("FAIL", f"secret env file included: {', '.join(envs)}")
secret_re = re.compile(rb"(sk-[A-Za-z0-9_\-]{20,}|sk-ant-[A-Za-z0-9_\-]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{35}|ghp_[A-Za-z0-9]{36}|(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"\s]{12,}['\"])", re.I)
abs_re = re.compile(rb"([A-Za-z]:\\\\?Users\\\\?[^\\\s'\"]+|/Users/[^/\s'\"]+/|/home/[^/\s'\"]+/)")
text_ext = re.compile(r"\.(py|js|ts|jsx|tsx|java|kt|go|rs|c|cc|cpp|h|hpp|cs|json|ya?ml|toml|ini|cfg|env|txt|md|ipynb|sh|bat|ps1)$|(^|/)\.env[^/]*$")
leaks, abspaths = [], []
for info, n in zip(infos, names):
    if base(n) == "check_zip.py":
        continue
    if not text_ext.search(n.lower()) or info.file_size > 2_000_000:
        continue
    data = zf.read(info)
    if secret_re.search(data) and not n.lower().endswith((".example", ".sample", ".template")):
        leaks.append(n)
    if abs_re.search(data):
        abspaths.append(n)
add("FAIL" if leaks else "PASS", f"possible API keys/secrets in: {', '.join(leaks[:5])}" if leaks else "no secrets detected")
if abspaths:
    add("WARN", f"absolute paths from your PC (break on the grader's machine): {', '.join(abspaths[:5])}")
if not any(re.search(r"\.env\.(example|sample|template)$", l) for l in lower) and (envs or leaks or any_name(r"\.py$|\.[jt]s$")):
    add("WARN", "no .env.example (list required env vars without values)")

# 6. Junk and size
junk_re = r"(^|/)(node_modules|venv|\.venv|env|__pycache__|\.git|\.idea|\.vscode|dist|build|\.pytest_cache|\.ipynb_checkpoints)/|(^|/)(\.ds_store|thumbs\.db)$|\.pyc$"
junk = sorted({m.group(0).strip("/") for l in lower if (m := re.search(junk_re, l))})
if junk:
    add("WARN", f"junk to remove: {', '.join(junk[:8])}")
big = [(n, i.file_size) for n, i in zip(names, infos) if i.file_size > 20_000_000]
for n, s in big:
    add("WARN", f"large file {n} ({s // 1_000_000} MB): check the size limit")
total = sum(i.file_size for i in infos)

# Report
print(f"{sys.argv[1]}: {len(names)} files, {total / 1_000_000:.1f} MB uncompressed")
order = {"FAIL": 0, "WARN": 1, "PASS": 2}
for level, msg in sorted(results, key=lambda r: order[r[0]]):
    print(f"{level:4}  {msg}")
fails = sum(1 for l, _ in results if l == "FAIL")
warns = sum(1 for l, _ in results if l == "WARN")
print(f"\nResult: {fails} FAIL, {warns} WARN. Next: unzip into a new folder and follow only the README (clean-run).")
sys.exit(1 if fails else 0)
