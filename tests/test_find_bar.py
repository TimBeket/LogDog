from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from gui.widgets.find_bar import FindBar


def _make_bar(qapp, initial_text):
    editor = QPlainTextEdit()
    editor.setPlainText(initial_text)
    bar = FindBar(editor)
    bar.show()
    return editor, bar


def _append_line(editor, text):
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    cursor.insertText(text + "\n")


def test_typing_search_jumps_to_first_match(qapp):
    editor, bar = _make_bar(qapp, "foo\nbar\nfoo\nbaz\nfoo\n")

    bar.input.setText("foo")

    assert bar._current_idx == 0
    assert len(bar._matches) == 3


def test_new_lines_preserve_current_match_position(qapp):
    editor, bar = _make_bar(qapp, "foo\nbar\nfoo\nbaz\nfoo\n")
    bar.input.setText("foo")
    assert bar._current_idx == 0

    bar._find_next()
    assert bar._current_idx == 1
    selected_pos = bar._matches[bar._current_idx].selectionStart()

    _append_line(editor, "foo")

    bar._on_debounced_search()

    assert len(bar._matches) == 4
    assert bar._current_idx == 1
    assert bar._matches[bar._current_idx].selectionStart() == selected_pos


def test_new_lines_do_not_move_editor_cursor(qapp):
    editor, bar = _make_bar(qapp, "foo\nbar\nfoo\nbaz\nfoo\n")
    bar.input.setText("foo")
    bar._find_next()

    cursor_pos_before = editor.textCursor().position()

    _append_line(editor, "foo")
    bar._on_debounced_search()

    assert editor.textCursor().position() == cursor_pos_before


def test_debounced_search_finds_new_matches_when_none_existed(qapp):
    editor, bar = _make_bar(qapp, "bar\nbaz\n")
    bar.input.setText("foo")
    assert bar._current_idx == -1
    assert len(bar._matches) == 0

    _append_line(editor, "foo")
    bar._on_debounced_search()

    assert len(bar._matches) == 1
    assert bar._current_idx == 0


def test_arrow_keys_move_between_matches(qtbot, qapp):
    from PySide6.QtCore import Qt
    editor, bar = _make_bar(qapp, "foo\nbar\nfoo\nbaz\nfoo\n")
    bar.input.setText("foo")
    assert bar._current_idx == 0
    qtbot.keyClick(bar.input, Qt.Key_Down)
    assert bar._current_idx == 1
    qtbot.keyClick(bar.input, Qt.Key_Down)
    qtbot.keyClick(bar.input, Qt.Key_Down)
    assert bar._current_idx == 0          # по кругу
    qtbot.keyClick(bar.input, Qt.Key_Up)
    assert bar._current_idx == 2
