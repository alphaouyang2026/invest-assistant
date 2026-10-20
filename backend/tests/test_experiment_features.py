"""Features and labels (ticket 06a): ratios of a code's research prices up
to the decision day's close, counted over its own bars, and the return
from the next session's open to the open five sessions later, counted over
the calendar."""

from __future__ import annotations

import math
from datetime import timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.experiments import AS_OF, FEATURE_NAMES, FEATURES_V1, feature_table, label_sessions, labels, within_universe
from app.market_data import CLOSE, HIGH, LOW, OPEN, TURNOVER, VOLUME
from app.market_data.frame import CODE, DATE, build_frame
from app.strategies import build_strategy
from tests.frames import NO_BAR, frame_of, sessions
from tests.random_bars import changed_after, frame_from, walk

DAYS = sessions(90)


def test_the_first_feature_set_is_ten_ratios_and_its_label_ends_six_sessions_on() -> None:
    assert FEATURES_V1 == "ohlcv_ratios_v1"
    assert FEATURE_NAMES == ("ret_1", "ret_5", "ret_20", "ret_60", "dist_sma20", "dist_sma60", "vol_20", "range_20",
                             "volume_ratio", "log_turnover_20")
    assert label_sessions() == 6


def test_each_feature_is_worked_out_over_the_bars_the_code_has_up_to_the_day() -> None:
    """A halts two sessions before the day and has no bar the session before
    that: its windows reach back over its bars, skipping both."""
    rows = walk(["A", "B"], DAYS, seed=1)
    halted, missing = DAYS[-3], DAYS[-4]
    rows = [dict(row, **{CLOSE: None}) if (row[CODE], row[DATE]) == ("A", halted) else row
            for row in rows if (row[CODE], row[DATE]) != ("A", missing)]
    day = DAYS[-1]

    table = feature_table(frame_from(rows), [day])

    bars = [row for row in rows if row[CODE] == "A" and row[CLOSE] is not None]
    close, high, low = (np.array([row[column] for row in bars]) for column in (CLOSE, HIGH, LOW))
    volume, turnover = (np.array([row[column] for row in bars]) for column in (VOLUME, TURNOVER))
    expected = {
        "ret_1": close[-1] / close[-2] - 1, "ret_5": close[-1] / close[-6] - 1,
        "ret_20": close[-1] / close[-21] - 1, "ret_60": close[-1] / close[-61] - 1,
        "dist_sma20": close[-1] / close[-20:].mean() - 1, "dist_sma60": close[-1] / close[-60:].mean() - 1,
        "vol_20": np.log(close[-20:] / close[-21:-1]).std(ddof=1),
        "range_20": ((high - low) / close)[-20:].mean(),
        "volume_ratio": volume[-5:].mean() / volume[-20:].mean(),
        "log_turnover_20": math.log(turnover[-20:].mean()),
    }
    assert list(table.columns) == list(FEATURE_NAMES)
    assert table.index.names == [AS_OF, CODE] and list(table.index) == [(day, "A"), (day, "B")]
    assert table.loc[(day, "A")].to_dict() == pytest.approx(expected, rel=1e-12)


def test_the_past_returns_count_back_as_the_short_reversal_does() -> None:
    """`ret_5` is short reversal's past return, halt and missing bar alike."""
    closes = [100.0 + n % 7 for n in range(70)]
    closes[-3], closes[-5] = None, NO_BAR
    frame = frame_of({"A": closes, "B": [50.0 + n % 3 for n in range(70)]}, sessions(70))
    day = sessions(70)[-1]

    table = feature_table(frame, [day])
    signals = build_strategy("short_reversal_v1", {}).evaluate(frame, day, [])

    assert [table.loc[(day, signal.code), "ret_5"] for signal in signals] == [
        signal.indicators["past_return"] for signal in signals]


def test_a_row_missing_any_feature_is_left_out() -> None:
    """B has 60 bars on the last day, one short of `ret_60`; C is halted on
    it; D trades nothing for 20 bars, so its turnover has no log."""
    rows = walk(["A", "B", "C", "D"], DAYS, seed=2)
    rows = [row for row in rows if not (row[CODE] == "B" and row[DATE] < DAYS[-60])]
    rows = [dict(row, **{CLOSE: None}) if (row[CODE], row[DATE]) == ("C", DAYS[-1]) else row for row in rows]
    rows = [dict(row, **{TURNOVER: 0.0}) if row[CODE] == "D" and row[DATE] > DAYS[-21] else row for row in rows]

    table = feature_table(frame_from(rows), [DAYS[-2], DAYS[-1]])

    assert list(table.index) == [(DAYS[-2], "A"), (DAYS[-2], "C"), (DAYS[-2], "D"), (DAYS[-1], "A")]
    assert np.isfinite(table.to_numpy()).all()


