from datetime import datetime
from PySide6.QtCore import QObject, Signal, QThread

class BaseReader(QThread):
    """Abstract base class for log transports. Inherits from QThread directly."""
    
    # Emits a list of parsed log lines to be processed by GUI/Processor
    lines_ready = Signal(list)
    # Emits a critical error message
    error_occurred = Signal(str)
    # For updating the UI status bar (connected, scanning, etc)
    status_changed = Signal(str)
    # Состояние связи для индикатора в строке состояния:
    # "connecting" | "streaming" (логи идут) | "waiting" (нет связи, ждём)
    state_changed = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_running = True

    def run(self):
        """Main loop of the reader thread."""
        raise NotImplementedError("Subclasses must implement the run method")

    def stop(self):
        """Gracefully stops the reader loop and thread."""
        self._is_running = False

    def emit_system_message(self, text: str):
        """Emits a [LogDog:System] status/error line with a synthetic timestamp
        prefix, so LogProcessor.is_new_log_line recognizes it as the start of a
        new block instead of silently gluing it onto whatever unrelated block
        happens to be open."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.lines_ready.emit([f"{now_str} [LogDog:System] {text}"])
