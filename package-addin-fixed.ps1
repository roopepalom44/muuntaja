[CmdletBinding()]
param(
    [string]$Configuration = 'Debug',
    [string]$TargetFramework = 'net8.0-windows'
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

$root = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$output = Join-Path $root "bin\$Configuration\$TargetFramework"
$stage = Join-Path $env:TEMP ('muuntaja-stage-' + [guid]::NewGuid().ToString('N'))
$zip = Join-Path $env:TEMP ('muuntaja-' + [guid]::NewGuid().ToString('N') + '.zip')
$package = Join-Path $output 'Muuntaja.esriAddInX'

# Add-inin juureen tulee vain manifesti ja kuvat. Runtime-tiedostot ovat
# Install-kansiossa, jotta ArcGIS Pro ei yritä ladata niitä väärästä polusta.
$files = @(
    @{ Relative = 'Config.daml'; Source = (Join-Path $root 'Config.daml') },
    @{ Relative = 'Images\AddInDesktop16.png'; Source = (Join-Path $root 'Images\AddInDesktop16.png') },
    @{ Relative = 'Images\AddInDesktop32.png'; Source = (Join-Path $root 'Images\AddInDesktop32.png') },
    @{ Relative = 'Images\muuntaja16.png'; Source = (Join-Path $root 'Images\muuntaja16.png') },
    @{ Relative = 'Images\muuntaja32.png'; Source = (Join-Path $root 'Images\muuntaja32.png') },
    @{ Relative = 'DarkImages\AddInDesktop16.png'; Source = (Join-Path $root 'DarkImages\AddInDesktop16.png') },
    @{ Relative = 'DarkImages\AddInDesktop32.png'; Source = (Join-Path $root 'DarkImages\AddInDesktop32.png') },
    @{ Relative = 'Install\Muuntaja.dll'; Source = (Join-Path $output 'Muuntaja.dll') },
    @{ Relative = 'Install\Muuntaja.pdb'; Source = (Join-Path $output 'Muuntaja.pdb') },
    @{ Relative = 'Install\Muuntaja.deps.json'; Source = (Join-Path $output 'Muuntaja.deps.json') },
    @{ Relative = 'Install\OpenMuuntajaToolButton.cs'; Source = (Join-Path $root 'OpenMuuntajaToolButton.cs') },
    @{ Relative = 'Install\Toolboxes\Muuntaja.pyt'; Source = (Join-Path $root 'Toolboxes\Muuntaja.pyt') }
)

try {
    foreach ($file in $files) {
        if (-not (Test-Path -LiteralPath $file.Source -PathType Leaf)) {
            throw "Missing package input: $($file.Source)"
        }
    }

    foreach ($file in $files) {
        $destination = Join-Path $stage $file.Relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        Copy-Item -LiteralPath $file.Source -Destination $destination
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $package) | Out-Null
    [IO.Compression.ZipFile]::CreateFromDirectory(
        $stage,
        $zip,
        [IO.Compression.CompressionLevel]::Optimal,
        $false
    )

    $archive = [IO.Compression.ZipFile]::OpenRead($zip)
    try {
        $entries = @($archive.Entries | ForEach-Object { $_.FullName.Replace('/', '\') })
    }
    finally {
        $archive.Dispose()
    }

    foreach ($file in $files) {
        if ($entries -notcontains $file.Relative) {
            throw "Package validation failed: $($file.Relative)"
        }
    }

    if ($entries -contains 'Muuntaja.dll' -or $entries -contains 'Toolboxes\Muuntaja.pyt') {
        throw 'Package validation failed: runtime files must be under Install\.'
    }

    Move-Item -LiteralPath $zip -Destination $package -Force
    $zip = $null
    Write-Output "Created: $package"
    Write-Output 'Package layout: OK'
}
finally {
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
    if ($zip -and (Test-Path -LiteralPath $zip)) {
        Remove-Item -LiteralPath $zip -Force
    }
}
