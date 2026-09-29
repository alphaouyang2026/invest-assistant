"""TOPIX market regimes and the intervals they form (issue 04b-B), on
synthetic closes small enough to check by hand."""
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.accounts.regimes import (
    DEFINITION, DEFINITION_VERSION, RegimeFilter, classify, discover, fingerprint, lookback_start,
)


def weekdays(count: int, start: date = date(2020, 1, 6), skip: frozenset[date] = frozenset()) -> list[date]:
    """`count` Monday-to-Friday sessions, leaving out the days in `skip` (holidays)."""
    days, day = [], start
    while len(days) < count:
        if day.weekday() < 5 and day not in skip:
            days.append(day)
        day += timedelta(days=1)
    return days


def closes_on(sessions, values):
    return {day: None if value is None else Decimal(str(value)) for day, value in zip(sessions, values)}


def trend_case(early, late):
    """220 closes whose last day (index 219) has MA200 = 100 exactly.

    c[0..19] = early sets the MA200 twenty sessions back (index 199):
    (20 * early + 180 * 100) / 200, so early 100 → slope 0, 90 → MA 99 and
    slope > 0, 110 → MA 101 and slope < 0. The last two closes add up to 200,
    so MA200[219] = 100 and gap = late / 100 - 1."""
    return [early] * 20 + [100] * 198 + [200 - late, late]


def rising(count):
    """Up every day once the 220 closes are in: the close runs 10% above a rising MA200."""
    return [Decimal(100) + Decimal("0.5") * k for k in range(count)]


def wiggle(count, burst=range(0)):
    """Closes going 100, 101, 100, 101 …; inside `burst` the pair is 99.6, 101.4.
    Every close stays within 1% of MA200 (about 100.5), so the trend is always
    neutral; away from the burst each 20-return window holds the same ten
    rises and ten falls, so RV20 is the same number every day."""
    return [(Decimal("99.6") if k % 2 == 0 else Decimal("101.4")) if k in burst
            else (Decimal(100) if k % 2 == 0 else Decimal(101)) for k in range(count)]


# ---- trend -------------------------------------------------------------

@pytest.mark.parametrize("early, late, trend", [
    (90, 102, "up"),        # gap +2%, slope > 0
    (110, 98, "down"),      # gap -2%, slope < 0
    (90, 101, "neutral"),   # gap exactly +1% is not above 1%
    (110, 99, "neutral"),   # gap exactly -1% is not below -1%
    (100, 102, "neutral"),  # slope exactly 0
    (100, 98, "neutral"),
    (110, 102, "neutral"),  # gap above 1% but the MA is falling
    (90, 98, "neutral"),    # gap below -1% but the MA is rising
])
def test_trend_thresholds_are_strict(early, late, trend):
    sessions = weekdays(220)
    label = classify(sessions, closes_on(sessions, trend_case(early, late)))[219]
    assert label.trend == trend and label.trend_unknown is None
    assert label.ma200 == Decimal(100)
    assert label.gap == Decimal(late) / 100 - 1


def test_equal_thresholds_are_exact_decimals():
    sessions = weekdays(220)
    labels = classify(sessions, closes_on(sessions, trend_case(100, 101)))
    assert labels[219].gap == Decimal("0.01")
    assert labels[219].slope20 == 0
    labels = classify(sessions, closes_on(sessions, trend_case(110, 99)))
    assert labels[219].gap == Decimal("-0.01")


def test_trend_needs_220_closes():
    sessions = weekdays(220)
    labels = classify(sessions, closes_on(sessions, trend_case(90, 102)))
    assert (labels[218].trend, labels[218].trend_unknown) == ("unknown", "warmup")
    assert labels[218].ma200 is not None and labels[218].slope20 is None  # MA200 is there, its slope is not
    assert labels[199].ma200 is not None and labels[198].ma200 is None
    assert labels[219].trend == "up"


# ---- volatility ----------------------------------------------------------

