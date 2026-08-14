"""BAR-309 — epoch normalization, and the pairs that break naive comparisons.

Two things are proven here that a reading of ``temporal.py`` cannot prove on its
own: that the diverging pair really diverges, and that ambiguity is refused
rather than guessed.

The first matters because the *obvious* illustration of the defect does not
work. ``09:00-05:00`` versus ``08:00Z`` sorts the same way as text and as an
instant, so a test built on it passes for the wrong reason and would keep
passing after the bug was reintroduced. A pair that genuinely diverges has to
cross a date boundary.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from baraza.schema.temporal import (
    MAX_INSTANT,
    MIN_INSTANT,
    TemporalError,
    intervals_overlap,
    to_epoch_millis,
    to_epoch_millis_optional,
    to_iso,
)

# The planted pair. `LATER` is 2026-05-02T01:00Z — one hour after `EARLIER` —
# but sorts before it as text.
LATER_INSTANT_EARLIER_TEXT = "2026-05-01T20:00:00-05:00"
EARLIER_INSTANT_LATER_TEXT = "2026-05-02T00:00:00Z"


class TestTheDivergingPair:
    def test_string_order_and_instant_order_disagree(self):
        as_text = sorted([LATER_INSTANT_EARLIER_TEXT, EARLIER_INSTANT_LATER_TEXT])
        assert as_text[0] == LATER_INSTANT_EARLIER_TEXT

        as_instants = sorted(
            [LATER_INSTANT_EARLIER_TEXT, EARLIER_INSTANT_LATER_TEXT],
            key=to_epoch_millis,
        )
        assert as_instants[0] == EARLIER_INSTANT_LATER_TEXT

        assert as_text != as_instants

    def test_the_gap_is_exactly_one_hour(self):
        delta = to_epoch_millis(LATER_INSTANT_EARLIER_TEXT) - to_epoch_millis(
            EARLIER_INSTANT_LATER_TEXT
        )
        assert delta == 3_600_000

    def test_the_obvious_illustration_does_not_diverge(self):
        """Recorded so nobody 'simplifies' the fixture back to a broken one.

        This is the pair the defect class is usually explained with, and it is
        useless as a test: text order and instant order agree.
        """
        a, b = "2026-05-01T09:00:00-05:00", "2026-05-01T08:00:00Z"
        assert sorted([a, b]) == sorted([a, b], key=to_epoch_millis)


class TestRefusesAmbiguity:
    def test_naive_datetime_raises(self):
        with pytest.raises(TemporalError) as caught:
            to_epoch_millis(datetime(2026, 5, 1, 20, 0, 0), field="observed_at")
        assert "observed_at" in str(caught.value)
        assert "no offset" in str(caught.value)

    def test_offsetless_iso_raises(self):
        with pytest.raises(TemporalError) as caught:
            to_epoch_millis("2026-04-14T19:30:00", field="valid_from")
        assert "valid_from" in str(caught.value)

    def test_none_raises(self):
        with pytest.raises(TemporalError):
            to_epoch_millis(None)

    def test_empty_string_raises(self):
        with pytest.raises(TemporalError):
            to_epoch_millis("   ")

    def test_bool_is_not_a_timestamp(self):
        # bool is an int subclass; without the explicit guard, True would
        # normalize to 1000ms and a flag would silently become an instant.
        with pytest.raises(TemporalError):
            to_epoch_millis(True)

    def test_aware_datetime_is_accepted(self):
        aware = datetime(2026, 5, 1, 20, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
        assert to_epoch_millis(aware) == to_epoch_millis(LATER_INSTANT_EARLIER_TEXT)


class TestBareIntegers:
    """The corpus mixes chat-export epoch seconds with our own epoch millis."""

    def test_below_the_ceiling_reads_as_seconds(self):
        assert to_epoch_millis(1_700_000_000) == 1_700_000_000_000
        assert to_epoch_millis(9_999_999_999) == 9_999_999_999_000

    def test_at_and_above_the_ceiling_reads_as_millis(self):
        assert to_epoch_millis(10_000_000_000) == 10_000_000_000
        assert to_epoch_millis(1_775_034_000_000) == 1_775_034_000_000

    def test_the_boundary_is_the_documented_one(self):
        """One below the ceiling is seconds; the ceiling itself is millis."""
        assert to_epoch_millis(9_999_999_999) != 9_999_999_999
        assert to_epoch_millis(10_000_000_000) == 10_000_000_000

    def test_float_seconds_round_to_millis(self):
        assert to_epoch_millis(1_700_000_000.5) == 1_700_000_000_500


class TestOtherForms:
    def test_bare_date_string_is_midnight_utc(self):
        assert to_epoch_millis("2026-05-02") == to_epoch_millis(
            "2026-05-02T00:00:00Z"
        )

    def test_date_object_is_midnight_utc(self):
        assert to_epoch_millis(date(2026, 5, 2)) == to_epoch_millis("2026-05-02")

    def test_offset_without_a_colon_parses(self):
        assert to_epoch_millis("2026-05-01T20:00:00-0500") == to_epoch_millis(
            LATER_INSTANT_EARLIER_TEXT
        )

    def test_to_iso_round_trips(self):
        instant = to_epoch_millis(LATER_INSTANT_EARLIER_TEXT)
        assert to_epoch_millis(to_iso(instant)) == instant

    def test_optional_substitutes_the_open_bound(self):
        assert to_epoch_millis_optional(None, default=MIN_INSTANT) == MIN_INSTANT
        assert to_epoch_millis_optional("2026-05-02", default=MIN_INSTANT) == (
            to_epoch_millis("2026-05-02")
        )


# Two consecutive fiscal years. This pair is a planted false positive: a
# treasurer's FY26 signing authority and their successor's FY27 authority are a
# change over time, not a disagreement, and the temporal gate is what keeps it
# off the ledger without spending a model call on it.
FY26 = (to_epoch_millis("2025-07-01"), to_epoch_millis("2026-07-01"))
FY27 = (to_epoch_millis("2026-07-01"), to_epoch_millis("2027-07-01"))


class TestIntervalOverlap:
    def test_consecutive_fiscal_years_do_not_overlap(self):
        assert intervals_overlap(*FY26, *FY27) is False
        assert intervals_overlap(*FY27, *FY26) is False

    def test_the_shared_boundary_is_half_open(self):
        """FY26 ends the instant FY27 begins; that is not one millisecond of
        overlap, and a closed interval would make every consecutive term a
        contradiction."""
        assert FY26[1] == FY27[0]
        assert intervals_overlap(*FY26, *FY27) is False

    def test_genuinely_overlapping_terms_do_overlap(self):
        mid_fy26 = (to_epoch_millis("2026-01-01"), to_epoch_millis("2026-03-01"))
        assert intervals_overlap(*FY26, *mid_fy26) is True

    def test_one_millisecond_of_overlap_counts(self):
        a = (0, 1_000)
        b = (999, 5_000)
        assert intervals_overlap(*a, *b) is True

    def test_open_start_reaches_back_forever(self):
        assert intervals_overlap(None, FY26[1], *FY26) is True
        assert intervals_overlap(None, FY26[0], *FY26) is False

    def test_open_end_reaches_forward_forever(self):
        still_in_force = (to_epoch_millis("2025-01-01"), None)
        assert intervals_overlap(*still_in_force, *FY27) is True

    def test_both_ends_open_overlaps_everything(self):
        assert intervals_overlap(None, None, *FY26) is True
        assert intervals_overlap(None, None, None, None) is True

    def test_open_bounds_normalize_to_the_sentinels(self):
        """A claim that is still in force must not be treated as zero-length."""
        assert MIN_INSTANT < FY26[0] < MAX_INSTANT
        assert intervals_overlap(FY26[0], None, None, FY26[0]) is False

    def test_inverted_interval_raises(self):
        with pytest.raises(TemporalError):
            intervals_overlap(FY26[1], FY26[0], *FY27)
