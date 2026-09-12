"""Live MCP smoke test: verify all 4 design servers connect with vaulted keys.

Usage (from the repo root or anywhere):
    python tests/mcp_smoke_live.py            # pretty output
    CLAUME_LIVE_MCP=1 python -m unittest tests.test_v2.TestMCPLiveConnectivity -v

Checks:
  1. All 4 design servers are configured
  2. Each one completes the MCP initialize handshake
     (vault keys like TWENTY_FIRST_API_KEY are injected automatically)
  3. Each one answers tools/list with a non-empty tool catalog
  4. Each one answers at least one real tool call (read-only probe)
  5. The full Link System pipeline runs with all 4 stages OK

Exit code 0 = all green. Run inside claume as: /doctor (live probe)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claume import keyvault, mcp  # noqa: E402

GREEN = "\033[38;5;46m"
RED = "\033[38;5;203m"
GOLD = "\033[38;5;220m"
GREY = "\033[38;5;245m"
RESET = "\033[0m"
BOLD = "\033[1m"


def _c(text: str, color: str) -> str:
    if sys.stdout.isatty():
        return f"{color}{text}{RESET}"
    return text


# Read-only probe per server: (tool, args) that must succeed.
PROBES = {
    "atomic-shadcnspace": ("searchBlocks", {"query": "hero"}),
    "uidiscovery-21st": ("search", {"query": "dashboard"}),
    "animation-motion": ("search_motion_docs", {"query": "animation", "framework": "react", "limit": 3}),
    "microinteractions-reactbits": ("list_categories", {}),
}


def main() -> int:
    print(_c("\nclaume live MCP smoke test", BOLD))
    print(_c("=" * 46, GREY))

    # 0) vault status
    keys = keyvault.list_keys()
    if keys.get("TWENTY_FIRST_API_KEY"):
        print(_c(f"[OK] vault: TWENTY_FIRST_API_KEY present ({keys['TWENTY_FIRST_API_KEY']})", GREEN))
    else:
        print(_c("[!!] vault: TWENTY_FIRST_API_KEY missing — 21st.dev will fail", GOLD))

    servers_cfg = mcp._servers_from_config()
    failures: list[str] = []

    expected = {"atomic-shadcnspace", "uidiscovery-21st", "animation-motion", "microinteractions-reactbits"}
    missing = expected - set(servers_cfg)
    if missing:
        for name in sorted(missing):
            print(_c(f"[!!] {name}: NOT CONFIGURED", GOLD))
        failures.extend(sorted(missing))

    # 1) handshake + tools/list
    catalogs = {}
    for name in sorted(expected & set(servers_cfg)):
        try:
            srv = mcp.get_server(name)
            tools = srv.list_tools()
            catalogs[name] = [t.get("name", "?") for t in tools]
            print(_c(f"[OK] {name}: handshake + {len(tools)} tools", GREEN))
        except mcp.MCPError as exc:
            print(_c(f"[FAIL] {name}: {exc}", RED))
            failures.append(name)

    # 2) one real read-only call per server
    for name, (tool, args) in PROBES.items():
        if name in failures or tool not in catalogs.get(name, []):
            if name not in failures:
                print(_c(f"[SKIP] {name}: probe tool '{tool}' not in catalog", GOLD))
            continue
        try:
            out = mcp.call_tool(name, tool, args)
            preview = " ".join(str(out).split())[:80]
            print(_c(f"[OK] {name}::{tool} -> {preview}", GREEN))
        except mcp.MCPError as exc:
            print(_c(f"[FAIL] {name}::{tool}: {exc}", RED))
            failures.append(f"{name}::{tool}")

    # 3) full pipeline
    try:
        report, is_err = mcp.design_pipeline("smoke test dashboard hero", Path("."))
        stages_ok = report.count("✓")
        if is_err or stages_ok < 4:
            print(_c(f"[FAIL] Link System pipeline: only {stages_ok}/4 stages OK", RED))
            failures.append("pipeline")
        else:
            print(_c(f"[OK] Link System pipeline: 4/4 stages", GREEN))
    except Exception as exc:
        print(_c(f"[FAIL] pipeline crashed: {exc}", RED))
        failures.append("pipeline")
    finally:
        mcp.shutdown_all()

    print(_c("=" * 46, GREY))
    if failures:
        print(_c(f"RESULT: {len(failures)} failure(s): {', '.join(failures)}", RED))
        return 1
    print(_c("RESULT: all 4 MCP servers + pipeline green", GREEN))
    return 0


if __name__ == "__main__":
    sys.exit(main())
