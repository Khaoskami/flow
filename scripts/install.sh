#!/usr/bin/env bash
# Ruflo / claude-flow installer
# Usage: curl -fsSL https://cdn.jsdelivr.net/gh/ruvnet/claude-flow@main/scripts/install.sh | bash
#        curl -fsSL ... | bash -s -- --full
set -euo pipefail

main() {

# ── Constants ────────────────────────────────────────────────────────────────

PACKAGE_NAME="ruflo"
DEFAULT_VERSION="latest"
NODE_MIN=20
NPM_MIN=9
REPO_URL="https://github.com/ruvnet/claude-flow"

# ── Color / formatting utilities ─────────────────────────────────────────────

USE_COLOR=true
if [ ! -t 1 ] || [ "${NO_COLOR:-}" = "1" ] || [ "${TERM:-}" = "dumb" ]; then
    USE_COLOR=false
fi

if $USE_COLOR; then
    BOLD="\033[1m"
    DIM="\033[2m"
    RED="\033[0;31m"
    GREEN="\033[0;32m"
    YELLOW="\033[0;33m"
    BLUE="\033[0;34m"
    CYAN="\033[0;36m"
    RESET="\033[0m"
else
    BOLD="" DIM="" RED="" GREEN="" YELLOW="" BLUE="" CYAN="" RESET=""
fi

info()    { printf "${BLUE}[INFO]${RESET} %s\n" "$*"; }
success() { printf "${GREEN}  ✓${RESET} %s\n" "$*"; }
warn()    { printf "${YELLOW}  ⚠${RESET} %s\n" "$*" >&2; }
fail()    { printf "${RED}  ✗${RESET} %s\n" "$*" >&2; }
step()    { printf "\n${BOLD}${CYAN}[$1/$TOTAL_STEPS]${RESET} ${BOLD}%s${RESET}\n" "$2"; }

banner() {
    printf "\n"
    printf "${BOLD}${CYAN}"
    printf "  ┌─────────────────────────────────────────┐\n"
    printf "  │         Ruflo / claude-flow              │\n"
    printf "  │         Installer v1.0                   │\n"
    printf "  └─────────────────────────────────────────┘\n"
    printf "${RESET}\n"
}

SPINNER_PID=""
cleanup() {
    if [ -n "$SPINNER_PID" ] && kill -0 "$SPINNER_PID" 2>/dev/null; then
        kill "$SPINNER_PID" 2>/dev/null
        wait "$SPINNER_PID" 2>/dev/null || true
    fi
    tput cnorm 2>/dev/null || true
}
trap cleanup EXIT INT TERM

start_spinner() {
    local msg="${1:-Working...}"
    if ! $USE_COLOR; then
        printf "  %s..." "$msg"
        return
    fi
    tput civis 2>/dev/null || true
    (
        local chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
        local i=0
        while true; do
            printf "\r  ${CYAN}%s${RESET} %s" "${chars:i%${#chars}:1}" "$msg"
            i=$((i + 1))
            sleep 0.1
        done
    ) &
    SPINNER_PID=$!
}

stop_spinner() {
    local ok="${1:-true}"
    if [ -n "$SPINNER_PID" ] && kill -0 "$SPINNER_PID" 2>/dev/null; then
        kill "$SPINNER_PID" 2>/dev/null
        wait "$SPINNER_PID" 2>/dev/null || true
        SPINNER_PID=""
    fi
    tput cnorm 2>/dev/null || true
    if $USE_COLOR; then
        if $ok; then
            printf "\r${GREEN}  ✓${RESET} %s\n" "$2"
        else
            printf "\r${RED}  ✗${RESET} %s\n" "$2"
        fi
    else
        if $ok; then
            printf " done.\n"
        else
            printf " failed.\n"
        fi
    fi
}

version_gte() {
    [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}

# ── Argument parsing ─────────────────────────────────────────────────────────

GLOBAL=false
MINIMAL=false
SETUP_MCP=false
DOCTOR=false
NO_INIT=false
FULL=false
VERSION="$DEFAULT_VERSION"

usage() {
    cat <<EOF
${BOLD}Ruflo / claude-flow Installer${RESET}

${BOLD}USAGE${RESET}
    curl -fsSL .../install.sh | bash
    curl -fsSL .../install.sh | bash -s -- [OPTIONS]
    bash install.sh [OPTIONS]

${BOLD}OPTIONS${RESET}
    -g, --global       Install globally (npm install -g)
    -m, --minimal      Skip optional deps (~15s vs ~35s)
    --setup-mcp        Auto-configure MCP server for Claude Code
    -d, --doctor       Run diagnostics after install
    --no-init          Skip project initialization
    -f, --full         Full setup (global + MCP + doctor)
    --version=X.X.X    Install specific version (default: latest)
    -h, --help         Show this help

${BOLD}EXAMPLES${RESET}
    bash install.sh --full
    bash install.sh --global --minimal
    bash install.sh --version=3.5.0 --setup-mcp
EOF
    exit 0
}

while [ $# -gt 0 ]; do
    case "$1" in
        --global|-g)    GLOBAL=true ;;
        --minimal|-m)   MINIMAL=true ;;
        --setup-mcp)    SETUP_MCP=true ;;
        --doctor|-d)    DOCTOR=true ;;
        --no-init)      NO_INIT=true ;;
        --full|-f)      FULL=true ;;
        --version=*)    VERSION="${1#*=}" ;;
        --help|-h)      usage ;;
        *)              warn "Unknown option: $1 (ignored)" ;;
    esac
    shift
