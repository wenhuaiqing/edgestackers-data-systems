"""The decision layer: model outputs put to work, behind the quality gate.

A deliberately plain short-horizon mean-reversion strategy on one-minute
consolidated bars. The point is not the strategy; it is that a strategy is a
consumer of the data with its own failure modes, so the data's defects can be
priced in its own currency - orders, positions and P&L.

  signal     z = (close - mean) / sd over the previous 30 published closes
  live (v1)  enter at |z| > 2.0 against the move, only when the distance to
             the mean is at least 2.5 spreads; exit at the mean or after 20
             minutes
  shadow(v2) as v1 at |z| > 2.2, and only on a bar carrying at least half the
             window's median volume
  sizing     A$50,000 a unit at the decision price, round lots of 100
  execution  at the next minute's consolidated book: buy at the ask, sell at
             the bid; 0.5 bp brokerage; flat at 15:59 every day
  gate       blocked - no orders for the instrument that minute
             degraded - positions capped at half a unit
  risk       a desk loss limit of A$20,000 marked to market: breach it and
             everything is flattened and the desk stops for the day. Marked on
             published prices - which is why one bad print can stop a desk.

Point in time: decisions see bars as first published, never as restated. A
backtest on restated bars is a backtest on information the desk did not have.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.app.pipeline import reference as ref

UNIT_NOTIONAL = 50_000.0
BROKERAGE_BP = 0.5
WINDOW = 30


@dataclass(frozen=True)
class Model:
    model_id: str
    stage: str
    entry_z: float
    exit_z: float
    volume_filter: float | None
    description: str


MAX_HOLD_MINUTES = 20
DESK_LOSS_LIMIT = 20_000.0
MIN_EDGE_SPREADS = 2.5

MODELS = [
    Model("mr-v1", "live", 2.0, 0.25, None,
          "Enter against a move beyond 2.0 sd of the last 30 minutes when the mean is at least 2.5 spreads away; "
          "exit at the mean or after 20 minutes."),
    Model("mr-v2", "shadow", 2.2, 0.25, 0.5,
          "As v1 at 2.2 sd, and only on a bar carrying at least half the window's median volume."),
]
MODEL_BY_ID = {m.model_id: m for m in MODELS}


def _minute_grid() -> pd.DatetimeIndex:
    parts = []
    for day in ref.TRADING_DAYS:
        start = pd.Timestamp.combine(day, ref.SESSION_OPEN)
        parts.append(pd.date_range(start, periods=ref.SESSION_SECONDS // 60, freq="min"))
    return parts[0].append(parts[1:])


def run_decisions(bars: pd.DataFrame, book: pd.DataFrame, gate: pd.DataFrame,
                  use_gate: bool = True, models: list[Model] | None = None) -> dict[str, pd.DataFrame]:
    """Run every model, then apply the desk loss limit.

    The limit couples the instruments, so it is found from the desk's
    aggregate equity and the run repeated with the stop in place until no new
    breach appears.
    """
    stops: dict[tuple[str, object], pd.Timestamp] = {}
    for _ in range(4):
        result = _run(bars, book, gate, use_gate, models or MODELS, stops)
        eq = result["equity"]
        desk = eq.groupby(["model_id", "minute"])["equity"].sum().reset_index()
        desk["day"] = desk["minute"].dt.date
        new = False
        for (model_id, day), g in desk.groupby(["model_id", "day"]):
            if (model_id, day) in stops:
                continue
            breach = g[g["equity"] < -DESK_LOSS_LIMIT]
            if len(breach):
                stops[(model_id, day)] = breach["minute"].iloc[0]
                new = True
        if not new:
            break
    result["kill_switch"] = pd.DataFrame({
        "model_id": pd.Series([k[0] for k in stops], dtype="string"),
        "day": pd.Series([pd.Timestamp(k[1]) for k in stops], dtype="datetime64[us]"),
        "triggered_at": pd.Series(list(stops.values()), dtype="datetime64[us]"),
    })
    return result


def _run(bars: pd.DataFrame, book: pd.DataFrame, gate: pd.DataFrame, use_gate: bool,
         models: list[Model], stops: dict) -> dict[str, pd.DataFrame]:
    grid = _minute_grid()
    orders: list[dict] = []
    equity_parts: list[pd.DataFrame] = []

    b = bars.set_index(["instrument_key", "minute"])
    bk = book.set_index(["instrument_key", "minute"])
    gt = gate.set_index(["instrument_key", "minute"])["state"]

    for key in sorted(bars["instrument_key"].dropna().unique()):
        frame = pd.DataFrame(index=grid)
        try:
            kb = b.xs(key, level=0)
        except KeyError:
            continue
        frame["close"] = kb["pub_close"].reindex(grid)
        frame["volume"] = kb["pub_volume"].reindex(grid).fillna(0.0)
        try:
            kbook = bk.xs(key, level=0)
            frame["bid"] = kbook["best_bid"].reindex(grid)
            frame["ask"] = kbook["best_ask"].reindex(grid)
        except KeyError:
            frame["bid"] = np.nan
            frame["ask"] = np.nan
        try:
            frame["gate"] = gt.xs(key, level=0).reindex(grid).fillna("open") if use_gate else "open"
        except KeyError:
            frame["gate"] = "open"
        frame["day"] = frame.index.date
        frame["close"] = frame.groupby("day")["close"].ffill()
        roll = frame.groupby("day")["close"].transform(lambda s: s.shift(1).rolling(WINDOW, min_periods=WINDOW).mean())
        sd = frame.groupby("day")["close"].transform(lambda s: s.shift(1).rolling(WINDOW, min_periods=WINDOW).std())
        frame["z"] = (frame["close"] - roll) / sd
        frame["gap_to_mean"] = (frame["close"] - roll).abs()
        vmed = frame.groupby("day")["volume"].transform(lambda s: s.shift(1).rolling(WINDOW, min_periods=WINDOW).median())
        frame["vol_ok"] = frame["volume"] >= 0.5 * vmed

        closes = frame["close"].to_numpy()
        bids = frame["bid"].to_numpy()
        asks = frame["ask"].to_numpy()
        zs = frame["z"].to_numpy()
        gaps = frame["gap_to_mean"].to_numpy()
        vol_ok = frame["vol_ok"].to_numpy()
        gates = frame["gate"].to_numpy()
        days = frame["day"].to_numpy()
        idx = frame.index
        n = len(frame)
        tick = ref.tick_size(float(np.nanmedian(closes))) if np.isfinite(np.nanmedian(closes)) else 0.01

        for m in models:
            pos = 0.0
            cash = 0.0
            equity = np.zeros(n)
            positions = np.zeros(n)
            pending: tuple[float, str, str, str] | None = None  # (target, reason, gate at decision, decided at)
            opened_at = -1
            stop_at = {day: t for (mid, day), t in stops.items() if mid == m.model_id}
            for i in range(n):
                last_of_day = i == n - 1 or days[i + 1] != days[i]
                # Execute what was decided last minute, at this minute's book.
                if pending is not None:
                    target, reason, g_state, decided = pending
                    qty = target - pos
                    if qty != 0:
                        px = asks[i] if qty > 0 else bids[i]
                        if not np.isfinite(px):
                            px = closes[i] + (tick if qty > 0 else -tick)
                        if np.isfinite(px):
                            notional = abs(qty) * px
                            cost = notional * BROKERAGE_BP / 10_000
                            cash -= qty * px + cost
                            orders.append({
                                "model_id": m.model_id, "instrument_key": key, "decided_at": decided,
                                "executed_at": idx[i], "side": "BUY" if qty > 0 else "SELL", "qty": abs(qty),
                                "price": float(px), "notional": float(notional), "cost": float(cost),
                                "reason": reason, "gate": g_state, "position_after": target,
                            })
                            if pos == 0:
                                opened_at = i
                            pos = target
                    pending = None

                c = closes[i]
                if np.isfinite(c):
                    equity[i] = cash + pos * c
                elif i:
                    equity[i] = equity[i - 1]
                positions[i] = pos

                if last_of_day:
                    if pos != 0:
                        px = bids[i] if pos > 0 else asks[i]
                        if not np.isfinite(px):
                            px = c
                        notional = abs(pos) * px
                        cost = notional * BROKERAGE_BP / 10_000
                        cash += pos * px - cost
                        orders.append({
                            "model_id": m.model_id, "instrument_key": key, "decided_at": idx[i],
                            "executed_at": idx[i], "side": "SELL" if pos > 0 else "BUY", "qty": abs(pos),
                            "price": float(px), "notional": float(notional), "cost": float(cost),
                            "reason": "flat at the close", "gate": gates[i], "position_after": 0.0,
                        })
                        pos = 0.0
                    equity[i] = cash
                    positions[i] = 0.0
                    # Each session's equity starts from zero: the day's P&L is
                    # its last value.
                    cash = 0.0
                    continue

                halt = stop_at.get(days[i])
                if halt is not None and idx[i] >= halt:
                    if pos != 0 and pending is None:
                        pending = (0.0, "kill switch: desk loss limit", gates[i], idx[i])
                    continue
                z = zs[i]
                if not np.isfinite(z) or not np.isfinite(c) or gates[i] == "blocked":
                    continue
                unit = max(100.0, round(UNIT_NOTIONAL / c / 100.0) * 100.0)
                cap = 0.5 if gates[i] == "degraded" else 1.0
                spread = asks[i] - bids[i] if np.isfinite(asks[i]) and np.isfinite(bids[i]) and asks[i] > bids[i] else 2 * tick
                target, reason = pos, ""
                if pos == 0:
                    ok = (m.volume_filter is None or bool(vol_ok[i])) and gaps[i] >= MIN_EDGE_SPREADS * spread
                    if z > m.entry_z and ok:
                        target, reason = -round(unit * cap / 100.0) * 100.0, "enter short"
                    elif z < -m.entry_z and ok:
                        target, reason = round(unit * cap / 100.0) * 100.0, "enter long"
                elif (pos > 0 and z > -m.exit_z) or (pos < 0 and z < m.exit_z):
                    target, reason = 0.0, "exit"
                elif i - opened_at >= MAX_HOLD_MINUTES:
                    target, reason = 0.0, "exit"
                elif cap < 1.0 and abs(pos) > unit * cap * 1.05:
                    target, reason = np.sign(pos) * round(unit * cap / 100.0) * 100.0, "cut to the gate's cap"
                if target != pos:
                    pending = (target, reason, gates[i], idx[i])

            equity_parts.append(pd.DataFrame({
                "model_id": m.model_id, "instrument_key": key, "minute": idx,
                "equity": equity, "position": positions, "close": closes,
            }))

    orders_df = pd.DataFrame(orders)
    equity_df = pd.concat(equity_parts, ignore_index=True) if equity_parts else pd.DataFrame()
    return {"orders": orders_df, "equity": equity_df}


def summarise(result: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Per model per day: P&L, orders, round trips, hit rate, drawdown."""
    eq = result["equity"]
    orders = result["orders"]
    if eq.empty:
        return pd.DataFrame()
    eq = eq.copy()
    eq["day"] = eq["minute"].dt.date
    rows = []
    for (model_id, day), g in eq.groupby(["model_id", "day"]):
        book_eq = g.groupby("minute")["equity"].sum()
        pnl = float(book_eq.iloc[-1])
        path = book_eq.to_numpy()
        drawdown = float(np.max(np.maximum.accumulate(np.maximum(path, 0)) - path)) if len(path) else 0.0
        o = orders[(orders["model_id"] == model_id) & (orders["executed_at"].dt.date == day)] if len(orders) else orders
        exits = o[o["reason"].isin(["exit", "flat at the close"])] if len(o) else o
        rows.append({
            "model_id": model_id, "day": day, "pnl": round(pnl, 2), "orders": int(len(o)),
            "round_trips": int(len(exits)), "max_drawdown": round(drawdown, 2),
            "peak_equity": round(float(path.max()), 2) if len(path) else 0.0,
            "costs": round(float(o["cost"].sum()), 2) if len(o) else 0.0,
            "gross_notional": round(float(o["notional"].sum()), 2) if len(o) else 0.0,
        })
    return pd.DataFrame(rows)


def round_trips(orders: pd.DataFrame) -> pd.DataFrame:
    """Pair entries with the exit that closes them; P&L per round trip."""
    if orders.empty:
        return pd.DataFrame()
    out = []
    for (model_id, key), g in orders.sort_values("executed_at").groupby(["model_id", "instrument_key"]):
        pos, cash, opened = 0.0, 0.0, None
        for _, o in g.iterrows():
            signed = o["qty"] if o["side"] == "BUY" else -o["qty"]
            if pos == 0 and signed != 0:
                opened, cash = o, 0.0
            cash -= signed * o["price"] + o["cost"]
            pos += signed
            if abs(pos) < 1e-9 and opened is not None:
                out.append({"model_id": model_id, "instrument_key": key, "opened_at": opened["executed_at"],
                            "closed_at": o["executed_at"], "direction": "long" if opened["side"] == "BUY" else "short",
                            "pnl": round(cash, 2)})
                opened, pos = None, 0.0
    return pd.DataFrame(out)