def test_volatility_needs_273_closes_and_equal_to_threshold_is_low():
    sessions = weekdays(300)
    labels = classify(sessions, closes_on(sessions, wiggle(300)))
    assert labels[19].rv20 is None and labels[20].rv20 is not None
    assert (labels[271].vol, labels[271].vol_unknown) == ("unknown", "warmup")
    assert labels[271].rv_threshold is None
    known = labels[272]
    assert known.vol_unknown is None and known.rv20 == known.rv_threshold > 0
    assert known.vol == "low"
    assert {label.vol for label in labels[272:]} == {"low"}


def test_flat_prices_are_low_volatility():
    sessions = weekdays(273)
    label = classify(sessions, closes_on(sessions, [100] * 273))[272]
    assert (label.rv20, label.rv_threshold, label.vol) == (0.0, 0.0, "low")


def test_volatility_above_the_median_of_the_previous_252_days_is_high():
    sessions = weekdays(330)
    labels = classify(sessions, closes_on(sessions, wiggle(330, burst=range(300, 306))))
    assert labels[299].vol == "low"
    assert labels[300].vol == "high" and labels[300].rv20 > labels[300].rv_threshold
    # The burst's six closes stay in the 20-return window for 20 more sessions.
    assert {label.vol for label in labels[300:326]} == {"high"}
    assert labels[326].vol == "low"
    assert {label.trend for label in labels[219:]} == {"neutral"}


# ---- data gaps ------------------------------------------------------------

@pytest.mark.parametrize("bad", [None, 0, -5])
def test_a_missing_or_non_positive_close_makes_both_windows_unknown(bad):
    sessions = weekdays(700)
    values = wiggle(700)
    values[300] = bad
    labels = classify(sessions, closes_on(sessions, values))
    assert labels[300].close is None
    assert (labels[299].trend, labels[299].vol) == ("neutral", "low")
    for i in (300, 519):
        assert (labels[i].trend, labels[i].trend_unknown) == ("unknown", "gap")
    assert labels[520].trend == "neutral"
    for i in (300, 572):
        assert (labels[i].vol, labels[i].vol_unknown) == ("unknown", "gap")
    assert labels[573].vol == "low"


def test_a_session_absent_from_the_closes_is_a_gap_not_a_holiday():
    sessions = weekdays(300)
    closes = closes_on(sessions, rising(300))
    del closes[sessions[250]]
    labels = classify(sessions, closes)
    assert labels[250].close is None and labels[250].trend_unknown == "gap"


def test_a_gap_inside_the_warmup_counts_as_a_gap():
    sessions = weekdays(220)
    values = trend_case(90, 102)
    values[5] = None
    labels = classify(sessions, closes_on(sessions, values))
    assert labels[100].trend_unknown == "gap"   # its window both starts before the data and has a hole
    assert labels[219].trend_unknown == "gap"


def test_a_label_never_looks_at_later_closes():
    sessions = weekdays(400)
    values = wiggle(400, burst=range(300, 306))
    before = classify(sessions, closes_on(sessions, values))
    values[350:] = [Decimal(500)] * 50
    values[320] = None
    after = classify(sessions, closes_on(sessions, values))
    assert after[:320] == before[:320]
    assert after[320] != before[320]


# ---- intervals -------------------------------------------------------------

def test_weekends_and_holidays_do_not_cut_an_interval():
    holiday = date(2020, 12, 31)
    sessions = weekdays(300, skip=frozenset({holiday}))
    found = discover(sessions, closes_on(sessions, rising(300)), sessions[230], sessions[299], RegimeFilter("up"))
    assert [(i.start, i.end, i.sessions) for i in found.intervals] == [(sessions[230], sessions[299], 70)]
    assert sessions[230] < holiday < sessions[299]
    assert found.diagnostics.gaps == []


