from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from gui.widgets.find_bar import FindBar


def _make_bar(qapp, initial_text):
    editor = QPlainTextEdit()
    editor.setPlainText(initial_text)
    editor.resize(400, 300)
    editor.show()
    bar = FindBar(editor)
    bar.show()
    return editor, bar


def _search(bar, text):
    """Набрать и не ждать паузы набора."""
    bar.input.setText(text)
    bar._search()


def _append_line(editor, text):
    cursor = QTextCursor(editor.document())
    cursor.movePosition(QTextCursor.End)
    cursor.insertText(text + "\n")


def _trim_lines(editor, n):
    """Как MainWindow._trim_display: срезать первые n строк."""
    doc = editor.document()
    cursor = QTextCursor(doc)
    cursor.setPosition(doc.findBlockByNumber(n).position(), QTextCursor.KeepAnchor)
    cursor.removeSelectedText()


def test_typing_search_jumps_to_first_match(qapp):
    editor, bar = _make_bar(qapp, "foo\nbar\nfoo\nbaz\nfoo\n")

    _search(bar, "foo")

    assert bar.current_index == 0
    assert bar.match_count == 3
    assert bar.lbl_count.text() == "1/3"
    assert editor.textCursor().selectedText() == "foo"


def test_search_waits_for_typing_pause(qtbot, qapp):
    """Поиск не на каждый символ: с полным окном логов это подвешивало программу."""
    editor, bar = _make_bar(qapp, "foo\nbar\n")
    bar.input.setText("f")
    bar.input.setText("fo")
    assert bar.match_count == 0
    qtbot.waitUntil(lambda: bar.match_count == 1, timeout=2000)


def test_enter_searches_without_waiting(qtbot, qapp):
    editor, bar = _make_bar(qapp, "foo\nbar\nfoo\n")
    bar.input.setText("foo")
    qtbot.keyClick(bar.input, Qt.Key_Return)
    # Enter во время паузы: найти сразу и встать на первое (а не перескочить на второе)
    assert bar.match_count == 2
    assert bar.current_index == 0


def test_case_insensitive_cyrillic(qapp):
    editor, bar = _make_bar(qapp, "Ошибка загрузки\nОШИБКА\nok\n")
    _search(bar, "ошибка")
    assert bar.match_count == 2


def test_positions_count_emoji_as_two_units(qapp):
    """QTextDocument считает позиции в UTF-16: эмодзи — две единицы."""
    editor, bar = _make_bar(qapp, "🔥 af_purchase\n😀😀 af_purchase\n")
    _search(bar, "af_purchase")
    # в Python-строке позиции другие — проверяем курсором документа
    doc = editor.document()
    for pos in bar.match_positions():
        cursor = QTextCursor(doc)
        cursor.setPosition(pos)
        cursor.setPosition(pos + bar._needle_len, QTextCursor.KeepAnchor)
        assert cursor.selectedText() == "af_purchase"
    assert bar.match_count == 2


def test_new_lines_preserve_current_match_position(qapp):
    editor, bar = _make_bar(qapp, "foo\nbar\nfoo\nbaz\nfoo\n")
    _search(bar, "foo")
    bar._find_next()
    assert bar.current_index == 1
    selected_pos = bar.match_positions()[1]

    _append_line(editor, "foo")
    bar._rescan()

    assert bar.match_count == 4
    assert bar.current_index == 1
    assert bar.match_positions()[1] == selected_pos


def test_new_lines_do_not_move_editor_cursor(qapp):
    editor, bar = _make_bar(qapp, "foo\nbar\nfoo\nbaz\nfoo\n")
    _search(bar, "foo")
    bar._find_next()
    cursor_pos_before = editor.textCursor().position()

    _append_line(editor, "foo")
    bar._rescan()

    assert editor.textCursor().position() == cursor_pos_before


