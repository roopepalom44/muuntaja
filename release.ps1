<#
.SYNOPSIS
  Rakentaa add-inin ja julkaisee sen GitHub-releasena (.esriAddInX liitteenä).
.DESCRIPTION
  Versio luetaan Config.daml:sta. Release-tagi on v<versio>. Liitteen nimi on
  aina Muuntaja.esriAddInX, joten vakaa latauslinkki on
  https://github.com/roopepalom44/muuntaja/releases/latest/download/Muuntaja.esriAddInX
  Vaatii .NET 8 SDK:n, täyden MSBuildin, Pro 3.5 Extensions NuGet -paketin sekä gh-kirjautumisen.
#>
[CmdletBinding()]
param(
    [string]$Notes = '',
    [switch]$Draft,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$repo = 'roopepalom44/muuntaja'
$remote = 'origin'
$branch = 'main'
$configuration = 'Release'
$framework = 'net8.0-windows'
Set-Location -LiteralPath $root

function Invoke-Native {
    param([scriptblock]$Command, [string]$Message)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Message (exit $LASTEXITCODE)" }
}

$daml = Get-Content -LiteralPath (Join-Path $root 'Config.daml') -Raw
if ($daml -notmatch '(?<=\s)version="(\d+(\.\d+){1,3})"') { throw 'Versiota ei löytynyt Config.daml:sta.' }
$version = $Matches[1]
$tag = "v$version"

if ($daml -notmatch 'desktopVersion="3\.5(?:\.|\")') {
    throw 'Config.daml:n ArcGIS Pro -vähimmäisversion pitää olla 3.5.'
}
$project = [xml](Get-Content -LiteralPath (Join-Path $root 'Muuntaja.csproj') -Raw)
$apiPackage = $project.SelectSingleNode('/Project/ItemGroup/PackageReference[@Include="Esri.ArcGISPro.Extensions30"]')
if ($null -eq $apiPackage -or $apiPackage.GetAttribute('Version') -ne '3.5.0.57366') {
    throw 'Julkaisu pitää kääntää Esri.ArcGISPro.Extensions30 3.5.0.57366 -paketilla.'
}

Invoke-Native { gh auth status } 'gh ei ole kirjautunut (aja: gh auth login)'
if (git status --porcelain) { throw 'Työhakemistossa on commitoimattomia muutoksia. Commitoi ne ensin.' }
if ((git rev-parse --abbrev-ref HEAD) -ne $branch) { throw "Julkaise -haarasta." }
Invoke-Native { git fetch $remote } 'git fetch epäonnistui'
if ((git rev-parse HEAD) -ne (git rev-parse "$remote/$branch")) {
    throw "HEAD ei vastaa $remote/$branch. Pushaa (tai pullaa) ensin, jotta tagi osoittaa julkaistuun committiin."
}
$ErrorActionPreference = 'Continue'
gh release view $tag -R $repo 2>&1 | Out-Null
$exists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = 'Stop'
if ($exists) { throw "Release $tag on jo olemassa. Nosta versiota Config.daml:ssa." }

if (-not $SkipBuild) {
    Invoke-Native { & (Join-Path $root 'build-addin.ps1') -Configuration $configuration -TargetFramework $framework } 'Käännös/paketointi epäonnistui'
}

$package = Join-Path $root "bin\$configuration\$framework\Muuntaja.esriAddInX"
if (-not (Test-Path -LiteralPath $package -PathType Leaf)) { throw "Pakettia ei löytynyt: $package" }

$asset = Join-Path ([IO.Path]::GetTempPath()) 'Muuntaja.esriAddInX'
Copy-Item -LiteralPath $package -Destination $asset -Force

$ghArgs = @('release', 'create', $tag, $asset, '-R', $repo, '--target', (git rev-parse HEAD), '--title', "Muuntaja $version")
if ($Notes) { $ghArgs += @('--notes', $Notes) } else { $ghArgs += '--generate-notes' }
if ($Draft) { $ghArgs += '--draft' }
& gh @ghArgs
if ($LASTEXITCODE -ne 0) { throw "Releasen luonti epäonnistui (exit $LASTEXITCODE)." }

Remove-Item -LiteralPath $asset -Force
Write-Output "Julkaistu: https://github.com/$repo/releases/tag/$tag"
Write-Output "Latauslinkki: https://github.com/$repo/releases/latest/download/Muuntaja.esriAddInX"
