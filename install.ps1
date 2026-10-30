<#
  Offline install of dsh-cascadeur-plugin into a DSH profile (no npm required).

  Recommended (needs npm access):
      dsh plugin --profile web add dsh-cascadeur-plugin

  This script is for: no npm access, or installing straight from a local checkout.

  NOTE (2026-10-21): never write the profile package.json with
  `Set-Content -Encoding UTF8` - Windows PowerShell 5.1 writes a BOM, and DSH's
  JSON.parse then fails with "Unexpected token '<BOM>'". This script uses
  [System.IO.File]::WriteAllText + UTF8Encoding($false) to guarantee no BOM.

  What it does:
    1. backs up the profile package.json
    2. adds the dependency + dsh.profile.bundles entry
       (and removes leftovers from the legacy name @dsh-external/dsh-cascadeur-plugin)
    3. writes without BOM + double validation (byte check + node JSON.parse), rolls back on failure
    4. creates a junction in node_modules

  Restart DSH afterwards.

  This file is intentionally ASCII-only: Windows PowerShell 5.1 reads .ps1 files
  as ANSI unless they have a BOM, so non-ASCII text can break parsing.
#>
param(
  [string]$ProfileDir = "$env:USERPROFILE\.dsh\profiles\desktop",
  [string]$PluginDir = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'
$pkgName = 'dsh-cascadeur-plugin'
$legacyName = '@dsh-external/dsh-cascadeur-plugin'
$pkgJsonPath = Join-Path $ProfileDir 'package.json'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

if (-not (Test-Path $pkgJsonPath)) { throw "profile package.json not found: $pkgJsonPath" }
if (-not (Test-Path $PluginDir)) { throw "plugin directory not found: $PluginDir" }

# -- 1. backup ---------------------------------------------------------------
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$bak = "$pkgJsonPath.bak-$stamp"
Copy-Item $pkgJsonPath $bak
Write-Host "backup: $bak"

# -- 2. read (strip BOM) and modify -----------------------------------------
$text = [System.IO.File]::ReadAllText($pkgJsonPath).TrimStart([char]0xFEFF)
$json = $text | ConvertFrom-Json

if (-not $json.dependencies) {
  $json | Add-Member -NotePropertyName dependencies -NotePropertyValue ([PSCustomObject]@{})
}

# migrate away from the old scoped package name
if ($json.dependencies.PSObject.Properties.Name -contains $legacyName) {
  $json.dependencies.PSObject.Properties.Remove($legacyName)
  Write-Host "removed legacy dependency: $legacyName"
}

$depValue = 'file:' + ($PluginDir -replace '\\', '/')
if ($json.dependencies.PSObject.Properties.Name -contains $pkgName) {
  $json.dependencies.$pkgName = $depValue
} else {
  $json.dependencies | Add-Member -NotePropertyName $pkgName -NotePropertyValue $depValue
}
$bundles = @($json.dsh.profile.bundles) | Where-Object { $_ -and $_ -ne $legacyName }
if ($bundles -notcontains $pkgName) { $bundles += $pkgName }
$json.dsh.profile.bundles = $bundles

# -- 3. write without BOM ----------------------------------------------------
$out = $json | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($pkgJsonPath, $out, $utf8NoBom)

# -- 4. validate (roll back on failure) -------------------------------------
$bytes = [System.IO.File]::ReadAllBytes($pkgJsonPath)
if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
  Copy-Item $bak $pkgJsonPath -Force
  throw "BOM detected after write; rolled back to backup."
}
Write-Host "byte check: no BOM [ok]"

$check = [System.IO.File]::ReadAllText($pkgJsonPath) | ConvertFrom-Json
if (@($check.dsh.profile.bundles) -notcontains $pkgName) {
  Copy-Item $bak $pkgJsonPath -Force
  throw "validation failed: bundles does not contain $pkgName; rolled back"
}
& node -e "JSON.parse(require('fs').readFileSync(process.argv[1],'utf8'));console.log('node JSON.parse: OK')" $pkgJsonPath
if ($LASTEXITCODE -ne 0) {
  Copy-Item $bak $pkgJsonPath -Force
  throw "node JSON.parse failed; rolled back"
}

# -- 5. junction -------------------------------------------------------------
$nmDir = Join-Path $ProfileDir 'node_modules'
New-Item -ItemType Directory -Force -Path $nmDir | Out-Null
$linkPath = Join-Path $nmDir $pkgName
if (Test-Path $linkPath) { Remove-Item $linkPath -Recurse -Force }
New-Item -ItemType Junction -Path $linkPath -Target $PluginDir | Out-Null
Write-Host "junction: $linkPath -> $PluginDir"

# remove the legacy-name junction if present (keep other packages under the scope)
$legacyLink = Join-Path $nmDir '@dsh-external\dsh-cascadeur-plugin'
if (Test-Path $legacyLink) {
  Remove-Item $legacyLink -Recurse -Force
  Write-Host "removed legacy junction: $legacyLink"
}

Write-Host ""
Write-Host "install complete (package.json has no BOM, JSON validation passed)." -ForegroundColor Green
Write-Host "  restart DSH, then run: casc_status"
Write-Host "  rollback: .\uninstall.ps1    backup: $bak"