done

if $FULL; then
    GLOBAL=true
    SETUP_MCP=true
    DOCTOR=true
fi

# Calculate total steps for step counter
TOTAL_STEPS=2
$SETUP_MCP && TOTAL_STEPS=$((TOTAL_STEPS + 1))
$NO_INIT   || TOTAL_STEPS=$((TOTAL_STEPS + 1))
$DOCTOR    && TOTAL_STEPS=$((TOTAL_STEPS + 1))
TOTAL_STEPS=$((TOTAL_STEPS + 1))  # summary

# ── Prerequisite checks ─────────────────────────────────────────────────────

check_prerequisites() {
    local current_step=$1
    step "$current_step" "Checking prerequisites"
    local failures=0

    # Node.js
    if command -v node >/dev/null 2>&1; then
        local node_ver
        node_ver="$(node --version 2>/dev/null | sed 's/^v//')"
        local node_major="${node_ver%%.*}"
        if [ -n "$node_major" ] && [ "$node_major" -ge "$NODE_MIN" ] 2>/dev/null; then
            success "Node.js v${node_ver} (>= ${NODE_MIN} required)"
        else
            fail "Node.js v${node_ver} found, but >= ${NODE_MIN} required"
            failures=$((failures + 1))
        fi
    else
        fail "Node.js not found"
        printf "    Install: ${CYAN}https://nodejs.org${RESET} or ${CYAN}nvm install ${NODE_MIN}${RESET}\n"
        failures=$((failures + 1))
    fi

    # npm
    if command -v npm >/dev/null 2>&1; then
        local npm_ver
        npm_ver="$(npm --version 2>/dev/null)"
        local npm_major="${npm_ver%%.*}"
        if [ -n "$npm_major" ] && [ "$npm_major" -ge "$NPM_MIN" ] 2>/dev/null; then
            success "npm v${npm_ver} (>= ${NPM_MIN} required)"
        else
            fail "npm v${npm_ver} found, but >= ${NPM_MIN} required"
            printf "    Run: ${CYAN}npm install -g npm@latest${RESET}\n"
            failures=$((failures + 1))
        fi
    else
        fail "npm not found (should come with Node.js)"
        failures=$((failures + 1))
    fi

    # git
    if command -v git >/dev/null 2>&1; then
        local git_ver
        git_ver="$(git --version 2>/dev/null | awk '{print $3}')"
        success "git v${git_ver}"
    else
        fail "git not found"
        local os_type
        os_type="$(uname -s 2>/dev/null || printf "unknown")"
        case "$os_type" in
            Darwin) printf "    Install: ${CYAN}xcode-select --install${RESET} or ${CYAN}brew install git${RESET}\n" ;;
            Linux)  printf "    Install: ${CYAN}sudo apt-get install git${RESET} or ${CYAN}sudo yum install git${RESET}\n" ;;
            *)      printf "    Install git from: ${CYAN}https://git-scm.com${RESET}\n" ;;
        esac
        failures=$((failures + 1))
    fi

    if [ "$failures" -gt 0 ]; then
        printf "\n"
        fail "$failures prerequisite(s) missing. Please install them and re-run."
        exit 1
    fi
}

# ── Installation ─────────────────────────────────────────────────────────────

