"""
연속 부하 및 메모리 누수, 포트 안정성 검증 스트레스 벤치마크 스크립트 (외부 모듈 무의존)
- 대상: FastAPI 추론 서버 (http://127.0.0.1:8000/v1/defects/inspect)
- 부하: MVTec Metal Nut 테스트셋 층화 인터리빙 200건 연속 요청
- 측정 지표: 지연시간(min, max, avg, P50, P95, P99), RSS 메모리 추이(MB), 감사로그 무유실(200건 일치)
"""

import os
import sys
import time
import json
import subprocess
import ctypes
from ctypes import wintypes
from pathlib import Path
import requests
import pandas as pd
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
TEST_DATA_DIR = BASE_DIR / "datasets" / "metal_nut" / "metal_nut" / "test"
AUDIT_LOG_FILE = BASE_DIR / "logs" / "inspection_audit.csv"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

TARGET_URL = "http://127.0.0.1:8000/v1/defects/inspect"
HEALTH_URL = "http://127.0.0.1:8000/health"
TOTAL_REQUESTS = 200


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD),
        ('PageFaultCount', wintypes.DWORD),
        ('PeakWorkingSetSize', ctypes.c_size_t),
        ('WorkingSetSize', ctypes.c_size_t),
        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPagedPoolUsage', ctypes.c_size_t),
        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
        ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
        ('PagefileUsage', ctypes.c_size_t),
        ('PeakPagefileUsage', ctypes.c_size_t)
    ]


def get_process_rss_mb(pid):
    if not pid:
        return 0.0
    try:
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not handle:
            return 0.0
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        success = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), ctypes.sizeof(counters))
        ctypes.windll.kernel32.CloseHandle(handle)
        if success:
            return counters.WorkingSetSize / (1024 * 1024)
        return 0.0
    except Exception:
        return 0.0


def get_server_pid(port=8000):
    try:
        cmd = f"powershell -Command \"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue).OwningProcess\""
        out = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
        lines = [line.strip() for line in out.splitlines() if line.strip().isdigit()]
        if lines:
            return int(lines[0])
    except Exception:
        pass
    return None


def collect_test_images():
    categories = ["good", "bent", "color", "flip", "scratch"]
    cat_images = {}
    for cat in categories:
        img_dir = TEST_DATA_DIR / cat
        if img_dir.exists():
            imgs = sorted(list(img_dir.glob("*.png")))
            cat_images[cat] = imgs
        else:
            cat_images[cat] = []

    # 층화 인터리빙: good 80개, 결함 4종 각 30개 (총 200개)
    targets = [
        ("good", 80),
        ("bent", 30),
        ("color", 30),
        ("flip", 30),
        ("scratch", 30)
    ]
    
    request_queue = []
    idx_map = {cat: 0 for cat in categories}
    counts = {cat: 0 for cat in categories}

    while len(request_queue) < TOTAL_REQUESTS:
        for cat, target_cnt in targets:
            if counts[cat] < target_cnt:
                imgs = cat_images[cat]
                if imgs:
                    img_path = imgs[idx_map[cat] % len(imgs)]
                    idx_map[cat] += 1
                    request_queue.append((cat, img_path))
                    counts[cat] += 1
                    if len(request_queue) >= TOTAL_REQUESTS:
                        break

    return request_queue


