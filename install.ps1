<#
  安装 @dsh-external/dsh-cascadeur-plugin 到 DSH profile。

  ⚠️ 血泪教训（2026-10-21）：
     绝不能用 `Set-Content -Encoding UTF8` 写 profile 的 package.json！
     Windows PowerShell 5.1 的 `-Encoding UTF8` 会写入 BOM，
     而 DSH 用 JSON.parse 读 profile → "Unexpected token '<BOM>'" → 应用启动崩溃。
     本脚本改用 [System.IO.File]::WriteAllText + UTF8Encoding($false) ← 保证无 BOM。

  做四件事：
    1. 备份 package.json
    2. 加依赖 + dsh.profile.bundles 条目
    3. 无 BOM 写出 + 双重校验（字节检查 + node JSON.parse），失败自动回滚
    4. node_modules/@dsh-external 下建 junction

  完成后重启 DSH 才会出现工具。
#>
param(
  [string]$ProfileDir = "$env:USERPROFILE\.dsh\profiles\desktop",
  [string]$PluginDir = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'
$pkgName = '@dsh-external/dsh-cascadeur-plugin'
$pkgJsonPath = Join-Path $ProfileDir 'package.json'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

if (-not (Test-Path $pkgJsonPath)) { throw "找不到 profile package.json: $pkgJsonPath" }
if (-not (Test-Path $PluginDir)) { throw "找不到插件目录: $PluginDir" }

# ── 1. 备份 ──
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$bak = "$pkgJsonPath.bak-$stamp"
Copy-Item $pkgJsonPath $bak
Write-Host "已备份: $bak"

# ── 2. 读取（自动去 BOM）并修改 ──
$text = [System.IO.File]::ReadAllText($pkgJsonPath).TrimStart([char]0xFEFF)
$json = $text | ConvertFrom-Json

if (-not $json.dependencies) {
  $json | Add-Member -NotePropertyName dependencies -NotePropertyValue ([PSCustomObject]@{})
}
$depValue = 'file:' + ($PluginDir -replace '\\', '/')
if ($json.dependencies.PSObject.Properties.Name -contains $pkgName) {
  $json.dependencies.$pkgName = $depValue
} else {
  $json.dependencies | Add-Member -NotePropertyName $pkgName -NotePropertyValue $depValue
}
$bundles = @($json.dsh.profile.bundles) | Where-Object { $_ }
if ($bundles -notcontains $pkgName) { $bundles += $pkgName }
$json.dsh.profile.bundles = $bundles

# ── 3. 无 BOM 写出 ──
$out = $json | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($pkgJsonPath, $out, $utf8NoBom)

# ── 4. 校验（失败自动回滚）──
$bytes = [System.IO.File]::ReadAllBytes($pkgJsonPath)
if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
  Copy-Item $bak $pkgJsonPath -Force
  throw "写出后检测到 BOM，已自动回滚到备份。"
}
Write-Host "字节校验: 无 BOM ✓"

$check = [System.IO.File]::ReadAllText($pkgJsonPath) | ConvertFrom-Json
if (@($check.dsh.profile.bundles) -notcontains $pkgName) {
  Copy-Item $bak $pkgJsonPath -Force
  throw "校验失败：bundles 里没有 $pkgName，已回滚"
}
& node -e "JSON.parse(require('fs').readFileSync(process.argv[1],'utf8'));console.log('node JSON.parse: OK')" $pkgJsonPath
if ($LASTEXITCODE -ne 0) {
  Copy-Item $bak $pkgJsonPath -Force
  throw "node 解析失败，已回滚"
}

# ── 5. junction ──
$nmScope = Join-Path $ProfileDir 'node_modules\@dsh-external'
New-Item -ItemType Directory -Force -Path $nmScope | Out-Null
$linkPath = Join-Path $nmScope 'dsh-cascadeur-plugin'
if (Test-Path $linkPath) { Remove-Item $linkPath -Recurse -Force }
New-Item -ItemType Junction -Path $linkPath -Target $PluginDir | Out-Null
Write-Host "已建 junction: $linkPath -> $PluginDir"

Write-Host ""
Write-Host "✅ 安装完成（package.json 无 BOM、JSON 校验通过）。" -ForegroundColor Green
Write-Host "   请【重启 DSH】，然后在会话里运行：casc_status"
Write-Host "   回滚: .\uninstall.ps1    备份: $bak"
