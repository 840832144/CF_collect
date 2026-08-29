# cf_start_frida_server.ps1 — push/start a renamed frida-server and return ownership metadata.
# The returned object is the only cleanup authority: pid + remote_path + started_by_run.
param(
  [Parameter(Mandatory=$true)]
  [string]$ServerPath,
  [string]$Serial = "127.0.0.1:5585",
  [string]$RemotePath = "/data/local/tmp/cf_rt_mon",
  [string]$AdbPath = "C:\Program Files\BlueStacks_nxt_cn\HD-Adb.exe",
  [string]$PythonPath = "python",
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

function Invoke-AdbChecked {
  param([string[]]$Arguments)
  $output = @(& $adb @Arguments 2>&1)
  if ($LASTEXITCODE -ne 0) {
    throw "adb exit=$LASTEXITCODE args=$($Arguments -join ' ') output=$($output -join ' ')"
  }
  return ,$output
}

function Get-ExactRemoteServerPids {
  $command = 'for d in /proc/[0-9]*; do [ -r "$d/cmdline" ] || continue; c=$(tr "\000" " " < "$d/cmdline"); case "$c" in "__REMOTE__ -D"*) printf "%s|%s\n" "${d##*/}" "$c";; esac; done'.Replace('__REMOTE__', $RemotePath)
  $lines = @(Invoke-AdbChecked -Arguments ($target + @("shell", $command)))
  $pids = New-Object System.Collections.Generic.List[int]
  foreach ($line in $lines) {
    $text = [string]$line
    if ($text -notmatch '^([0-9]+)\|(.*)$') { continue }
    $processId = [int]$Matches[1]
    $cmdline = $Matches[2].Trim()
    $executable = ($cmdline -split '\s+', 2)[0]
    if ($executable -eq $RemotePath) { $pids.Add($processId) }
  }
  return ,$pids.ToArray()
}

function Test-RemoteFile {
  $output = @(Invoke-AdbChecked -Arguments ($target + @("shell", "if [ -e '$RemotePath' ]; then echo PRESENT; else echo ABSENT; fi")))
  return (($output -join " ").Trim() -eq "PRESENT")
}

function Get-ExistingServerFiles {
  $present = New-Object System.Collections.Generic.List[string]
  foreach ($path in @($RemotePath, "$RemotePath.log")) {
    $output = @(Invoke-AdbChecked -Arguments ($target + @("shell", "if [ -e '$path' ]; then echo PRESENT; else echo ABSENT; fi")))
    if (($output -join " ").Trim() -eq "PRESENT") { $present.Add($path) }
  }
  return ,$present.ToArray()
}

function Stop-OwnedServerPids {
  param([int[]]$Pids, [string]$RootLauncher)
  foreach ($processId in $Pids) {
    $current = @(Get-ExactRemoteServerPids)
    if ($current -notcontains $processId) { continue }
    $null = Invoke-AdbChecked -Arguments ($target + @("shell", "$RootLauncher -c 'kill $processId'"))
    for ($attempt=0; $attempt -lt 10; $attempt++) {
      Start-Sleep -Milliseconds 200
      if (@(Get-ExactRemoteServerPids) -notcontains $processId) { break }
    }
    if (@(Get-ExactRemoteServerPids) -contains $processId) {
      $null = Invoke-AdbChecked -Arguments ($target + @("shell", "$RootLauncher -c 'kill -9 $processId'"))
      Start-Sleep -Milliseconds 200
    }
    if (@(Get-ExactRemoteServerPids) -contains $processId) {
      throw "owned frida-server pid $processId did not stop"
    }
  }
}

$pushedByRun = $false
$startedByRun = $false
$ownedPids = @()
$rootLauncher = $null
try {
  $null = Invoke-AdbChecked -Arguments @("connect", $Serial)
  $null = Invoke-AdbChecked -Arguments ($target + @("get-state"))

  $existing = @(Get-ExactRemoteServerPids)
  if ($existing.Count -gt 1) {
    throw "multiple exact frida-server processes already exist at ${RemotePath}: $($existing -join ',')"
  }
  if ($existing.Count -eq 0 -and (Test-RemoteFile)) {
    throw "remote path already exists without an owned process: $RemotePath"
  }

  if ($existing.Count -eq 0) {
    $pushOutput = @(Invoke-AdbChecked -Arguments ($target + @("push", $ServerPath, $RemotePath)))
    $pushOutput | ForEach-Object { Write-Host $_ }
    $pushedByRun = $true
    $null = Invoke-AdbChecked -Arguments ($target + @("shell", "chmod 755 '$RemotePath'"))
  }

  $serverVersion = ((Invoke-AdbChecked -Arguments ($target + @("shell", "$RemotePath --version"))) -join " ").Trim()
  $hostOutput = @(& $PythonPath -c "import frida; print(frida.__version__)" 2>&1)
  if ($LASTEXITCODE -ne 0) { throw "host Frida version check failed: $($hostOutput -join ' ')" }
  $hostVersion = ($hostOutput -join " ").Trim()
  Write-Host "Host Frida:   $hostVersion"
  Write-Host "Server Frida: $serverVersion"
  if ($hostVersion -ne $serverVersion) {
    throw "Host/server Frida version mismatch ($hostVersion vs $serverVersion)."
  }

  if ($existing.Count -eq 0) {
    foreach ($su in @("/system/xbin/bstk/su", "/system/xbin/su")) {
      $identityOutput = @(& $adb @target shell "$su -c 'id'" 2>&1)
      if ($LASTEXITCODE -eq 0 -and (($identityOutput -join " ") -match 'uid=0\(root\)')) {
        $rootLauncher = $su
        break
      }
    }

    if ($rootLauncher) {
      Write-Host "Starting frida-server through $rootLauncher (renamed: $RemotePath)"
      $null = Invoke-AdbChecked -Arguments ($target + @("shell", "$rootLauncher -c '$RemotePath -D >$RemotePath.log 2>&1 </dev/null'"))
    } elseif ($DiagnosticShellMode) {
      Write-Warning "Starting frida-server as shell for diagnostics only; attach will fail."
      $null = Invoke-AdbChecked -Arguments ($target + @("shell", "$RemotePath -D >$RemotePath.log 2>&1 </dev/null"))
    } else {
      throw "No usable root launcher. Enable root on Pie64_3 (with backup/rollback) before the session."
    }

    Start-Sleep -Seconds 2
    $ownedPids = @(Get-ExactRemoteServerPids)
    if ($ownedPids.Count -ne 1) {
      throw "expected one exact frida-server process at $RemotePath, got $($ownedPids.Count): $($ownedPids -join ',')"
    }
    $startedByRun = $true
  } else {
    $ownedPids = $existing
  }

  Write-Host "Testing Frida device..."
  $deviceOutput = @(& $PythonPath -c "import frida; d=frida.get_device_manager().get_device('$Serial', timeout=10); print('Device:', d.name); print('Processes:', len(d.enumerate_processes()))" 2>&1)
  if ($LASTEXITCODE -ne 0) { throw "Frida device test failed: $($deviceOutput -join ' ')" }
  $deviceOutput | ForEach-Object { Write-Host $_ }

  [pscustomobject]@{
    pid = [int]$ownedPids[0]
    remote_path = $RemotePath
    started_by_run = [bool]$startedByRun
  }
} catch {
  $primary = $_.Exception.Message
  $cleanupErrors = New-Object System.Collections.Generic.List[string]
  if ($pushedByRun -and $existing.Count -eq 0) {
    try {
      $rollbackPids = @(Get-ExactRemoteServerPids)
      if (-not $rootLauncher -and -not $DiagnosticShellMode) { throw "root launcher unavailable for helper rollback" }
      if ($rootLauncher) { Stop-OwnedServerPids -Pids $rollbackPids -RootLauncher $rootLauncher }
      elseif ($DiagnosticShellMode) {
        foreach ($processId in $rollbackPids) {
          $null = Invoke-AdbChecked -Arguments ($target + @("shell", "kill $processId"))
        }
      }
    } catch { $cleanupErrors.Add("process rollback: $($_.Exception.Message)") }
  }
  if ($pushedByRun) {
    try {
      $null = Invoke-AdbChecked -Arguments ($target + @("shell", "rm -f '$RemotePath' '$RemotePath.log'"))
      $remainingFiles = @(Get-ExistingServerFiles)
      if ($remainingFiles.Count -gt 0) { throw "remote files remain: $($remainingFiles -join ',')" }
    } catch { $cleanupErrors.Add("file rollback: $($_.Exception.Message)") }
  }
  $remaining = @()
  try { $remaining = @(Get-ExactRemoteServerPids) } catch { $cleanupErrors.Add("process verify: $($_.Exception.Message)") }
  if ($remaining.Count -gt 0 -and $existing.Count -eq 0) {
    $cleanupErrors.Add("process residual: $($remaining -join ',')")
  }
  $suffix = if ($cleanupErrors.Count -gt 0) { " | helper cleanup: $($cleanupErrors -join '; ')" } else { "" }
  throw "$primary$suffix"
}
