"""Data contracts: load the YAML, decide which version governs a partition,
and judge a partition's schema against it.

A partition that breaks its contract is quarantined whole. The pipeline does
not guess what a renamed field means - that is a decision for the people who
consume it, recorded as a new contract version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

from src.settings import settings


@dataclass
class SchemaVerdict:
    ok: bool
    version: int
    missing: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    renamed: dict[str, str] = field(default_factory=dict)

    @property
    def reason(self) -> str:
        parts = []
        if self.missing:
            parts.append(f"required field{'s' if len(self.missing) > 1 else ''} missing: {', '.join(self.missing)}")
        if self.unknown:
            parts.append(f"unknown field{'s' if len(self.unknown) > 1 else ''}: {', '.join(self.unknown)}")
        return "; ".join(parts) or "conforms"


@lru_cache(maxsize=1)
def load_all(contracts_dir: str | None = None) -> dict[str, dict]:
    root = Path(contracts_dir or settings.contracts_dir)
    out: dict[str, dict] = {}
    for path in sorted(root.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        doc["_file"] = f"contracts/{path.name}"
        out[doc["id"]] = doc
    return out


def contract_for(venue: str, stream: str) -> dict:
    return load_all()[f"{venue.lower()}.{stream}"]


# Version 2 of the ALT trades contract, as proposed. It lives here rather than
# in alt.trades.yaml because it is not approved; the platform holds the
# proposal and the approval, and the YAML would change in review.
ALT_TRADES_V2 = {
    "version": 2,
    "status": "proposed",
    "effective_from": "2026-10-15",
    "on_unknown_field": "quarantine_partition",
    "renames": {"size": "qty"},
    "fields_added": {"liquidity_flag": {"type": "string", "required": False, "enum": ["A", "R"]}},
}


def version_fields(contract: dict, version: int) -> dict:
    for v in contract["versions"]:
        if v["version"] == version:
            return v["fields"]
    if contract["id"] == "alt.trades" and version == 2:
        base = dict(next(v for v in contract["versions"] if v["version"] == 1)["fields"])
        qty = base.pop("qty")
        base["size"] = qty
        base.update(ALT_TRADES_V2["fields_added"])
        return base
    raise KeyError(f"{contract['id']} has no version {version}")


def judge(contract: dict, version: int, columns: list[str]) -> SchemaVerdict:
    fields = version_fields(contract, version)
    required = [name for name, spec in fields.items() if spec.get("required")]
    missing = [name for name in required if name not in columns]
    unknown = [c for c in columns if c not in fields]
    renamed = ALT_TRADES_V2["renames"] if (contract["id"] == "alt.trades" and version == 2) else {}
    return SchemaVerdict(ok=not missing and not unknown, version=version,
                         missing=missing, unknown=unknown, renamed=dict(renamed))


def active_version(contract_id: str, day: date, approved: dict[str, list[tuple[int, date]]]) -> int:
    """The newest approved version effective on `day`.

    `approved` maps contract id to (version, effective_from) pairs approved on
    the platform, on top of the versions approved in the YAML.
    """
    contract = load_all()[contract_id]
    candidates = [(v["version"], date.fromisoformat(str(v["effective_from"]))) for v in contract["versions"]
                  if v.get("status") == "approved"]
    candidates += approved.get(contract_id, [])
    live = [v for v, eff in candidates if eff <= day]
    return max(live) if live else 1
