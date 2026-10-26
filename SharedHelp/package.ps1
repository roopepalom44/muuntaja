# Dot-source from a package script after its $root has been resolved.
& python (Join-Path $root 'SharedHelp\sync.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Shared help validation failed. Run python SharedHelp/sync.py.' }
$sharedHelpPackageFiles = @(
    @{ Relative = 'Install\SharedHelp\index.html'; Source = (Join-Path $root 'SharedHelp\index.html'); Required = $true },
    @{ Relative = 'Install\SharedHelp\manifest.json'; Source = (Join-Path $root 'SharedHelp\manifest.json'); Required = $true }
)
foreach ($icon in (Get-ChildItem -LiteralPath (Join-Path $root 'SharedHelp\Icons') -Filter '*.png' -File)) {
    $sharedHelpPackageFiles += @{
        Relative = ('SharedHelp\Icons\' + $icon.Name)
        Source = $icon.FullName
        Required = $true
    }
}
if ($sharedHelpPackageFiles.Count -ne 12) { throw 'Shared help must include both sizes of all five icons.' }

function Assert-SharedHelpDamlTypes {
    param([Parameter(Mandatory)][string]$AssemblyPath)
    & dotnet run --project (Join-Path $root 'SharedHelp\TypeCheck\TypeCheck.csproj') `
        --configuration Release --no-launch-profile -- $AssemblyPath (Join-Path $root 'Config.daml')
    if ($LASTEXITCODE -ne 0) {
        throw 'DAML classes do not match the compiled DLL. The add-in must not be packaged.'
    }
}
