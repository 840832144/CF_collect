# cf_start_frida_server.ps1 — 推送并启动改名 frida-server（隐身）
# 改编自 Huuuge `start_frida_server.ps1`；改动：adb 路径默认蓝叠 HD-Adb，
# server 远程文件名使用中性名（会话后删除）。
#
# 用法（由 run_collector.ps1 调用，或手动）：
#   powershell -ExecutionPolicy Bypass -File cf_start_frida_server.ps1 `
#       -ServerPath <frida-server-17.17.0-android-x86_64 的路径> `
#       -Serial 127.0.0.1:5585
param(
  [Parameter(Mandatory=$true)]
  [string]$ServerPath,
  [string]$Serial = "127.0.0.1:5585",
  [string]$RemotePath = "/data/local/tmp/cf_rt_mon",
  [string]$AdbPath = "C:\Program Files\BlueStacks_nxt_cn\HD-Adb.exe",
  [switch]$DiagnosticShellMode
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $ServerPath)) { throw "frida-server file not found: $ServerPath" }
if (-not (Test-Path $AdbPath)) {
  $AdbPath = "C:\platform-tools\adb.exe"
  if (-not (Test-Path $AdbPath)) { throw "No usable adb; set -AdbPath" }
}
$adb = $AdbPath

$target = @("-s", $Serial)
& $adb connect $Serial | Out-Null
& $adb @target get-state | Out-Null
& $adb @target push $ServerPath $RemotePath
& $adb @target shell chmod 755 $RemotePath

$serverVersion = (& $adb @target shell "$RemotePath --version").Trim()
$hostVersion = (python -c "import frida; print(frida.__version__)").Trim()
if (-not $hostVersion) { $hostVersion = (py -c "import frida; print(frida.__version__)").Trim() }
Write-Host "Host Frida:   $hostVersion"
Write-Host "Server Frida: $serverVersion"
if ($hostVersion -ne $serverVersion) {
  throw "Host/server Frida version mismatch ($hostVersion vs $serverVersion)."
}

$rootLauncher = $null
foreach ($su in @("/system/xbin/bstk/su", "/system/xbin/su")) {
  $identity = (& $adb @target shell "$su -c 'id'" 2>&1) -join " "
  if ($identity -match 'uid=0\(root\)') { $rootLauncher = $su; break }
}

if ($rootLauncher) {
  Write-Host "Starting frida-server through $rootLauncher (renamed: $RemotePath)"
  & $adb @target shell "$rootLauncher -c '$RemotePath -D >$RemotePath.log 2>&1 </dev/null'"
} elseif ($DiagnosticShellMode) {
  Write-Warning "Starting frida-server as shell for diagnostics only; attach will fail."
  & $adb @target shell "$RemotePath -D >$RemotePath.log 2>&1 </dev/null"
} else {
  throw "No usable root launcher. Enable root on Pie64_3 (with backup/rollback) before the session."
}

Start-Sleep -Seconds 2
Write-Host "Testing Frida device..."
python -c "import frida; d=frida.get_device_manager().get_device('$Serial', timeout=10); print('Device:', d.name); print('Processes:', len(d.enumerate_processes()))"
