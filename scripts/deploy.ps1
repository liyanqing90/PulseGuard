param(
    [string]$ServiceUrl = $env:PULSEGUARD_DEPLOY_URL,
    [int]$WaitSeconds = 60,
    [switch]$SkipPostDeployRun
)

$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $true
}

if ([string]::IsNullOrWhiteSpace($ServiceUrl)) {
    $ServiceUrl = "http://127.0.0.1:8787"
}
$ServiceUrl = $ServiceUrl.TrimEnd("/")

function Invoke-PulseGuardJson {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$TimeoutSeconds = 30
    )

    Invoke-RestMethod -Method $Method -Uri "$ServiceUrl$Path" -TimeoutSec $TimeoutSeconds
}

function Invoke-DockerCompose {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Wait-PulseGuardHealthy {
    param([int]$TimeoutSeconds = 120)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $health = Invoke-PulseGuardJson -Method "GET" -Path "/api/health" -TimeoutSeconds 5
            if ($health.status -eq "ok") {
                return
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)

    throw "PulseGuard did not become healthy within $TimeoutSeconds seconds"
}

function Invoke-PulseGuardJsonWithRetry {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$TimeoutSeconds = 30,
        [int]$Attempts = 5,
        [int]$DelaySeconds = 3
    )

    $lastError = $null
    for ($attempt = 1; $attempt -le $Attempts; $attempt += 1) {
        try {
            return Invoke-PulseGuardJson -Method $Method -Path $Path -TimeoutSeconds $TimeoutSeconds
        }
        catch {
            $lastError = $_
            if ($attempt -ge $Attempts) {
                throw
            }
            Start-Sleep -Seconds $DelaySeconds
        }
    }

    throw $lastError
}

$prepared = $false
try {
    Invoke-PulseGuardJson -Method "POST" -Path "/api/deployment/prepare?wait_seconds=$WaitSeconds&reason=docker-deploy" -TimeoutSeconds ($WaitSeconds + 30) | Out-Null
    $prepared = $true

    Invoke-DockerCompose -Arguments @("build")
    Invoke-DockerCompose -Arguments @("up", "-d")
    Wait-PulseGuardHealthy

    $runEnabled = if ($SkipPostDeployRun) { "false" } else { "true" }
    Invoke-PulseGuardJsonWithRetry -Method "POST" -Path "/api/deployment/complete?run_enabled=$runEnabled" -TimeoutSeconds 300 | Out-Null
}
catch {
    if ($prepared) {
        try {
            Invoke-PulseGuardJsonWithRetry -Method "POST" -Path "/api/deployment/complete?run_enabled=false" -TimeoutSeconds 30 | Out-Null
        }
        catch {
            Write-Warning "Failed to resume PulseGuard deployment window automatically. Check /api/deployment/complete after the service is healthy."
        }
    }
    throw
}