do_install() {
    local current_step=$1
    local install_target="${PACKAGE_NAME}@${VERSION}"

    if $GLOBAL; then
        step "$current_step" "Installing ${install_target} globally"
    else
        step "$current_step" "Setting up ${install_target}"
    fi

    local npm_args=""
    if $MINIMAL; then
        npm_args="--omit=optional"
        info "Minimal mode: skipping optional dependencies"
    fi

    local install_output
    local install_ok=true

    if $GLOBAL; then
        start_spinner "Installing ${install_target} globally..."
        if install_output=$(npm install -g ${npm_args} "${install_target}" 2>&1); then
            stop_spinner true "Installed ${install_target} globally"
        else
            stop_spinner false "Installation failed"
            install_ok=false
        fi
    else
        start_spinner "Caching ${install_target}..."
        if install_output=$(npx --yes "${install_target}" --version 2>&1); then
            stop_spinner true "Cached ${install_target}"
        else
            stop_spinner false "Setup failed"
            install_ok=false
        fi
    fi

    if ! $install_ok; then
        printf "\n"
        fail "Installation failed. Output:"
        printf "${DIM}%s${RESET}\n" "$install_output"
        printf "\n"

        # Detect common errors
        if printf "%s" "$install_output" | grep -qi "EACCES\|permission denied"; then
            warn "Permission error. Try one of:"
            printf "    ${CYAN}sudo bash install.sh --global${RESET}\n"
            printf "    Or fix npm permissions: ${CYAN}https://docs.npmjs.com/resolving-eacces-permissions-errors${RESET}\n"
        elif printf "%s" "$install_output" | grep -qi "ENOTFOUND\|EAI_AGAIN\|network"; then
            warn "Network error. Check your internet connection and try again."
        elif printf "%s" "$install_output" | grep -qi "404\|not found\|no matching version"; then
            warn "Version '${VERSION}' not found. Check available versions:"
            printf "    ${CYAN}npm view ${PACKAGE_NAME} versions --json${RESET}\n"
        fi
        exit 1
    fi
}

# ── MCP Setup ────────────────────────────────────────────────────────────────

setup_mcp() {
    local current_step=$1
    step "$current_step" "Configuring MCP server"

    if ! command -v claude >/dev/null 2>&1; then
        warn "Claude Code CLI not found — skipping MCP setup"
        warn "Install Claude Code first, then run:"
        printf "    ${CYAN}claude mcp add claude-flow npx claude-flow@v3alpha mcp start${RESET}\n"
        return
    fi

    start_spinner "Adding claude-flow MCP server..."
    local mcp_output
    if mcp_output=$(claude mcp add claude-flow npx claude-flow@v3alpha mcp start 2>&1); then
        stop_spinner true "MCP server configured"
    else
        stop_spinner false "MCP setup failed"
        warn "You can configure manually later:"
        printf "    ${CYAN}claude mcp add claude-flow npx claude-flow@v3alpha mcp start${RESET}\n"
    fi
}

# ── Init ─────────────────────────────────────────────────────────────────────

run_init() {
    local current_step=$1
    step "$current_step" "Initializing project"

    local init_cmd
    if $GLOBAL; then
        init_cmd="${PACKAGE_NAME} init"
    else
        init_cmd="npx ${PACKAGE_NAME}@${VERSION} init"
    fi

    info "Running: ${init_cmd}"
    if $GLOBAL; then
        "$PACKAGE_NAME" init
    else
        npx --yes "${PACKAGE_NAME}@${VERSION}" init
    fi
}

# ── Doctor ───────────────────────────────────────────────────────────────────

run_doctor() {
    local current_step=$1
    step "$current_step" "Running diagnostics"

    info "Running: npx claude-flow@v3alpha doctor --fix"
    npx --yes claude-flow@v3alpha doctor --fix
}

# ── Summary ──────────────────────────────────────────────────────────────────

print_summary() {
    local current_step=$1
    step "$current_step" "Done!"

    printf "\n"
    printf "${BOLD}${GREEN}"
    printf "  ╭─────────────────────────────────────────╮\n"
    printf "  │   Ruflo installed successfully!          │\n"
    printf "  ╰─────────────────────────────────────────╯\n"
    printf "${RESET}\n"

    printf "  ${BOLD}Next steps:${RESET}\n"
    if $GLOBAL; then
        printf "    ${CYAN}ruflo init --wizard${RESET}           # Interactive setup\n"
        printf "    ${CYAN}ruflo agent spawn${RESET}             # Spawn your first agent\n"
        printf "    ${CYAN}ruflo doctor${RESET}                  # Run diagnostics\n"
    else
        printf "    ${CYAN}npx ruflo@latest init --wizard${RESET}   # Interactive setup\n"
        printf "    ${CYAN}npx ruflo@latest agent spawn${RESET}     # Spawn your first agent\n"
        printf "    ${CYAN}npx ruflo@latest doctor${RESET}          # Run diagnostics\n"
    fi

    if $SETUP_MCP; then
        printf "\n"
        printf "  ${BOLD}MCP:${RESET} Claude Code MCP server configured\n"
    fi

    printf "\n"
    printf "  ${DIM}Docs:   ${REPO_URL}${RESET}\n"
    printf "  ${DIM}Issues: ${REPO_URL}/issues${RESET}\n"
    printf "\n"
}

# ── Main flow ────────────────────────────────────────────────────────────────

banner

local s=1

check_prerequisites $s; s=$((s + 1))
do_install $s;         s=$((s + 1))

if $SETUP_MCP; then
    setup_mcp $s; s=$((s + 1))
fi

if ! $NO_INIT; then
    run_init $s; s=$((s + 1))
fi

if $DOCTOR; then
    run_doctor $s; s=$((s + 1))
fi

print_summary $s

}

main "$@"
