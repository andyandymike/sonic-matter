[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string[]]$GodotArguments,

    [string]$ExpectedSentinel = "",

    [ValidateRange(1, 1800)]
    [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"

function Resolve-GodotExecutable {
    if ($env:GODOT) {
        if (-not (Test-Path -LiteralPath $env:GODOT -PathType Leaf)) {
            throw "GODOT points to a missing executable: $($env:GODOT)"
        }
        return (Resolve-Path -LiteralPath $env:GODOT -ErrorAction Stop).Path
    }

    $command = Get-Command godot -CommandType Application -ErrorAction Stop
    return $command.Source
}

$godotPath = Resolve-GodotExecutable
$startInfo = [System.Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = $godotPath
$startInfo.UseShellExecute = $false
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$startInfo.CreateNoWindow = $true

foreach ($argument in $GodotArguments) {
    [void]$startInfo.ArgumentList.Add($argument)
}

$process = [System.Diagnostics.Process]::new()
$process.StartInfo = $startInfo

try {
    if (-not $process.Start()) {
        throw "Godot did not start: $godotPath"
    }

    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()

    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        try {
            $process.Kill($true)
            $process.WaitForExit()
        }
        catch {
            Write-Warning "Failed to stop timed-out Godot process $($process.Id): $_"
        }
        throw "Godot timed out after $TimeoutSeconds seconds: $($GodotArguments -join ' ')"
    }

    # Complete redirected stream reads and refresh ExitCode after the process exits.
    $process.WaitForExit()
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()

    if ($stdout) {
        [Console]::Out.Write($stdout)
    }
    if ($stderr) {
        [Console]::Error.Write($stderr)
    }

    if ($process.ExitCode -ne 0) {
        throw "Godot exited with code $($process.ExitCode): $($GodotArguments -join ' ')"
    }

    if ($ExpectedSentinel -and -not $stdout.Contains($ExpectedSentinel, [System.StringComparison]::Ordinal)) {
        throw "Godot exited without expected sentinel '$ExpectedSentinel': $($GodotArguments -join ' ')"
    }
}
finally {
    $process.Dispose()
}
