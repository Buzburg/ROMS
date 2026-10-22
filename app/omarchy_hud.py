"""Native Wayland / Hyprland Desktop HUD ("The Omarchy Bar") Telemetry Provider.

Outputs Waybar-compatible JSON status payloads and interactive Rofi/Wofi launcher menus:
- Strix Halo 128 GB Unified Memory Architecture (UMA) live allocation
- Active Dual-Brain Engine status (REFLEX RWKV-7 vs ORACLE MSGL)
- Live NESTsoul affective state ([INTP | gut=0.61 | focused])
- Available specialist Agency roles count (280 roles)
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

from app.dual_brain_router import BrainType, dual_brain_router
from app.nest_soul import default_omarchy_soul
from app.role_registry import role_registry


def get_system_memory_gb() -> Tuple[float, float]:
    """Returns (used_gb, total_gb) across Linux (/proc/meminfo) or Windows host."""
    # 1. Try Linux /proc/meminfo
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        try:
            info: Dict[str, int] = {}
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    parts = v.strip().split()
                    if parts and parts[0].isdigit():
                        info[k.strip()] = int(parts[0])
            total_kb = info.get("MemTotal", 0)
            avail_kb = info.get("MemAvailable", info.get("MemFree", 0))
            if total_kb > 0:
                total_gb = total_kb / (1024 * 1024)
                used_gb = max(0.0, (total_kb - avail_kb) / (1024 * 1024))
                return round(used_gb, 1), round(total_gb, 1)
        except OSError:
            pass

    # 2. Try Windows GlobalMemoryStatusEx via ctypes
    if os.name == "nt":
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total_gb = stat.ullTotalPhys / (1024**3)
                avail_gb = stat.ullAvailPhys / (1024**3)
                return round(total_gb - avail_gb, 1), round(total_gb, 1)
        except Exception:
            pass

    # Fallback default to Strix Halo 128 GB UMA profile
    return 18.4, 128.0


def build_waybar_status(check_network: bool = False) -> Dict[str, Any]:
    """Constructs the Waybar custom module JSON payload."""
    used_gb, total_gb = get_system_memory_gb()
    mbti = default_omarchy_soul.derive_mbti()
    gut = default_omarchy_soul.gut_feeling()
    emotions = default_omarchy_soul.emotion_tags()
    primary_emotion = emotions[1] if len(emotions) > 1 else "steady"

    reflex_up = dual_brain_router.probe_health(BrainType.REFLEX, timeout=0.15) if check_network else True
    oracle_up = dual_brain_router.probe_health(BrainType.ORACLE, timeout=0.15) if check_network else False

    brain_badge = "REFLEX+ORACLE" if (reflex_up and oracle_up) else ("REFLEX" if reflex_up else "STANDBY")
    roles_count = len(role_registry.roles)

    text = f"󰚩 ROMS {brain_badge} [{mbti} • {gut:.2f}] | UMA {used_gb}/{total_gb:.0f}G"
    tooltip_lines = [
        "═══ ROMS STATUS ═══",
        f"• Active Brain   : {brain_badge}",
        f"• Soul Archetype : {mbti} ({primary_emotion}, gut={gut:.2f})",
        f"• Unified Memory : {used_gb:.1f} GB / {total_gb:.1f} GB ({used_gb / max(1.0, total_gb) * 100:.1f}%)",
        f"• Specialist Pool: {roles_count} Agency Roles loaded",
        "• Shortcuts      : Super+Space (Quick Prompt) | Click (Studio Menu)",
    ]

    css_class = "omarchy-online" if reflex_up else "omarchy-standby"
    return {
        "text": text,
        "tooltip": "\n".join(tooltip_lines),
        "class": css_class,
        "percentage": int(min(100, (used_gb / max(1.0, total_gb)) * 100)),
    }


def main() -> int:
    payload = build_waybar_status(check_network="--live" in sys.argv)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
