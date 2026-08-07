#!/bin/sh
set -eu

umask 022

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_PREFIX=${CHORD_2GO_SPOTIFY_ROOT:-}
SYSTEMCTL=${SYSTEMCTL:-systemctl}
LOGGER_CMD=${LOGGER_CMD:-logger}

SERVICE_NAME=librespot.service
SUCCESS_MARKER=CHORD_2GO_SPOTIFY_INSTALL_SUCCESS
STATE_DIR=/var/lib/chord-2go-spotify
BACKUP_DIR=$STATE_DIR/backups
STAGING_BASE=$STATE_DIR/staging
STAGING_DIR=$STAGING_BASE/install.$$
MANIFEST_PATH=$STATE_DIR/manifest.tsv
SERVICE_STATE_PATH=$STATE_DIR/original-service-state.env
CACHE_DIR=/var/cache/chord-2go-spotify

DEST_LIBRESPOT=/usr/local/bin/librespot
DEST_APLAY=/usr/local/bin/librespot-aplay
DEST_AUDIO=/usr/local/sbin/librespot-audio
DEST_UNINSTALL=/usr/local/sbin/uninstall-chord-2go-spotify
DEST_SERVICE=/etc/systemd/system/librespot.service
DEST_DOC_DIR=/usr/local/share/doc/chord-2go-spotify
DEST_LIBRESPOT_LICENSE=$DEST_DOC_DIR/librespot-LICENSE
DEST_PROJECT_LICENSE=$DEST_DOC_DIR/chord-2go-spotify-LICENSE
DEST_THIRD_PARTY_NOTICES=$DEST_DOC_DIR/chord-2go-spotify-THIRD_PARTY_NOTICES.md

STAGING_REAL=
ROLLBACK_DIR_REAL=
ROLLBACK_INDEX_REAL=
LEGACY_BACKUP_DIR_REAL=
LEGACY_INDEX_REAL=
NEW_MANIFEST_REAL=
CURRENT_MANIFEST_REAL=
NEW_SERVICE_STATE_REAL=
CURRENT_SERVICE_STATE_REAL=
CHANGES_APPLIED=0
COMMITTED=0
SERVICE_WAS_PRESENT=0
SERVICE_WAS_ENABLED=0
SERVICE_WAS_ACTIVE=0

log_notice()
{
    printf '%s\n' "$*" >&2
    "$LOGGER_CMD" -t chord-2go-spotify-install "$*" >/dev/null 2>&1 || true
}

fail()
{
    log_notice "ERROR: $*"
    exit 1
}

