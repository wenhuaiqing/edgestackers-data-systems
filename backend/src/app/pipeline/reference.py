"""Fixed reference for the synthetic tape: venues, instruments, sessions, and
the defects seeded into the feeds.

Everything that the generator injects and the pipeline must find is declared
here, once, so the tests can assert that each defect is caught without the
test knowing how the generator works.

Instrument codes are four letters on purpose: no real listing uses them, so
no figure on screen can be mistaken for a quote of a real security.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

SEED = 20261012

# Exchange local time (Sydney, AEDT in October). Stored naive; labelled on
# screen.
TZ_LABEL = "AEDT"
SESSION_OPEN = time(10, 0, 0)
SESSION_CLOSE = time(16, 0, 0)
SESSION_SECONDS = 6 * 3600

TRADING_DAYS: list[date] = [date(2026, 10, 12) + timedelta(days=i) for i in range(5)]


@dataclass(frozen=True)
class Venue:
    code: str
    label: str
    kind: str
    median_latency_ms: float


VENUES: dict[str, Venue] = {
    "PRIMARY": Venue("PRIMARY", "Primary exchange (direct feed)", "direct", 1.2),
    "ALT": Venue("ALT", "Alternative venue (direct feed)", "direct", 2.5),
    # A redundant feed of PRIMARY from a market-data vendor: later, a
    # different shape, its own sequence numbers - and the backup that fills
    # PRIMARY's gaps.
    "VENDOR": Venue("VENDOR", "Vendor feed of the primary exchange (redundant)", "vendor", 180.0),
}


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    symbol: str
    sector: str
    base_price: float
    daily_vol: float          # fraction of price, one session
    primary_rate: float       # trades per second on PRIMARY
    alt_share: float          # ALT trades as a share of PRIMARY's


INSTRUMENTS: list[Instrument] = [
    Instrument("INS-001", "ALBA", "Materials", 18.40, 0.018, 0.050, 0.42),
    Instrument("INS-002", "BRIG", "Financials", 32.10, 0.011, 0.060, 0.38),
    Instrument("INS-003", "CALD", "Energy", 7.85, 0.024, 0.040, 0.35),
    Instrument("INS-004", "DUNE", "Industrials", 12.30, 0.014, 0.035, 0.30),
    Instrument("INS-005", "EYRE", "Materials", 3.12, 0.028, 0.045, 0.40),
    Instrument("INS-006", "FLIN", "Health care", 54.60, 0.012, 0.030, 0.33),
    Instrument("INS-007", "GAWL", "Consumer", 9.42, 0.016, 0.032, 0.36),
    Instrument("INS-008", "HUON", "Consumer", 21.75, 0.013, 0.028, 0.31),
    Instrument("INS-009", "IRON", "Materials", 41.20, 0.020, 0.055, 0.44),
    Instrument("INS-010", "JARR", "Utilities", 6.18, 0.010, 0.025, 0.28),
    Instrument("INS-011", "KOSC", "Technology", 15.90, 0.022, 0.038, 0.41),
    Instrument("INS-012", "LACH", "Real estate", 4.55, 0.012, 0.030, 0.30),
    Instrument("INS-013", "MURR", "Energy", 4.21, 0.026, 0.042, 0.37),
    Instrument("INS-014", "NAMO", "Financials", 27.35, 0.010, 0.048, 0.39),
    Instrument("INS-015", "OTWA", "Industrials", 11.05, 0.015, 0.027, 0.29),
    Instrument("INS-016", "PEEL", "Telecoms", 3.86, 0.011, 0.033, 0.32),
    Instrument("INS-017", "QUIL", "Technology", 68.90, 0.021, 0.036, 0.43),
    Instrument("INS-018", "ROPE", "Health care", 23.40, 0.014, 0.026, 0.30),
    Instrument("INS-019", "SNOW", "Consumer", 8.66, 0.017, 0.031, 0.34),
    Instrument("INS-020", "TWEE", "Utilities", 13.70, 0.009, 0.024, 0.27),
]

INSTRUMENT_BY_SYMBOL = {i.symbol: i for i in INSTRUMENTS}


def tick_size(price: float) -> float:
    return 0.005 if price < 2.0 else 0.01


def at(day: date, hh: int, mm: int, ss: float = 0.0) -> datetime:
    whole = int(ss)
    micro = int(round((ss - whole) * 1_000_000))
    return datetime(day.year, day.month, day.day, hh, mm, whole, micro)


D1, D2, D3, D4, D5 = TRADING_DAYS

# ---- Seeded defects --------------------------------------------------------
# Each is something that happens to real feeds. The pipeline is expected to
# find every one of them from the data alone.

# ALT reconnects at 11:42:10 on 13/10 and re-sends fifteen minutes of trades
# with fresh event ids but the original trade ids.
DUP_BURST = {
    "venue": "ALT", "day": D2,
    "resend_from": at(D2, 11, 27, 10), "resend_to": at(D2, 11, 42, 10),
    "reconnect_at": at(D2, 11, 42, 10.5),
}

# PRIMARY's direct feed drops out; the vendor feed still has the trades.
FEED_GAPS = [
    {"venue": "PRIMARY", "day": D2, "start": at(D2, 14, 5), "end": at(D2, 14, 16)},
    {"venue": "PRIMARY", "day": D3, "start": at(D3, 13, 31), "end": at(D3, 13, 33)},
]

# The vendor's clock runs 1.8 s fast from 09:58 on 14/10: its exchange
# timestamps are late by that much, so its events look as if they arrived
# before they happened.
VENDOR_SKEW = {"venue": "VENDOR", "from": at(D3, 9, 58), "offset_ms": 1800.0}

# A decimal-shift print on PRIMARY, cancelled by the exchange minutes later.
# The build chooses the minute so the live strategy holds the instrument at
# the time, and the direction so the mark goes against it: ten times the
# price against a short, a tenth of it against a long. See
# scripts/build_platform.py.
BAD_PRINT = {
    "venue": "PRIMARY", "day": D3, "symbol": "MURR", "multiplier": 10.0, "qty": 2000,
    "cancel_after_seconds": 513.0,
    "window": (at(D3, 11, 0), at(D3, 13, 30)),
    "default_at": at(D3, 11, 23, 59.412),
}

# A genuine move, confirmed on two independent venues. The price band must
# flag it and then release it - a band that cannot tell this from a bad print
# stops the desk trading the moves that matter.
GENUINE_MOVE = {"day": D2, "symbol": "KOSC", "at": at(D2, 13, 2, 14.0), "jump": 0.09}

# ALT renames qty to size and adds liquidity_flag from the open on 15/10,
# without notice.
SCHEMA_DRIFT = {"venue": "ALT", "stream": "trades", "from_day": D4,
                "renamed": {"qty": "size"}, "added": ["liquidity_flag"]}

# ALT's ask goes stale for half an hour on 16/10 while the bid moves through
# it: a crossed book that a fill simulator would happily trade against.
CROSSED_BOOK = {"venue": "ALT", "day": D5, "start": at(D5, 13, 10), "end": at(D5, 13, 41),
                "symbols": ["IRON", "QUIL", "BRIG", "NAMO"]}

# EYRE becomes EYRA on 16/10. The symbol master update lands at 10:07:30,
# seven and a half minutes after the open.
SYMBOL_CHANGE = {"old": "EYRE", "new": "EYRA", "instrument_id": "INS-005",
                 "effective": D5, "master_arrives": at(D5, 10, 7, 30)}

# Late delivery: share of events that arrive well after they happened.
LATE_SHARE = {"PRIMARY": 0.0005, "ALT": 0.0003, "VENDOR": 0.004}

# How long a bar waits for stragglers before it is published.
WATERMARK_SECONDS = 3.0
