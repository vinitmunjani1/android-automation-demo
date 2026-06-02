from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ActionLogger:
    def __init__(self, path: str | Path = "logs/actions.csv") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fields = ["timestamp", "action", "target", "status", "details"]
        if not self.path.exists():
            with self.path.open("w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=self.fields).writeheader()

    def log(self, action: str, target: str, status: str = "success", details: Any = "-") -> None:
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": action,
            "target": target,
            "status": status,
            "details": str(details),
        }
        with self.path.open("a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=self.fields).writerow(row)
        print(f"[{row['timestamp']}] {action} | {target} | {status} | {details}")
