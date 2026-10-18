from projection.config import DEFAULT_SETTINGS
from projection.data.load import build_dataset
from projection.data.report import address_match_rate, costs_names, sources_overview, to_markdown
from tests.fixtures import TODAY, raw_sheet


def _ds():
    return build_dataset(raw_sheet(), DEFAULT_SETTINGS, today=TODAY)


def test_costs_split_uses_non_marketing_setting():
    df = costs_names(_ds(), DEFAULT_SETTINGS)
    assert df.loc["ACQ Payroll", "class"] == "non-marketing"
    assert df.loc["PPC NW RDS", "class"] == "marketing"
    assert df.loc["PPC NW RDS", "total"] == 20000.00 + 21000.00 + 25000.00


def test_sources_overview_joins_tabs_on_exact_name():
    df = sources_overview(_ds(), DEFAULT_SETTINGS)
    assert df.loc["PPC NW RDS", "in_tabs"] == "C/R/K"
    assert df.loc["PPC NW RDS", "leads"] == 2 and df.loc["PPC NW RDS", "net_leads"] == 1
    assert df.loc["SELF GEN", "in_tabs"] == "R"
    assert "ACQ Payroll" not in df.index


def test_address_match_rate():
    matched, total = address_match_rate(_ds())
    # 3060 SE Fairmont St, 55 Elm St and both 2903 NW 104th Ct rows match KPI addresses
    assert (matched, total) == (4, 7)


def test_markdown_report_has_sections_and_no_personal_data():
    md = to_markdown(_ds(), DEFAULT_SETTINGS)
    for heading in ("## Months covered", "## COSTS names and proposed split", "## Distinct values: KPI",
                    "## Blank KPI Dates", "## Issues", "Near-duplicate source spellings"):
        assert heading in md
    assert "/contacts/" not in md and not any(cid in md for cid in ("AAA111", "BBB222", "CCC333"))
