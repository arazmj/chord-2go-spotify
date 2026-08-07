#!/bin/sh
set -eu

umask 022

ROOT_PREFIX=${CHORD_2GO_SPOTIFY_ROOT:-}
SYSTEMCTL=${SYSTEMCTL:-systemctl}
LOGGER_CMD=${LOGGER_CMD:-logger}

SERVICE_NAME=librespot.service
STATE_DIR=/var/lib/chord-2go-spotify
BACKUP_DIR=$STATE_DIR/backups
MANIFEST_PATH=$STATE_DIR/manifest.tsv
SERVICE_STATE_PATH=$STATE_DIR/original-service-state.env
CACHE_DIR=/var/cache/chord-2go-spotify

DEST_DOC_DIR=/usr/local/share/doc/chord-2go-spotify
AUDIO_SERVICE=/etc/systemd/system/librespot.service
AUDIO_HELPER=/usr/local/sbin/librespot-audio

ORIGINAL_SERVICE_PRESENT=0
ORIGINAL_SERVICE_ENABLED=0
ORIGINAL_SERVICE_ACTIVE=0

log_notice()
{
    printf '%s\n' "$*" >&2
    "$LOGGER_CMD" -t chord-2go-spotify-uninstall "$*" >/dev/null 2>&1 || true
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

restore_saved_copy()
{
    saved=$1
    dest=$2
    dest_real=$(resolve_path "$dest")
    parent=$(dirname "$dest_real")
    tmp=$parent/.chord-2go-spotify-uninstall.$$.tmp
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

remove_known_tree()
{
    case "$1" in
        /var/lib/chord-2go-spotify|/var/cache/chord-2go-spotify)
            rm -rf "$(resolve_path "$1")"
            ;;
        *)
            log_notice "WARNING: refusing to remove unexpected path $1"
            ;;
    esac
}

remove_created_file()
{
    dest=$1
    expected_fingerprint=$2
    dest_real=$(resolve_path "$dest")
    if ! path_exists "$dest_real"; then
        return 0
    fi
    if [ -z "$expected_fingerprint" ]; then
        log_notice "WARNING: leaving $dest because its fingerprint is unknown"
        return 0
    fi
    if current_fingerprint=$(fingerprint_for "$dest_real" 2>/dev/null); then
        if [ "$current_fingerprint" = "$expected_fingerprint" ]; then
            remove_known_file "$dest"
            return 0
        fi
    fi
    log_notice "WARNING: leaving modified file $dest"
}

load_original_service_state()
{
    [ -f "$SERVICE_STATE_REAL" ] || return 0

    while IFS='=' read -r key value; do
        case "$value" in
            1)
                value=1
                ;;
            *)
                value=0
                ;;
        esac
        case "$key" in
            present)
                ORIGINAL_SERVICE_PRESENT=$value
                ;;
            enabled)
                ORIGINAL_SERVICE_ENABLED=$value
                ;;
            active)
                ORIGINAL_SERVICE_ACTIVE=$value
                ;;
        esac
    done < "$SERVICE_STATE_REAL"
}

restore_original_service_state()
{
    audio_service_real=$(resolve_path "$AUDIO_SERVICE")

    if [ "$ORIGINAL_SERVICE_PRESENT" -ne 1 ]; then
        "$SYSTEMCTL" disable "$SERVICE_NAME" >/dev/null 2>&1 || true
        "$SYSTEMCTL" stop "$SERVICE_NAME" >/dev/null 2>&1 || true
        return 0
    fi

    if ! path_exists "$audio_service_real"; then
        log_notice "WARNING: original librespot.service file was not restored"
        return 0
    fi

    if [ "$ORIGINAL_SERVICE_ENABLED" -eq 1 ]; then
        "$SYSTEMCTL" enable "$SERVICE_NAME" >/dev/null 2>&1 || log_notice "WARNING: failed to re-enable $SERVICE_NAME"
    else
        "$SYSTEMCTL" disable "$SERVICE_NAME" >/dev/null 2>&1 || true
    fi

    if [ "$ORIGINAL_SERVICE_ACTIVE" -eq 1 ]; then
        "$SYSTEMCTL" start "$SERVICE_NAME" >/dev/null 2>&1 || log_notice "WARNING: failed to restart $SERVICE_NAME"
    else
        "$SYSTEMCTL" stop "$SERVICE_NAME" >/dev/null 2>&1 || true
    fi
}

MANIFEST_REAL=$(resolve_path "$MANIFEST_PATH")
BACKUP_REAL=$(resolve_path "$BACKUP_DIR")
SERVICE_STATE_REAL=$(resolve_path "$SERVICE_STATE_PATH")
AUDIO_HELPER_REAL=$(resolve_path "$AUDIO_HELPER")

load_original_service_state

"$SYSTEMCTL" disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
if [ -x "$AUDIO_HELPER_REAL" ]; then
    "$AUDIO_HELPER_REAL" release >/dev/null 2>&1 || true
fi

if [ -f "$MANIFEST_REAL" ]; then
    while IFS='|' read -r path kind backup fingerprint; do
        [ -n "$path" ] || continue
        case "$kind" in
            backup)
                if [ "$backup" = "-" ] || [ ! -f "$BACKUP_REAL/$backup" ]; then
                    log_notice "WARNING: missing backup for $path"
                else
                    restore_saved_copy "$BACKUP_REAL/$backup" "$path" || log_notice "WARNING: failed to restore $path"
                fi
                ;;
            created)
                remove_created_file "$path" "${fingerprint:-}"
                ;;
            *)
                log_notice "WARNING: ignoring unknown manifest action for $path"
                ;;
        esac
    done < "$MANIFEST_REAL"
else
    log_notice "No install manifest found; cleaning only dedicated state and cache"
fi

"$SYSTEMCTL" daemon-reload >/dev/null 2>&1 || true
restore_original_service_state

remove_known_dir_if_empty "$DEST_DOC_DIR"
remove_known_tree "$CACHE_DIR"
remove_known_tree "$STATE_DIR"

log_notice "Chord-2go-Spotify uninstall complete"
