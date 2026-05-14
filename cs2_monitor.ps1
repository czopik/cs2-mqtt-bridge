$projectDir = "C:\Users\chemi\cs2-mqtt-bridge"
$python    = "$projectDir\.venv\Scripts\python.exe"

$mainProc      = $null
$hudProc       = $null
$cs2WasRunning = $false

while ($true) {
    $cs2 = Get-Process -Name "cs2" -ErrorAction SilentlyContinue

    if ($cs2 -and -not $cs2WasRunning) {
        # CS2 właśnie wystartował
        Start-Sleep -Seconds 3   # poczekaj aż sieć CS2 się zainicjuje
        $mainProc = Start-Process -FilePath $python `
                                  -ArgumentList "main.py" `
                                  -WorkingDirectory $projectDir `
                                  -PassThru -WindowStyle Hidden
        Start-Sleep -Seconds 2
        $hudProc  = Start-Process -FilePath $python `
                                  -ArgumentList "hud_display.py" `
                                  -WorkingDirectory $projectDir `
                                  -PassThru -WindowStyle Hidden
        $cs2WasRunning = $true
    }
    elseif (-not $cs2 -and $cs2WasRunning) {
        # CS2 właśnie się zamknął
        if ($mainProc -and -not $mainProc.HasExited) { $mainProc.Kill() }
        if ($hudProc  -and -not $hudProc.HasExited)  { $hudProc.Kill()  }
        $mainProc      = $null
        $hudProc       = $null
        $cs2WasRunning = $false
    }

    Start-Sleep -Seconds 3
}
