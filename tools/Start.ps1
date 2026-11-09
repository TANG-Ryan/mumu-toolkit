. (Join-Path $PSScriptRoot 'Common.ps1')
Write-Host 'MuMu 复用工具包 v2'
Write-Host '1. 打开离线手册'
Write-Host '2. 校验资料包'
Write-Host '3. 安装一个 APK'
$choice = Read-Host '选择入口（留空退出）'
switch ($choice) {
    '1' { Start-Process -FilePath (Get-PackPath '00_开始阅读.html') }
    '2' { [void](Test-Pack); Read-Host '按回车退出' | Out-Null }
    '3' { & (Join-Path $PSScriptRoot 'Install-APK.ps1'); Read-Host '按回车退出' | Out-Null }
}
