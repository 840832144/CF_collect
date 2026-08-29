param(
  [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = 'Stop'
$runPath = Join-Path $Root 'run_collector.ps1'
$helperPath = Join-Path $Root 'collector\cf_start_frida_server.ps1'
$passed = 0

function Import-ProductionFunction {
  param([string]$Path, [string]$Name)
  $tokens = $null
  $parseErrors = $null
  $source = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
  $ast = [System.Management.Automation.Language.Parser]::ParseInput(
    $source,
    $Path,
    [ref]$tokens,
    [ref]$parseErrors
  )
  if ($parseErrors.Count -gt 0) {
    throw "PowerShell parse failed for ${Path}: $($parseErrors.Message -join '; ')"
  }
  $definition = $ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
      $node.Name -eq $Name
  }, $true) | Select-Object -First 1
  if ($null -eq $definition) { throw "Production function not found: $Name in $Path" }
  $bodyText = $definition.Body.Extent.Text
  $bodyText = $bodyText.Substring(1, $bodyText.Length - 2)
  Set-Item -Path "Function:script:$Name" -Value ([scriptblock]::Create($bodyText))
}

function Assert-FlatSequence {
  param([object[]]$Actual, [object[]]$Expected, [string]$Name)
  $items = @($Actual)
  if ($items.Count -ne $Expected.Count) {
    throw "$Name count expected=$($Expected.Count) actual=$($items.Count); types=$((@($items | ForEach-Object { if ($null -eq $_) { '<null>' } else { $_.GetType().FullName } })) -join ',')"
  }
  for ($index = 0; $index -lt $Expected.Count; $index++) {
    if ($items[$index] -is [array]) { throw "$Name item[$index] is a nested array" }
    if ([string]$items[$index] -ne [string]$Expected[$index]) {
      throw "$Name item[$index] expected=$($Expected[$index]) actual=$($items[$index])"
    }
  }
}

function Pass([string]$Name) {
  $script:passed += 1
  Write-Output "PASS $Name"
}

function Set-FakeAdbCommand {
  function script:Invoke-FakeAdb {
    param([Parameter(ValueFromRemainingArguments=$true)][object[]]$Ignored)
    $global:LASTEXITCODE = 0
    foreach ($line in $script:fakeAdbLines) { Write-Output $line }
  }
  $script:adb = 'Invoke-FakeAdb'
}

function Test-AdbLineShape([string]$Path, [string]$Label) {
  Import-ProductionFunction -Path $Path -Name 'Invoke-AdbChecked'
  Set-FakeAdbCommand
  foreach ($case in @(
    @{ Input = @(); Expected = @() },
    @{ Input = @('line-a'); Expected = @('line-a') },
    @{ Input = @('line-a','line-b'); Expected = @('line-a','line-b') }
  )) {
    $script:fakeAdbLines = @($case.Input)
    $actual = @(Invoke-AdbChecked -Arguments @('shape-test'))
    Assert-FlatSequence -Actual $actual -Expected $case.Expected -Name "$Label ADB lines"
  }
  Pass "$Label ADB line shape 0/1/2"
}

function Set-LineMock([object[]]$Lines) {
  $script:mockAdbLines = @($Lines)
  function script:Invoke-AdbChecked {
    param([string[]]$Arguments)
    foreach ($line in $script:mockAdbLines) { Write-Output $line }
  }
}

function Test-ExactPidShape([string]$Path, [string]$Label, [bool]$HasParameter) {
  Import-ProductionFunction -Path $Path -Name 'Get-ExactRemoteServerPids'
  $script:RemotePath = '/data/local/tmp/cf_rt_mon'
  $script:target = @('-s','SERIAL')
  foreach ($case in @(
    @{ Input = @(); Expected = @() },
    @{ Input = @('101|/data/local/tmp/cf_rt_mon -D '); Expected = @(101) },
    @{ Input = @('101|/data/local/tmp/cf_rt_mon -D ','202|/data/local/tmp/cf_rt_mon -D --listen'); Expected = @(101,202) }
  )) {
    Set-LineMock -Lines $case.Input
    $actual = if ($HasParameter) {
      @(Get-ExactRemoteServerPids -RemotePath '/data/local/tmp/cf_rt_mon')
    } else {
      @(Get-ExactRemoteServerPids)
    }
    Assert-FlatSequence -Actual $actual -Expected $case.Expected -Name "$Label exact PID"
  }
  Pass "$Label exact PID shape 0/1/2"
}

function Set-ResponseQueue([object[]]$Responses) {
  $script:responseQueue = [System.Collections.Queue]::new()
  foreach ($response in $Responses) { $script:responseQueue.Enqueue($response) }
  function script:Invoke-AdbChecked {
    param([string[]]$Arguments)
    if ($script:responseQueue.Count -eq 0) { throw 'mock response queue exhausted' }
    $response = $script:responseQueue.Dequeue()
    foreach ($line in @($response)) { Write-Output $line }
  }
}

Test-AdbLineShape -Path $runPath -Label 'run'
Test-AdbLineShape -Path $helperPath -Label 'helper'
Test-ExactPidShape -Path $runPath -Label 'run' -HasParameter $true
Test-ExactPidShape -Path $helperPath -Label 'helper' -HasParameter $false

