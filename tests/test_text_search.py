from core.text_search import find_all, utf16_len, utf16_positions


def test_find_all_case_insensitive_non_overlapping():
    assert find_all("AppsFlyer appsflyer APPSFLYER", "appsFlyer") == [0, 10, 20]
    assert find_all("aaaa", "aa") == [0, 2]
    assert find_all("Ошибка ОШИБКА", "ошибка") == [0, 7]
    assert find_all("abc", "") == []


def test_find_all_when_lower_changes_length():
    text = "İİ error"            # «İ».lower() — два символа
    assert find_all(text, "ERROR") == [3]


def test_utf16_positions_and_len():
    text = "🔥 a 😀a"
    assert utf16_positions(text, find_all(text, "a")) == [3, 7]
    assert utf16_positions("plain a", [6]) == [6]
    assert utf16_len("😀ab") == 4
