# 本地启动 LH 标注工具（Auto-labeling-LH）
# 数据根默认指向本仓库下的 with_cameras_capture_*（不要用 E:\robot）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\start_lh_local.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\start_lh_local.ps1 -Python "D:\Anaconda\envs\model-group\python.exe"

param(
  [string]$Python = "",
  [string]$DatasetRoot = "",
  [int]$Port = 8080
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$LhRoot = Join-Path $RepoRoot "Auto-labeling-LH"

if (-not (Test-Path $LhRoot)) {
  throw "找不到 Auto-labeling-LH: $LhRoot"
}

if (-not $DatasetRoot) {
  $caps = @(Get-ChildItem -Path $RepoRoot -Directory -Filter "with_cameras_capture_*" -ErrorAction SilentlyContinue)
  if ($caps.Count -gt 0) {
    $DatasetRoot = $RepoRoot
  } else {
    throw "仓库根下没有 with_cameras_capture_*。请把采集目录放到仓库根，或用 -DatasetRoot 指定。"
  }
}

if (-not $Python) {
  $candidates = @(
    "D:\Anaconda\envs\model-group\python.exe",
    "python"
  )
  foreach ($c in $candidates) {
    if ($c -eq "python") { $Python = $c; break }
    if (Test-Path $c) { $Python = $c; break }
  }
}

$env:LH_DATASET_ROOT = $DatasetRoot
$env:LABEL_WITH_ANNOTATION_AND_DEPTH_ROOT = Join-Path $RepoRoot "label_with_annotation_and_depth"
$env:WEB_HOST = "127.0.0.1"
$env:WEB_PORT = "$Port"
# 本机无 GPU 时可改 cpu；有 CUDA 可删掉这行
if (-not $env:MODEL_DEVICE) { $env:MODEL_DEVICE = "cpu" }

Write-Host "LH_DATASET_ROOT = $env:LH_DATASET_ROOT"
Write-Host "LABEL_ROOT      = $env:LABEL_WITH_ANNOTATION_AND_DEPTH_ROOT"
Write-Host "Open            = http://127.0.0.1:$Port/annotate"
Write-Host "Health          = http://127.0.0.1:$Port/health"
Write-Host ""

Set-Location $LhRoot
& $Python -m web_server.app
