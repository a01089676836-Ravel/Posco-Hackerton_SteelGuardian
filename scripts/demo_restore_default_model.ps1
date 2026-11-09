# SteelGuardian: 기본 모델(default) 복구 트리거
$ErrorActionPreference = "Stop"
$serverUrl = "http://127.0.0.1:8000/v1/models/activate"
$modelName = "default"

Write-Host "[SteelGuardian] 기본 모델(default) 복구 트리거 호출" -ForegroundColor Yellow
$body = @{ model_name = $modelName } | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri $serverUrl -Method Post -Body $body -ContentType "application/json"
    Write-Host "[성공] 기본 모델 복구 완료! 활성 모델: $($response.active_model)" -ForegroundColor Green
} catch {
    Write-Host "[실패] 기본 모델 복구 실패: $_" -ForegroundColor Red
}
