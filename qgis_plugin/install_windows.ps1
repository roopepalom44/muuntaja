param([Parameter(Mandatory = $true)][string]$PluginName)

$ErrorActionPreference = 'Stop'
try {
    if ($PluginName -notmatch '^[a-z][a-z0-9_]+$') { throw 'Virheellinen lisäosan nimi.' }
    $source = Join-Path $PSScriptRoot $PluginName
    if (-not (Test-Path -LiteralPath (Join-Path $source 'metadata.txt') -PathType Leaf)) {
        throw 'Lisäosakansiota ei löydy. Pura koko Windows-asennuspaketti ennen asennusta.'
    }
    if (-not $env:APPDATA) { throw 'Windowsin APPDATA-kansiota ei löydy.' }
    $running = Get-Process -Name 'qgis', 'qgis-bin', 'qgis-ltr', 'qgis-ltr-bin' -ErrorAction SilentlyContinue
    if ($running) { throw 'Sulje QGIS ennen asennusta ja suorita tämä tiedosto uudelleen.' }

    $profilesRoot = Join-Path $env:APPDATA 'QGIS\QGIS3\profiles'
    if (-not (Test-Path -LiteralPath $profilesRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $profilesRoot -Force | Out-Null
    }
    $profiles = @(Get-ChildItem -LiteralPath $profilesRoot -Directory)
    if ($profiles.Count -eq 0) {
        $profiles = @(New-Item -ItemType Directory -Path (Join-Path $profilesRoot 'default') -Force)
    }

    foreach ($profile in $profiles) {
        $target = Join-Path $profile.FullName "python\plugins\$PluginName"
        New-Item -ItemType Directory -Path $target -Force | Out-Null
        foreach ($file in Get-ChildItem -LiteralPath $source -File -Recurse) {
            $relative = $file.FullName.Substring($source.Length).TrimStart('\')
            $destination = Join-Path $target $relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
        }

        $settings = Join-Path $profile.FullName 'QGIS\QGIS3.ini'
        New-Item -ItemType Directory -Path (Split-Path -Parent $settings) -Force | Out-Null
        $lines = New-Object 'System.Collections.Generic.List[string]'
        if (Test-Path -LiteralPath $settings -PathType Leaf) {
            foreach ($line in (Get-Content -LiteralPath $settings -Encoding UTF8)) { $lines.Add($line) }
        }
        $section = -1
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -eq '[PythonPlugins]') { $section = $i; break }
        }
        if ($section -lt 0) {
            $lines.Add('')
            $lines.Add('[PythonPlugins]')
            $lines.Add("$PluginName=true")
        } else {
            $end = $section + 1
            while ($end -lt $lines.Count -and $lines[$end] -notmatch '^\[') { $end++ }
            $found = $false
            for ($i = $section + 1; $i -lt $end; $i++) {
                if ($lines[$i] -match ('^' + [regex]::Escape($PluginName) + '=')) {
                    $lines[$i] = "$PluginName=true"
                    $found = $true
                    break
                }
            }
            if (-not $found) { $lines.Insert($end, "$PluginName=true") }
        }
        [System.IO.File]::WriteAllLines($settings, $lines, (New-Object System.Text.UTF8Encoding($false)))
        Write-Host "Asennettu profiiliin: $($profile.Name)"
    }
    Write-Host 'Valmis. Käynnistä QGIS; lisäosa on käytössä.'
    exit 0
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