Import-ProductionFunction -Path $runPath -Name 'Get-PackagePids'
$script:serial = 'SERIAL'
$script:pkg = 'PACKAGE'
foreach ($case in @(
  @{ Input = @(); Expected = @() },
  @{ Input = @('101'); Expected = @(101) },
  @{ Input = @('101 202'); Expected = @(101,202) }
)) {
  Set-LineMock -Lines $case.Input
  $actual = @(Get-PackagePids)
  Assert-FlatSequence -Actual $actual -Expected $case.Expected -Name 'run package PID'
}
Pass 'run package PID shape 0/1/2'

Import-ProductionFunction -Path $runPath -Name 'Get-ExistingRemotePaths'
foreach ($case in @(
  @{ Responses = @('ABSENT','ABSENT'); Expected = @() },
  @{ Responses = @('PRESENT','ABSENT'); Expected = @('/path/a') },
  @{ Responses = @('PRESENT','PRESENT'); Expected = @('/path/a','/path/b') }
)) {
  Set-ResponseQueue -Responses $case.Responses
  $actual = @(Get-ExistingRemotePaths -Paths @('/path/a','/path/b'))
  Assert-FlatSequence -Actual $actual -Expected $case.Expected -Name 'run existing paths'
}
Pass 'run path shape 0/1/2'

Import-ProductionFunction -Path $helperPath -Name 'Get-ExistingServerFiles'
$script:RemotePath = '/data/local/tmp/cf_rt_mon'
$script:target = @('-s','SERIAL')
foreach ($case in @(
  @{ Responses = @('ABSENT','ABSENT'); Expected = @() },
  @{ Responses = @('PRESENT','ABSENT'); Expected = @('/data/local/tmp/cf_rt_mon') },
  @{ Responses = @('PRESENT','PRESENT'); Expected = @('/data/local/tmp/cf_rt_mon','/data/local/tmp/cf_rt_mon.log') }
)) {
  Set-ResponseQueue -Responses $case.Responses
  $actual = @(Get-ExistingServerFiles)
  Assert-FlatSequence -Actual $actual -Expected $case.Expected -Name 'helper existing paths'
}
Pass 'helper path shape 0/1/2'

Import-ProductionFunction -Path $runPath -Name 'Get-CfTempResidue'
foreach ($case in @(
  @{ Input = @(); Expected = @() },
  @{ Input = @('/data/local/tmp/cf_one'); Expected = @('/data/local/tmp/cf_one') },
  @{ Input = @('/data/local/tmp/cf_one','/data/local/tmp/cf_two'); Expected = @('/data/local/tmp/cf_one','/data/local/tmp/cf_two') }
)) {
  Set-LineMock -Lines $case.Input
  $actual = @(Get-CfTempResidue)
  Assert-FlatSequence -Actual $actual -Expected $case.Expected -Name 'run cf_* paths'
}
Pass 'run cf_* path shape 0/1/2'

Import-ProductionFunction -Path $runPath -Name 'Test-CollectorResiduals'
$script:serial = 'SERIAL'
$script:gadgetPort = 27042
function script:Test-OwnedLocalProcessAbsent { [pscustomobject]@{ Success = $true; Detail = 'absent' } }
function script:Get-ExactRemoteServerPids { foreach ($value in $script:residualPids) { Write-Output $value } }
function script:Test-ForwardPresent { return [bool]$script:residualForward }
function script:Get-ExistingRemotePaths { foreach ($value in $script:residualPaths) { Write-Output $value } }
function script:Get-CfTempResidue { foreach ($value in $script:residualCfPaths) { Write-Output $value } }

$script:residualPids = @(); $script:residualForward = $false; $script:residualPaths = @(); $script:residualCfPaths = @()
$emptyPidErrors = @(Test-CollectorResiduals -DeviceConfirmed $false -ServerPath '/data/local/tmp/cf_rt_mon' -AppGadgetPath $null -AppConfigPath $null -ProbePid $null -ProbeStartTicks $null)
Assert-FlatSequence -Actual $emptyPidErrors -Expected @() -Name 'empty PID ownership residual'
Pass 'empty PID does not create ownership residual'

$emptyResiduals = @(Test-CollectorResiduals -DeviceConfirmed $true -ServerPath '/data/local/tmp/cf_rt_mon' -AppGadgetPath '/app/gadget' -AppConfigPath '/app/config' -ProbePid $null -ProbeStartTicks $null)
Assert-FlatSequence -Actual $emptyResiduals -Expected @() -Name 'empty residual errors'
$verifyErrors = @($emptyResiduals | ForEach-Object { "verify: $_" })
Assert-FlatSequence -Actual $verifyErrors -Expected @() -Name 'empty verify errors'

$script:residualPids = @(101)
$oneResidual = @(Test-CollectorResiduals -DeviceConfirmed $true -ServerPath '/data/local/tmp/cf_rt_mon' -AppGadgetPath '/app/gadget' -AppConfigPath '/app/config' -ProbePid $null -ProbeStartTicks $null)
Assert-FlatSequence -Actual $oneResidual -Expected @('server residual: exact pid=101 path=/data/local/tmp/cf_rt_mon') -Name 'one residual error'

$script:residualForward = $true
$twoResiduals = @(Test-CollectorResiduals -DeviceConfirmed $true -ServerPath '/data/local/tmp/cf_rt_mon' -AppGadgetPath '/app/gadget' -AppConfigPath '/app/config' -ProbePid $null -ProbeStartTicks $null)
Assert-FlatSequence -Actual $twoResiduals -Expected @('server residual: exact pid=101 path=/data/local/tmp/cf_rt_mon','forward residual: SERIAL tcp:27042') -Name 'two residual errors'
Pass 'residual-error shape 0/1/2 and empty verify suppression'

Write-Output "Production collection shape tests: PASS ($passed/10)"
