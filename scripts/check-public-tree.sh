#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

FORBIDDEN_EXTENSIONS='apk|bin|dec|dll|elf|exe|img|iso|nupkg|so|tgz|xapk'
if git ls-files | grep -E "\.($FORBIDDEN_EXTENSIONS)$" >/dev/null; then
    echo "Forbidden opaque or proprietary artifact is tracked:" >&2
    git ls-files | grep -E "\.($FORBIDDEN_EXTENSIONS)$" >&2
    exit 1
fi

if git grep -n -E '192\.168\.1\.(183|188)|com\.companyname\.PolyUniversal|runtime-pack-2|spotify-[0-9]+\.[0-9]+\.[0-9]+\.exe' -- . \
    ':(exclude)scripts/check-public-tree.sh' >/dev/null; then
    echo "Private analysis detail found in public files:" >&2
    git grep -n -E '192\.168\.1\.(183|188)|com\.companyname\.PolyUniversal|runtime-pack-2|spotify-[0-9]+\.[0-9]+\.[0-9]+\.exe' -- . \
        ':(exclude)scripts/check-public-tree.sh' >&2
    exit 1
fi

MAX_BYTES=5242880
git ls-files | while IFS= read -r path; do
    size=$(wc -c < "$path")
    if [ "$size" -gt "$MAX_BYTES" ]; then
        echo "Tracked file exceeds 5 MiB: $path" >&2
        exit 1
    fi
done

echo "Public tree check passed."