def test_a_gap_cuts_an_interval_and_is_reported():
    sessions = weekdays(500)
    values = rising(500)
    values[300] = None
    found = discover(sessions, closes_on(sessions, values), sessions[250], sessions[499], RegimeFilter("up"))
    [before] = found.intervals   # the window reaches past the gap only at 520, after the search end
    assert (before.start, before.end, before.at_search_end) == (sessions[250], sessions[299], False)
    assert found.diagnostics.gaps == [sessions[300]]
    assert found.diagnostics.gap_unknown == [(sessions[300], sessions[499])]
    assert found.diagnostics.warmup_unknown == []


def test_intervals_resume_once_the_window_is_past_the_gap():
    sessions = weekdays(600)
    values = rising(600)
    values[300] = Decimal(0)
    found = discover(sessions, closes_on(sessions, values), sessions[250], sessions[599], RegimeFilter("up"))
    assert [(i.start, i.end) for i in found.intervals] == [(sessions[250], sessions[299]),
                                                           (sessions[520], sessions[599])]
    assert found.diagnostics.gap_unknown == [(sessions[300], sessions[519])]
    assert found.diagnostics.matched_sessions == 50 + 80
    assert found.diagnostics.trend_counts == {"up": 130, "down": 0, "neutral": 0, "unknown": 220}


def test_trend_only_is_not_cut_by_volatility_switches_or_its_warmup():
    sessions = weekdays(360)
    closes = closes_on(sessions, wiggle(360, burst=range(300, 306)))
    found = discover(sessions, closes, sessions[230], sessions[359], RegimeFilter("neutral"))
    assert [(i.start, i.end) for i in found.intervals] == [(sessions[230], sessions[359])]
    assert {label.vol for label in found.labels} == {"unknown", "low", "high"}
    assert found.diagnostics.warmup_unknown == []
    assert found.diagnostics.vol_counts == {"high": 26, "low": 62, "unknown": 42}

    low = discover(sessions, closes, sessions[230], sessions[359], RegimeFilter("neutral", "low"))
    assert [(i.start, i.end) for i in low.intervals] == [(sessions[272], sessions[299]),
                                                         (sessions[326], sessions[359])]
    assert low.diagnostics.warmup_unknown == [(sessions[230], sessions[271])]
    high = discover(sessions, closes, sessions[230], sessions[359], RegimeFilter("neutral", "high"))
    [burst] = high.intervals
    assert (burst.start, burst.end, burst.sessions) == (sessions[300], sessions[325], 26)
    assert burst.rv20_min <= burst.rv20_max and burst.rv20_min > low.labels[60].rv20


def test_single_day_and_zero_match():
    sessions = weekdays(221)
    values = trend_case(90, 102) + [100]
    closes = closes_on(sessions, values)
    found = discover(sessions, closes, sessions[210], sessions[220], RegimeFilter("up"))
    [day] = found.intervals
    assert (day.start, day.end, day.sessions) == (sessions[219], sessions[219], 1)
    assert day.single_day and day.short and day.topix_return == 0.0
    assert (day.topix_start, day.topix_end) == (Decimal(102), Decimal(102))
    assert not day.truncated_start and not day.at_search_end
    assert found.diagnostics.warmup_unknown == [(sessions[210], sessions[218])]
    assert found.diagnostics.search_sessions == 11

    none = discover(sessions, closes, sessions[210], sessions[220], RegimeFilter("down"))
    assert none.intervals == [] and none.diagnostics.matched_sessions == 0
    assert none.diagnostics.trend_counts == {"up": 1, "down": 0, "neutral": 1, "unknown": 9}


def test_search_edges_are_flagged():
    sessions = weekdays(400)
    closes = closes_on(sessions, rising(400))
    inside = discover(sessions, closes, sessions[300], sessions[350], RegimeFilter("up"))
    [cut] = inside.intervals
    assert cut.truncated_start and cut.at_search_end
    assert not cut.short and not cut.single_day
    assert cut.topix_start == Decimal(250) and cut.topix_end == Decimal("275")
    assert cut.topix_return == pytest.approx(0.1)
    assert [label.day for label in inside.labels] == sessions[300:351]

    first = discover(sessions, closes, sessions[219], sessions[350], RegimeFilter("up"))
    assert not first.intervals[0].truncated_start   # the session before it is still warming up


