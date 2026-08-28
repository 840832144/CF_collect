# setup.ps1 — CF_collect 部署（自动检测，无 DSH 依赖）
# 作用：检测 Python/venv、adb(蓝叠)、研究实例与【游戏】包、
#       下载/定位 Frida 17.17.0 二进制、检查 root，输出 ready 摘要。
param(
  [string]$ProjectRoot = (Split-Path -Parent $MyInvocation.MyCommand.Path)
)
$ErrorActionPreference = "Stop"
$project = (Resolve-Path $ProjectRoot).Path
$configPath = Join-Path $project "config.json"
$config = Get-Content $configPath -Raw | ConvertFrom-Json
$binDir = Join-Path $project "bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

function Step([string]$t){ Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Ok([string]$t){ Write-Host "[OK] $t" -ForegroundColor Green }
function Warn([string]$t){ Write-Host "[WARN] $t" -ForegroundColor Yellow }

Step "1. Python venv"
$py = (Get-Command py -ErrorAction SilentlyContinue)
$pythonExe = $null
if ($py) { $pythonExe = "py" } else { $probe = Get-Command python -ErrorAction SilentlyContinue; if ($probe) { $pythonExe = "python" } }
if (-not $pythonExe) { throw "Python 3.10+ not found. Install Python 3 first." }
$venv = Join-Path $project ".venv"
$venvPy = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  & $pythonExe -m venv $venv
  if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}
& $venvPy -m pip install -q --upgrade pip | Out-Null
& $venvPy -m pip install -q -r (Join-Path $project "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
Ok "venv ready: $venvPy"

Step "2. Detect adb (BlueStacks HD-Adb)"
$adb = $null
foreach ($cand in @(
  "C:\Program Files\BlueStacks_nxt_cn\HD-Adb.exe",
  "C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
  "C:\platform-tools\adb.exe"
)) { if (Test-Path $cand) { $adb = $cand; break } }
if (-not $adb) {
  $reg = Get-ItemProperty "HKLM:\SOFTWARE\BlueStacks_nxt_cn" -ErrorAction SilentlyContinue
  if ($reg -and $reg.InstallDir) { $c = Join-Path $reg.InstallDir "HD-Adb.exe"; if (Test-Path $c) { $adb = $c } }
}
if (-not $adb) { Warn "adb not auto-found; set config/bin or ADB path"; } else { Ok "adb: $adb" }

Step "3. Connect research instance"
$serial = $config.adb_serial
if ($adb) {
  & $adb connect $serial | Out-Null
  $state = (& $adb -s $serial get-state 2>&1).Trim()
  if ($state -eq "device") { Ok "device online: $serial" } else { Warn "device not online: $serial ($state)" }
  $pkg = (& $adb -s $serial shell "pm path $($config.package)" 2>&1)
  if ($pkg -match "base.apk") { Ok "package installed: $($config.package)" } else { Warn "package NOT found: $($config.package) — install 【游戏】 on the instance" }
  $su = (& $adb -s $serial shell "$($config.root_launcher) -c id" 2>&1) -join " "
  if ($su -match "uid=0") { Ok "root active; will inject Gadget" } else { Warn "root NOT active. Enable root on the research instance (see docs/ROOT_TOGGLE.md) before running." }
}

Step "4. Frida 17.17.0 binaries (.bin)"
$cfgFridaServer = $config.bin.frida_server
$cfgFridaGadget = $config.bin.frida_gadget
$serverLocal = if ($cfgFridaServer) { $cfgFridaServer } else { Join-Path $binDir "frida-server-17.17.0-android-x86_64" }
$gadgetLocal = if ($cfgFridaGadget) { $cfgFridaGadget } else { Join-Path $binDir "frida-gadget-17.17.0-android-arm64.so" }
$baseUrl = "https://github.com/frida/frida/releases/download/17.17.0"
if (-not (Test-Path $serverLocal)) {
  Warn "frida-server missing; attempting download to $serverLocal"
  curl.exe -sL -o "$serverLocal.xz" "$baseUrl/frida-server-17.17.0-android-x86_64.xz" --max-time 120
  & $venvPy -c "import lzma,shutil; shutil.copyfileobj(lzma.open(r'$serverLocal.xz'), open(r'$serverLocal','wb'))"
  Remove-Item "$serverLocal.xz" -ErrorAction SilentlyContinue
  if (Test-Path $serverLocal) { Ok "frida-server downloaded" } else { Warn "frida-server download failed; place binary manually into bin/" }
}
if (-not (Test-Path $gadgetLocal)) {
  Warn "frida-gadget missing; attempting download to $gadgetLocal"
  curl.exe -sL -o "$gadgetLocal.xz" "$baseUrl/frida-gadget-17.17.0-android-arm64.so.xz" --max-time 120
  & $venvPy -c "import lzma,shutil; shutil.copyfileobj(lzma.open(r'$gadgetLocal.xz'), open(r'$gadgetLocal','wb'))"
  Remove-Item "$gadgetLocal.xz" -ErrorAction SilentlyContinue
  if (Test-Path $gadgetLocal) { Ok "frida-gadget downloaded" } else { Warn "frida-gadget download failed; place binary manually into bin/" }
}
if ((Test-Path $serverLocal) -and (Test-Path $gadgetLocal)) { Ok "Frida binaries ready" }

Step "5. Host frida version check"
$hostVer = (& $venvPy -c "import frida; print(frida.__version__)" 2>$null).Trim()
if ($hostVer -eq $config.frida_version) { Ok "host frida: $hostVer" } else { Warn "host frida: $hostVer (expected $($config.frida_version))" }

"`n=== setup complete ==="
"  config:     $configPath"
"  venv:       $venvPy"
"  adb:        $adb"
"  serial:     $serial"
"  frida bin:  $binDir"
"Next: powershell -ExecutionPolicy Bypass -File run_collector.ps1"