def test_bars_after_the_day_change_none_of_its_features() -> None:
    day = DAYS[70]
    rows = walk(["A", "B", "C"], DAYS, seed=3)

    def rewritten(row: dict) -> dict | None:
        if row[CODE] == "C":
            return None  # delisted
        if row[CODE] == "B" and row[DATE] == DAYS[71]:
            return dict(row, **{CLOSE: None})  # halted
        return dict(row, **{column: row[column] * 3 for column in (OPEN, HIGH, LOW, CLOSE, VOLUME, TURNOVER)})

    before, after = (feature_table(frame_from(each), DAYS[:71]) for each in (rows, changed_after(rows, day, rewritten)))

    assert len(before) == 3 * 11
    pd.testing.assert_frame_equal(before, after, check_exact=True)


def test_a_split_after_the_day_moves_none_of_its_features() -> None:
    """A 1:5 split later rescales every research price and volume before
    it; ratios do not move, past rounding."""
    stored = [{CODE: row[CODE], DATE: row[DATE],
               **{column: Decimal(str(round(row[column], 1))) for column in (OPEN, HIGH, LOW, CLOSE)},
               VOLUME: Decimal(int(row[VOLUME])), TURNOVER: Decimal(int(row[TURNOVER])),
               "upper_limit_hit": False, "lower_limit_hit": False, "quality_status": "ok",
               "adjustment_factor": Decimal(1), "ex_rights_type": None} for row in walk(["A"], DAYS, seed=4)]
    split = {CODE: "A", DATE: DAYS[-1] + timedelta(days=3), "adjustment_factor": Decimal("0.2"), "ex_rights_type": 1}

    plain = feature_table(build_frame(stored, []), DAYS[-5:])
    rescaled = feature_table(build_frame(stored, [split]), DAYS[-5:])

    assert build_frame(stored, [split]).data[CLOSE].iloc[-1] != build_frame(stored, []).data[CLOSE].iloc[-1]
    # (build_frame types the code level differently with and without later factors)
    pd.testing.assert_frame_equal(plain, rescaled, rtol=1e-12, check_index_type=False)


def test_the_label_runs_from_the_next_open_to_the_open_five_sessions_later_by_the_calendar() -> None:
    """Opens equal closes here. B has no bar on the fourth session and still
    gets a label over it — the sessions are the calendar's, not B's bars —
    though not from the day before, whose label would start there; C is
    halted on the second and the eighth, so the days whose label starts or
    ends there have none; the last six sessions' labels run past the frame."""
    days = sessions(10)
    frame = frame_of({"A": [100.0 + n for n in range(10)],
                      "B": [200.0, 201.0, 202.0, NO_BAR, 204.0, 205.0, 206.0, 207.0, 208.0, 209.0],
                      "C": [300.0, None, 302.0, 303.0, 304.0, 305.0, 306.0, None, 308.0, 309.0]}, days)

    found = labels(frame, days)

    assert found.index.names == [AS_OF, CODE]
    assert list(found.index) == sorted(found.index)
    assert found.to_dict() == pytest.approx({
        (days[0], "A"): 106 / 101 - 1, (days[1], "A"): 107 / 102 - 1, (days[2], "A"): 108 / 103 - 1,
        (days[3], "A"): 109 / 104 - 1,
        (days[0], "B"): 206 / 201 - 1, (days[1], "B"): 207 / 202 - 1, (days[3], "B"): 209 / 204 - 1,
        (days[2], "C"): 308 / 303 - 1, (days[3], "C"): 309 / 304 - 1,
    }, rel=1e-12)
    assert labels(frame, [days[1]], horizon=2).to_dict() == pytest.approx({
        (days[1], "A"): 104 / 102 - 1, (days[1], "B"): 204 / 202 - 1, (days[1], "C"): 304 / 302 - 1})


def test_only_the_days_universe_is_kept() -> None:
    day, next_day = DAYS[0], DAYS[1]
    index = pd.MultiIndex.from_tuples([(day, "A"), (day, "B"), (next_day, "A"), (next_day, "B")], names=[AS_OF, CODE])
    table = pd.DataFrame({"ret_1": [1.0, 2.0, 3.0, 4.0]}, index=index)

    kept = within_universe(table, {day: ["B", "Z"]})

    assert list(kept.index) == [(day, "B")]
    assert list(within_universe(table["ret_1"], {next_day: ["A", "B"]}).index) == [(next_day, "A"), (next_day, "B")]
