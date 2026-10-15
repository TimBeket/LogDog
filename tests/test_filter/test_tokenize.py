import pytest
from core.filter import LogFilter


@pytest.fixture
def f():
    return LogFilter()


def test_single_word(f):
    assert f._tokenize("error") == ["error"]


def test_simple_and(f):
    assert f._tokenize("A AND B") == ["A", "AND", "B"]


def test_simple_or(f):
    assert f._tokenize("A OR B") == ["A", "OR", "B"]


def test_not(f):
    assert f._tokenize("NOT A") == ["NOT", "A"]


def test_parentheses(f):
    assert f._tokenize("(A OR B)") == ["(", "A", "OR", "B", ")"]


def test_quoted_string(f):
    assert f._tokenize('"hello world"') == ['"hello world"']


def test_single_quoted_string(f):
    assert f._tokenize("'hello world'") == ["'hello world'"]


def test_field_prefix(f):
    assert f._tokenize("level:error") == ["level:error"]


def test_complex_query(f):
    result = f._tokenize('level:e AND (proc:foo OR text:"has consent")')
    assert result == ["level:e", "AND", "(", "proc:foo", "OR", 'text:"has consent"', ")"]


def test_not_at_start(f):
    assert f._tokenize("A AND NOT B") == ["A", "AND", "NOT", "B"]


def test_empty_string(f):
    assert f._tokenize("") == []


def test_whitespace_only(f):
    assert f._tokenize("   ") == []


def test_multiple_spaces_between(f):
    assert f._tokenize("A    AND    B") == ["A", "AND", "B"]


def test_unclosed_quote_in_field(f):
    tokens = f._tokenize('level:"unclosed')
    # " after : is treated as start of a quoted segment;
    # 'level:' is emitted first, then '"unclosed' as a separate token
    assert tokens == ['level:', '"unclosed']


def test_attached_parentheses_stay_in_word(f):
    assert f._tokenize("proc:a(B) AND (x)") == ["proc:a(B)", "AND", "(", "x", ")"]
    assert f._tokenize("(proc:a(B))") == ["(", "proc:a(B)", ")"]
    assert f._tokenize("(level:error)") == ["(", "level:error", ")"]
