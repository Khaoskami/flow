---
name: install
description: Install or set up Ruflo/claude-flow. Use when the user wants to install, set up, or configure claude-flow — globally, locally, with MCP, or run diagnostics.
argument-hint: [--global] [--minimal] [--setup-mcp] [--doctor] [--no-init] [--full] [--version=X.X.X]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Ruflo / claude-flow Installer

Run the installer script at `${CLAUDE_SKILL_DIR}/../../../scripts/install.sh` with the user's requested flags.

## Available Flags

| Flag | Short | Description |
|------|-------|-------------|
| `--global` | `-g` | Install globally via `npm install -g` |
| `--minimal` | `-m` | Skip optional deps (faster, ~15s) |
| `--setup-mcp` | | Auto-configure MCP server for Claude Code |
| `--doctor` | `-d` | Run diagnostics after install |
| `--no-init` | | Skip project initialization |
| `--full` | `-f` | Full setup: global + MCP + doctor |
| `--version=X.X.X` | | Install a specific version (default: latest) |

## Steps

1. **Parse arguments**: Map `$ARGUMENTS` to the appropriate flags. If no arguments are given, run with defaults (local install + init).

2. **Run the installer**: Execute the script with the resolved flags:
   ```bash
   bash scripts/install.sh $ARGUMENTS
   ```

3. **Handle errors**: If the script fails, read the output and help the user resolve the issue (missing Node.js, npm permissions, network problems, etc.).

4. **Verify**: After installation, confirm it worked:
   - If global: `ruflo --version`
   - If local: `npx ruflo@latest --version`

## Examples

```
/install                     # Default: local install + init
/install --full              # Global + MCP + doctor
/install --global --minimal  # Fast global install, no optional deps
/install --setup-mcp         # Just configure MCP server
/install --version=3.5.0     # Pin to a specific version
```

## Curl Alternative

Users can also install without Claude Code by running directly in their terminal:
```bash
curl -fsSL https://cdn.jsdelivr.net/gh/ruvnet/claude-flow@main/scripts/install.sh | bash
curl -fsSL https://cdn.jsdelivr.net/gh/ruvnet/claude-flow@main/scripts/install.sh | bash -s -- --full
```
