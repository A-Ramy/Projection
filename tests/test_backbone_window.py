"""A quarter's backbone window never includes the quarter itself."""

import pytest

from projection.config import DEFAULT_SETTINGS
from projection.data.load import build_dataset
from projection.model import QuarterProjection
from projection.periods import Month, quarter
from projection.suggest.quarter import history_months
from tests import metrics_fixture as mf


@pytest.fixture(scope="module")
def ds():
    return build_dataset(mf.raw_sheet(), DEFAULT_SETTINGS, today=mf.TODAY)


def proj(qid: str, **kw) -> QuarterProjection:
    return QuarterProjection(quarter_id=qid, **kw)


def test_window_is_before_the_quarter(ds):
    assert history_months(ds, quarter(2026, 4), proj("2026-Q4")) == [Month(2026, m) for m in (7, 8, 9)]
    assert history_months(ds, quarter(2026, 3), proj("2026-Q3")) == [Month(2026, m) for m in (4, 5, 6)]
    assert history_months(ds, quarter(2026, 1), proj("2026-Q1")) == []  # nothing before the start date
    assert history_months(ds, quarter(2026, 4), proj("2026-Q4", lookback="all"))[-1] == Month(2026, 9)
    custom = proj("2026-Q4", lookback="custom", lookback_from="2026-02", lookback_to="2026-03")
    assert history_months(ds, quarter(2026, 4), custom) == [Month(2026, 2), Month(2026, 3)]
    assert history_months(ds, quarter(2026, 4), proj("2026-Q4", lookback="custom")) == []