def test_truncated_start_sees_the_previous_session_with_a_volatility_filter():
    """The caller hands over sessions from `lookback_start`; the session
    before the search start must still get a full volatility label."""
    sessions = weekdays(400)
    closes = closes_on(sessions, wiggle(400))
    start = lookback_start(sessions, sessions[350])
    scope = sessions[sessions.index(start):]
    found = discover(scope, closes, sessions[350], sessions[399], RegimeFilter("neutral", "low"))
    [whole] = found.intervals
    assert whole.truncated_start and whole.at_search_end and whole.sessions == 50


def test_short_is_a_flag_only():
    sessions = weekdays(250)
    found = discover(sessions, closes_on(sessions, rising(250)), sessions[230], sessions[240], RegimeFilter("up"))
    [short] = found.intervals
    assert short.short and short.sessions == 11


def test_search_range_must_hold_a_session_and_the_filter_must_be_known():
    sessions = weekdays(250)
    closes = closes_on(sessions, rising(250))
    with pytest.raises(ValueError):
        discover(sessions, closes, sessions[240], sessions[230], RegimeFilter("up"))
    with pytest.raises(ValueError):
        discover(sessions, closes, date(2030, 1, 1), date(2030, 2, 1), RegimeFilter("up"))
    with pytest.raises(ValueError):
        RegimeFilter("sideways")
    with pytest.raises(ValueError):
        RegimeFilter("up", "medium")


def test_sessions_after_the_search_end_are_not_used():
    sessions = weekdays(400)
    closes = closes_on(sessions, rising(400))
    found = discover(sessions, closes, sessions[300], sessions[350], RegimeFilter("up"))
    assert found.labels[-1].day == sessions[350] and found.intervals[0].end == sessions[350]


# ---- lookback and fingerprint ---------------------------------------------

def test_lookback_reaches_back_far_enough_for_the_session_before_the_search():
    sessions = weekdays(400)
    assert lookback_start(sessions, sessions[350]) == sessions[350 - DEFINITION.full_min_closes]
    assert lookback_start(sessions, sessions[100]) == sessions[0]
    saturday = sessions[350] - timedelta(days=sessions[350].weekday() + 2)
    assert saturday.weekday() == 5
    assert lookback_start(sessions, saturday) == lookback_start(sessions, saturday + timedelta(days=2))


def test_fingerprint_changes_with_one_close_and_ignores_later_sessions():
    sessions = weekdays(400)
    values = rising(400)
    closes = closes_on(sessions, values)
    scope = sessions[50:300]
    base = fingerprint(scope, closes)
    assert base["definition_version"] == DEFINITION_VERSION
    assert (base["from"], base["through"], base["sessions"]) == (sessions[50].isoformat(),
                                                                 sessions[299].isoformat(), 250)

    edited = dict(closes)
    edited[sessions[120]] += Decimal("0.01")
    assert fingerprint(scope, edited)["sha256"] != base["sha256"]
    missing = dict(closes)
    missing[sessions[120]] = None
    assert fingerprint(scope, missing)["sha256"] != base["sha256"]

    more = weekdays(450)
    grown = closes_on(more, rising(450))
    assert fingerprint([d for d in more if d <= sessions[299]][50:], grown) == base
    as_floats = {day: float(value) for day, value in closes.items()}
    assert fingerprint(scope, as_floats) == base


def test_definition_is_json_ready_with_its_formulas():
    shown = DEFINITION.as_dict()
    assert shown["version"] == "topix_trend_vol_v1"
    assert shown["gap_threshold"] == "0.01"
    assert json.loads(json.dumps(shown, ensure_ascii=False)) == shown
    assert "MA200" in shown["formulas"]["ma200"]
