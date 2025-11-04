#!/usr/bin/env pwsh
# Script de monitoring des métriques du bot wallet-monitor
# Collecte les métriques Prometheus et les sauvegarde pour analyse

param(
    [int]$DurationHours = 24,
    [int]$IntervalSeconds = 60
)

$OutputDir = "monitoring_data"
$StartTime = Get-Date
$EndTime = $StartTime.AddHours($DurationHours)

# Créer le dossier de sortie
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

# Fichier de log
$LogFile = Join-Path $OutputDir "monitoring_log_$(Get-Date -Format 'yyyyMMdd_HHmmss').txt"
$MetricsFile = Join-Path $OutputDir "metrics_history_$(Get-Date -Format 'yyyyMMdd_HHmmss').json"

$MetricsHistory = @()

Write-Host "=== Monitoring des métriques wallet-monitor ===" -ForegroundColor Cyan
Write-Host "Durée: $DurationHours heures" -ForegroundColor Yellow
Write-Host "Intervalle: $IntervalSeconds secondes" -ForegroundColor Yellow
Write-Host "Début: $StartTime" -ForegroundColor Green
Write-Host "Fin prévue: $EndTime" -ForegroundColor Green
Write-Host "Fichier de log: $LogFile" -ForegroundColor Cyan
Write-Host "Fichier de métriques: $MetricsFile" -ForegroundColor Cyan
Write-Host ""

$Iteration = 0

function Get-Metrics {
    param([string]$MetricName)
    try {
        $metrics = curl.exe -s http://localhost:8000/metrics 2>&1 | Select-String "^$MetricName" 
        return $metrics
    } catch {
        return $null
    }
}

function Extract-MetricValue {
    param([string]$MetricLine)
    if ($MetricLine) {
        $parts = $MetricLine.ToString().Split()
        if ($parts.Length -gt 0) {
            return $parts[-1]
        }
    }
    return $null
}

