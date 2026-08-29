# run_collector.ps1 — CF_collect 一键采集（config 驱动，无 DSH 依赖）
# 前置：已运行 setup.ps1；User 已按文档手动开启研究实例 Root；【游戏】可游玩。
# 流程：预检 -> frida-server -> gadget+config -> forward -> bootstrap -> 探针 READY
#       ->（玩家正常游玩）-> STOP -> 提取 -> 汇总 -> finally 强制清理运行时资源
# 注意：本脚本只检测 Root，不改变 Root；会话后由 User 手动关闭 Root、重启并验证失效。
param(
  [string]$ProjectRoot = $PSScriptRoot,
  [int]$DurationSeconds = 0     # 0 表示用 config.json 的 session_duration_seconds
)
$ErrorActionPreference = "Stop"
$project = (Resolve-Path $ProjectRoot).Path
$config = Get-Content (Join-Path $project "config.json") -Raw | ConvertFrom-Json
$scriptDir = Join-Path $project "collector"
$venvPy = Join-Path $project ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { throw "Run setup.ps1 first (missing $venvPy)" }
if ($DurationSeconds -le 0) { $DurationSeconds = [int]$config.session_duration_seconds }

$serial = $config.adb_serial
$pkg = $config.package
$gadgetPort = $config.gadget_port
$rootLauncher = $config.root_launcher
$maxDepth = $config.max_depth
$env:PYTHONPATH = $project
$env:CF_APP_VERSION = [string]$config.app_version

function Adb {
  foreach ($cand in @("C:\Program Files\BlueStacks_nxt_cn\HD-Adb.exe","C:\Program Files\BlueStacks_nxt\HD-Adb.exe","C:\platform-tools\adb.exe")) {
    if (Test-Path $cand) { return $cand }
  }
  $reg = Get-ItemProperty "HKLM:\SOFTWARE\BlueStacks_nxt_cn" -ErrorAction SilentlyContinue
  if ($reg -and $reg.InstallDir) {
    $c = Join-Path $reg.InstallDir "HD-Adb.exe"; if (Test-Path $c) { return $c }
  }
  throw "adb not found. Run setup.ps1."
}

