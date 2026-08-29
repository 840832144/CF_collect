# Injectable cleanup engine. Production actions live in run_collector.ps1;
# tests provide fake Stop/Verify scriptblocks without adb, Frida, or an emulator.

function New-CollectorCleanupAction {
  param(
    [Parameter(Mandatory=$true)][string]$Name,
    [Parameter(Mandatory=$true)][scriptblock]$Stop,
    [Parameter(Mandatory=$true)][scriptblock]$Verify,
    [bool]$Owned = $true
  )
  [pscustomobject]@{
    Name = $Name
    Owned = $Owned
    Stop = $Stop
    Verify = $Verify
  }
}

function Invoke-CollectorCleanup {
  param(
    [Parameter(Mandatory=$true)][System.Collections.IList]$Items
  )
  $errors = New-Object System.Collections.Generic.List[string]
  $order = New-Object System.Collections.Generic.List[string]
  $skipped = New-Object System.Collections.Generic.List[string]

  for ($index = $Items.Count - 1; $index -ge 0; $index--) {
    $item = $Items[$index]
    if (-not [bool]$item.Owned) {
      $skipped.Add([string]$item.Name)
      continue
    }

    $name = [string]$item.Name
    $order.Add($name)
    try {
      $null = & $item.Stop
    } catch {
      $errors.Add("$name stop failed: $($_.Exception.Message)")
    }

    try {
      $verification = & $item.Verify
      if ($verification -is [array]) {
        throw "verify returned multiple results"
      }
      if ($verification -is [bool]) {
        $success = $verification
        $detail = if ($success) { "absent" } else { "residual present" }
      } elseif ($null -ne $verification -and $null -ne $verification.PSObject.Properties['Success']) {
        $success = [bool]$verification.Success
        $detail = [string]$verification.Detail
      } else {
        throw "verify must return bool or {Success, Detail}"
      }
      if (-not $success) {
        $errors.Add("$name residual: $detail")
      }
    } catch {
      $errors.Add("$name verify failed: $($_.Exception.Message)")
    }
  }

  [pscustomobject]@{
    Success = ($errors.Count -eq 0)
    Order = @($order)
    Skipped = @($skipped)
    Errors = @($errors)
  }
}
