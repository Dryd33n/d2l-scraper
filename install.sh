#!/bin/sh
# D2L Scraper installer for macOS and Linux:
#   curl -fsSL https://raw.githubusercontent.com/Dryd33n/d2l-scraper/master/install.sh | sh
# Installs uv (if needed), which installs Python (if needed) and D2L Scraper for this user only.
# No admin rights needed. Run it again to update.
#
# Optional settings:
#   D2L_SCRAPER_SOURCE    install from this path or URL instead of GitHub
#   D2L_SCRAPER_NO_START  don't start the program when done

set -eu

# everything is in a function so a partly downloaded script can't run half of itself
main() {
    source="${D2L_SCRAPER_SOURCE:-https://github.com/Dryd33n/d2l-scraper/archive/refs/heads/master.zip}"

    dir="${UV_UNMANAGED_INSTALL:-${UV_INSTALL_DIR:-$HOME/.local/bin}}"
    uv="$(command -v uv || true)"
    if [ -z "$uv" ] && [ -x "$dir/uv" ]; then
        uv="$dir/uv"
    fi
    if [ -z "$uv" ]; then
        echo "Installing uv..."
        curl -fsSL https://astral.sh/uv/install.sh | sh
        uv="$dir/uv"
    fi

    echo "Installing D2L Scraper..."
    "$uv" tool install --force --reinstall-package d2l-scraper --python 3.13 "$source"
    bin="$("$uv" tool dir --bin)"

    # An unmanaged uv is a test install, which must leave the user's PATH alone
    if [ -z "${UV_UNMANAGED_INSTALL:-}" ]; then
        "$uv" tool update-shell >/dev/null 2>&1 || true
    fi

    echo
    echo "D2L Scraper is installed. Next time, open a new terminal and type: d2l-scraper"
    echo
    # piped through sh, stdin is this script, so the program needs the terminal handed to it
    if [ -z "${D2L_SCRAPER_NO_START:-}" ] && [ -r /dev/tty ]; then
        "$bin/d2l-scraper" </dev/tty || true
    fi
}

main