function Step([string]$t){ Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Ok([string]$t){ Write-Host "[OK] $t" -ForegroundColor Green }
function Warn([string]$t){ Write-Host "[WARN] $t" -ForegroundColor Yellow }

function Test-ProbeReadyState([object]$State) {
  if ($null -eq $State -or $State.status -ne "ready") { return $false }
  if ($null -eq $State.readiness -or $State.readiness.status -ne "verified") { return $false }
  if ($State.readiness.mode -ne "lua" -or $State.readiness.kind -ne "hook-status") { return $false }
  $installed = @($State.readiness.installed_hooks)
  return (($installed -contains "onUIThreadReceiveMessage") -and ($installed -contains "lua_pcall"))
}

function Invoke-CollectorCleanup {
  param(
    [System.Collections.IList]$Items,
    [string]$AdbPath,
    [string]$DeviceSerial,
    [string]$PackageName,
    [bool]$CanForceStop
  )
  $cleanupErrors = New-Object System.Collections.Generic.List[string]
  for ($index = $Items.Count - 1; $index -ge 0; $index--) {
    $item = $Items[$index]
    try {
      switch ($item.Kind) {
        "Process" {
          Stop-Process -Id ([int]$item.Id) -Force -ErrorAction SilentlyContinue
        }
        "Forward" {
          $nativeOutput = & $AdbPath -s $DeviceSerial forward --remove "tcp:$($item.Port)" 2>&1
          if ($LASTEXITCODE -ne 0) { throw "adb forward cleanup exit=$LASTEXITCODE output=$($nativeOutput -join ' ')" }
        }
        "Shell" {
          $nativeOutput = & $AdbPath -s $DeviceSerial shell $item.Command 2>&1
          if ($LASTEXITCODE -ne 0) { throw "adb shell cleanup exit=$LASTEXITCODE output=$($nativeOutput -join ' ')" }
        }
        default { throw "unknown cleanup kind: $($item.Kind)" }
      }
    } catch {
      $cleanupErrors.Add("$($item.Kind): $($_.Exception.Message)")
    }
  }
  if ($CanForceStop) {
    try {
      $nativeOutput = & $AdbPath -s $DeviceSerial shell "am force-stop $PackageName" 2>&1
      if ($LASTEXITCODE -ne 0) { throw "force-stop exit=$LASTEXITCODE output=$($nativeOutput -join ' ')" }
    } catch {
      $cleanupErrors.Add("ForceStop: $($_.Exception.Message)")
    }
  }
  return $cleanupErrors.ToArray()
}

$adb = Adb
$serverLocal = if ($config.bin.frida_server) { $config.bin.frida_server } else { Join-Path $project "bin\frida-server-17.17.0-android-x86_64" }
$gadgetHost  = if ($config.bin.frida_gadget) { $config.bin.frida_gadget } else { Join-Path $project "bin\frida-gadget-17.17.0-android-arm64.so" }
$configHost  = Join-Path $scriptDir "cf_gadget.config.so"

$cleanup = New-Object System.Collections.Generic.List[object]
$canForceStop = $false
$runError = $null
$sessionDir = $null
$probe = $null

try {
  Step "0. Preflight"
  if (-not (Test-Path $serverLocal)) { throw "frida-server not found: $serverLocal (run setup.ps1)" }
  if (-not (Test-Path $gadgetHost))  { throw "frida-gadget not found: $gadgetHost (run setup.ps1)" }
  & $adb connect $serial | Out-Null
  if ((& $adb -s $serial get-state 2>&1).Trim() -ne "device") { throw "device offline: $serial" }
  $pkgLine = (& $adb -s $serial shell "pm path $pkg" 2>&1 | Select-String "base.apk" | Select-Object -First 1)
  if (-not $pkgLine) { throw "package not installed: $pkg" }
  $canForceStop = $true
  $appDir = ($pkgLine -replace '^package:', '' -replace '/base\.apk\s*$', '').Trim()
  $gadgetPath = "$appDir/lib/arm64/libcash-gadget.so"
  $configPath = "$appDir/lib/arm64/libcash-gadget.config.so"
  $su = (& $adb -s $serial shell "$rootLauncher -c id" 2>&1) -join " "
  if ($su -notmatch "uid=0") { throw "root NOT active. User must enable Root on the research instance (docs/ROOT_TOGGLE.md)." }
  Ok "device online; appDir=$appDir; root active"
  $sessionId = "session_" + (Get-Date -Format 'yyyyMMdd_HHmmss')
  $sessionDir = Join-Path $project (Join-Path $config.output_root "sessions\$sessionId")
  New-Item -ItemType Directory -Force -Path $sessionDir | Out-Null
  Ok "session dir: $sessionDir"

  Step "1. Start renamed frida-server"
  $cleanup.Add([pscustomobject]@{ Kind = "Shell"; Command = "rm -f /data/local/tmp/cf_rt_mon /data/local/tmp/cf_rt_mon.log" })
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scriptDir "cf_start_frida_server.ps1") -ServerPath $serverLocal -Serial $serial -AdbPath $adb -PythonPath $venvPy | Out-Host

  Step "2. Stage gadget + config into game namespace"
  $cleanup.Add([pscustomobject]@{ Kind = "Shell"; Command = "rm -f /data/local/tmp/cf_gadget.so /data/local/tmp/cf_gadget.config.so" })
  $cleanup.Add([pscustomobject]@{ Kind = "Shell"; Command = "$rootLauncher -c 'rm -f $gadgetPath $configPath'" })
  & $adb -s $serial push $gadgetHost /data/local/tmp/cf_gadget.so | Out-Null
  & $adb -s $serial push $configHost /data/local/tmp/cf_gadget.config.so | Out-Null
  & $adb -s $serial shell "$rootLauncher -c 'cp /data/local/tmp/cf_gadget.so $gadgetPath && cp /data/local/tmp/cf_gadget.config.so $configPath && chmod 755 $gadgetPath && chmod 644 $configPath && echo STAGED_OK'" | Out-Null
  $staged = (& $adb -s $serial shell "test -f $gadgetPath && echo OK").Trim()
  if ($staged -ne "OK") { throw "gadget staging failed" }
  Ok "gadget staged"

  Step "3. ADB forward"
  $cleanup.Add([pscustomobject]@{ Kind = "Forward"; Port = $gadgetPort })
  & $adb -s $serial forward --remove "tcp:$gadgetPort" 2>$null | Out-Null
  & $adb -s $serial forward "tcp:$gadgetPort" "tcp:$gadgetPort" | Out-Null

  Step "4. Bootstrap gadget (cold start game)"
  & $venvPy (Join-Path $scriptDir "cf_bootstrap_gadget.py") --device-id $serial --package $pkg --module libcocos2dlua.so --gadget-path $gadgetPath --timeout 180 | Out-Host

  Step "5. Start probe, wait READY"
  $probeLog = Join-Path $sessionDir "probe.out.log"
  $probeErr = Join-Path $sessionDir "probe.err.log"
  $probe = Start-Process -FilePath $venvPy -ArgumentList @(
    (Join-Path $scriptDir "cf_probe.py"),
    "--session-dir", $sessionDir,
    "--endpoint", "127.0.0.1:$gadgetPort",
    "--duration", "$DurationSeconds",
    "--mode", "lua",
    "--max-depth", "$maxDepth",
    "--package", "$pkg",
    "--instance", "$($config.instance)",
    "--adb-serial", "$serial"
  ) -RedirectStandardOutput $probeLog -RedirectStandardError $probeErr -PassThru -NoNewWindow
  $cleanup.Add([pscustomobject]@{ Kind = "Process"; Id = $probe.Id })
  $ready = $false
  for ($i=0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    if ($probe.HasExited) { break }
    $statePath = Join-Path $sessionDir "state.json"
    if (Test-Path $statePath) {
      $state = Get-Content $statePath -Raw | ConvertFrom-Json
      if (Test-ProbeReadyState $state) { $ready = $true; break }
    }
  }
  if (-not $ready) {
    Get-Content $probeErr -ErrorAction SilentlyContinue | Select-Object -Last 20
    throw "probe not READY: required lua hook-status for onUIThreadReceiveMessage + lua_pcall was not verified"
  }

  Step "6. PLAYER PHASE"
  Write-Host "`n采集已就绪！READY 已验证两个 scoped Lua hooks。请玩家按本次授权手动执行普通 Spin；采集器不会自动操作游戏。" -ForegroundColor Yellow
  Write-Host "完成够样本后，在另一个终端执行：  New-Item -ItemType File -Path '$sessionDir\STOP' -Force"
  Write-Host "或等待 $DurationSeconds 秒自动结束。`n"
  $stopPath = Join-Path $sessionDir "STOP"
  while (-not $probe.HasExited) { if (Test-Path $stopPath) { break }; Start-Sleep -Seconds 5 }
  if (-not $probe.HasExited) { New-Item -ItemType File -Path $stopPath -Force | Out-Null; Wait-Process -Id $probe.Id -Timeout 30 -ErrorAction SilentlyContinue }
  Ok "probe stopped"

  Step "7. Extract + summarize"
  $env:PYTHONPATH = $project
  & $venvPy (Join-Path $scriptDir "cf_rextract.py") $sessionDir | Out-Host
  & $venvPy (Join-Path $scriptDir "cf_summarize.py") (Join-Path $sessionDir "events.jsonl") --output (Join-Path $sessionDir "summary.json") --markdown (Join-Path $sessionDir "summary.md") --spin-records (Join-Path $sessionDir "spin_records.jsonl") | Out-Host
  Write-Host "`n---- summary ----" -ForegroundColor Cyan
  Get-Content (Join-Path $sessionDir "summary.json") -Raw
} catch {
  $runError = $_
  throw
} finally {
  Step "8. Forced cleanup"
  $cleanupErrors = @(Invoke-CollectorCleanup -Items $cleanup -AdbPath $adb -DeviceSerial $serial -PackageName $pkg -CanForceStop $canForceStop)
  if ($cleanupErrors.Count -eq 0) {
    Ok "runtime cleanup complete"
  } else {
    foreach ($cleanupError in $cleanupErrors) { Warn $cleanupError }
  }
  Warn "Collector cleanup did not change BlueStacks Root. User must disable Root, restart the research instance, and verify su -c id no longer returns uid=0."
  if (($null -eq $runError) -and $cleanupErrors.Count -gt 0) {
    throw "collector cleanup incomplete: $($cleanupErrors -join '; ')"
  }
}

Ok "done. data -> $sessionDir"
