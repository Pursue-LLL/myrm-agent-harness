#!/bin/bash

# Resilience Init Script
# Injected into BashExecutor to provide transparent fallback for common commands

# -----------------------------------------------------------------------------
# Global Defense Environment Variables
# -----------------------------------------------------------------------------
# Force non-interactive mode to prevent Agent from hanging on prompts (e.g., npm init)
export CI=1
# Disable telemetry to speed up execution and reduce noise
export NEXT_TELEMETRY_DISABLED=1
export NUXT_TELEMETRY_DISABLED=1
export DO_NOT_TRACK=1
export GATSBY_TELEMETRY_DISABLED=1

# -----------------------------------------------------------------------------
# Smart Env Injection for Package Managers
# -----------------------------------------------------------------------------
_inject_smart_env() {
    local cmd_name="$1"
    shift
    local should_inject=0
    
    for arg in "$@"; do
        if [[ "$arg" == "build" || "$arg" == "dev" || "$arg" == "tsc" || "$arg" == "lint" || "$arg" == "prisma" ]]; then
            should_inject=1
            break
        fi
    done
    
    if [ $should_inject -eq 1 ]; then
        SKIP_ENV_VALIDATION=1 IGNORE_ENV_VALIDATION=1 command $cmd_name "$@"
    else
        command $cmd_name "$@"
    fi
}

# -----------------------------------------------------------------------------
# GitHub Credential & Identity Injection (push / commit)
# -----------------------------------------------------------------------------
# When GITHUB_TOKEN is present (injected by the credential pipeline), HTTPS
# GitHub pushes authenticate automatically, and commits get a resolved identity
# even in freshly-provisioned sandboxes that have no global git config.

_git_is_https_github_remote() {
    case "$1" in
        https://github.com/* | http://github.com/* | https://www.github.com/*) return 0 ;;
        *) return 1 ;;
    esac
}

_git_has_existing_credentials() {
    [ -n "$(command git config --get credential.helper 2>/dev/null)" ] && return 0
    [ -f "$HOME/.git-credentials" ] && return 0
    return 1
}

_git_remote_url() {
    local branch remote
    branch=$(command git symbolic-ref --short HEAD 2>/dev/null)
    remote=$(command git config --get "branch.${branch}.remote" 2>/dev/null)
    [ -z "$remote" ] && remote="origin"
    command git remote get-url "$remote" 2>/dev/null
}

_git_resolve_identity() {
    local name email login cached cname cemail cache_file
    name=$(command git config --get user.name 2>/dev/null) || name=""
    email=$(command git config --get user.email 2>/dev/null) || email=""
    if [ -z "$name" ] || [ -z "$email" ]; then
        if [ -n "$GITHUB_TOKEN" ]; then
            cache_file="${TMPDIR:-/tmp}/myrm_gh_identity"
            if [ -f "$cache_file" ]; then
                cached=$(cat "$cache_file")
                cname="${cached%%|*}"
                cemail="${cached#*|}"
                [ -z "$name" ] && name="$cname"
                [ -z "$email" ] && email="$cemail"
            fi
            if [ -z "$name" ] || [ -z "$email" ]; then
                login=$(curl -fsSL --max-time 5 -H "Authorization: Bearer ${GITHUB_TOKEN}" \
                    https://api.github.com/user 2>/dev/null \
                    | grep -o '"login":"[^"]*"' | head -n 1 | cut -d'"' -f4)
                if [ -n "$login" ]; then
                    [ -z "$name" ] && name="$login"
                    [ -z "$email" ] && email="${login}@users.noreply.github.com"
                    printf '%s|%s' "$name" "$email" > "$cache_file" 2>/dev/null || true
                fi
            fi
        fi
    fi
    [ -z "$name" ] && name="myrm-agent"
    [ -z "$email" ] && email="myrm-agent@users.noreply.github.com"
    printf '%s|%s' "$name" "$email"
}

_git_push() {
    local extra_args=() url
    if [ -n "$GITHUB_TOKEN" ]; then
        url=$(_git_remote_url)
        if _git_is_https_github_remote "$url" && ! _git_has_existing_credentials; then
            # The token is referenced via the environment (never inlined), so it
            # cannot inject shell metacharacters into the credential helper. The
            # helper is host-scoped: it only answers for github.com hosts, so the
            # token is never handed to third-party HTTPS git servers the agent may
            # push to (e.g. a self-hosted GitLab remote or a raw HTTPS URL).
            extra_args+=(-c 'credential.helper=!f() { host=""; while IFS= read -r line; do case "$line" in host=*) host="${line#host=}";; esac; done; if [ "$host" = "github.com" ] || [ "$host" = "www.github.com" ]; then echo username=git; echo password="${GITHUB_TOKEN}"; fi; }; f')
        fi
    fi
    command git "${extra_args[@]}" "$@"
}

_git_commit() {
    if ! command git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        command git "$@"
        return $?
    fi
    if ! command git config --get user.name >/dev/null 2>&1 || ! command git config --get user.email >/dev/null 2>&1; then
        local ident name email
        ident=$(_git_resolve_identity)
        name="${ident%%|*}"
        email="${ident#*|}"
        command git -c "user.name=${name}" -c "user.email=${email}" "$@"
        return $?
    fi
    command git "$@"
}

# -----------------------------------------------------------------------------
# Command Hijacking
# -----------------------------------------------------------------------------

