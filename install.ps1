# D2L Scraper installer for Windows:
#   irm https://raw.githubusercontent.com/Dryd33n/d2l-scraper/master/install.ps1 | iex
# Installs uv (if needed), which installs Python (if needed) and D2L Scraper for this user only.
# No admin rights needed. Run it again to update.
#
# Optional settings:
#   D2L_SCRAPER_SOURCE    install from this path or URL instead of GitHub
#   D2L_SCRAPER_NO_START  don't start the program when done

& {
    $ErrorActionPreference = 'Stop'
    $source = $env:D2L_SCRAPER_SOURCE
    if (-not $source) { $source = 'https://github.com/Dryd33n/d2l-scraper/archive/refs/heads/master.zip' }

    $dir = $env:UV_UNMANAGED_INSTALL
    if (-not $dir) { $dir = $env:UV_INSTALL_DIR }
    if (-not $dir) { $dir = Join-Path $HOME '.local\bin' }
    $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uv -and (Test-Path (Join-Path $dir 'uv.exe'))) { $uv = Join-Path $dir 'uv.exe' }
    if (-not $uv) {
        Write-Host 'Installing uv...'
        # its own process: the uv installer may exit, which would close this window
        powershell -NoProfile -ExecutionPolicy Bypass -Command 'irm https://astral.sh/uv/install.ps1 | iex'
        if ($LASTEXITCODE) { throw 'Could not install uv. Check your internet connection and try again.' }
        $uv = Join-Path $dir 'uv.exe'
    }

    Write-Host 'Installing D2L Scraper...'
    & $uv tool install --force --reinstall-package d2l-scraper --python 3.13 $source
    if ($LASTEXITCODE) { throw 'Could not install D2L Scraper. Check your internet connection and try again.' }
    $bin = & $uv tool dir --bin

    # An unmanaged uv is a test install, which must leave the user's PATH alone
    if (-not $env:UV_UNMANAGED_INSTALL) { & $uv tool update-shell *> $null }
    # this window started before the PATH changed, so it needs telling too
    if (($env:Path -split ';') -notcontains $bin) { $env:Path = "$bin;$env:Path" }

    Write-Host ''
    Write-Host 'D2L Scraper is installed. Next time, open a terminal and type: d2l-scraper' -ForegroundColor Green
    Write-Host ''
    if (-not $env:D2L_SCRAPER_NO_START) { & (Join-Path $bin 'd2l-scraper.exe') }
}
