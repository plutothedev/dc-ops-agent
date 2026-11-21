# (C)
"""Read-only queries over the fictional site topology and scenario files."""
from __future__ import annotations

import json
import os
from pathlib import Path

MIN_MINUTES = 1
MAX_MINUTES = 1440


class DataDirNotFound(FileNotFoundError):
    """The data folder (site, scenarios, runbooks) is not where it should be."""


def data_dir() -> Path:
    """DCOPS_DATA when set, else the repo's data/ folder (found from an editable install)."""
    env = os.environ.get("DCOPS_DATA")
    root = Path(env) if env else Path(__file__).resolve().parents[2] / "data"
    if not root.is_dir():
        raise DataDirNotFound(
            f'data folder not found at {root}: install with "pip install -e ." from a clone, or set DCOPS_DATA'
        )
    return root


def list_scenarios(data_path: Path | None = None) -> list[str]:
    root = Path(data_path) if data_path else data_dir()
    return sorted(p.stem for p in (root / "scenarios").glob("*.json"))


class Site:
    def __init__(self, scenario_name: str, scenario: dict, topology: list[dict]):
        self.name = scenario_name
        self.scenario = scenario
        overrides = scenario.get("status_overrides", {})
        self._equipment: dict[str, dict] = {}
        for e in topology:
            item = dict(e)
            item["downstream"] = list(e.get("downstream", []))
            item["upstream"] = []
            item["status"] = overrides.get(e["id"], e.get("status", "normal"))
            self._equipment[e["id"]] = item
        for e in self._equipment.values():
            for d in e["downstream"]:
                if d in self._equipment:
                    self._equipment[d]["upstream"].append(e["id"])

    @classmethod
    def load(cls, scenario: str, data_path: Path | None = None) -> "Site":
        root = Path(data_path) if data_path else data_dir()
        topo = json.loads((root / "site" / "equipment.json").read_text(encoding="utf-8"))
        path = root / "scenarios" / f"{scenario}.json"
        if not path.is_file():
            raise ValueError(f"unknown scenario: {scenario}")
        sc = json.loads(path.read_text(encoding="utf-8"))
        return cls(scenario, sc, topo["equipment"])

    def all_equipment(self) -> list[dict]:
        return [self.equipment(i) for i in self._equipment]

    def alarms(self) -> list[dict]:
        """Every active alarm, with its operator note under "note" when it has one."""
        keys = ("id", "equipment_id", "severity", "message", "raised_at")
        notes = self.scenario.get("notes", {})
        out = []
        for a in self.scenario["alarms"]:
            item = {k: a[k] for k in keys}
            if notes.get(a["id"]):
                item["note"] = notes[a["id"]]
            out.append(item)
        return out

    def alarm(self, alarm_id: str) -> dict | None:
        for a in self.scenario["alarms"]:
            if a["id"] == alarm_id:
                out = {k: a[k] for k in ("id", "equipment_id", "severity", "message", "raised_at")}
                out["note"] = self.scenario.get("notes", {}).get(alarm_id)
                out["details"] = dict(a.get("details", {}))
                return out
        return None

    def equipment(self, equipment_id: str) -> dict | None:
        e = self._equipment.get(equipment_id)
        if e is None:
            return None
        keys = ("id", "type", "name", "power_path", "status")
        out = {k: e[k] for k in keys}
        out["upstream"] = list(e["upstream"])
        out["downstream"] = list(e["downstream"])
        out["metrics"] = self.metrics(equipment_id)
        return out

    def metrics(self, equipment_id: str) -> list[str]:
        """The sensor metric names this scenario has for one piece of equipment, sorted."""
        prefix = f"{equipment_id}/"
        return sorted(k[len(prefix):] for k in self.scenario.get("sensors", {}) if k.startswith(prefix))

    def sensor_history(self, equipment_id: str, metric: str, minutes: int) -> dict | None:
        series = self.scenario.get("sensors", {}).get(f"{equipment_id}/{metric}")
        if series is None:
            return None
        m = max(MIN_MINUTES, min(MAX_MINUTES, int(minutes)))
        pts = [[a, v] for a, v in series["points"] if a <= m]
        return {
            "equipment_id": equipment_id,
            "metric": metric,
            "unit": series["unit"],
            "normal_range": list(series["normal_range"]),
            "points": pts,
        }
