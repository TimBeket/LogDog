"""Разбор фильтра для поля ввода: подсветка, ошибки, подсказки."""
from core.filter_syntax import analyze, complete


def kinds(text):
    return [(text[s.start:s.end], s.kind) for s in analyze(text).spans]


def messages(text):
    return [p.message for p in analyze(text).problems]


def test_spans():
    assert kinds('level:error AND (proc:game OR "Has consent") crash') == [
        ("level:", "field"), ("error", "value"), ("AND", "operator"), ("(", "paren"),
        ("proc:", "field"), ("game", "value"), ("OR", "operator"), ('"Has consent"', "string"), (")", "paren"),
    ]


def test_valid_filter_has_no_problems():
    assert messages('level:e OR (proc:game AND NOT text:"time out") Exception: http://x') == []


def test_problems():
    assert messages("level:fatal") == ["Нет уровня «fatal». Есть: error, warn, info, debug"]
    assert messages("pid:abc") == ["pid — это число"]
    assert messages("(level:error") == ["Скобка не закрыта"]
    assert messages("level:error)") == ["Лишняя закрывающая скобка"]
    assert messages("level:error AND") == ["После AND нужно условие"]
    assert messages("OR crash") == ["Перед OR нет условия"]
    assert messages('"unclosed') == ["Кавычка не закрыта"]
    assert messages("()") == ["Пустые скобки"]


def test_lowercase_operator_warns():
    (problem,) = analyze("cats and dogs").problems
    assert problem.severity == "warning" and '"and"' in problem.message


def test_empty_field_value_warns():
    (problem,) = analyze("level:").problems
    assert problem.severity == "warning"


def items(text, cursor=None, procs=()):
    c = complete(text, len(text) if cursor is None else cursor, procs)
    return None if c is None else [i.text for i in c.items]


def test_complete_fields_at_operand_start():
    assert items("le") == ["level:"]
    assert items("") == ["level:", "proc:", "pid:", "text:", "NOT ", "("]
    assert items("level:error AND p") == ["proc:", "pid:"]


def test_complete_values():
    assert items("level:") == ["error ", "warn ", "info ", "debug "]
    assert items("level:w") == ["warn "]
    assert items("proc:sp", procs=["SpringBoard", "game", "Spotlight Helper"]) == [
        "SpringBoard ", '"Spotlight Helper" ']


def test_complete_operators_after_operand():
    assert items("level:error ") == ["AND ", "OR "]
    assert items("(level:error ") == ["AND ", "OR ", ") "]
    assert items("level:error o") == ["OR "]


def test_complete_replaces_typed_prefix():
    c = complete("level:error AND le", 18)
    assert (c.start, c.end) == (16, 18)
    c = complete("level:w", 7)
    assert (c.start, c.end) == (6, 7)


def test_nothing_to_complete_inside_quotes_or_after_typed_operator():
    assert items('text:"abc') is None
    assert items('"abc') is None
    assert items("level:error AND") is None


def test_text_and_pid_give_only_context_hint():
    c = complete("text:", 5)
    assert c.items == [] and "кавычк" in c.context


def test_process_name_with_subsystem_is_one_value():
    assert kinds("proc:mygame(UnityFramework)") == [("proc:", "field"), ("mygame(UnityFramework)", "value")]
    assert messages("proc:mygame(UnityFramework)") == []
