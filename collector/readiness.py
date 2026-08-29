from __future__ import annotations

from typing import Any


REQUIRED_LUA_HOOKS = ("onUIThreadReceiveMessage", "lua_pcall")


def classify_ready_payload(mode: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Classify only the probe message that is authoritative for READY."""
    if mode == "lua":
        if payload.get("kind") != "hook-status" or payload.get("mode") != "lua":
            return None
        installed = payload.get("installed")
        installed_hooks = (
            sorted({str(name) for name in installed})
            if isinstance(installed, list)
            else []
        )
        missing_hooks = sorted(set(REQUIRED_LUA_HOOKS) - set(installed_hooks))
        return {
            "status": "verified" if not missing_hooks else "rejected",
            "mode": "lua",
            "kind": "hook-status",
            "required_hooks": list(REQUIRED_LUA_HOOKS),
            "installed_hooks": installed_hooks,
            "missing_hooks": missing_hooks,
        }

    if mode == "stability" and payload.get("kind") == "stability-ready":
        module_present = payload.get("modulePresent") is True
        return {
            "status": "verified" if module_present else "rejected",
            "mode": "stability",
            "kind": "stability-ready",
            "module_present": module_present,
        }

    return None
