#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
COMMIT=d36f9f1907e8cc9d68a93f8ebc6b627b1bf7267d
TARGET=armv7-unknown-linux-musleabihf
TOOLCHAIN=${RUST_TOOLCHAIN:-1.85.0}
OUTPUT=${1:-"$ROOT/dist/librespot-armv7"}

case "$OUTPUT" in
    /*) ;;
    *) OUTPUT="$ROOT/$OUTPUT" ;;
esac

command -v git >/dev/null 2>&1 || {
    echo "git is required" >&2
    exit 1
}
command -v cargo >/dev/null 2>&1 || {
    echo "cargo is required" >&2
    exit 1
}
command -v cargo-zigbuild >/dev/null 2>&1 &&
    cargo-zigbuild --version >/dev/null 2>&1 &&
    cargo +"$TOOLCHAIN" --version >/dev/null 2>&1 || {
    echo "Rust $TOOLCHAIN and cargo-zigbuild are required" >&2
    exit 1
}

WORK=$(mktemp -d "${TMPDIR:-/tmp}/chord-2go-librespot.XXXXXX")
cleanup()
{
    rm -rf "$WORK"
}
trap cleanup EXIT HUP INT TERM

git clone --quiet --filter=blob:none \
    https://github.com/librespot-org/librespot.git "$WORK/librespot"
git -C "$WORK/librespot" checkout --quiet --detach "$COMMIT"
test "$(git -C "$WORK/librespot" rev-parse HEAD)" = "$COMMIT"

SOURCE_DATE_EPOCH=$(git -C "$WORK/librespot" show -s --format=%ct HEAD)
export SOURCE_DATE_EPOCH
export RUSTFLAGS="${RUSTFLAGS:-} -C strip=symbols"

cargo +"$TOOLCHAIN" zigbuild \
    --manifest-path "$WORK/librespot/Cargo.toml" \
    --release \
    --locked \
    --target "$TARGET" \
    --no-default-features \
    --features rustls-tls-webpki-roots,with-libmdns

mkdir -p "$(dirname -- "$OUTPUT")"
cp "$WORK/librespot/target/$TARGET/release/librespot" "$OUTPUT"
cp "$WORK/librespot/LICENSE" "$(dirname -- "$OUTPUT")/librespot.LICENSE"
chmod 0755 "$OUTPUT"

if command -v file >/dev/null 2>&1; then
    FILE_INFO=$(file "$OUTPUT")
    echo "$FILE_INFO"
    echo "$FILE_INFO" | grep -q "ELF 32-bit.*ARM"
    echo "$FILE_INFO" | grep -q "statically linked"
fi

if command -v qemu-arm >/dev/null 2>&1; then
    qemu-arm "$OUTPUT" --version
fi

if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$OUTPUT"
else
    shasum -a 256 "$OUTPUT"
fi
