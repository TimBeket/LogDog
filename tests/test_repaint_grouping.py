from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor
from PySide6.QtWidgets import QPlainTextEdit

from gui.main_window import repaint_document_by_level


def _insert_colored(editor, text, color):
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.End)
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    cursor.insertText(text + "\n", fmt)


def _color_for_level(level):
    return {
        "error": "#ff0000",
        "warn": "#ffff00",
        "info": "#0000ff",
        "debug": "#00ff00",
        "system": "#999999",
    }.get(level, "#0000ff")


def _block_colors(doc):
    """Colors of every non-empty text block, sampled via a cursor positioned
    inside the block's actual text run (QTextBlock.charFormat() reflects the
    block-boundary/separator format, not the real character formatting, so it
    can't be used directly to inspect applied colors)."""
    colors = []
    block = doc.firstBlock()
    while block.isValid():
        if block.length() > 1:  # length includes the trailing separator; >1 means real text
            cursor = QTextCursor(doc)
            cursor.setPosition(block.position() + 1)
            colors.append(cursor.charFormat().foreground().color().name())
        block = block.next()
    return colors


def test_repaint_recolors_multiline_entry_as_one_group(qapp):
    editor = QPlainTextEdit()
    _insert_colored(editor, "2024-01-01 12:00:00 NullReferenceException at Foo", "#000000")
    _insert_colored(editor, "  at Foo.Bar() [0x00000]", "#000000")
    _insert_colored(editor, "  at Baz.Qux() [0x00001]", "#000000")

    repaint_document_by_level(editor.document(), _color_for_level)

    assert _block_colors(editor.document()) == ["#ff0000", "#ff0000", "#ff0000"]


def test_repaint_keeps_separate_entries_independently_colored(qapp):
    editor = QPlainTextEdit()
    _insert_colored(editor, "2024-01-01 12:00:00 all good here", "#000000")
    _insert_colored(editor, "2024-01-01 12:00:01 NullReferenceException oops", "#000000")

    repaint_document_by_level(editor.document(), _color_for_level)

    assert _block_colors(editor.document()) == ["#0000ff", "#ff0000"]


def test_repaint_system_tag_survives_after_rename(qapp):
    editor = QPlainTextEdit()
    _insert_colored(editor, "2024-01-01 12:00:00 [System] Соединение потеряно", "#000000")

    repaint_document_by_level(editor.document(), _color_for_level)

    assert _block_colors(editor.document()) == ["#999999"]


def test_repaint_empty_document_noop(qapp):
    editor = QPlainTextEdit()
    repaint_document_by_level(editor.document(), _color_for_level)  # must not raise