def test_new_matches_found_when_none_existed(qtbot, qapp):
    editor, bar = _make_bar(qapp, "bar\nbaz\n")
    _search(bar, "foo")
    assert bar.current_index == -1
    assert bar.match_count == 0

    _append_line(editor, "foo")
    qtbot.waitUntil(lambda: bar.match_count == 1, timeout=2000)   # досмотр без ручного вызова
    assert bar.current_index == 0


def test_trimmed_old_lines_drop_their_matches(qapp):
    editor, bar = _make_bar(qapp, "foo 1\nbar\nfoo 2\nfoo 3\n")
    _search(bar, "foo")
    bar._find_next()                        # текущее — «foo 2»
    _trim_lines(editor, 2)                  # ушли «foo 1» и «bar»
    _append_line(editor, "foo 4")
    bar._rescan()

    text = editor.document().toPlainText()
    assert [text[p:p + 5] for p in bar.match_positions()] == ["foo 2", "foo 3", "foo 4"]
    assert bar.current_index == 0
    assert bar.lbl_count.text() == "1/3"


def test_trimmed_current_match_moves_to_next(qapp):
    editor, bar = _make_bar(qapp, "foo 1\nfoo 2\n")
    _search(bar, "foo")                     # текущее — «foo 1»
    _trim_lines(editor, 1)
    bar._rescan()
    assert bar.match_count == 1
    assert bar.current_index == 0


def test_change_in_the_middle_rescans(qapp):
    """Перестроение окна (фильтр, перекраска) — искать заново, а не сдвигать позиции."""
    editor, bar = _make_bar(qapp, "foo\nbar\nfoo\n")
    _search(bar, "foo")
    editor.setPlainText("x\nfoo\ny\nfoo\nfoo\n")
    bar._rescan()
    text = editor.document().toPlainText()
    assert [text[p:p + 3] for p in bar.match_positions()] == ["foo"] * 3


def test_repeat_counter_edit_at_the_end(qapp):
    """«×N» дописывается в последнюю строку — её надо досмотреть заново."""
    editor, bar = _make_bar(qapp, "a\nping\n")
    _search(bar, "×3")
    assert bar.match_count == 0
    doc = editor.document()
    cursor = QTextCursor(doc.findBlockByNumber(1))
    cursor.movePosition(QTextCursor.EndOfBlock)
    cursor.insertText("  ×3")
    bar._rescan()
    assert bar.match_count == 1


def test_only_visible_matches_are_painted(qapp):
    lines = "\n".join(f"line {i} match" for i in range(5000))
    editor, bar = _make_bar(qapp, lines)
    _search(bar, "match")
    assert bar.match_count == 5000
    assert 0 < len(editor.extraSelections()) < 200


def test_painted_selections_are_capped(qapp):
    """У каждой подсветки свой QTextCursor, а пик живых курсоров навсегда
    замедляет документ — даже при «a» по всему экрану подсветок не больше лимита."""
    from gui.widgets.find_bar import MAX_PAINTED
    editor, bar = _make_bar(qapp, "\n".join("a" * 200 for _ in range(200)))
    _search(bar, "a")
    assert bar.match_count == 40000
    assert len(editor.extraSelections()) <= MAX_PAINTED + 1


def test_arrow_keys_move_between_matches(qtbot, qapp):
    editor, bar = _make_bar(qapp, "foo\nbar\nfoo\nbaz\nfoo\n")
    _search(bar, "foo")
    assert bar.current_index == 0
    qtbot.keyClick(bar.input, Qt.Key_Down)
    assert bar.current_index == 1
    qtbot.keyClick(bar.input, Qt.Key_Down)
    qtbot.keyClick(bar.input, Qt.Key_Down)
    assert bar.current_index == 0          # по кругу
    qtbot.keyClick(bar.input, Qt.Key_Up)
    assert bar.current_index == 2


def test_hide_clears_search(qapp):
    editor, bar = _make_bar(qapp, "foo\n")
    _search(bar, "foo")
    bar.hide()
    assert bar.match_count == 0
    assert editor.extraSelections() == []
    _append_line(editor, "foo")
    bar._rescan()
    assert bar.match_count == 0
