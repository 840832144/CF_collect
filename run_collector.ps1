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
. (Join-Path $scriptDir "cf_cleanup.ps1")

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

function Invoke-AdbChecked {
  param([string[]]$Arguments)
  $output = @(& $adb @Arguments 2>&1)
  if ($LASTEXITCODE -ne 0) {
    throw "adb exit=$LASTEXITCODE args=$($Arguments -join ' ') output=$($output -join ' ')"
  }
  return $output
}

function Get-ExactRemoteServerPids {
  param([string]$RemotePath)
  $command = 'for d in /proc/[0-9]*; do [ -r "$d/cmdline" ] || continue; c=$(tr "\000" " " < "$d/cmdline"); case "$c" in "__REMOTE__ -D"*) printf "%s|%s\n" "${d##*/}" "$c";; esac; done'.Replace('__REMOTE__', $RemotePath)
  $lines = @(Invoke-AdbChecked -Arguments @("-s", $serial, "shell", $command))
  $pids = New-Object System.Collections.Generic.List[int]
  foreach ($line in $lines) {
    $text = [string]$line
    if ($text -notmatch '^([0-9]+)\|(.*)$') { continue }
    $processId = [int]$Matches[1]
    $cmdline = $Matches[2].Trim()
    $executable = ($cmdline -split '\s+', 2)[0]
    if ($executable -eq $RemotePath) { $pids.Add($processId) }
  }
  return $pids.ToArray()
}

function Get-ExistingRemotePaths {
  param([string[]]$Paths)
  $present = New-Object System.Collections.Generic.List[string]
  foreach ($path in $Paths) {
    $output = @(Invoke-AdbChecked -Arguments @("-s", $serial, "shell", "if [ -e '$path' ]; then echo PRESENT; else echo ABSENT; fi"))
    if (($output -join " ").Trim() -eq "PRESENT") { $present.Add($path) }
  }
  return $present.ToArray()
}