while ((Get-Date) -lt $EndTime) {
    $Iteration++
    $CurrentTime = Get-Date
    $Elapsed = $CurrentTime - $StartTime
    
    Write-Host "[$($CurrentTime.ToString('HH:mm:ss'))] Itération #$Iteration (Elapsed: $($Elapsed.ToString('hh\:mm\:ss')))" -ForegroundColor Cyan
    
    $MetricsSnapshot = @{
        timestamp = $CurrentTime.ToString('o')
        iteration = $Iteration
        elapsed_seconds = $Elapsed.TotalSeconds
    }
    
    # Healthcheck
    try {
        $health = curl.exe -s http://localhost:8001/healthz 2>&1
        $MetricsSnapshot.healthcheck = $health.ToString().Trim()
        Write-Host "  Healthcheck: $health" -ForegroundColor $(if ($health -eq "OK") { "Green" } else { "Red" })
    } catch {
        $MetricsSnapshot.healthcheck = "ERROR"
        Write-Host "  Healthcheck: ERROR" -ForegroundColor Red
    }
    
    # Métriques principales
    $app_up = Extract-MetricValue (Get-Metrics "wallet_app_up")
    $watchlist_size = Extract-MetricValue (Get-Metrics "wallet_watchlist_size")
    $mainloop_ts = Extract-MetricValue (Get-Metrics "wallet_mainloop_timestamp")
    
    $MetricsSnapshot.app_up = $app_up
    $MetricsSnapshot.watchlist_size = $watchlist_size
    $MetricsSnapshot.mainloop_timestamp = $mainloop_ts
    
    if ($mainloop_ts) {
        $lag = (Get-Date).ToUniversalTime().ToFileTimeUtc() / 10000000 - [double]$mainloop_ts
        $MetricsSnapshot.loop_lag_seconds = $lag
        Write-Host "  App UP: $app_up | Watchlist: $watchlist_size | Loop lag: $([math]::Round($lag, 2))s" -ForegroundColor $(if ($lag -lt 180) { "Green" } else { "Red" })
    }
    
    # Latences RPC
    $rpc_latency_count = Extract-MetricValue (Get-Metrics "wallet_rpc_latency_seconds_count\{method=`"get_signatures_for_address`"}")
    $rpc_latency_sum = Extract-MetricValue (Get-Metrics "wallet_rpc_latency_seconds_sum\{method=`"get_signatures_for_address`"}")
    
    if ($rpc_latency_count -and $rpc_latency_sum -and [double]$rpc_latency_count -gt 0) {
        $rpc_avg = [double]$rpc_latency_sum / [double]$rpc_latency_count
        $MetricsSnapshot.rpc_latency_avg = $rpc_avg
        $MetricsSnapshot.rpc_latency_count = $rpc_latency_count
        $MetricsSnapshot.rpc_latency_sum = $rpc_latency_sum
        Write-Host "  RPC Latency: avg=$([math]::Round($rpc_avg, 3))s (count=$rpc_latency_count)" -ForegroundColor Yellow
    }
    
    # Latences Scan TX
    $scan_count = Extract-MetricValue (Get-Metrics "wallet_tx_scan_seconds_count")
    $scan_sum = Extract-MetricValue (Get-Metrics "wallet_tx_scan_seconds_sum")
    
    if ($scan_count -and $scan_sum -and [double]$scan_count -gt 0) {
        $scan_avg = [double]$scan_sum / [double]$scan_count
        $MetricsSnapshot.scan_latency_avg = $scan_avg
        $MetricsSnapshot.scan_latency_count = $scan_count
        $MetricsSnapshot.scan_latency_sum = $scan_sum
        Write-Host "  Scan Latency: avg=$([math]::Round($scan_avg, 3))s (count=$scan_count)" -ForegroundColor Yellow
    }
    
    # Erreurs RPC
    $rpc_errors = Get-Metrics "wallet_rpc_errors_total"
    $error_count = 0
    if ($rpc_errors) {
        foreach ($error in $rpc_errors) {
            $parts = $error.ToString().Split()
            if ($parts.Length -gt 0) {
                $error_count += [double]$parts[-1]
            }
        }
    }
    $MetricsSnapshot.rpc_errors_total = $error_count
    if ($error_count -gt 0) {
        Write-Host "  RPC Errors: $error_count" -ForegroundColor Red
    } else {
        Write-Host "  RPC Errors: 0" -ForegroundColor Green
    }
    
    # Alertes
    $alerts_total = Extract-MetricValue (Get-Metrics "wallet_alerts_total")
    $profit_gauges = Get-Metrics "wallet_last_profit_sol"
    
    $alerts_count = 0
    $positive_profits = 0
    if ($profit_gauges) {
        foreach ($gauge in $profit_gauges) {
            $parts = $gauge.ToString().Split()
            if ($parts.Length -gt 0) {
                $profit = [double]$parts[-1]
                if ($profit -gt 0) {
                    $positive_profits++
                }
            }
        }
    }
    
    $MetricsSnapshot.alerts_total = $alerts_total
    $MetricsSnapshot.positive_profits = $positive_profits
    
    if ($positive_profits -gt 0) {
        Write-Host "  Alertes: $alerts_total total | $positive_profits wallets avec profit > 0" -ForegroundColor Green
    } else {
        Write-Host "  Alertes: $alerts_total total | Aucun profit détecté" -ForegroundColor Yellow
    }
    
    # Sauvegarder le snapshot
    $MetricsHistory += $MetricsSnapshot
    
    # Écrire dans le log
    $LogEntry = "$($CurrentTime.ToString('o')) | Iteration $Iteration | App UP: $app_up | Watchlist: $watchlist_size | RPC Latency: $([math]::Round($rpc_avg, 3))s | Scan Latency: $([math]::Round($scan_avg, 3))s | RPC Errors: $error_count | Alertes: $alerts_total | Profits positifs: $positive_profits"
    Add-Content -Path $LogFile -Value $LogEntry
    
    # Sauvegarder le JSON périodiquement (toutes les 10 itérations)
    if ($Iteration % 10 -eq 0) {
        $MetricsHistory | ConvertTo-Json -Depth 10 | Set-Content -Path $MetricsFile
        Write-Host "  → Métriques sauvegardées dans $MetricsFile" -ForegroundColor Cyan
    }
    
    Write-Host ""
    
    # Attendre avant la prochaine itération
    Start-Sleep -Seconds $IntervalSeconds
}

# Sauvegarder final
$MetricsHistory | ConvertTo-Json -Depth 10 | Set-Content -Path $MetricsFile
Write-Host "=== Monitoring terminé ===" -ForegroundColor Cyan
Write-Host "Fichier de log: $LogFile" -ForegroundColor Green
Write-Host "Fichier de métriques: $MetricsFile" -ForegroundColor Green