# Git clone fallback
git() {
    if [ "$1" = "clone" ]; then
        # Extract URL from arguments
        local url=""
        local has_depth=0
        for arg in "$@"; do
            if [[ "$arg" == http* ]]; then
                url="$arg"
            fi
            if [[ "$arg" == "--depth"* ]]; then
                has_depth=1
            fi
        done
        
        # Try normal clone first with a timeout
        if timeout 30s command git "$@"; then
            return 0
        else
            local exit_code=$?
            
            # Tier 1.5: Try with --depth 1 if not already specified
            if [ $has_depth -eq 0 ] && [ -n "$url" ]; then
                echo "[Fallback] Git clone timed out. Attempting shallow clone (--depth 1)..."
                if timeout 30s command git clone --depth 1 "$url"; then
                    echo "[System Note: Original command timed out. The framework automatically fell back to shallow clone (--depth 1) to guarantee success.]"
                    return 0
                fi
            fi
            
            if [ -n "$url" ] && [[ "$url" == *github.com* ]]; then
                echo "[Fallback] Git clone timed out or failed (exit code $exit_code). Attempting zipball download..."
                
                # Extract repo name
                local repo_name=$(basename "$url" .git)
                
                # Download zip
                local curl_args=(-sSL)
                if [ -n "$GITHUB_TOKEN" ]; then
                    curl_args+=(-H "Authorization: token ${GITHUB_TOKEN}")
                fi
                
                if curl "${curl_args[@]}" "${url}/archive/HEAD.zip" -o "${repo_name}.zip" && [ -s "${repo_name}.zip" ]; then
                    echo "[Fallback] Zipball downloaded. Extracting..."
                    unzip -q "${repo_name}.zip"
                    # Find the extracted directory (it might be repo-main or repo-master)
                    local extracted_dir=$(unzip -Z1 "${repo_name}.zip" | head -n 1 | cut -d/ -f1)
                    if [ -n "$extracted_dir" ] && [ -d "$extracted_dir" ]; then
                        mv "$extracted_dir" "${repo_name}"
                        rm "${repo_name}.zip"
                        echo "[System Note: Original command timed out. The framework automatically fell back to zipball download to guarantee success.]"
                        return 0
                    else
                        echo "[Fallback] Failed to find extracted directory."
                        return 1
                    fi
                else
                    echo "[Fallback] Zipball download failed."
                    return 1
                fi
            else
                return $exit_code
            fi
        fi
    elif [ "$1" = "status" ]; then
        local has_format_arg=0
        for arg in "$@"; do
            if [ "$arg" = "--short" ] || [ "$arg" = "-s" ] || [ "$arg" = "--porcelain" ]; then
                has_format_arg=1
                break
            fi
        done
        if [ $has_format_arg -eq 0 ]; then
            shift
            # Force English locale to ensure predictable output if any non-porcelain text leaks
            LC_ALL=C command git status --porcelain -b -uall "$@"
            local exit_code=$?
            if [ $exit_code -eq 0 ]; then
                echo "[System Note: Command was automatically optimized for machine readability]"
            fi
            return $exit_code
        else
            command git "$@"
        fi
    elif [ "$1" = "diff" ]; then
        local has_stat_arg=0
        local has_no_compact_arg=0
        local diff_args=()
        for arg in "$@"; do
            if [ "$arg" = "--stat" ] || [ "$arg" = "--numstat" ] || [ "$arg" = "--shortstat" ] || [ "$arg" = "--name-only" ]; then
                has_stat_arg=1
            fi
            if [ "$arg" = "--no-compact" ]; then
                has_no_compact_arg=1
            elif [ "$arg" != "diff" ]; then
                diff_args+=("$arg")
            fi
        done
        
        if [ $has_stat_arg -eq 0 ] && [ $has_no_compact_arg -eq 0 ]; then
            echo "[System Note: Command was automatically optimized. Showing --stat summary first.]"
            LC_ALL=C command git diff --stat "${diff_args[@]}"
            echo ""
            echo "--- Changes ---"
            LC_ALL=C command git diff "${diff_args[@]}"
            return $?
        else
            LC_ALL=C command git diff "${diff_args[@]}"
        fi
    elif [ "$1" = "push" ]; then
        shift
        _git_push "$@"
    elif [ "$1" = "commit" ]; then
        shift
        _git_commit "$@"
    else
        command git "$@"
    fi
}

# NPM install fallback and smart env injection
npm() {
    if [ "$1" = "install" ] || [ "$1" = "i" ]; then
        if timeout 60s command npm "$@"; then
            return 0
        else
            local exit_code=$?
            echo "[Fallback] npm install timed out or failed (exit code $exit_code). Attempting bun install..."
            if command -v bun >/dev/null 2>&1; then
                if bun install; then
                    echo "[System Note: Original npm install failed. The framework automatically fell back to bun install to guarantee success.]"
                    return 0
                else
                    return 1
                fi
            else
                echo "[Fallback] bun not found. Retrying npm install with clean cache..."
                command npm cache clean --force
                if command npm "$@"; then
                    echo "[System Note: Original npm install failed. The framework automatically cleaned cache and retried to guarantee success.]"
                    return 0
                else
                    return 1
                fi
            fi
        fi
    else
        _inject_smart_env npm "$@"
    fi
}

npx() { _inject_smart_env npx "$@"; }
bun() { _inject_smart_env bun "$@"; }
bunx() { _inject_smart_env bunx "$@"; }
yarn() { _inject_smart_env yarn "$@"; }
pnpm() { _inject_smart_env pnpm "$@"; }

