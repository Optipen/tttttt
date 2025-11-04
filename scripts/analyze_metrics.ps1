#!/usr/bin/env pwsh
# Script d'analyse des métriques collectées
# Calcule les quantiles p95, p99, moyenne, min, max et génère un rapport

param(
    [string]$MetricsFile = $null
)

if (-not $MetricsFile) {
    # Chercher le dernier fichier de métriques
    $LatestFile = Get-ChildItem -Path "monitoring_data" -Filter "metrics_history_*.json" | 
                  Sort-Object LastWriteTime -Descending | 
                  Select-Object -First 1
    
    if (-not $LatestFile) {
        Write-Host "Aucun fichier de métriques trouvé dans monitoring_data/" -ForegroundColor Red
        exit 1
    }
    
    $MetricsFile = $LatestFile.FullName
    Write-Host "Utilisation du fichier: $MetricsFile" -ForegroundColor Cyan
}

if (-not (Test-Path $MetricsFile)) {
    Write-Host "Fichier non trouvé: $MetricsFile" -ForegroundColor Red
    exit 1
}

Write-Host "=== Analyse des métriques ===" -ForegroundColor Cyan
Write-Host "Fichier: $MetricsFile" -ForegroundColor Yellow
Write-Host ""

# Charger les métriques
$MetricsData = Get-Content $MetricsFile | ConvertFrom-Json

if (-not $MetricsData -or $MetricsData.Count -eq 0) {
    Write-Host "Aucune donnée dans le fichier de métriques" -ForegroundColor Red
    exit 1
}

Write-Host "Nombre de snapshots: $($MetricsData.Count)" -ForegroundColor Green
Write-Host "Période: $($MetricsData[0].timestamp) → $($MetricsData[-1].timestamp)" -ForegroundColor Green
Write-Host ""

# Fonction pour calculer les statistiques
function Calculate-Stats {
    param(
        [array]$Values,
        [string]$MetricName
    )
    
    $ValidValues = $Values | Where-Object { $_ -ne $null -and $_ -ge 0 } | ForEach-Object { [double]$_ }
    
    if ($ValidValues.Count -eq 0) {
        return @{
            Name = $MetricName
            Count = 0
            Mean = 0
            Min = 0
            Max = 0
            P50 = 0
            P95 = 0
            P99 = 0
        }
    }
    
    $Sorted = $ValidValues | Sort-Object
    $Count = $Sorted.Count
    
    $Mean = ($Sorted | Measure-Object -Average).Average
    $Min = $Sorted[0]
    $Max = $Sorted[-1]
    $P50 = $Sorted[[math]::Floor($Count * 0.50)]
    $P95 = $Sorted[[math]::Floor($Count * 0.95)]
    $P99 = $Sorted[[math]::Floor($Count * 0.99)]
    
    return @{
        Name = $MetricName
        Count = $Count
        Mean = $Mean
        Min = $Min
        Max = $Max
        P50 = $P50
        P95 = $P95
        P99 = $P99
    }
}

# Collecter les métriques
$RpcLatencies = @()
$ScanLatencies = @()
$LoopLags = @()
$RpcErrors = @()
$Alerts = @()
$PositiveProfits = @()

foreach ($snapshot in $MetricsData) {
    if ($snapshot.rpc_latency_avg) {
        $RpcLatencies += $snapshot.rpc_latency_avg
    }
    if ($snapshot.scan_latency_avg) {
        $ScanLatencies += $snapshot.scan_latency_avg
    }
    if ($snapshot.loop_lag_seconds) {
        $LoopLags += $snapshot.loop_lag_seconds
    }
    if ($snapshot.rpc_errors_total) {
        $RpcErrors += $snapshot.rpc_errors_total
    }
    if ($snapshot.alerts_total) {
        $Alerts += $snapshot.alerts_total
    }
    if ($snapshot.positive_profits) {
        $PositiveProfits += $snapshot.positive_profits
    }
}

# Calculer les statistiques
$RpcStats = Calculate-Stats $RpcLatencies "RPC Latency (s)"
$ScanStats = Calculate-Stats $ScanLatencies "Scan Latency (s)"
$LoopLagStats = Calculate-Stats $LoopLags "Loop Lag (s)"
$RpcErrorsStats = Calculate-Stats $RpcErrors "RPC Errors"
$AlertsStats = Calculate-Stats $Alerts "Alertes totales"
$PositiveProfitsStats = Calculate-Stats $PositiveProfits "Profits positifs"

# Afficher le rapport
Write-Host "=== RAPPORT D'ANALYSE ===" -ForegroundColor Cyan
Write-Host ""

Write-Host "📊 LATENCES RPC" -ForegroundColor Yellow
Write-Host "  Moyenne: $([math]::Round($RpcStats.Mean, 3))s"
Write-Host "  P50 (médiane): $([math]::Round($RpcStats.P50, 3))s"
Write-Host "  P95: $([math]::Round($RpcStats.P95, 3))s" -ForegroundColor $(if ($RpcStats.P95 -lt 0.8) { "Green" } else { "Red" })
Write-Host "  P99: $([math]::Round($RpcStats.P99, 3))s"
Write-Host "  Min: $([math]::Round($RpcStats.Min, 3))s | Max: $([math]::Round($RpcStats.Max, 3))s"
Write-Host "  Échantillons: $($RpcStats.Count)"
Write-Host ""

