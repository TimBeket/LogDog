import pytest
from core.filter import LogFilter


def make_filter(text):
    f = LogFilter()
    f.set_filter(text)
    return f


def test_empty_filter():
    f = make_filter("")
    assert f.match({"level": "info", "text": "anything"}) is True


def test_level_error_match():
    f = make_filter("level:error")
    assert f.match({"level": "error"}) is True


def test_level_error_no_match():
    f = make_filter("level:error")
    assert f.match({"level": "info"}) is False


def test_level_shorthand_e():
    f = make_filter("level:e")
    assert f.match({"level": "error"}) is True
    assert f.match({"level": "info"}) is False


def test_level_shorthand_w():
    f = make_filter("level:w")
    assert f.match({"level": "warn"}) is True
    assert f.match({"level": "info"}) is False


def test_level_shorthand_i():
    f = make_filter("level:i")
    assert f.match({"level": "info"}) is True
    assert f.match({"level": "error"}) is False


def test_level_shorthand_d():
    f = make_filter("level:d")
    assert f.match({"level": "debug"}) is True


def test_proc_match():
    f = make_filter("proc:unity")
    assert f.match({"proc": "unity"}) is True


def test_proc_no_match():
    f = make_filter("proc:unity")
    assert f.match({"proc": "system"}) is False


def test_pid_match():
    f = make_filter("pid:123")
    assert f.match({"pid": "123"}) is True


def test_pid_no_match():
    f = make_filter("pid:123")
    assert f.match({"pid": "456"}) is False


def test_text_match():
    f = make_filter("text:crash")
    assert f.match({"text": "game crashed unexpectedly"}) is True


def test_text_no_match():
    f = make_filter("text:crash")
    assert f.match({"text": "game loaded ok"}) is False


def test_and_both_match():
    f = make_filter("level:error AND proc:unity")
    assert f.match({"level": "error", "proc": "unity"}) is True


def test_and_one_fails():
    f = make_filter("level:error AND proc:unity")
    assert f.match({"level": "error", "proc": "system"}) is False


def test_or_one_match():
    f = make_filter("level:error OR level:warn")
    assert f.match({"level": "warn"}) is True
    assert f.match({"level": "error"}) is True


def test_or_none_match():
    f = make_filter("level:error OR level:warn")
    assert f.match({"level": "info"}) is False


def test_not():
    f = make_filter("NOT level:error")
    assert f.match({"level": "info"}) is True
    assert f.match({"level": "error"}) is False


def test_parentheses_or_and():
    f = make_filter("(level:error OR level:warn) AND proc:unity")
    assert f.match({"level": "error", "proc": "unity"}) is True
    assert f.match({"level": "warn", "proc": "unity"}) is True
    assert f.match({"level": "error", "proc": "system"}) is False


def test_quoted_bare_text():
    f = make_filter('"hello world"')
    assert f.match({"text": "hello world and more"}) is True
    assert f.match({"text": "hello"}) is False


def test_unquoted_bare_text():
    f = make_filter("hello")
    assert f.match({"text": "say hello world"}) is True


def test_invalid_filter_fallback():
    f = make_filter("level:")
    assert f.match({"level": "info"}) is True


def test_unknown_field_is_searched_as_text_with_colon():
    f = make_filter("Exception:")
    assert f.match({"text": "nullreferenceexception: object"}) is True
    assert f.match({"text": "all good"}) is False  # раньше «Exception:» совпадало со всем


def test_url_and_quoted_colon_text():
    assert make_filter("http://cdn").match({"text": "get http://cdn.host/x"}) is True
    assert make_filter('text:"a:b"').match({"text": "key a:b"}) is True
    assert make_filter('text:"a:b"').match({"text": "key a b"}) is False


def test_adjacent_words_all_required():
    f = make_filter("Failed to fetch")
    assert f.match({"text": "failed to fetch remote config"}) is True
    assert f.match({"text": "fetch ok"}) is False  # раньше учитывалось только последнее слово


def test_implicit_and_with_fields_and_groups():
    f = make_filter("level:error (proc:unity OR proc:game) NOT timeout")
    assert f.match({"level": "error", "proc": "game", "text": "crash"}) is True
    assert f.match({"level": "error", "proc": "game", "text": "timeout"}) is False
    assert f.match({"level": "warn", "proc": "game", "text": "crash"}) is False


def test_parentheses_attached_to_word_are_part_of_it():
    f = make_filter("proc:mygame(UnityFramework)")
    assert f.match({"proc": "mygame(unityframework)", "text": "x"}) is True
    # раньше это было «proc:mygame AND (UnityFramework)» и находило процесс по любому слову в строке
    assert f.match({"proc": "mygame", "text": "unityframework loaded"}) is False


def test_group_parentheses_still_work_next_to_attached_ones():
    f = make_filter("(proc:game(Foo) OR level:error) NOT timeout")
    assert f.match({"proc": "game(foo)", "level": "info", "text": "ok"}) is True
    assert f.match({"proc": "game", "level": "info", "text": "foo"}) is False
    assert f.match({"proc": "x", "level": "error", "text": "timeout"}) is False
