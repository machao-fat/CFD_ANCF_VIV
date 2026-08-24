param(
    [Parameter(Mandatory=$true)]
    [string]$CasePath
)

$command = "source /opt/openfoam10/etc/bashrc && cd `"$CasePath`" && pimpleFoam"
$wslDistro = "Ubuntu-22.04"
$availableDistros = (wsl.exe --list --quiet 2>$null) -join "`n"
if ($availableDistros -notmatch [regex]::Escape($wslDistro)) {
    if ($availableDistros -match "Ubuntu") {
        $wslDistro = "Ubuntu"
    }
}
wsl.exe -d $wslDistro bash -lc $command
exit $LASTEXITCODE
