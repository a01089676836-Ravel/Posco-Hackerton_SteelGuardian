# SteelGuardian 시연 3: 무중단 핫스왑 원클릭 트리거
# 대시보드에서 컨베이어 스트리밍이 가동 중인 상태에서 이 스크립트를 실행하면,
# 스트리밍 중단 없이 백엔드 모델이 metal_nut_fg (전경 마스크 개선 모델)로 즉시 활성화됩니다.

$ErrorActionPreference = "Stop"
$serverUrl = "http://127.0.0.1:8000/v1/models/activate"
$modelName = "metal_nut_fg"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " [SteelGuardian] 무중단 모델 핫스왑 트리거 호출" -ForegroundColor Yellow
Write-Host " 대상 모델: $modelName (전경 마스크 개선 PatchCore)" -ForegroundColor Gray
Write-Host " 엔드포인트: $serverUrl" -ForegroundColor Gray
Write-Host "============================================================" -ForegroundColor Cyan

$body = @{
    model_name = $modelName
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri $serverUrl -Method Post -Body $body -ContentType "application/json"
    Write-Host "`n[성공] 모델 활성화 완료!" -ForegroundColor Green
    Write-Host " - 활성 모델: $($response.active_model)"
    Write-Host " - 모델 SHA256 해시: $($response.model_hash)"
    Write-Host " - 메시지: $($response.message)"
    
    Write-Host "`n[시연 확인 포인트]" -ForegroundColor Magenta
    Write-Host " 1. 대시보드 상단 배너: 1프레임 모델 불일치 감지 후 즉시 '동기화 정상(해시 일치)'으로 자동 전환"
    Write-Host " 2. 감사 로그 파일: logs/model_activation_audit.csv 에서 모델 교체 이력 실시간 확인"
} catch {
    Write-Host "`n[실패] 모델 활성화 요청 실패: $_" -ForegroundColor Red
    Write-Host " 백엔드 서버(server.py)가 가동 중인지 확인하십시오." -ForegroundColor Yellow
}
