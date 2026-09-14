"""Parse the supervisor's daily WhatsApp room-assignment message.

Room-level assignment exists nowhere else - not in Mews, not in the hours
sheets - only in these messages, which follow a consistent shape:

    Good morning Assigned rooms for HK Kiko
    Check out
    G01,G04,102,103
    Stay over
    B02,G02,G03,101,104
    Cleaning stairs and corridors on the 1th, ground floor, ...
    Collect and wash your towels from the rooms

Parsing rules, all chosen against real messages:

- The name follows "for HK" (falling back to "for"), and is normalised
  through the SAME map the hours sheets use (hk_parser.normalize_name), since
  these messages use the same nicknames. A name that doesn't resolve is
  flagged for the preview, never silently accepted.
- A line belongs to a room list only if every comma-separated token on it
  looks like a room code. Room codes are alphanumeric ("G01", "B02", "102"),
  so this can't assume digits.
- That test is what separates rooms from prose: the trailing instructions
  ("Collect and wash your towels...") sit under the "Stay over" heading with
  no blank line, so position alone would swallow them. They're kept as notes
  rather than dropped - useful later for explaining an outlier - but no
  structured time is inferred from them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from hk_dashboard.hk_parser import normalize_name

NAME_RE = re.compile(r"\bfor\s+HK\s+(.+)$", re.IGNORECASE)
NAME_FALLBACK_RE = re.compile(r"\bfor\s+(.+)$", re.IGNORECASE)
ROOM_CODE_RE = re.compile(r"^[A-Za-z]{0,2}\d{1,4}[A-Za-z]?$")

CHECKOUT_LABELS = ("check out", "checkout", "check-out", "departures", "departure")
STAYOVER_LABELS = ("stay over", "stayover", "stay-over", "stayovers")


class AssignmentParseError(Exception):
    """Raised when a pasted message has no usable room data at all."""


@dataclass
class ParsedAssignment:
    raw_name: str
    employee: str
    name_flagged: bool
    checkout_rooms: list[str] = field(default_factory=list)
    stayover_rooms: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def checkout_count(self) -> int:
        return len(self.checkout_rooms)

    @property
    def stayover_count(self) -> int:
        return len(self.stayover_rooms)

    @property
    def rooms_assigned(self) -> int:
        return self.checkout_count + self.stayover_count


def _label_of(line: str) -> str | None:
    cleaned = line.strip().strip(":").lower()
    if cleaned in CHECKOUT_LABELS:
        return "checkout"
    if cleaned in STAYOVER_LABELS:
        return "stayover"
    return None


def _room_tokens(line: str) -> list[str] | None:
    """Return the line's room codes, or None if it isn't a room list."""
    tokens = [t.strip() for t in re.split(r"[,/;]+", line) if t.strip()]
    if not tokens:
        return None
    if all(ROOM_CODE_RE.match(t) for t in tokens):
        return [t.upper() for t in tokens]
    return None


def _extract_name(lines: list[str]) -> str:
    for line in lines:
        match = NAME_RE.search(line) or NAME_FALLBACK_RE.search(line)
        if match:
            candidate = match.group(1).strip(" .:-")
            if candidate:
                return candidate
    return ""


def parse_assignment_message(message: str) -> ParsedAssignment:
    lines = [line.strip() for line in (message or "").splitlines() if line.strip()]
    if not lines:
        raise AssignmentParseError("The message is empty - paste the WhatsApp text first.")

    raw_name = _extract_name(lines)
    employee, flagged = normalize_name(raw_name) if raw_name else ("", True)

    checkout: list[str] = []
    stayover: list[str] = []
    notes: list[str] = []
    section: str | None = None

    for line in lines:
        label = _label_of(line)
        if label:
            section = label
            continue

        rooms = _room_tokens(line)
        if rooms is not None and section == "checkout":
            checkout.extend(rooms)
            continue
        if rooms is not None and section == "stayover":
            stayover.extend(rooms)
            continue

        # Not a room list: the header line, or free-text instructions that
        # happen to sit under a section heading.
        if NAME_RE.search(line) or NAME_FALLBACK_RE.search(line):
            continue
        notes.append(line)

    if not checkout and not stayover:
        raise AssignmentParseError(
            "No room lists found. Expected a 'Check out' and/or 'Stay over' label with "
            "comma-separated room codes underneath (e.g. G01,G04,102)."
        )

    return ParsedAssignment(
        raw_name=raw_name,
        employee=employee,
        name_flagged=flagged,
        checkout_rooms=checkout,
        stayover_rooms=stayover,
        notes="\n".join(notes),
    )
