<#
  Uninstall dsh-cascadeur-plugin.

  Mirrors install.ps1: removes the profile package.json dependency / bundle entry
  and deletes the junction. The plugin directory itself is left untouched.

  Must also write without BOM (see the note at the top of install.ps1).
  ASCII-only on purpose (Windows PowerShell 5.1 reads .ps1 as ANSI without a BOM).
#>
param(
  [string]$ProfileDir = "$env:USERPROFILE\.dsh\profiles\desktop"
)

$ErrorActionPreference = 'Stop'
$pkgName = 'dsh-cascadeur-plugin'
$legacyName = '@dsh-external/dsh-cascadeur-plugin'
$pkgJsonPath = Join-Path $ProfileDir 'package.json'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

if (-not (Test-Path $pkgJsonPath)) { throw "profile package.json not found: $pkgJsonPath" }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$bak = "$pkgJsonPath.bak-$stamp"
Copy-Item $pkgJsonPath $bak
Write-Host "backup: $bak"

$json = [System.IO.File]::ReadAllText($pkgJsonPath).TrimStart([char]0xFEFF) | ConvertFrom-Json

# remove both the current and the legacy package names
foreach ($name in @($pkgName, $legacyName)) {
  if ($json.dependencies -and ($json.dependencies.PSObject.Properties.Name -contains $name)) {
    $json.dependencies.PSObject.Properties.Remove($name)
    Write-Host "removed dependency: $name"
  }
}

$bundles = @($json.dsh.profile.bundles) | Where-Object { $_ -and $_ -ne $pkgName -and $_ -ne $legacyName }
$json.dsh.profile.bundles = $bundles
Write-Host "bundles left: $($bundles.Count)"

$out = $json | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($pkgJsonPath, $out, $utf8NoBom)

$bytes = [System.IO.File]::ReadAllBytes($pkgJsonPath)
if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
  Copy-Item $bak $pkgJsonPath -Force
  throw "BOM detected after write; rolled back"
}
& node -e "JSON.parse(require('fs').readFileSync(process.argv[1],'utf8'));console.log('node JSON.parse: OK')" $pkgJsonPath
if ($LASTEXITCODE -ne 0) {
  Copy-Item $bak $pkgJsonPath -Force
  throw "node JSON.parse failed; rolled back"
}

$nmDir = Join-Path $ProfileDir 'node_modules'
foreach ($linkPath in @((Join-Path $nmDir $pkgName), (Join-Path $nmDir '@dsh-external\dsh-cascadeur-plugin'))) {
  if (Test-Path $linkPath) {
    Remove-Item $linkPath -Recurse -Force
    Write-Host "removed junction: $linkPath"
  }
}

Write-Host ""
Write-Host "uninstall complete (no BOM, validation passed). Restart DSH." -ForegroundColor Green
