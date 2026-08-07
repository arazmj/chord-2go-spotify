#!/bin/sh
set -eu

umask 022
export COPYFILE_DISABLE=1

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PAYLOAD_DIR=$REPO_ROOT/payload
REPO_LICENSE=$REPO_ROOT/LICENSE
REPO_THIRD_PARTY_NOTICES=$REPO_ROOT/THIRD_PARTY_NOTICES.md

usage()
{
    cat >&2 <<'EOF'
Usage: build-payload.sh [LIBRESPOT_BINARY] [OUTPUT_PATH]

Positional arguments:
  LIBRESPOT_BINARY  Path to the ARM librespot binary. Optional when
                    LIBRESPOT_BINARY is already exported.
  OUTPUT_PATH       Archive path. Defaults to dist/spotify-install.tar.gz.

Environment:
  LIBRESPOT_BINARY  Path to the ARM librespot binary.
  LIBRESPOT_LICENSE Path to the upstream librespot LICENSE file. If unset,
                    the builder expects LICENSE or librespot.LICENSE next to
                    the librespot binary.
EOF
    exit 1
}

absolute_path()
{
    case "$1" in
        /*)
            printf '%s\n' "$1"
            ;;
        *)
            printf '%s/%s\n' "$(pwd)" "$1"
            ;;
    esac
}

require_file()
{
    if [ ! -f "$1" ]; then
        printf 'ERROR: missing file: %s\n' "$1" >&2
        exit 1
    fi
}

require_executable()
{
    require_file "$1"
    if [ ! -x "$1" ]; then
        printf 'ERROR: file is not executable: %s\n' "$1" >&2
        exit 1
    fi
}

sha256_of()
{
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        openssl dgst -sha256 "$1" | awk '{print $2}'
    fi
}

binary_input=${LIBRESPOT_BINARY:-}
output_input=

case $# in
    0)
        ;;
    1)
        if [ -n "$binary_input" ]; then
            output_input=$1
        else
            binary_input=$1
        fi
        ;;
    2)
        binary_input=$1
        output_input=$2
        ;;
    *)
        usage
        ;;
esac

[ -n "$binary_input" ] || usage
binary_path=$(absolute_path "$binary_input")
require_executable "$binary_path"

license_input=${LIBRESPOT_LICENSE:-}
if [ -z "$license_input" ]; then
    binary_dir=$(dirname "$binary_path")
    if [ -f "$binary_dir/LICENSE" ]; then
        license_input=$binary_dir/LICENSE
    elif [ -f "$binary_dir/librespot.LICENSE" ]; then
        license_input=$binary_dir/librespot.LICENSE
    else
        printf 'ERROR: set LIBRESPOT_LICENSE or place LICENSE or librespot.LICENSE next to %s\n' "$binary_path" >&2
        exit 1
    fi
fi

license_path=$(absolute_path "$license_input")
require_file "$license_path"

output_path=$(absolute_path "${output_input:-$REPO_ROOT/dist/spotify-install.tar.gz}")
output_dir=$(dirname "$output_path")
stage_dir=$output_dir/.build-payload.$$
tmp_archive=$output_path.tmp.$$

cleanup()
{
    if [ -d "$stage_dir" ]; then
        rm -rf "$stage_dir"
    fi
    rm -f "$tmp_archive"
}

trap cleanup EXIT HUP INT TERM

mkdir -p "$output_dir"
mkdir -p "$stage_dir"

for name in install.sh uninstall.sh librespot-aplay librespot-audio librespot.service; do
    require_file "$PAYLOAD_DIR/$name"
done
require_file "$REPO_LICENSE"
require_file "$REPO_THIRD_PARTY_NOTICES"

cp "$PAYLOAD_DIR/install.sh" "$stage_dir/install.sh"
cp "$PAYLOAD_DIR/uninstall.sh" "$stage_dir/uninstall.sh"
cp "$PAYLOAD_DIR/librespot-aplay" "$stage_dir/librespot-aplay"
cp "$PAYLOAD_DIR/librespot-audio" "$stage_dir/librespot-audio"
cp "$PAYLOAD_DIR/librespot.service" "$stage_dir/librespot.service"
cp "$binary_path" "$stage_dir/librespot"
cp "$license_path" "$stage_dir/librespot-LICENSE"
cp "$REPO_LICENSE" "$stage_dir/chord-2go-spotify-LICENSE"
cp "$REPO_THIRD_PARTY_NOTICES" "$stage_dir/chord-2go-spotify-THIRD_PARTY_NOTICES.md"

chmod 0755 \
    "$stage_dir/install.sh" \
    "$stage_dir/uninstall.sh" \
    "$stage_dir/librespot-aplay" \
    "$stage_dir/librespot-audio" \
    "$stage_dir/librespot"
chmod 0644 \
    "$stage_dir/librespot.service" \
    "$stage_dir/librespot-LICENSE" \
    "$stage_dir/chord-2go-spotify-LICENSE" \
    "$stage_dir/chord-2go-spotify-THIRD_PARTY_NOTICES.md"

touch -t 202001010000 \
    "$stage_dir/install.sh" \
    "$stage_dir/uninstall.sh" \
    "$stage_dir/librespot-aplay" \
    "$stage_dir/librespot-audio" \
    "$stage_dir/librespot.service" \
    "$stage_dir/librespot" \
    "$stage_dir/librespot-LICENSE" \
    "$stage_dir/chord-2go-spotify-LICENSE" \
    "$stage_dir/chord-2go-spotify-THIRD_PARTY_NOTICES.md"

(
    cd "$stage_dir"
    tar -cf - \
        chord-2go-spotify-LICENSE \
        chord-2go-spotify-THIRD_PARTY_NOTICES.md \
        install.sh \
        librespot \
        librespot-LICENSE \
        librespot-aplay \
        librespot-audio \
        librespot.service \
        uninstall.sh
) | gzip -n > "$tmp_archive"

mv -f "$tmp_archive" "$output_path"
checksum=$(sha256_of "$output_path")
printf 'SHA256  %s  %s\n' "$checksum" "$output_path"