Write-Host "📊 LATENCES SCAN TX" -ForegroundColor Yellow
Write-Host "  Moyenne: $([math]::Round($ScanStats.Mean, 3))s"
Write-Host "  P50 (médiane): $([math]::Round($ScanStats.P50, 3))s"
Write-Host "  P95: $([math]::Round($ScanStats.P95, 3))s" -ForegroundColor $(if ($ScanStats.P95 -lt 3.0) { "Green" } else { "Red" })
Write-Host "  P99: $([math]::Round($ScanStats.P99, 3))s"
Write-Host "  Min: $([math]::Round($ScanStats.Min, 3))s | Max: $([math]::Round($ScanStats.Max, 3))s"
Write-Host "  Échantillons: $($ScanStats.Count)"
Write-Host ""

Write-Host "📊 LOOP LAG" -ForegroundColor Yellow
Write-Host "  Moyenne: $([math]::Round($LoopLagStats.Mean, 3))s"
Write-Host "  P95: $([math]::Round($LoopLagStats.P95, 3))s" -ForegroundColor $(if ($LoopLagStats.P95 -lt 180) { "Green" } else { "Red" })
Write-Host "  Max: $([math]::Round($LoopLagStats.Max, 3))s"
Write-Host ""

Write-Host "📊 ERREURS RPC" -ForegroundColor Yellow
Write-Host "  Total: $($RpcErrorsStats.Max)"
Write-Host "  Moyenne par snapshot: $([math]::Round($RpcErrorsStats.Mean, 2))"
if ($RpcErrorsStats.Max -eq 0) {
    Write-Host "  ✅ Aucune erreur HTTP429" -ForegroundColor Green
} else {
    Write-Host "  ⚠️ Erreurs détectées" -ForegroundColor Red
}
Write-Host ""

Write-Host "📊 ALERTES" -ForegroundColor Yellow
Write-Host "  Total: $($AlertsStats.Max)"
Write-Host "  Wallets avec profit > 0: $($PositiveProfitsStats.Max)"
Write-Host ""

# Critères de validation
Write-Host "=== VALIDATION DES CRITÈRES ===" -ForegroundColor Cyan
Write-Host ""

$PassCount = 0
$TotalCount = 4

if ($RpcStats.P95 -lt 0.8) {
    Write-Host "✅ P95 RPC < 800ms: $([math]::Round($RpcStats.P95 * 1000, 0))ms" -ForegroundColor Green
    $PassCount++
} else {
    Write-Host "❌ P95 RPC < 800ms: $([math]::Round($RpcStats.P95 * 1000, 0))ms" -ForegroundColor Red
}

if ($ScanStats.P95 -lt 3.0) {
    Write-Host "✅ P95 Scan < 3s: $([math]::Round($ScanStats.P95, 2))s" -ForegroundColor Green
    $PassCount++
} else {
    Write-Host "❌ P95 Scan < 3s: $([math]::Round($ScanStats.P95, 2))s" -ForegroundColor Red
}

if ($LoopLagStats.P95 -lt 180) {
    Write-Host "✅ Loop lag P95 < 180s: $([math]::Round($LoopLagStats.P95, 2))s" -ForegroundColor Green
    $PassCount++
} else {
    Write-Host "❌ Loop lag P95 < 180s: $([math]::Round($LoopLagStats.P95, 2))s" -ForegroundColor Red
}

if ($RpcErrorsStats.Max -eq 0) {
    Write-Host "✅ Aucune erreur HTTP429: 0" -ForegroundColor Green
    $PassCount++
} else {
    Write-Host "❌ Aucune erreur HTTP429: $($RpcErrorsStats.Max) erreurs" -ForegroundColor Red
}

Write-Host ""
Write-Host "Score: $PassCount/$TotalCount critères validés" -ForegroundColor $(if ($PassCount -eq $TotalCount) { "Green" } else { "Yellow" })

# Générer un rapport JSON
$ReportFile = "monitoring_data/report_$(Get-Date -Format 'yyyyMMdd_HHmmss').json"
$Report = @{
    timestamp = (Get-Date).ToString('o')
    metrics_file = $MetricsFile
    period = @{
        start = $MetricsData[0].timestamp
        end = $MetricsData[-1].timestamp
        snapshots = $MetricsData.Count
    }
    stats = @{
        rpc_latency = $RpcStats
        scan_latency = $ScanStats
        loop_lag = $LoopLagStats
        rpc_errors = $RpcErrorsStats
        alerts = $AlertsStats
        positive_profits = $PositiveProfitsStats
    }
    validation = @{
        p95_rpc_lt_800ms = ($RpcStats.P95 -lt 0.8)
        p95_scan_lt_3s = ($ScanStats.P95 -lt 3.0)
        loop_lag_lt_180s = ($LoopLagStats.P95 -lt 180)
        no_rpc_errors = ($RpcErrorsStats.Max -eq 0)
        score = "$PassCount/$TotalCount"
    }
}

$Report | ConvertTo-Json -Depth 10 | Set-Content -Path $ReportFile
Write-Host ""
Write-Host "Rapport JSON sauvegardé: $ReportFile" -ForegroundColor Green

