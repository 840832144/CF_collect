$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $root 'collector\cf_cleanup.ps1')

$passed = 0
function Assert-True([bool]$Condition, [string]$Message) {
  if (-not $Condition) { throw $Message }
}
function Pass([string]$Name) {
  $script:passed += 1
  Write-Output "PASS $Name"
}
function New-FakeAction {
  param(
    [string]$Name,
    [hashtable]$State,
    [bool]$StopFails = $false,
    [bool]$LeavesResidual = $false,
    [bool]$Owned = $true
  )
  $stop = {
    $State.order.Add($Name)
    if ($StopFails) { throw "injected stop failure" }
    if (-not $LeavesResidual) { $State.active[$Name] = $false }
  }.GetNewClosure()
  $verify = {
    $active = [bool]$State.active[$Name]
    [pscustomobject]@{ Success = (-not $active); Detail = if ($active) { 'injected residual' } else { 'absent' } }
  }.GetNewClosure()
  New-CollectorCleanupAction -Name $Name -Stop $stop -Verify $verify -Owned $Owned
}

# Every injected acquisition-step failure must clean all resources acquired so far.
for ($fault = 0; $fault -lt 7; $fault++) {
  $state = @{ order = New-Object System.Collections.Generic.List[string]; active = @{} }
  $items = New-Object System.Collections.Generic.List[object]
  try {
    for ($step = 0; $step -lt 7; $step++) {
      $name = "step-$step"
      $state.active[$name] = $true
      $items.Add((New-FakeAction -Name $name -State $state))
      if ($step -eq $fault) { throw "fault-$fault" }
    }
  } catch {
    $result = Invoke-CollectorCleanup -Items $items
  }
  $expected = @($fault..0 | ForEach-Object { "step-$_" })
  Assert-True $result.Success "fault-$fault cleanup failed: $($result.Errors -join '; ')"
  Assert-True (($result.Order -join ',') -eq ($expected -join ',')) "fault-$fault not LIFO"
}
Pass 'all-step fault injection'

$state = @{ order = New-Object System.Collections.Generic.List[string]; active = @{A=$true;B=$true;C=$true} }
$items = New-Object System.Collections.Generic.List[object]
foreach ($name in @('A','B','C')) { $items.Add((New-FakeAction -Name $name -State $state)) }
$result = Invoke-CollectorCleanup -Items $items
Assert-True (($result.Order -join ',') -eq 'C,B,A') 'strict LIFO failed'
Pass 'strict LIFO'

$state = @{ order = New-Object System.Collections.Generic.List[string]; active = @{owned=$true} }
$items = New-Object System.Collections.Generic.List[object]
$items.Add((New-FakeAction -Name 'owned' -State $state))
$first = Invoke-CollectorCleanup -Items $items
$second = Invoke-CollectorCleanup -Items $items
Assert-True ($first.Success -and $second.Success -and -not $state.active.owned) 'idempotency failed'
Pass 'idempotent cleanup'

$state = @{ order = New-Object System.Collections.Generic.List[string]; active = @{server=$true} }
$items = New-Object System.Collections.Generic.List[object]
$items.Add((New-FakeAction -Name 'server' -State $state -StopFails $true))
$result = Invoke-CollectorCleanup -Items $items
Assert-True (-not $result.Success) 'stop failure was hidden'
Assert-True (($result.Errors -join '|') -match 'server stop failed') 'stop failure missing from aggregate'
Assert-True (($result.Errors -join '|') -match 'server residual') 'stop residual missing from aggregate'
Pass 'stop failure is explicit'

$state = @{ order = New-Object System.Collections.Generic.List[string]; active = @{gadget=$true} }
$items = New-Object System.Collections.Generic.List[object]
$items.Add((New-FakeAction -Name 'gadget' -State $state -LeavesResidual $true))
$result = Invoke-CollectorCleanup -Items $items
Assert-True (-not $result.Success) 'residual was hidden'
Assert-True (($result.Errors -join '|') -match 'gadget residual') 'residual detail missing'
Pass 'residual verification'

$state = @{ order = New-Object System.Collections.Generic.List[string]; active = @{one=$true;two=$true} }
$items = New-Object System.Collections.Generic.List[object]
$items.Add((New-FakeAction -Name 'one' -State $state -StopFails $true))
$items.Add((New-FakeAction -Name 'two' -State $state -StopFails $true))
$result = Invoke-CollectorCleanup -Items $items
Assert-True (($result.Order -join ',') -eq 'two,one') 'aggregation order is not LIFO'
Assert-True ($result.Errors.Count -eq 4) "expected 4 aggregate errors, got $($result.Errors.Count)"
Pass 'error aggregation continues'

$state = @{ order = New-Object System.Collections.Generic.List[string]; active = @{foreign=$true} }
$items = New-Object System.Collections.Generic.List[object]
$items.Add((New-FakeAction -Name 'foreign' -State $state -Owned $false))
$result = Invoke-CollectorCleanup -Items $items
Assert-True $result.Success 'unowned action changed result'
Assert-True ($state.active.foreign -and $state.order.Count -eq 0) 'unowned process was stopped'
Assert-True (($result.Skipped -join ',') -eq 'foreign') 'unowned action was not reported skipped'
Pass 'ownership gate'

Write-Output "Cleanup injectable tests: PASS ($passed/7)"
