"""Поле фильтра: подсветка не мешает вводу, подсказки по Tab/стрелкам, Enter всегда применяет."""
import pytest
from PySide6.QtCore import Qt

from gui.widgets.filter_edit import FilterLineEdit


@pytest.fixture
def edit(qtbot):
    w = FilterLineEdit()
    w.set_proc_source(lambda: ["springboard", "game", "spotlight"])
    qtbot.addWidget(w)
    w.show()
    w.activateWindow()
    w.setFocus()
    qtbot.waitUntil(w.hasFocus, timeout=2000)
    return w


def type_text(qtbot, edit, text):
    qtbot.keyClicks(edit, text)


def test_typing_is_not_changed_by_highlighting(qtbot, edit):
    type_text(qtbot, edit, 'level:error AND (proc:game OR "a b")')
    assert edit.text() == 'level:error AND (proc:game OR "a b")'
    assert edit.cursorPosition() == len(edit.text())


def shown(edit):
    return [edit.popup.list.item(i).text() for i in range(edit.popup.list.count())] \
        if edit.popup.isVisible() and edit.popup.list.isVisible() else []


def test_list_appears_while_typing_and_tab_accepts(qtbot, edit):
    type_text(qtbot, edit, "le")
    assert shown(edit) == ["level:"]
    qtbot.keyClick(edit, Qt.Key_Tab)
    assert edit.text() == "level:" and edit.hasFocus()
    assert shown(edit) == ["error", "warn", "info", "debug"]  # после «:» — сразу значения
    qtbot.keyClick(edit, Qt.Key_Down)
    qtbot.keyClick(edit, Qt.Key_Return)                      # Enter в списке — вставить, как в IDE
    assert edit.text() == "level:warn "


def test_ctrl_space_shows_all_options_for_position(qtbot, edit):
    type_text(qtbot, edit, "level:error ")
    assert shown(edit) == []                                  # ничего не набрано — список не навязываем
    qtbot.keyClick(edit, Qt.Key_Space, Qt.ControlModifier)
    assert shown(edit) == ["AND", "OR"]
    qtbot.keyClick(edit, Qt.Key_Up)
    qtbot.keyClick(edit, Qt.Key_Tab)
    assert edit.text() == "level:error OR "


def test_proc_values_from_logs(qtbot, edit):
    type_text(qtbot, edit, "proc:sp")
    assert shown(edit) == ["springboard", "spotlight"]
    qtbot.keyClick(edit, Qt.Key_Tab)
    assert edit.text() == "proc:springboard "


def test_click_on_item_inserts_it(qtbot, edit):
    type_text(qtbot, edit, "pr")
    rect = edit.popup.list.visualItemRect(edit.popup.list.item(0))
    qtbot.mouseClick(edit.popup.list.viewport(), Qt.LeftButton, pos=rect.center())
    assert edit.text() == "proc:" and edit.hasFocus()


def test_enter_without_list_applies_filter(qtbot, edit):
    applied = []
    edit.returnPressed.connect(lambda: applied.append(edit.text()))
    type_text(qtbot, edit, "crash")
    assert shown(edit) == []
    qtbot.keyClick(edit, Qt.Key_Return)
    assert applied == ["crash"]


def test_escape_closes_list(qtbot, edit):
    type_text(qtbot, edit, "le")
    qtbot.keyClick(edit, Qt.Key_Escape)
    assert not edit.popup.isVisible()
    type_text(qtbot, edit, "v")
    assert shown(edit) == ["level:"]


def test_problem_shown_after_pause(qtbot, edit):
    type_text(qtbot, edit, "level:fatal")
    qtbot.waitUntil(lambda: edit.popup.isVisible() and "fatal" in edit.popup.footer.text(), timeout=2000)


def test_accept_is_undoable(qtbot, edit):
    type_text(qtbot, edit, "le")
    qtbot.keyClick(edit, Qt.Key_Tab)
    edit.undo()
    assert edit.text() == "le"


def test_problems_shown_in_tooltip(qtbot, edit):
    type_text(qtbot, edit, "(level:fatal")
    assert "Нет уровня «fatal»" in edit.toolTip() and "Скобка не закрыта" in edit.toolTip()
    edit.setText("level:error")
    assert edit.toolTip() == ""
