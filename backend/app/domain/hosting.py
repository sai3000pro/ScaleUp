"""Recognising a deployment platform from its own environment variables.

A hosted environment arms the same safety checks as `DEPLOYED=true` without
anyone having to remember a flag: the platform already told us where it is.

# @spec OPS-CONFIG-009, OPS-CONFIG-010
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

__all__ = ["CI_SIGNALS", "PLATFORM_SIGNALS", "HostingSignal", "detect_hosting"]


@dataclass(frozen=True, slots=True)
class HostingSignal:
    variable: str  # env var that armed it
    platform: str  # human name


PLATFORM_SIGNALS: tuple[HostingSignal, ...] = (
    HostingSignal("KOYEB_APP_NAME", "Koyeb"),
    HostingSignal("RENDER", "Render"),
    HostingSignal("FLY_APP_NAME", "Fly.io"),
    HostingSignal("RAILWAY_ENVIRONMENT", "Railway"),
    HostingSignal("K_SERVICE", "Cloud Run"),
)

# A CI runner can set any of the above through an adopted workflow or a fork,
# and it is never the thing being deployed.
CI_SIGNALS = ("CI", "GITHUB_ACTIONS")


# @spec OPS-CONFIG-009, OPS-CONFIG-010
def detect_hosting(environ: Mapping[str, str]) -> HostingSignal | None:
    """First recognised platform variable present with a non-empty value.

    None under CI -- a runner with a platform variable set is still a runner,
    not a deployment -- and None when nothing matches.
    """
    if any(environ.get(signal) for signal in CI_SIGNALS):
        return None
    for signal in PLATFORM_SIGNALS:
        if environ.get(signal.variable):
            return signal
    return None