resolve_path()
{
    case "$1" in
        /*)
            if [ -n "$ROOT_PREFIX" ] && [ "$ROOT_PREFIX" != "/" ]; then
                printf '%s%s\n' "${ROOT_PREFIX%/}" "$1"
            else
                printf '%s\n' "$1"
            fi
            ;;
        *)
            printf '%s\n' "$1"
            ;;
    esac
}

path_exists()
{
    [ -e "$1" ] || [ -L "$1" ]
}

ensure_dir_real()
{
    ensure_dir_real_path=$1
    ensure_dir_real_mode=$2
    mkdir -p "$ensure_dir_real_path"
    chmod "$ensure_dir_real_mode" "$ensure_dir_real_path"
}

ensure_dir()
{
    ensure_dir_real "$(resolve_path "$1")" "$2"
}

safe_name()
{
    printf '%s\n' "$1" | sed 's#^/##; s#[/ ]#_#g'
}

fingerprint_for()
{
    fingerprint_path=$1
    fingerprint_digest=

    if command -v sha256sum >/dev/null 2>&1; then
        fingerprint_digest=$(sha256sum "$fingerprint_path" 2>/dev/null || true)
    fi
    if [ -z "$fingerprint_digest" ] && command -v shasum >/dev/null 2>&1; then
        fingerprint_digest=$(shasum -a 256 "$fingerprint_path" 2>/dev/null || true)
    fi
    [ -n "$fingerprint_digest" ] || return 1

    printf 'sha256:%s\n' "${fingerprint_digest%% *}"
}

stage_copy()
{
    src=$1
    dst=$2
    mode=$3
    tmp=$dst.tmp.$$
    rm -f "$tmp"
    if ! cp "$src" "$tmp"; then
        rm -f "$tmp"
        fail "failed to stage $src"
    fi
    if ! chmod "$mode" "$tmp"; then
        rm -f "$tmp"
        fail "failed to chmod $dst"
    fi
    if ! mv -f "$tmp" "$dst"; then
        rm -f "$tmp"
        fail "failed to finalize $dst"
    fi
}

install_staged_file()
{
    src=$1
    dest=$2
    mode=$3
    dest_real=$(resolve_path "$dest")
    parent=$(dirname "$dest_real")
    tmp=$parent/.chord-2go-spotify-install.$$.tmp
    ensure_dir_real "$parent" 0755
    rm -f "$tmp"
    if ! cp "$src" "$tmp"; then
        rm -f "$tmp"
        fail "failed to copy $dest"
    fi
    if ! chmod "$mode" "$tmp"; then
        rm -f "$tmp"
        fail "failed to chmod $dest"
    fi
    if ! mv -f "$tmp" "$dest_real"; then
        rm -f "$tmp"
        fail "failed to install $dest"
    fi
}

restore_saved_copy()
{
    saved=$1
    dest=$2
    dest_real=$(resolve_path "$dest")
    parent=$(dirname "$dest_real")
    tmp=$parent/.chord-2go-spotify-restore.$$.tmp
    ensure_dir_real "$parent" 0755
    rm -f "$tmp"
    if ! cp -p "$saved" "$tmp"; then
        rm -f "$tmp"
        return 1
    fi
    if ! mv -f "$tmp" "$dest_real"; then
        rm -f "$tmp"
        return 1
    fi
    return 0
}

remove_known_file()
{
    rm -f "$(resolve_path "$1")"
}

remove_known_dir_if_empty()
{
    rmdir "$(resolve_path "$1")" 2>/dev/null || true
}

require_payload_file()
{
    path=$1
    if [ ! -f "$path" ]; then
        fail "missing required payload file: $(basename "$path")"
    fi
}

require_payload_executable()
{
    path=$1
    require_payload_file "$path"
    if [ ! -x "$path" ]; then
        fail "payload file is not executable: $(basename "$path")"
    fi
}

manifest_lookup()
{
    target=$1
    if [ ! -f "$CURRENT_MANIFEST_REAL" ]; then
        return 1
    fi
    while IFS='|' read -r path kind backup fingerprint; do
        [ -n "$path" ] || continue
        [ "$path" = "$target" ] || continue
        printf '%s|%s|%s\n' "$kind" "$backup" "${fingerprint:-}"
        return 0
    done < "$CURRENT_MANIFEST_REAL"
    return 1
}

append_manifest_entry()
{
    printf '%s|%s|%s|%s\n' "$1" "$2" "$3" "$4" >> "$NEW_MANIFEST_REAL"
}

record_original_service_state()
{
    [ -f "$CURRENT_SERVICE_STATE_REAL" ] && return 0

    cat > "$NEW_SERVICE_STATE_REAL" <<EOF
present=$SERVICE_WAS_PRESENT
enabled=$SERVICE_WAS_ENABLED
active=$SERVICE_WAS_ACTIVE
EOF
}

ensure_persistent_manifest_entry()
{
    dest=$1
    fingerprint=$2
    if entry=$(manifest_lookup "$dest"); then
        IFS='|' read -r kind backup _saved_fingerprint <<EOF
$entry
EOF
        if [ "$kind" = backup ] && [ "$backup" != "-" ] && ! path_exists "$(resolve_path "$BACKUP_DIR/$backup")"; then
            fail "missing saved backup for $dest"
        fi
    else
        dest_real=$(resolve_path "$dest")
        if path_exists "$dest_real"; then
            kind=backup
            backup=$(safe_name "$dest").bak
            ensure_dir "$BACKUP_DIR" 0755
            if ! cp -p "$dest_real" "$(resolve_path "$BACKUP_DIR/$backup")"; then
                fail "failed to preserve original $dest"
            fi
        else
            kind=created
            backup=-
        fi
    fi
    append_manifest_entry "$dest" "$kind" "$backup" "$fingerprint"
}

capture_rollback_state()
{
    dest=$1
    dest_real=$(resolve_path "$dest")
    saved_name=$(safe_name "$dest").rollback
    if path_exists "$dest_real"; then
        if ! cp -p "$dest_real" "$ROLLBACK_DIR_REAL/$saved_name"; then
            fail "failed to capture previous $dest"
        fi
        printf '%s|present|%s\n' "$dest" "$saved_name" >> "$ROLLBACK_INDEX_REAL"
    else
        printf '%s|absent|-\n' "$dest" >> "$ROLLBACK_INDEX_REAL"
    fi
}

legacy_playplay_owned()
{
    legacy_exec=$(resolve_path /usr/local/libexec/librespot-playplay)
    legacy_doc_dir=$(resolve_path /usr/local/share/doc/librespot-playplay)
    if ! path_exists "$legacy_exec" || [ ! -d "$legacy_doc_dir" ]; then
        return 1
    fi
    if [ -f "$legacy_doc_dir/LICENSE" ] || [ -f "$legacy_doc_dir/source.tar.gz" ]; then
        return 0
    fi
    return 1
}

capture_and_remove_legacy_file()
{
    dest=$1
    dest_real=$(resolve_path "$dest")
    saved_name=$(safe_name "$dest").legacy
    if ! path_exists "$dest_real"; then
        return 0
    fi
    ensure_dir_real "$LEGACY_BACKUP_DIR_REAL" 0755
    if ! cp -p "$dest_real" "$LEGACY_BACKUP_DIR_REAL/$saved_name"; then
        fail "failed to capture legacy file $dest"
    fi
    printf '%s|present|%s\n' "$dest" "$saved_name" >> "$LEGACY_INDEX_REAL"
    remove_known_file "$dest"
}

remove_legacy_artifacts()
{
    : > "$LEGACY_INDEX_REAL"
    if legacy_playplay_owned; then
        capture_and_remove_legacy_file /usr/local/libexec/librespot-playplay
        capture_and_remove_legacy_file /usr/local/share/doc/librespot-playplay/LICENSE
        capture_and_remove_legacy_file /usr/local/share/doc/librespot-playplay/source.tar.gz
        remove_known_dir_if_empty /usr/local/share/doc/librespot-playplay
    fi
    capture_and_remove_legacy_file /usr/local/sbin/uninstall-2go-spotify
    capture_and_remove_legacy_file /usr/local/sbin/rollback-2go-spotify-lossless
}

rollback_install()
{
    set +e
    "$SYSTEMCTL" stop "$SERVICE_NAME" >/dev/null 2>&1 || true

    if [ -f "$ROLLBACK_INDEX_REAL" ]; then
        while IFS='|' read -r path state saved_name; do
            [ -n "$path" ] || continue
            case "$state" in
                present)
                    restore_saved_copy "$ROLLBACK_DIR_REAL/$saved_name" "$path" || true
                    ;;
                absent)
                    remove_known_file "$path"
                    ;;
            esac
        done < "$ROLLBACK_INDEX_REAL"
    fi

    if [ -f "$LEGACY_INDEX_REAL" ]; then
        while IFS='|' read -r path state saved_name; do
            [ -n "$path" ] || continue
            case "$state" in
                present)
                    restore_saved_copy "$LEGACY_BACKUP_DIR_REAL/$saved_name" "$path" || true
                    ;;
            esac
        done < "$LEGACY_INDEX_REAL"
    fi

    "$SYSTEMCTL" daemon-reload >/dev/null 2>&1 || true
    if [ "$SERVICE_WAS_ENABLED" -eq 1 ]; then
        "$SYSTEMCTL" enable "$SERVICE_NAME" >/dev/null 2>&1 || true
    else
        "$SYSTEMCTL" disable "$SERVICE_NAME" >/dev/null 2>&1 || true
    fi
    if [ "$SERVICE_WAS_ACTIVE" -eq 1 ]; then
        "$SYSTEMCTL" restart "$SERVICE_NAME" >/dev/null 2>&1 || true
    else
        "$SYSTEMCTL" stop "$SERVICE_NAME" >/dev/null 2>&1 || true
    fi
    log_notice "Installation failed; restored previous state"
    set -e
}

cleanup_stage()
{
    if [ -n "$STAGING_REAL" ] && [ -d "$STAGING_REAL" ]; then
        rm -rf "$STAGING_REAL"
    fi
}

on_exit()
{
    status=$?
    if [ "$status" -ne 0 ] && [ "$CHANGES_APPLIED" -eq 1 ] && [ "$COMMITTED" -eq 0 ]; then
        rollback_install
    fi
    cleanup_stage
}

trap 'exit 1' HUP INT TERM
trap on_exit EXIT

SRC_LIBRESPOT=$SCRIPT_DIR/librespot
SRC_LIBRESPOT_LICENSE=$SCRIPT_DIR/librespot-LICENSE
SRC_PROJECT_LICENSE=$SCRIPT_DIR/chord-2go-spotify-LICENSE
SRC_THIRD_PARTY_NOTICES=$SCRIPT_DIR/chord-2go-spotify-THIRD_PARTY_NOTICES.md
SRC_APLAY=$SCRIPT_DIR/librespot-aplay
SRC_AUDIO=$SCRIPT_DIR/librespot-audio
SRC_SERVICE=$SCRIPT_DIR/librespot.service
SRC_UNINSTALL=$SCRIPT_DIR/uninstall.sh

require_payload_executable "$SRC_LIBRESPOT"
require_payload_file "$SRC_LIBRESPOT_LICENSE"
require_payload_file "$SRC_PROJECT_LICENSE"
require_payload_file "$SRC_THIRD_PARTY_NOTICES"
require_payload_file "$SRC_APLAY"
require_payload_file "$SRC_AUDIO"
require_payload_file "$SRC_SERVICE"
require_payload_file "$SRC_UNINSTALL"

CURRENT_MANIFEST_REAL=$(resolve_path "$MANIFEST_PATH")
CURRENT_SERVICE_STATE_REAL=$(resolve_path "$SERVICE_STATE_PATH")
STAGING_REAL=$(resolve_path "$STAGING_DIR")
ROLLBACK_DIR_REAL=$STAGING_REAL/rollback
ROLLBACK_INDEX_REAL=$STAGING_REAL/rollback.tsv
LEGACY_BACKUP_DIR_REAL=$STAGING_REAL/legacy-backups
LEGACY_INDEX_REAL=$STAGING_REAL/legacy.tsv
NEW_MANIFEST_REAL=$STAGING_REAL/manifest.tsv
NEW_SERVICE_STATE_REAL=$STAGING_REAL/original-service-state.env

ensure_dir "$STATE_DIR" 0755
ensure_dir "$BACKUP_DIR" 0755
ensure_dir "$STAGING_BASE" 0755
ensure_dir_real "$STAGING_REAL" 0755
ensure_dir_real "$ROLLBACK_DIR_REAL" 0755
: > "$ROLLBACK_INDEX_REAL"
: > "$NEW_MANIFEST_REAL"

if path_exists "$(resolve_path "$DEST_SERVICE")"; then
    SERVICE_WAS_PRESENT=1
fi
if "$SYSTEMCTL" is-enabled --quiet "$SERVICE_NAME" >/dev/null 2>&1; then
    SERVICE_WAS_ENABLED=1
fi
if "$SYSTEMCTL" is-active --quiet "$SERVICE_NAME" >/dev/null 2>&1; then
    SERVICE_WAS_ACTIVE=1
fi
record_original_service_state

stage_copy "$SRC_LIBRESPOT" "$STAGING_REAL/librespot" 0755
stage_copy "$SRC_LIBRESPOT_LICENSE" "$STAGING_REAL/librespot-LICENSE" 0644
stage_copy "$SRC_PROJECT_LICENSE" "$STAGING_REAL/chord-2go-spotify-LICENSE" 0644
stage_copy "$SRC_THIRD_PARTY_NOTICES" "$STAGING_REAL/chord-2go-spotify-THIRD_PARTY_NOTICES.md" 0644
stage_copy "$SRC_APLAY" "$STAGING_REAL/librespot-aplay" 0755
stage_copy "$SRC_AUDIO" "$STAGING_REAL/librespot-audio" 0755
stage_copy "$SRC_SERVICE" "$STAGING_REAL/librespot.service" 0644
stage_copy "$SRC_UNINSTALL" "$STAGING_REAL/uninstall.sh" 0755

if ! fingerprint_librespot=$(fingerprint_for "$STAGING_REAL/librespot"); then
    fail "failed to fingerprint staged librespot"
fi
if ! fingerprint_aplay=$(fingerprint_for "$STAGING_REAL/librespot-aplay"); then
    fail "failed to fingerprint staged librespot-aplay"
fi
if ! fingerprint_audio=$(fingerprint_for "$STAGING_REAL/librespot-audio"); then
    fail "failed to fingerprint staged librespot-audio"
fi
if ! fingerprint_service=$(fingerprint_for "$STAGING_REAL/librespot.service"); then
    fail "failed to fingerprint staged librespot.service"
fi
if ! fingerprint_uninstall=$(fingerprint_for "$STAGING_REAL/uninstall.sh"); then
    fail "failed to fingerprint staged uninstall.sh"
fi
if ! fingerprint_librespot_license=$(fingerprint_for "$STAGING_REAL/librespot-LICENSE"); then
    fail "failed to fingerprint staged librespot-LICENSE"
fi
if ! fingerprint_project_license=$(fingerprint_for "$STAGING_REAL/chord-2go-spotify-LICENSE"); then
    fail "failed to fingerprint staged chord-2go-spotify-LICENSE"
fi
if ! fingerprint_third_party_notices=$(fingerprint_for "$STAGING_REAL/chord-2go-spotify-THIRD_PARTY_NOTICES.md"); then
    fail "failed to fingerprint staged chord-2go-spotify-THIRD_PARTY_NOTICES.md"
fi

capture_rollback_state "$DEST_LIBRESPOT"
ensure_persistent_manifest_entry "$DEST_LIBRESPOT" "$fingerprint_librespot"
CHANGES_APPLIED=1
install_staged_file "$STAGING_REAL/librespot" "$DEST_LIBRESPOT" 0755

capture_rollback_state "$DEST_APLAY"
ensure_persistent_manifest_entry "$DEST_APLAY" "$fingerprint_aplay"
install_staged_file "$STAGING_REAL/librespot-aplay" "$DEST_APLAY" 0755

capture_rollback_state "$DEST_AUDIO"
ensure_persistent_manifest_entry "$DEST_AUDIO" "$fingerprint_audio"
install_staged_file "$STAGING_REAL/librespot-audio" "$DEST_AUDIO" 0755

capture_rollback_state "$DEST_UNINSTALL"
ensure_persistent_manifest_entry "$DEST_UNINSTALL" "$fingerprint_uninstall"
install_staged_file "$STAGING_REAL/uninstall.sh" "$DEST_UNINSTALL" 0755

capture_rollback_state "$DEST_SERVICE"
ensure_persistent_manifest_entry "$DEST_SERVICE" "$fingerprint_service"
install_staged_file "$STAGING_REAL/librespot.service" "$DEST_SERVICE" 0644

capture_rollback_state "$DEST_LIBRESPOT_LICENSE"
ensure_persistent_manifest_entry "$DEST_LIBRESPOT_LICENSE" "$fingerprint_librespot_license"
install_staged_file "$STAGING_REAL/librespot-LICENSE" "$DEST_LIBRESPOT_LICENSE" 0644

capture_rollback_state "$DEST_PROJECT_LICENSE"
ensure_persistent_manifest_entry "$DEST_PROJECT_LICENSE" "$fingerprint_project_license"
install_staged_file "$STAGING_REAL/chord-2go-spotify-LICENSE" "$DEST_PROJECT_LICENSE" 0644

capture_rollback_state "$DEST_THIRD_PARTY_NOTICES"
ensure_persistent_manifest_entry "$DEST_THIRD_PARTY_NOTICES" "$fingerprint_third_party_notices"
install_staged_file "$STAGING_REAL/chord-2go-spotify-THIRD_PARTY_NOTICES.md" "$DEST_THIRD_PARTY_NOTICES" 0644

ensure_dir "$CACHE_DIR" 0755

if ! "$SYSTEMCTL" daemon-reload >/dev/null 2>&1; then
    fail "failed to reload systemd"
fi
if ! "$SYSTEMCTL" enable "$SERVICE_NAME" >/dev/null 2>&1; then
    fail "failed to enable $SERVICE_NAME"
fi
if ! "$SYSTEMCTL" restart "$SERVICE_NAME" >/dev/null 2>&1; then
    fail "failed to restart $SERVICE_NAME"
fi
if ! "$SYSTEMCTL" is-active --quiet "$SERVICE_NAME" >/dev/null 2>&1; then
    fail "$SERVICE_NAME did not become active"
fi

remove_legacy_artifacts

if ! mv -f "$NEW_MANIFEST_REAL" "$CURRENT_MANIFEST_REAL"; then
    fail "failed to write install manifest"
fi
if [ -f "$NEW_SERVICE_STATE_REAL" ] && ! mv -f "$NEW_SERVICE_STATE_REAL" "$CURRENT_SERVICE_STATE_REAL"; then
    fail "failed to record original service state"
fi

COMMITTED=1
log_notice "Installed Chord-2go-Spotify stable payload"
printf '%s\n' "$SUCCESS_MARKER"
