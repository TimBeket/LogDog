import pytest
from core.filter import LogFilter


@pytest.fixture
def f():
    return LogFilter()


def test_and(f):
    assert f._to_rpn(["A", "AND", "B"]) == ["A", "B", "AND"]


def test_or(f):
    assert f._to_rpn(["A", "OR", "B"]) == ["A", "B", "OR"]


def test_not(f):
    assert f._to_rpn(["NOT", "A"]) == ["A", "NOT"]


def test_and_precedence(f):
    assert f._to_rpn(["A", "AND", "B", "OR", "C"]) == ["A", "B", "AND", "C", "OR"]


def test_parentheses_override_precedence(f):
    tokens = ["A", "AND", "(", "B", "OR", "C", ")"]
    assert f._to_rpn(tokens) == ["A", "B", "C", "OR", "AND"]


def test_not_and(f):
    assert f._to_rpn(["NOT", "A", "AND", "B"]) == ["A", "NOT", "B", "AND"]


def test_nested_parentheses(f):
    tokens = ["(", "A", "AND", "B", ")", "OR", "(", "C", "AND", "D", ")"]
    assert f._to_rpn(tokens) == ["A", "B", "AND", "C", "D", "AND", "OR"]


def test_triple_and(f):
    assert f._to_rpn(["A", "AND", "B", "AND", "C"]) == ["A", "B", "AND", "C", "AND"]


def test_not_with_parentheses(f):
    tokens = ["NOT", "(", "A", "AND", "B", ")"]
    assert f._to_rpn(tokens) == ["A", "B", "AND", "NOT"]