def run_benchmark():
    print(f"=== [1] 서버 헬스체크 및 프로세스 확인 ===")
    try:
        r = requests.get(HEALTH_URL, timeout=5)
        if r.status_code != 200:
            print(f"ERROR: Server health check failed with status {r.status_code}")
            return False
        health_info = r.json()
        print(f"Server Status: {health_info.get('status')}, Model: {health_info.get('model')}")
    except Exception as e:
        print(f"ERROR: Cannot connect to {HEALTH_URL}: {e}")
        return False

    server_pid = get_server_pid(8000)
    print(f"Tracking Server Process PID on port 8000: {server_pid}")

    # 초기 감사 로그 행 수 확인
    initial_audit_rows = 0
    if AUDIT_LOG_FILE.exists():
        try:
            df = pd.read_csv(AUDIT_LOG_FILE)
            initial_audit_rows = len(df)
            print(f"Initial Audit Log Rows: {initial_audit_rows}")
        except Exception as e:
            print(f"Audit Log Read Warning: {e}")

    # 이미지 큐 준비
    images = collect_test_images()
    print(f"\n=== [2] 200건 층화 연속 부하 테스트 시작 ===")
    print(f"Total Requests: {len(images)} (Good: 80, Bent: 30, Color: 30, Flip: 30, Scratch: 30)")

    latencies_ms = []
    memory_snapshots = []
    error_count = 0
    verdicts = {"PASS": 0, "REWORK": 0, "SCRAP": 0}

    initial_rss_mb = get_process_rss_mb(server_pid)
    memory_snapshots.append({"request_idx": 0, "rss_mb": round(initial_rss_mb, 2)})
    print(f"Initial Server RSS Memory: {initial_rss_mb:.2f} MB")

    t_start = time.perf_counter()

    for idx, (cat, img_path) in enumerate(images, 1):
        req_start = time.perf_counter()
        with open(img_path, "rb") as f:
            file_bytes = f.read()

        payload = {
            "camera_id": f"STRESS_CAM_{cat.upper()}",
            "operating_mode": "SAFETY_FIRST",
            "part_geometry": "generic",
            "include_heatmap": "true"
        }
        files = {"file": (img_path.name, file_bytes, "image/png")}

        try:
            resp = requests.post(TARGET_URL, data=payload, files=files, timeout=10)
            req_duration_ms = (time.perf_counter() - req_start) * 1000.0
            latencies_ms.append(req_duration_ms)

            if resp.status_code == 200:
                res_data = resp.json()
                v = res_data.get("decision", "UNKNOWN")
                verdicts[v] = verdicts.get(v, 0) + 1
            else:
                error_count += 1
                print(f"[{idx}/200] FAILED: Status {resp.status_code} - {resp.text[:100]}")
        except Exception as e:
            req_duration_ms = (time.perf_counter() - req_start) * 1000.0
            latencies_ms.append(req_duration_ms)
            error_count += 1
            print(f"[{idx}/200] EXCEPTION: {e}")

        # 25건마다 진행 상황 및 메모리 스냅샷
        if idx % 25 == 0 or idx == TOTAL_REQUESTS:
            curr_rss = get_process_rss_mb(server_pid)
            memory_snapshots.append({"request_idx": idx, "rss_mb": round(curr_rss, 2)})
            recent_avg = np.mean(latencies_ms[-25:])
            print(f"[{idx:3d}/200] Recent 25 Latency: {recent_avg:.1f}ms | Current RSS: {curr_rss:.1f} MB | Errors: {error_count}")

    t_total = time.perf_counter() - t_start
    print(f"\n=== [3] 부하 테스트 완료 요약 ===")
    print(f"Total Time: {t_total:.2f} s | Throughput: {TOTAL_REQUESTS / t_total:.2f} req/s")

    # 통계 계산
    p50 = np.percentile(latencies_ms, 50)
    p90 = np.percentile(latencies_ms, 90)
    p95 = np.percentile(latencies_ms, 95)
    p99 = np.percentile(latencies_ms, 99)
    avg_lat = np.mean(latencies_ms)
    min_lat = np.min(latencies_ms)
    max_lat = np.max(latencies_ms)

    early_20_avg = np.mean(latencies_ms[:20])
    late_20_avg = np.mean(latencies_ms[-20:])
    drift_percent = ((late_20_avg - early_20_avg) / early_20_avg) * 100.0

    final_rss_mb = get_process_rss_mb(server_pid)
    rss_growth_mb = final_rss_mb - initial_rss_mb

    print(f"Latency: Avg={avg_lat:.1f}ms, P50={p50:.1f}ms, P95={p95:.1f}ms, P99={p99:.1f}ms, Min={min_lat:.1f}ms, Max={max_lat:.1f}ms")
    print(f"Early 20 Avg: {early_20_avg:.1f}ms vs Late 20 Avg: {late_20_avg:.1f}ms (Drift: {drift_percent:+.2f}%)")
    print(f"Memory RSS: Initial={initial_rss_mb:.1f} MB -> Final={final_rss_mb:.1f} MB (Delta: {rss_growth_mb:+.1f} MB)")
    print(f"Verdicts: PASS={verdicts.get('PASS', 0)}, REWORK={verdicts.get('REWORK', 0)}, SCRAP={verdicts.get('SCRAP', 0)}")
    print(f"Errors: {error_count} / {TOTAL_REQUESTS} ({error_count/TOTAL_REQUESTS*100:.2f}%)")

    # 감사 로그 무결성 검증
    final_audit_rows = 0
    audit_row_delta = 0
    if AUDIT_LOG_FILE.exists():
        try:
            df = pd.read_csv(AUDIT_LOG_FILE)
            final_audit_rows = len(df)
            audit_row_delta = final_audit_rows - initial_audit_rows
            print(f"Audit Log Rows: {initial_audit_rows} -> {final_audit_rows} (Delta: {audit_row_delta})")
        except Exception as e:
            print(f"Audit Log Verification Warning: {e}")

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "total_requests": TOTAL_REQUESTS,
        "total_time_seconds": round(t_total, 2),
        "throughput_req_per_sec": round(TOTAL_REQUESTS / t_total, 2),
        "latency_ms": {
            "mean": round(float(avg_lat), 2),
            "p50": round(float(p50), 2),
            "p90": round(float(p90), 2),
            "p95": round(float(p95), 2),
            "p99": round(float(p99), 2),
            "min": round(float(min_lat), 2),
            "max": round(float(max_lat), 2)
        },
        "performance_drift": {
            "early_20_avg_ms": round(float(early_20_avg), 2),
            "late_20_avg_ms": round(float(late_20_avg), 2),
            "drift_percent": round(float(drift_percent), 2)
        },
        "memory_rss_mb": {
            "initial": round(float(initial_rss_mb), 2),
            "final": round(float(final_rss_mb), 2),
            "delta": round(float(rss_growth_mb), 2),
            "snapshots": memory_snapshots
        },
        "verdicts": verdicts,
        "error_count": error_count,
        "error_rate_percent": round((error_count / TOTAL_REQUESTS) * 100.0, 2),
        "audit_log_verification": {
            "initial_rows": initial_audit_rows,
            "final_rows": final_audit_rows,
            "delta_rows": audit_row_delta,
            "expected_delta": TOTAL_REQUESTS,
            "lossless": (audit_row_delta == TOTAL_REQUESTS)
        }
    }

    report_path = RESULTS_DIR / "stress_test_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"Report saved to {report_path}")
    return True


if __name__ == "__main__":
    success = run_benchmark()
    sys.exit(0 if success else 1)
