from finance_tools.exit_view import explicit_stop_from_reason


def test_explicit_stop_requires_a_number_immediately_after_keyword():
    reason = "Ingresso su supporto 13.915, con stop sotto supporto e news non negative."
    assert explicit_stop_from_reason(reason) is None


def test_explicit_stop_is_read_from_entry_reason():
    reason = "Scenario breakout. Stop inval. sotto 40.97."
    assert explicit_stop_from_reason(reason) == 40.97
