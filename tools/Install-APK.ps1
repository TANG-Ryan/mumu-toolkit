param([string]$AdbPath, [string]$Serial, [string]$AppId)
. (Join-Path $PSScriptRoot 'Common.ps1')

function Invoke-Adb([string[]]$Arguments) {
    $oldPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $lines = @(& $AdbPath @Arguments 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $oldPreference }
    return [pscustomobject]@{Lines=$lines; ExitCode=$code}
}
function Read-Adb([string[]]$Arguments) {
    $result = Invoke-Adb $Arguments
    if ($result.ExitCode -ne 0) { throw ('ADB 读取失败：' + ($result.Lines -join ' ')) }
    return ($result.Lines -join "`n").Trim()
}

[void](Test-Pack)
if (-not $AdbPath) {
    $found = Get-Command adb.exe -ErrorAction SilentlyContinue
    if ($found) { $AdbPath = $found.Source }
}
if (-not $AdbPath) { $AdbPath = (Read-Host '输入已有 adb.exe 的完整路径（留空退出）').Trim().Trim('"') }
if (-not $AdbPath) { return }
if (-not (Test-Path -LiteralPath $AdbPath -PathType Leaf) -or [IO.Path]::GetFileName($AdbPath) -ine 'adb.exe') { throw 'adb.exe 路径无效。' }
$AdbPath = (Resolve-Path -LiteralPath $AdbPath).ProviderPath
[void](Read-Adb @('version'))
$deviceText = Read-Adb @('devices')
Write-Host $deviceText
$devices = @($deviceText -split "`n" | ForEach-Object { if ($_ -match '^([^\s]+)\s+device\s*$') { $Matches[1] } })
if ($devices.Count -eq 0) { throw '没有在线设备。请在 MuMu 中核对 ADB 信息；助手不会猜端口或自动连接。' }
if (-not $Serial) { $Serial = (Read-Host '输入目标模拟器的完整序列号（留空退出）').Trim() }
if (-not $Serial) { return }
if ($devices -cnotcontains $Serial) { throw '目标序列号不在在线设备列表。' }
$model = Read-Adb @('-s',$Serial,'shell','getprop','ro.product.model')
$sdkText = Read-Adb @('-s',$Serial,'shell','getprop','ro.build.version.sdk')
if ($sdkText -notmatch '^\d+$') { throw '无法确认目标 Android API。' }
$abiText = Read-Adb @('-s',$Serial,'shell','getprop','ro.product.cpu.abilist')
$abis = @($abiText -split ',' | ForEach-Object { $_.Trim() })
if ($abis.Count -eq 0 -or -not $abiText) { throw '无法确认目标 ABI。' }
Write-Host ('目标：' + $Serial + ' / ' + $model + ' / API ' + $sdkText + ' / ABI ' + $abiText)
$apps = @(Get-Content -LiteralPath (Get-PackPath 'metadata/apps.json') -Raw -Encoding UTF8 | ConvertFrom-Json)
if ($AppId) {
    $selected = @($apps | Where-Object { $_.id -ceq $AppId })
    if ($selected.Count -ne 1) { throw '应用 ID 不唯一或不存在。' }
    $app = $selected[0]
} else {
    for ($i=0; $i -lt $apps.Count; $i++) { Write-Host (([string]($i+1)) + '. ' + $apps[$i].name + ' ' + $apps[$i].version) }
    $choice = Read-Host '选择一个 APK 编号（留空退出）'
    if (-not $choice) { return }
    if ($choice -notmatch '^\d+$' -or [long]$choice -lt 1 -or [long]$choice -gt $apps.Count) { throw '应用编号无效。' }
    $app = $apps[[int]$choice-1]
}
if ($app.package -notmatch '^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$') { throw '应用包名无效。' }
if ([int]$sdkText -lt [int]$app.min_sdk) { throw 'Android API 低于应用要求。' }
$matching = @($app.abis | Where-Object { $abis -ccontains $_ })
if (@($app.abis).Count -gt 0 -and $matching.Count -eq 0) { throw '应用 ABI 与目标兼容列表不匹配，已停止。' }
$apkPath = Get-PackPath $app.path
if ((Get-PackSha256 $apkPath) -cne $app.sha256.ToLowerInvariant()) { throw 'APK 哈希与应用元数据不符。' }
$expectedCerts = @($app.certificate_sha256 | ForEach-Object { $_.ToLowerInvariant() } | Sort-Object -Unique)
$sourceCerts = @(Get-ApkSignerSha256 $apkPath | Sort-Object -Unique)
if ($expectedCerts.Count -eq 0 -or ($expectedCerts -join ',') -cne ($sourceCerts -join ',')) { throw 'APK 签名证书与元数据不符。' }

# Listing packages distinguishes an absent app from a failed package lookup.
$packageList = Read-Adb @('-s',$Serial,'shell','pm','list','packages',$app.package)
$installed = @($packageList -split "`n" | Where-Object { $_.Trim() -ceq ('package:'+$app.package) }).Count -gt 0
if ($installed) {
    $packageInfo = Read-Adb @('-s',$Serial,'shell','dumpsys','package',$app.package)
    if ($packageInfo -notmatch 'versionCode=(\d+)') { throw '无法确认已有应用版本，已停止。' }
    if ([long]$Matches[1] -gt [long]$app.version_code) { throw '已有应用版本更高，禁止降级。保留原数据，另建实例验证。' }
    $installedPaths = Read-Adb @('-s',$Serial,'shell','pm','path',$app.package)
    $remotePaths = @($installedPaths -split "`n" | Where-Object { $_ -match '^package:/data/app/[^\r\n]+\.apk\s*$' } | ForEach-Object { $_.Trim().Substring(8) })
    $basePaths = @($remotePaths | Where-Object { $_.EndsWith('/base.apk') })
    if ($basePaths.Count -eq 1) { $remoteApk = $basePaths[0] }
    elseif ($remotePaths.Count -eq 1) { $remoteApk = $remotePaths[0] }
    else { throw '无法唯一定位已有应用的主 APK，已停止。' }
    $tempApk = Join-Path ([IO.Path]::GetTempPath()) ('mumu-toolkit-apk-' + [Guid]::NewGuid().ToString('N') + '.apk')
    try {
        [void](Read-Adb @('-s',$Serial,'pull',$remoteApk,$tempApk))
        $installedCerts = @(Get-ApkSignerSha256 $tempApk | Sort-Object -Unique)
        if (($installedCerts -join ',') -cne ($expectedCerts -join ',')) { throw '已有应用签名不同，禁止覆盖。先完整备份并按手册迁移；助手不会卸载原应用。' }
    } finally {
        if (Test-Path -LiteralPath $tempApk -PathType Leaf) { Remove-Item -LiteralPath $tempApk -Force }
    }
}
Write-Host ('预检通过：' + $app.name + ' ' + $app.version + ' → ' + $Serial)
if ($app.compatibility_note) { Write-Host $app.compatibility_note -ForegroundColor Yellow }
if ((Read-Host '确认目标和应用后输入 INSTALL，其余输入取消') -cne 'INSTALL') { return }
$result = Invoke-Adb @('-s',$Serial,'install','-r',$apkPath)
$result.Lines | Write-Host
if ($result.ExitCode -ne 0 -or -not ($result.Lines | Where-Object { $_.Trim() -ceq 'Success' })) { throw '安装未确认成功。不会卸载、强制降级或自动重试。' }
Write-Host '安装成功。请按手册验证启动、配置及联网。' -ForegroundColor Green
