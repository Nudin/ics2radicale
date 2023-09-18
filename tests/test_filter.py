import pytest
from ics2radicale.import_ics import apply_operator


def test_equal_operator():
    assert apply_operator(5, 5, "==") is True
    assert apply_operator(5, 6, "==") is False


def test_not_equal_operator():
    assert apply_operator(5, 5, "!=") is False
    assert apply_operator(5, 6, "!=") is True


def test_in_operator():
    assert apply_operator(2, [1, 2, 3], "in") is True
    assert apply_operator(4, [1, 2, 3], "in") is False


def test_not_in_operator():
    assert apply_operator(4, [1, 2, 3], "not in") is True
    assert apply_operator(2, [1, 2, 3], "not in") is False


def test_match_operator():
    assert apply_operator("apple", r"app\w+", "match") is True
    assert apply_operator("banana", r"app\w+", "match") is False


def test_not_match_operator():
    assert apply_operator("apple", r"app\w+", "not match") is False
    assert apply_operator("banana", r"app\w+", "not match") is True


def test_invalid_operator():
    with pytest.raises(ValueError):
        apply_operator(5, 6, "<")


def test_invalid_values():
    with pytest.raises(ValueError):
        apply_operator(5, None, "in")
