# ============================================================================
# Bước 0 — Smoke test toàn stack qua Docker.
# Chạy từ thư mục backend:  .\scripts\smoke_test.ps1
# Yêu cầu: Docker Desktop đang chạy + đã có file .env (copy từ .env.example).
# ============================================================================
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

if (-not (Test-Path ".env")) { throw "Thiếu .env — chạy: Copy-Item .env.example .env rồi điền secrets" }

Step "1/6 Build & up toàn stack"
docker compose up -d --build

Step "2/6 Chờ Postgres + Redis healthy"
$deadline = (Get-Date).AddMinutes(3)
do {
    Start-Sleep -Seconds 5
    $db = docker compose ps db --format json | ConvertFrom-Json
    $redis = docker compose ps redis --format json | ConvertFrom-Json
    Write-Host "  db=$($db.Health) redis=$($redis.Health)"
} until ((($db.Health -eq "healthy") -and ($redis.Health -eq "healthy")) -or ((Get-Date) -gt $deadline))

Step "3/6 Migrate (alembic upgrade head)"
docker compose run --rm migrate

Step "4/6 Bootstrap RBAC + tài khoản mặc định"
docker compose exec -T api python -m scripts.bootstrap

Step "5/6 Health check"
$health = Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get
Write-Host "  /health => $($health | ConvertTo-Json -Compress)"

Step "6/6 Auth E2E (login -> me -> refresh -> logout)"
$base = "http://localhost:8000/api/v1"
# /login and /refresh return a TokenResponse directly (not wrapped in {data}).
$login = Invoke-RestMethod -Uri "$base/auth/login" -Method Post -ContentType "application/json" `
    -Body (@{ username = "admin"; password = "Admin@12345" } | ConvertTo-Json)
$access = $login.access_token; $refresh = $login.refresh_token
# /me IS wrapped in an envelope: { "data": { ... } }
$me = Invoke-RestMethod -Uri "$base/auth/me" -Headers @{ Authorization = "Bearer $access" }
Write-Host "  /me => $($me.data.username) roles=$($me.data.roles -join ',')"
$ref = Invoke-RestMethod -Uri "$base/auth/refresh" -Method Post -ContentType "application/json" `
    -Body (@{ refresh_token = $refresh } | ConvertTo-Json)
Write-Host "  refresh => new access token len=$($ref.access_token.Length)"

Write-Host "`nSMOKE TEST PASSED ✅" -ForegroundColor Green
Write-Host "OpenAPI: http://localhost:8000/docs | MinIO: http://localhost:9001"
