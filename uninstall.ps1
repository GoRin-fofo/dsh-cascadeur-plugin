<#
  卸载 @dsh-external/dsh-cascadeur-plugin。

  与 install.ps1 对称：移除 profile package.json 里的依赖/bundle 条目 + 删除 junction。
  不删插件目录本身（D:\dsh-plugins\dsh-cascadeur-plugin 保留）。

  ⚠️ 同样必须无 BOM 写出（见 install.ps1 顶部的血泪教训）。
#>
param(
  [string]$ProfileDir = "$env:USERPROFILE\.dsh\profiles\desktop"
)

$ErrorActionPreference = 'Stop'
$pkgName = '@dsh-external/dsh-cascadeur-plugin'
$pkgJsonPath = Join-Path $ProfileDir 'package.json'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

if (-not (Test-Path $pkgJsonPath)) { throw "找不到 profile package.json: $pkgJsonPath" }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$bak = "$pkgJsonPath.bak-$stamp"
Copy-Item $pkgJsonPath $bak
Write-Host "已备份: $bak"

$json = [System.IO.File]::ReadAllText($pkgJsonPath).TrimStart([char]0xFEFF) | ConvertFrom-Json

if ($json.dependencies -and ($json.dependencies.PSObject.Properties.Name -contains $pkgName)) {
  $json.dependencies.PSObject.Properties.Remove($pkgName)
  Write-Host "已移除依赖"
}

$bundles = @($json.dsh.profile.bundles) | Where-Object { $_ -and $_ -ne $pkgName }
$json.dsh.profile.bundles = $bundles
Write-Host "已从 bundles 移除（剩 $($bundles.Count) 项）"

$out = $json | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($pkgJsonPath, $out, $utf8NoBom)

$bytes = [System.IO.File]::ReadAllBytes($pkgJsonPath)
if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
  Copy-Item $bak $pkgJsonPath -Force
  throw "写出后检测到 BOM，已回滚"
}
& node -e "JSON.parse(require('fs').readFileSync(process.argv[1],'utf8'));console.log('node JSON.parse: OK')" $pkgJsonPath
if ($LASTEXITCODE -ne 0) {
  Copy-Item $bak $pkgJsonPath -Force
  throw "node 解析失败，已回滚"
}

$linkPath = Join-Path $ProfileDir 'node_modules\@dsh-external\dsh-cascadeur-plugin'
if (Test-Path $linkPath) {
  Remove-Item $linkPath -Recurse -Force
  Write-Host "已删除 junction"
}

Write-Host ""
Write-Host "✅ 已卸载（无 BOM、校验通过）。重启 DSH 后工具会消失。" -ForegroundColor Green