function Get-CfTempResidue {
  $command = 'for f in /data/local/tmp/cf_*; do [ -e "$f" ] && printf "%s\n" "$f"; done'
  $output = @(Invoke-AdbChecked -Arguments @("-s", $serial, "shell", $command))
  return @($output | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
}

function Test-ForwardPresent {
  $lines = @(Invoke-AdbChecked -Arguments @("-s", $serial, "forward", "--list"))
  foreach ($line in $lines) {
    $parts = ([string]$line).Trim() -split '\s+'
    if ($parts.Count -ge 3 -and $parts[0] -eq $serial -and $parts[1] -eq "tcp:$gadgetPort") { return $true }
  }
  return $false
}

function Get-PackagePids {
  $output = @(Invoke-AdbChecked -Arguments @("-s", $serial, "shell", "pidof '$pkg' 2>/dev/null || true"))
  $text = ($output -join " ").Trim()
  if (-not $text) { return @() }
  return @($text -split '\s+' | Where-Object { $_ -match '^[0-9]+$' } | ForEach-Object { [int]$_ })
}

function Stop-ExactRemoteServer {
  param([int]$ExpectedPid, [string]$RemotePath)
  $current = @(Get-ExactRemoteServerPids -RemotePath $RemotePath)
  if ($current -notcontains $ExpectedPid) { return }
  $null = Invoke-AdbChecked -Arguments @("-s", $serial, "shell", "$rootLauncher -c 'kill $ExpectedPid'")
  for ($attempt=0; $attempt -lt 10; $attempt++) {
    Start-Sleep -Milliseconds 200
    if (@(Get-ExactRemoteServerPids -RemotePath $RemotePath) -notcontains $ExpectedPid) { return }
  }
  $null = Invoke-AdbChecked -Arguments @("-s", $serial, "shell", "$rootLauncher -c 'kill -9 $ExpectedPid'")
  Start-Sleep -Milliseconds 200
  if (@(Get-ExactRemoteServerPids -RemotePath $RemotePath) -contains $ExpectedPid) {
    throw "owned frida-server pid $ExpectedPid did not stop"
  }
}

function Stop-OwnedLocalProcess {
  param([int]$ProcessId, [long]$StartTicks)
  $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  if ($null -eq $process) { return }
  if ($process.StartTime.ToUniversalTime().Ticks -ne $StartTicks) {
    throw "pid $ProcessId was reused; refusing to stop a foreign process"
  }
  Stop-Process -Id $ProcessId -Force -ErrorAction Stop
  Wait-Process -Id $ProcessId -Timeout 10 -ErrorAction SilentlyContinue
  $remaining = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  if ($null -ne $remaining -and $remaining.StartTime.ToUniversalTime().Ticks -eq $StartTicks) {
    throw "owned local process pid $ProcessId did not stop"
  }
}

function Test-OwnedLocalProcessAbsent {
  param([int]$ProcessId, [long]$StartTicks)
  $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  $ownedPresent = ($null -ne $process -and $process.StartTime.ToUniversalTime().Ticks -eq $StartTicks)
  [pscustomobject]@{ Success = (-not $ownedPresent); Detail = if ($ownedPresent) { "pid=$ProcessId still running" } else { "absent" } }
}

function Test-CollectorResiduals {
  param(
    [bool]$DeviceConfirmed,
    [string]$ServerPath,
    [string]$AppGadgetPath,
    [string]$AppConfigPath,
    [Nullable[int]]$ProbePid,
    [Nullable[long]]$ProbeStartTicks
  )
  $errors = New-Object System.Collections.Generic.List[string]
  if ($null -ne $ProbePid -and $null -ne $ProbeStartTicks) {
    $probeState = Test-OwnedLocalProcessAbsent -ProcessId $ProbePid.Value -StartTicks $ProbeStartTicks.Value
    if (-not $probeState.Success) { $errors.Add("Probe residual: $($probeState.Detail)") }
  }
  if (-not $DeviceConfirmed) { return $errors.ToArray() }

  try {
    $serverPids = @(Get-ExactRemoteServerPids -RemotePath $ServerPath)
    if ($serverPids.Count -gt 0) { $errors.Add("server residual: exact pid=$($serverPids -join ',') path=$ServerPath") }
  } catch { $errors.Add("server verify failed: $($_.Exception.Message)") }
  try {
    if (Test-ForwardPresent) { $errors.Add("forward residual: $serial tcp:$gadgetPort") }
  } catch { $errors.Add("forward verify failed: $($_.Exception.Message)") }
  if ($AppGadgetPath -and $AppConfigPath) {
    try {
      $appResidual = @(Get-ExistingRemotePaths -Paths @($AppGadgetPath, $AppConfigPath))
      if ($appResidual.Count -gt 0) { $errors.Add("Gadget/config residual: $($appResidual -join ',')") }
    } catch { $errors.Add("Gadget/config verify failed: $($_.Exception.Message)") }
  }
  try {
    $cfResidual = @(Get-CfTempResidue)
    if ($cfResidual.Count -gt 0) { $errors.Add("cf_* residual: $($cfResidual -join ',')") }
  } catch { $errors.Add("cf_* verify failed: $($_.Exception.Message)") }
  return $errors.ToArray()
}

$adb = Adb
$serverLocal = if ($config.bin.frida_server) { $config.bin.frida_server } else { Join-Path $project "bin\frida-server-17.17.0-android-x86_64" }
$gadgetHost  = if ($config.bin.frida_gadget) { $config.bin.frida_gadget } else { Join-Path $project "bin\frida-gadget-17.17.0-android-arm64.so" }
$configHost  = Join-Path $scriptDir "cf_gadget.config.so"
$serverRemotePath = "/data/local/tmp/cf_rt_mon"

$cleanup = New-Object System.Collections.Generic.List[object]
$runError = $null
$finalFailure = $null
$sessionDir = $null
$probe = $null
$probePid = $null
$probeStartTicks = $null
$deviceConfirmed = $false
$appDir = $null
$gadgetPath = $null
$configPath = $null

try {
  Step "0. Preflight"
  if (-not (Test-Path $serverLocal)) { throw "frida-server not found: $serverLocal (run setup.ps1)" }
  if (-not (Test-Path $gadgetHost))  { throw "frida-gadget not found: $gadgetHost (run setup.ps1)" }
  & $adb connect $serial | Out-Null
  if ((& $adb -s $serial get-state 2>&1).Trim() -ne "device") { throw "device offline: $serial" }
  $deviceConfirmed = $true
  $pkgLine = (& $adb -s $serial shell "pm path $pkg" 2>&1 | Select-String "base.apk" | Select-Object -First 1)
  if (-not $pkgLine) { throw "package not installed: $pkg" }
  $appDir = ($pkgLine -replace '^package:', '' -replace '/base\.apk\s*$', '').Trim()
  $gadgetPath = "$appDir/lib/arm64/libcash-gadget.so"
  $configPath = "$appDir/lib/arm64/libcash-gadget.config.so"
  $su = (& $adb -s $serial shell "$rootLauncher -c id" 2>&1) -join " "
  if ($su -notmatch "uid=0") { throw "root NOT active. User must enable Root on the research instance (docs/ROOT_TOGGLE.md)." }

  $preexisting = New-Object System.Collections.Generic.List[string]
  $existingServer = @(Get-ExactRemoteServerPids -RemotePath $serverRemotePath)
  if ($existingServer.Count -gt 0) { $preexisting.Add("server pid=$($existingServer -join ',')") }
  $existingFiles = @(Get-ExistingRemotePaths -Paths @($gadgetPath, $configPath))
  foreach ($path in $existingFiles) { $preexisting.Add($path) }
  if (Test-ForwardPresent) { $preexisting.Add("forward=$serial tcp:$gadgetPort") }
  foreach ($path in @(Get-CfTempResidue)) { $preexisting.Add($path) }
  if ($preexisting.Count -gt 0) {
    throw "preflight ownership gate found residuals; no foreign resource was changed: $($preexisting -join '; ')"
  }

  Ok "device online; appDir=$appDir; root active"
  $sessionId = "session_" + (Get-Date -Format 'yyyyMMdd_HHmmss')
  $sessionDir = Join-Path $project (Join-Path $config.output_root "sessions\$sessionId")
  New-Item -ItemType Directory -Force -Path $sessionDir | Out-Null
  Ok "session dir: $sessionDir"

  Step "1. Start renamed frida-server"
  $serverObjects = @(& (Join-Path $scriptDir "cf_start_frida_server.ps1") -ServerPath $serverLocal -Serial $serial -RemotePath $serverRemotePath -AdbPath $adb -PythonPath $venvPy)
  $serverResult = @($serverObjects | Where-Object { $null -ne $_.PSObject.Properties['pid'] -and $null -ne $_.PSObject.Properties['remote_path'] -and $null -ne $_.PSObject.Properties['started_by_run'] })
  if ($serverResult.Count -ne 1) { throw "server helper did not return exactly one ownership result" }
  $serverResult = $serverResult[0]
  $serverPid = [int]$serverResult.pid
  $serverOwned = [bool]$serverResult.started_by_run
  $serverPathOwned = [string]$serverResult.remote_path

  $serverFileStop = { $null = Invoke-AdbChecked -Arguments @("-s", $serial, "shell", "rm -f '$serverPathOwned' '$serverPathOwned.log'") }.GetNewClosure()
  $serverFileVerify = {
    $present = @(Get-ExistingRemotePaths -Paths @($serverPathOwned, "$serverPathOwned.log"))
    [pscustomobject]@{ Success = ($present.Count -eq 0); Detail = if ($present.Count) { $present -join ',' } else { 'absent' } }
  }.GetNewClosure()
  $cleanup.Add((New-CollectorCleanupAction -Name "server-files:$serverPathOwned" -Owned $serverOwned -Stop $serverFileStop -Verify $serverFileVerify))

  $serverStop = { Stop-ExactRemoteServer -ExpectedPid $serverPid -RemotePath $serverPathOwned }.GetNewClosure()
  $serverVerify = {
    $pids = @(Get-ExactRemoteServerPids -RemotePath $serverPathOwned)
    [pscustomobject]@{ Success = ($pids.Count -eq 0); Detail = if ($pids.Count) { "exact pid=$($pids -join ',')" } else { 'absent' } }
  }.GetNewClosure()
  $cleanup.Add((New-CollectorCleanupAction -Name "server-process:$serverPid" -Owned $serverOwned -Stop $serverStop -Verify $serverVerify))
  if (-not $serverOwned) { throw "server helper reused pid $serverPid; this run did not acquire ownership" }

  Step "2. Stage gadget + config into game namespace"
  $tempGadgetPaths = @('/data/local/tmp/cf_gadget.so','/data/local/tmp/cf_gadget.config.so')
  $tempStop = { $null = Invoke-AdbChecked -Arguments @("-s", $serial, "shell", "rm -f '$($tempGadgetPaths[0])' '$($tempGadgetPaths[1])'") }.GetNewClosure()
  $tempVerify = {
    $present = @(Get-ExistingRemotePaths -Paths $tempGadgetPaths)
    [pscustomobject]@{ Success = ($present.Count -eq 0); Detail = if ($present.Count) { $present -join ',' } else { 'absent' } }
  }.GetNewClosure()
  $cleanup.Add((New-CollectorCleanupAction -Name "temp-gadget-config" -Stop $tempStop -Verify $tempVerify))

  $appGadgetPaths = @($gadgetPath,$configPath)
  $appStop = { $null = Invoke-AdbChecked -Arguments @("-s", $serial, "shell", "$rootLauncher -c 'rm -f $($appGadgetPaths[0]) $($appGadgetPaths[1])'") }.GetNewClosure()
  $appVerify = {
    $present = @(Get-ExistingRemotePaths -Paths $appGadgetPaths)
    [pscustomobject]@{ Success = ($present.Count -eq 0); Detail = if ($present.Count) { $present -join ',' } else { 'absent' } }
  }.GetNewClosure()
  $cleanup.Add((New-CollectorCleanupAction -Name "app-gadget-config" -Stop $appStop -Verify $appVerify))

  & $adb -s $serial push $gadgetHost /data/local/tmp/cf_gadget.so | Out-Null
  & $adb -s $serial push $configHost /data/local/tmp/cf_gadget.config.so | Out-Null
  & $adb -s $serial shell "$rootLauncher -c 'cp /data/local/tmp/cf_gadget.so $gadgetPath && cp /data/local/tmp/cf_gadget.config.so $configPath && chmod 755 $gadgetPath && chmod 644 $configPath && echo STAGED_OK'" | Out-Null
  $staged = (& $adb -s $serial shell "test -f $gadgetPath && echo OK").Trim()
  if ($staged -ne "OK") { throw "gadget staging failed" }
  Ok "gadget staged"

  Step "3. ADB forward"
  $forwardStop = { if (Test-ForwardPresent) { $null = Invoke-AdbChecked -Arguments @("-s", $serial, "forward", "--remove", "tcp:$gadgetPort") } }.GetNewClosure()
  $forwardVerify = { $present = Test-ForwardPresent; [pscustomobject]@{ Success = (-not $present); Detail = if ($present) { "$serial tcp:$gadgetPort" } else { 'absent' } } }.GetNewClosure()
  $cleanup.Add((New-CollectorCleanupAction -Name "adb-forward:$gadgetPort" -Stop $forwardStop -Verify $forwardVerify))
  & $adb -s $serial forward "tcp:$gadgetPort" "tcp:$gadgetPort" | Out-Null

  Step "4. Bootstrap gadget (cold start game)"
  $packageStop = { if (@(Get-PackagePids).Count -gt 0) { $null = Invoke-AdbChecked -Arguments @("-s", $serial, "shell", "am force-stop '$pkg'") } }.GetNewClosure()
  $packageVerify = { $pids = @(Get-PackagePids); [pscustomobject]@{ Success = ($pids.Count -eq 0); Detail = if ($pids.Count) { "pid=$($pids -join ',')" } else { 'absent' } } }.GetNewClosure()
  $cleanup.Add((New-CollectorCleanupAction -Name "package-process:$pkg" -Stop $packageStop -Verify $packageVerify))
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
  $probePid = [int]$probe.Id
  $probeStartTicks = [long]$probe.StartTime.ToUniversalTime().Ticks
  $probeStop = { Stop-OwnedLocalProcess -ProcessId $probePid -StartTicks $probeStartTicks }.GetNewClosure()
  $probeVerify = { Test-OwnedLocalProcessAbsent -ProcessId $probePid -StartTicks $probeStartTicks }.GetNewClosure()
  $cleanup.Add((New-CollectorCleanupAction -Name "probe-process:$probePid" -Stop $probeStop -Verify $probeVerify))
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
  $runError = $_.Exception.Message
} finally {
  Step "8. Forced cleanup"
  $cleanupResult = Invoke-CollectorCleanup -Items $cleanup
  $residualErrors = @(Test-CollectorResiduals -DeviceConfirmed $deviceConfirmed -ServerPath $serverRemotePath -AppGadgetPath $gadgetPath -AppConfigPath $configPath -ProbePid $probePid -ProbeStartTicks $probeStartTicks)
  $allErrors = New-Object System.Collections.Generic.List[string]
  if ($runError) { $allErrors.Add("run: $runError") }
  foreach ($cleanupError in @($cleanupResult.Errors)) { $allErrors.Add("cleanup: $cleanupError") }
  foreach ($residualError in $residualErrors) { $allErrors.Add("verify: $residualError") }

  if ($allErrors.Count -eq 0) {
    Ok "runtime cleanup complete; Probe/server/forward/Gadget/config/cf_* are absent"
  } else {
    foreach ($errorText in $allErrors) { Warn $errorText }
    $finalFailure = "collector lifecycle failed: $($allErrors -join ' | ')"
  }
  Warn "Collector cleanup did not change BlueStacks Root. User must disable Root, restart the research instance, and verify su -c id no longer returns uid=0."
}

if ($finalFailure) { throw $finalFailure }
Ok "done. data -> $sessionDir"
