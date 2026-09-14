"""Editable settings (a tab in the rate-store Google Sheet).

Only the golden-time targets live here so far. They're stored rather than
hardcoded because they're the supervisor's aim, not a measurement - they will
be tuned, and tuning them shouldn't need a code change and a redeploy.

Each setting can be set globally (`scope` = "default") or overridden for one
hotel (`scope` = the hotel code); `golden_settings_for()` resolves
hotel -> default -> the seed value in config.py, in that order.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from hk_dashboard.config import (
    GOLDEN_SETTING_KEYS,
    SETTINGS_HEADER,
    SETTINGS_WORKSHEET,
)
from hk_dashboard.sheets_client import fetch_rate_store_worksheet

DEFAULT_SCOPE = "default"


@dataclass(frozen=True)
class GoldenSettings:
    hotel: str
    checkout_minutes: float
    stayover_minutes: float
    extra_tasks_minutes: float
    is_hotel_specific: bool

    def room_minutes(self, checkout_count: float, stayover_count: float) -> float:
        return checkout_count * self.checkout_minutes + stayover_count * self.stayover_minutes


def _ensure_header(ws) -> None:
    first_row = ws.row_values(1)
    if first_row == SETTINGS_HEADER:
        return
    if not first_row:
        ws.update("A1", [SETTINGS_HEADER])
        return
    all_values = ws.get_all_values()
    old_header, old_rows = all_values[0], all_values[1:]
    migrated = [
        [dict(zip(old_header, row)).get(col, "") for col in SETTINGS_HEADER] for row in old_rows
    ]
    ws.clear()
    ws.update("A1", [SETTINGS_HEADER] + migrated)


def read_settings(spreadsheet_id: str) -> pd.DataFrame:
    ws = fetch_rate_store_worksheet(spreadsheet_id, SETTINGS_WORKSHEET)
    _ensure_header(ws)
    df = pd.DataFrame(ws.get_all_records(), columns=SETTINGS_HEADER)
    if df.empty:
        return df
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df[df["value"].notna()].reset_index(drop=True)


def _resolve(settings_df: pd.DataFrame, hotel: str, key: str) -> tuple[float, bool]:
    """Returns (value, came_from_a_hotel_specific_row)."""
    fallback = GOLDEN_SETTING_KEYS[key]
    if settings_df.empty:
        return fallback, False

    hotel_row = settings_df[(settings_df["scope"] == hotel) & (settings_df["key"] == key)]
    if not hotel_row.empty:
        return float(hotel_row.iloc[0]["value"]), True

    default_row = settings_df[(settings_df["scope"] == DEFAULT_SCOPE) & (settings_df["key"] == key)]
    if not default_row.empty:
        return float(default_row.iloc[0]["value"]), False

    return fallback, False


def golden_settings_for(settings_df: pd.DataFrame, hotel: str) -> GoldenSettings:
    checkout, checkout_specific = _resolve(settings_df, hotel, "golden_checkout_min")
    stayover, stayover_specific = _resolve(settings_df, hotel, "golden_stayover_min")
    extras, extras_specific = _resolve(settings_df, hotel, "extra_tasks_min")
    return GoldenSettings(
        hotel=hotel,
        checkout_minutes=checkout,
        stayover_minutes=stayover,
        extra_tasks_minutes=extras,
        is_hotel_specific=any([checkout_specific, stayover_specific, extras_specific]),
    )


def upsert_settings(spreadsheet_id: str, scope: str, values: dict[str, float]) -> pd.DataFrame:
    """Write one scope's settings, replacing that scope's existing rows."""
    existing = read_settings(spreadsheet_id)
    new_df = pd.DataFrame(
        [{"scope": scope, "key": key, "value": value} for key, value in values.items()]
    )

    if existing.empty:
        merged = new_df
    else:
        keyed = existing.set_index(["scope", "key"])
        new_keyed = new_df.set_index(["scope", "key"])
        keyed = keyed[~keyed.index.isin(new_keyed.index)]
        merged = pd.concat([keyed, new_keyed]).reset_index()

    merged = merged.sort_values(["scope", "key"]).reset_index(drop=True)
    _write_settings(spreadsheet_id, merged)
    return merged


def delete_scope(spreadsheet_id: str, scope: str) -> pd.DataFrame:
    """Drop one hotel's overrides so it falls back to the global defaults."""
    existing = read_settings(spreadsheet_id)
    if existing.empty:
        return existing
    remaining = existing[existing["scope"] != scope].reset_index(drop=True)
    _write_settings(spreadsheet_id, remaining)
    return remaining


def _write_settings(spreadsheet_id: str, df: pd.DataFrame) -> None:
    ws = fetch_rate_store_worksheet(spreadsheet_id, SETTINGS_WORKSHEET)
    frame = df.reindex(columns=SETTINGS_HEADER)
    rows = [
        ["" if pd.isna(v) else str(v) for v in row]
        for row in frame.itertuples(index=False, name=None)
    ]
    ws.clear()
    ws.update("A1", [SETTINGS_HEADER] + rows)
