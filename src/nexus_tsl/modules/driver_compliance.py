"""[04] Czas pracy kierowcy i dane z tachografu.

Sprawdza plan jazdy względem kluczowych limitów rozporządzenia (WE) 561/2006:
- maks. 4,5 h jazdy bez przerwy 45 min,
- maks. 9 h jazdy dziennie (10 h dopuszczalne 2x w tygodniu),
- maks. 56 h jazdy tygodniowo, 90 h w dwóch kolejnych tygodniach.
Uproszczenie edukacyjne - nie zastępuje certyfikowanej analizy tachografu.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MAX_CONTINUOUS_H = 4.5
MIN_BREAK_H = 0.75
MAX_DAILY_H = 9.0
MAX_DAILY_EXTENDED_H = 10.0
MAX_EXTENSIONS_PER_WEEK = 2
MAX_WEEKLY_H = 56.0
MAX_FORTNIGHT_H = 90.0


@dataclass
class Activity:
    kind: str     # "drive" | "break" | "rest" | "work"
    hours: float


@dataclass
class ComplianceReport:
    ok: bool
    violations: list[str] = field(default_factory=list)
    driven_today_h: float = 0.0


@dataclass
class DriverLedger:
    driver_id: str
    week_drive_h: float = 0.0
    prev_week_drive_h: float = 0.0
    extensions_used: int = 0


class DriverCompliance:
    def check_day(self, ledger: DriverLedger, day: list[Activity]) -> ComplianceReport:
        violations: list[str] = []
        continuous = driven = 0.0
        for act in day:
            if act.kind == "drive":
                continuous += act.hours
                driven += act.hours
                if continuous > MAX_CONTINUOUS_H + 1e-9:
                    violations.append(f"Jazda ciągła {continuous:.2f} h > {MAX_CONTINUOUS_H} h bez przerwy 45 min")
            elif act.kind in ("break", "rest") and act.hours >= MIN_BREAK_H:
                continuous = 0.0
        limit = MAX_DAILY_H
        if driven > MAX_DAILY_H and ledger.extensions_used < MAX_EXTENSIONS_PER_WEEK:
            limit = MAX_DAILY_EXTENDED_H
        if driven > limit + 1e-9:
            violations.append(f"Dzienny czas jazdy {driven:.2f} h > {limit} h")
        if ledger.week_drive_h + driven > MAX_WEEKLY_H + 1e-9:
            violations.append(f"Tygodniowy czas jazdy przekroczy {MAX_WEEKLY_H} h")
        if ledger.prev_week_drive_h + ledger.week_drive_h + driven > MAX_FORTNIGHT_H + 1e-9:
            violations.append(f"Dwutygodniowy czas jazdy przekroczy {MAX_FORTNIGHT_H} h")
        return ComplianceReport(ok=not violations, violations=violations, driven_today_h=driven)

    def plan_trip(self, drive_hours: float) -> list[Activity]:
        """Rozkłada przejazd na bloki jazdy z obowiązkowymi przerwami i odpoczynkiem dobowym."""
        plan: list[Activity] = []
        left, today = drive_hours, 0.0
        while left > 1e-9:
            block = min(MAX_CONTINUOUS_H, left, MAX_DAILY_H - today)
            plan.append(Activity("drive", round(block, 2)))
            left -= block
            today += block
            if left <= 1e-9:
                break
            if today >= MAX_DAILY_H - 1e-9:
                plan.append(Activity("rest", 11.0))
                today = 0.0
            else:
                plan.append(Activity("break", MIN_BREAK_H))
        return plan
