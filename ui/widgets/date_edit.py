#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Custom date edit widget — free-text typing + calendar popup with
year/month dropdown navigation.

Replaces QDateEdit across all tabs with a more intuitive UX:
  - Users can type dates directly (e.g. "2025-01-01")
  - Calendar popup has year/month QComboBox selectors instead of arrows
  - Built-in clear button (no separate widget needed)

API is backward-compatible with QDateEdit for easy migration:
  date()          -> QDate (sentinel QDate(2000,1,1) when empty)
  setDate(QDate)  -> set or clear
  date_str()      -> "yyyy-MM-dd" or ""
  setDateString() -> set from string
  clear()         -> clear
  isEmpty()       -> bool
"""

from PySide6.QtCore import QDate, QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QCalendarWidget,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.theme import COLORS_LIGHT, COLORS_DARK, RADIUS, SPACING

# Sentinel: matches the old QDateEdit minimum-date convention.
_SENTINEL = QDate(2000, 1, 1)
_DATE_FMT = "yyyy-MM-dd"


def _current_colors() -> dict:
    """Detect dark mode by checking app palette and return matching colors."""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QPalette
    app = QApplication.instance()
    if app:
        bg = app.palette().color(QPalette.ColorRole.Window)
        if bg.lightness() < 128:
            return COLORS_DARK
    return COLORS_LIGHT


def _popup_qss(c: dict) -> str:
    """QSS for the calendar popup frame."""
    return f"""
    _CalendarPopup, QFrame#calendarPopup {{
        background: {c['bg']};
        border: 1px solid {c['border']};
        border-radius: {RADIUS['md']}px;
    }}
    QCalendarWidget {{
        background: {c['bg']};
        border: none;
    }}
    QCalendarWidget QToolButton {{
        background: transparent;
        border: none;
        color: {c['text']};
        padding: 4px;
        font-size: 11pt;
        font-weight: bold;
    }}
    QCalendarWidget QToolButton:hover {{
        background: {c['surface']};
        border-radius: {RADIUS['sm']}px;
    }}
    QCalendarWidget QMenu {{
        background: {c['bg']};
        border: 1px solid {c['border']};
    }}
    QCalendarWidget QMenu::item:selected {{
        background: {c['primary']};
        color: white;
    }}
    QCalendarWidget QAbstractItemView {{
        background: {c['bg']};
        selection-background-color: {c['primary']};
        selection-color: white;
        border: none;
        font-size: 10pt;
    }}
    QCalendarWidget QWidget {{
        alternate-background-color: {c['surface']};
    }}
    /* Navigation bar combos */
    QComboBox#calCombo {{
        border: 1px solid {c['border']};
        border-radius: {RADIUS['sm']}px;
        padding: 2px 6px;
        background: {c['bg']};
        color: {c['text']};
        min-height: 22px;
    }}
    QComboBox#calCombo::drop-down {{
        border: none;
        width: 16px;
    }}
    QComboBox#calCombo QAbstractItemView {{
        border: 1px solid {c['border']};
        background: {c['bg']};
        selection-background-color: {c['primary']};
        selection-color: white;
    }}
    /* Nav prev/next buttons */
    QToolButton#calNav {{
        background: transparent;
        border: 1px solid {c['border']};
        border-radius: {RADIUS['sm']}px;
        color: {c['text']};
        font-size: 10pt;
    }}
    QToolButton#calNav:hover {{
        background: {c['surface']};
    }}
    /* Year/month labels */
    QLabel#calLabel {{
        color: {c['text_secondary']};
        font-size: 9pt;
    }}
    """


# ── Calendar popup with year/month dropdowns ──────────────────────────


class _CalendarPopup(QFrame):
    """Popup calendar with year and month dropdown navigation.

    Hides the default QCalendarWidget navbar (tiny arrows) and replaces
    it with two QComboBox widgets for direct year/month selection.
    """

    date_selected = Signal(QDate)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("calendarPopup")
        self._syncing = False
        self._build_ui()
        self.setStyleSheet(_popup_qss(_current_colors()))

    # ── construction ──────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # --- Navigation bar: [◀] ... [year ▾] 年 [month ▾] 月 ... [▶] ---
        nav = QHBoxLayout()
        nav.setSpacing(4)

        prev_btn = QToolButton()
        prev_btn.setObjectName("calNav")
        prev_btn.setText("\u25C0")  # ◀
        prev_btn.setFixedSize(28, 28)
        prev_btn.setToolTip("\u4e0a\u4e2a\u6708")
        prev_btn.clicked.connect(self._go_prev)

        next_btn = QToolButton()
        next_btn.setObjectName("calNav")
        next_btn.setText("\u25B6")  # ▶
        next_btn.setFixedSize(28, 28)
        next_btn.setToolTip("\u4e0b\u4e2a\u6708")
        next_btn.clicked.connect(self._go_next)

        current_year = QDate.currentDate().year()
        self._year_combo = QComboBox()
        self._year_combo.setObjectName("calCombo")
        for y in range(2000, current_year + 6):
            self._year_combo.addItem(str(y), y)
        self._year_combo.setFixedWidth(78)

        self._month_combo = QComboBox()
        self._month_combo.setObjectName("calCombo")
        for m in range(1, 13):
            self._month_combo.addItem(f"{m}\u6708", m)
        self._month_combo.setFixedWidth(58)

        year_label = QLabel("\u5e74")
        year_label.setObjectName("calLabel")
        month_label = QLabel("\u6708")
        month_label.setObjectName("calLabel")

        self._year_combo.currentIndexChanged.connect(self._on_combo_changed)
        self._month_combo.currentIndexChanged.connect(self._on_combo_changed)

        nav.addWidget(prev_btn)
        nav.addStretch()
        nav.addWidget(self._year_combo)
        nav.addWidget(year_label)
        nav.addWidget(self._month_combo)
        nav.addWidget(month_label)
        nav.addStretch()
        nav.addWidget(next_btn)

        # --- Calendar widget (builtin navbar hidden) ---
        self._cal = QCalendarWidget()
        self._cal.setNavigationBarVisible(False)
        self._cal.setGridVisible(False)
        self._cal.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self._cal.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        self._cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self._cal.clicked.connect(self._on_date_clicked)
        self._cal.currentPageChanged.connect(self._on_page_changed)

        layout.addLayout(nav)
        layout.addWidget(self._cal)

    # ── public API ────────────────────────────────────────────────

    def set_date(self, qdate: QDate):
        """Set the selected date and navigate to its month."""
        self._cal.setSelectedDate(qdate)
        self._cal.setCurrentPage(qdate.year(), qdate.month())
        self._sync_combos(qdate.year(), qdate.month())

    def show_at(self, widget: QWidget):
        """Position popup below *widget* and show it."""
        self.adjustSize()
        pos = widget.mapToGlobal(QPoint(0, widget.height()))
        screen = widget.screen().availableGeometry()
        if pos.x() + self.width() > screen.right():
            pos.setX(screen.right() - self.width())
        if pos.y() + self.height() > screen.bottom():
            pos.setY(widget.mapToGlobal(QPoint(0, 0)).y() - self.height())
        self.move(pos)
        self.show()
        self.setFocus()

    # ── internal ──────────────────────────────────────────────────

    def _sync_combos(self, year: int, month: int):
        """Update combo boxes to reflect *year*/*month* (no signal loop)."""
        self._syncing = True
        idx = self._year_combo.findData(year)
        if idx >= 0:
            self._year_combo.setCurrentIndex(idx)
        idx = self._month_combo.findData(month)
        if idx >= 0:
            self._month_combo.setCurrentIndex(idx)
        self._syncing = False

    def _on_combo_changed(self):
        if self._syncing:
            return
        year = self._year_combo.currentData()
        month = self._month_combo.currentData()
        if year is not None and month is not None:
            self._cal.setCurrentPage(year, month)

    def _on_page_changed(self, year: int, month: int):
        """Calendar page changed (e.g. via keyboard) — sync combos."""
        self._sync_combos(year, month)

    def _on_date_clicked(self, qdate: QDate):
        self.date_selected.emit(qdate)
        self.close()

    def _go_prev(self):
        self._cal.showPreviousMonth()

    def _go_next(self):
        self._cal.showNextMonth()


# ── Main widget ───────────────────────────────────────────────────────


class DateEdit(QWidget):
    """Date input: QLineEdit for free-text + calendar popup + clear button.

    Drop-in replacement for the QDateEdit + QPushButton(x) pair used
    across all tabs.  Provides backward-compatible ``date()`` and
    ``setDate()`` so existing value-reading code works without changes.

    The widget is styled as a single cohesive input field (objectName
    "dateEdit") with the calendar and clear buttons embedded in the
    right side — matching the visual style of QComboBox.
    """

    date_changed = Signal(QDate)
    cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dateEdit")
        self._date: QDate | None = None
        self._popup: _CalendarPopup | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 0, 0)
        layout.setSpacing(0)

        self._line = QLineEdit()
        self._line.setPlaceholderText("yyyy-MM-dd")
        self._line.setMaxLength(10)
        self._line.editingFinished.connect(self._commit_text)
        self._line.setFocusPolicy(Qt.StrongFocus)
        # Forward child focus events to update container border
        self._line.installEventFilter(self)

        self._cal_btn = QToolButton()
        self._cal_btn.setObjectName("dateEditCalBtn")
        self._cal_btn.setText("\u25BE")  # ▾
        self._cal_btn.setFixedWidth(20)
        self._cal_btn.setToolTip("\u9009\u62e9\u65e5\u671f")
        self._cal_btn.clicked.connect(self._toggle_calendar)

        self._clear_btn = QToolButton()
        self._clear_btn.setObjectName("dateEditClearBtn")
        self._clear_btn.setText("\u00d7")  # x
        self._clear_btn.setFixedWidth(18)
        self._clear_btn.setToolTip("\u6e05\u9664\u65e5\u671f")
        self._clear_btn.clicked.connect(self.clear)

        layout.addWidget(self._line, 1)
        layout.addWidget(self._cal_btn)
        layout.addWidget(self._clear_btn)

        self.setFixedHeight(32)
        self.setMinimumWidth(130)
        self.setMaximumWidth(160)

    # ── event filter for focus border ─────────────────────────────

    def eventFilter(self, obj, event):
        if obj is self._line:
            et = event.type()
            if et == event.Type.FocusIn:
                self.setProperty("focused", True)
                self.style().unpolish(self)
                self.style().polish(self)
            elif et == event.Type.FocusOut:
                self.setProperty("focused", False)
                self.style().unpolish(self)
                self.style().polish(self)
        return super().eventFilter(obj, event)

    # ── public API (backward-compatible with QDateEdit) ───────────

    def date(self) -> QDate:
        """Return current QDate, or the sentinel QDate(2000,1,1) if empty."""
        if self._date is not None:
            return self._date
        return _SENTINEL

    def setDate(self, qdate: QDate):
        """Set the date. Passing the sentinel or an invalid date clears."""
        if not qdate.isValid() or qdate == _SENTINEL:
            self.clear()
            return
        self._date = qdate
        self._line.setText(qdate.toString(_DATE_FMT))
        self._line.setStyleSheet("")
        self.date_changed.emit(qdate)

    def date_str(self) -> str:
        """Return ``"yyyy-MM-dd"`` or ``""`` if empty."""
        if self._date is not None:
            return self._date.toString(_DATE_FMT)
        return ""

    def setDateString(self, text: str):
        """Set from ``"yyyy-MM-dd"`` string. Empty/clears on failure."""
        if text and len(text) == 10:
            d = QDate.fromString(text, _DATE_FMT)
            if d.isValid() and d.year() >= 2000:
                self.setDate(d)
                return
        self.clear()

    def clear(self):
        """Clear the date field."""
        changed = self._date is not None
        self._date = None
        self._line.clear()
        self._line.setStyleSheet("")
        if changed:
            self.cleared.emit()

    def isEmpty(self) -> bool:
        """True when no date is set."""
        return self._date is None

    # ── calendar popup ────────────────────────────────────────────

    def _toggle_calendar(self):
        if self._popup and self._popup.isVisible():
            self._popup.close()
            return
        self._popup = _CalendarPopup(self)
        if self._date:
            self._popup.set_date(self._date)
        else:
            self._popup.set_date(QDate.currentDate())
        self._popup.date_selected.connect(self._on_cal_selected)
        self._popup.show_at(self)

    def _on_cal_selected(self, qdate: QDate):
        self.setDate(qdate)

    # ── text input validation ─────────────────────────────────────

    def _commit_text(self):
        """Validate the typed text and update internal state."""
        text = self._line.text().strip()
        if not text:
            self.clear()
            return

        d = QDate.fromString(text, _DATE_FMT)
        if d.isValid() and d.year() >= 2000:
            self._date = d
            self._line.setText(d.toString(_DATE_FMT))
            self._line.setStyleSheet("")
            self.date_changed.emit(d)
        else:
            # Invalid input — red flash on container border, then revert
            c = _current_colors()
            self.setStyleSheet(
                f"QWidget#dateEdit {{ border: 1.5px solid {c['error']}; }}"
            )
            if self._date:
                self._line.setText(self._date.toString(_DATE_FMT))
            else:
                self._line.clear()
            # Revert border after 1.5s
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1500, self._revert_border)

    def _revert_border(self):
        self.setStyleSheet("")
