[CmdletBinding()]
param(
    [string]$Configuration = 'Debug',
    [string]$TargetFramework = 'net8.0-windows',
    [string]$MSBuildPath = ''
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$projectPath = Join-Path $root 'Muuntaja.csproj'

function Resolve-MSBuildPath {
    param([string]$ExplicitPath)

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        $resolved = Resolve-Path -LiteralPath $ExplicitPath -ErrorAction Stop
        if ((Split-Path -Leaf $resolved.Path) -ine 'MSBuild.exe') {
            throw "MSBuildPath must point to MSBuild.exe: $($resolved.Path)"
        }
        return $resolved.Path
    }

    $candidates = @()
    $vsWhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path -LiteralPath $vsWhere -PathType Leaf) {
        $installations = @(& $vsWhere -all -products * -requires Microsoft.Component.MSBuild -property installationPath)
        $installations = @($installations | Sort-Object {
            if ($_ -match 'BuildTools') { 3 }
            elseif ($_ -match '\\2022\\') { 0 }
            elseif ($_ -match '\\18\\') { 1 }
            else { 2 }
        })
        foreach ($installation in $installations) {
            if (-not [string]::IsNullOrWhiteSpace($installation)) {
                $candidates += Join-Path $installation 'MSBuild\Current\Bin\MSBuild.exe'
                $candidates += Join-Path $installation 'MSBuild\Current\Bin\amd64\MSBuild.exe'
            }
        }
    }

    $candidates += @(
        (Join-Path ${env:ProgramFiles} 'Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe'),
        (Join-Path ${env:ProgramFiles} 'Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe'),
        (Join-Path ${env:ProgramFiles} 'Microsoft Visual Studio\2022\Enterprise\MSBuild\Current\Bin\MSBuild.exe'),
        (Join-Path ${env:ProgramFiles} 'Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe'),
        (Join-Path ${env:ProgramFiles} 'Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe'),
        (Join-Path ${env:ProgramFiles} 'Microsoft Visual Studio\18\Professional\MSBuild\Current\Bin\MSBuild.exe'),
        (Join-Path ${env:ProgramFiles} 'Microsoft Visual Studio\18\Enterprise\MSBuild\Current\Bin\MSBuild.exe'),
        (Join-Path ${env:ProgramFiles} 'Microsoft Visual Studio\18\BuildTools\MSBuild\Current\Bin\MSBuild.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\18\BuildTools\MSBuild\Current\Bin\MSBuild.exe')
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw 'Full-framework MSBuild.exe was not found. Install Visual Studio 2022 Build Tools or pass -MSBuildPath explicitly.'
}

$dotnet = Get-Command dotnet -ErrorAction Stop
$installedSdks = @(& $dotnet.Source --list-sdks)
$buildableSdks = @($installedSdks | ForEach-Object {
    if ($_ -match '^(?<version>\d+(?:\.\d+){1,3})\s') { [version]$Matches.version }
})
if ($LASTEXITCODE -ne 0 -or -not ($buildableSdks | Where-Object { $_.Major -ge 8 })) {
    throw 'Install the .NET 8 SDK or newer before building the ArcGIS Pro AddInX.'
}

$msbuild = Resolve-MSBuildPath -ExplicitPath $MSBuildPath
Write-Output "Using MSBuild: $msbuild"

& $msbuild $projectPath '/restore' '/t:Rebuild' "/p:Configuration=$Configuration" "/p:TargetFramework=$TargetFramework" '/p:ArcGISFolder=' '/nologo' '/v:minimal'
if ($LASTEXITCODE -ne 0) {
    throw "MSBuild failed with exit code $LASTEXITCODE. The package was not created."
}

$assemblyPath = Join-Path $root "bin\$Configuration\$TargetFramework\Muuntaja.dll"
if (-not (Test-Path -LiteralPath $assemblyPath -PathType Leaf)) {
    throw "Rebuild completed but the expected assembly was not found: $assemblyPath"
}

& (Join-Path $root 'package-addin-fixed.ps1') -Configuration $Configuration -TargetFramework $TargetFramework
if ($LASTEXITCODE -ne 0) {
    throw "Packaging failed with exit code $LASTEXITCODE."
}

$packagePath = Join-Path $root "bin\$Configuration\$TargetFramework\Muuntaja.esriAddInX"
if (-not (Test-Path -LiteralPath $packagePath -PathType Leaf)) {
    throw "The expected AddInX package was not created: $packagePath"
}
Get-Item -LiteralPath $packagePath | Select-Object FullName, Length
