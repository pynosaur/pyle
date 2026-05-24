#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: @spacemany2k38
# 2026-04-08

import curses
import shutil
import time
from pathlib import Path
from .scanner import (
    LazyScanner,
    format_size, size_ratio, bar_string,
    invalidate_cache,
)


COLOR_DIR = 1
COLOR_FILE = 2
COLOR_SYMLINK = 3
COLOR_ERROR = 4
COLOR_BAR_LOW = 5
COLOR_BAR_MED = 6
COLOR_BAR_HIGH = 7
COLOR_HEADER = 8
COLOR_SELECTED = 9
COLOR_STATUS = 10
COLOR_PERCENT = 11


def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(COLOR_DIR, curses.COLOR_BLUE, -1)
    curses.init_pair(COLOR_FILE, curses.COLOR_WHITE, -1)
    curses.init_pair(COLOR_SYMLINK, curses.COLOR_CYAN, -1)
    curses.init_pair(COLOR_ERROR, curses.COLOR_RED, -1)
    curses.init_pair(COLOR_BAR_LOW, curses.COLOR_GREEN, -1)
    curses.init_pair(COLOR_BAR_MED, curses.COLOR_YELLOW, -1)
    curses.init_pair(COLOR_BAR_HIGH, curses.COLOR_RED, -1)
    curses.init_pair(COLOR_HEADER, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(COLOR_SELECTED, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(COLOR_STATUS, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(COLOR_PERCENT, curses.COLOR_MAGENTA, -1)


def bar_color(ratio):
    if ratio >= 0.5:
        return COLOR_BAR_HIGH
    if ratio >= 0.2:
        return COLOR_BAR_MED
    return COLOR_BAR_LOW


def _safe_addnstr(stdscr, row, col, text, length, attr=0):
    try:
        stdscr.addnstr(row, col, text, length, attr)
    except curses.error:
        pass


_SPINNER = "|/-\\"


def draw_header(stdscr, current_path, total_size, max_x, scanner, tick=0):
    header = f" pyle: {current_path}"
    if scanner.is_paused:
        total_str = "[paused] "
    elif scanner.is_scanning:
        spin = _SPINNER[tick % len(_SPINNER)]
        dirs = scanner.dirs_count
        if dirs > 0:
            done = scanner.dirs_sized
            pct = int(done * 100 / dirs)
            total_str = f"[{spin}] {pct}% ({done}/{dirs}) {format_size(total_size)} "
        else:
            total_str = f"[{spin}] scanning... "
    else:
        total_str = f"Size: {format_size(total_size)} "
    pad = max(0, max_x - len(header) - len(total_str))
    line = (header + " " * pad + total_str)[:max_x]
    stdscr.attron(curses.color_pair(COLOR_HEADER) | curses.A_BOLD)
    _safe_addnstr(stdscr, 0, 0, line.ljust(max_x), max_x)
    stdscr.attroff(curses.color_pair(COLOR_HEADER) | curses.A_BOLD)


def draw_entry(stdscr, row, entry, total, selected, max_x, bar_width):
    if row < 0:
        return

    ratio = size_ratio(entry["size"], total)
    pct = ratio * 100
    size_str = format_size(entry["size"])
    pct_str = f"{pct:3.0f}%" if entry["size"] >= 0 else "  -"
    bar = bar_string(ratio, bar_width)

    name = entry["name"]
    if entry["is_dir"]:
        name += "/"
    if entry["is_symlink"]:
        name = "@ " + name
    if entry["error"]:
        name += " [!]"

    size_col = 1
    pct_col = size_col + 8
    bar_col = pct_col + 5
    name_col = bar_col + bar_width + 4

    available = max_x - name_col - 1
    if available > 0 and len(name) > available:
        name = name[:available - 1] + "~"

    if selected:
        stdscr.attron(curses.color_pair(COLOR_SELECTED))
        _safe_addnstr(stdscr, row, 0, " " * max_x, max_x)
        stdscr.attroff(curses.color_pair(COLOR_SELECTED))

    attr = curses.color_pair(COLOR_SELECTED) if selected else 0

    _safe_addnstr(
        stdscr, row, size_col, f"{size_str:>7}", 7,
        attr | curses.A_BOLD,
    )

    pct_attr = attr if selected else curses.color_pair(COLOR_PERCENT)
    _safe_addnstr(stdscr, row, pct_col, pct_str, 6, pct_attr)

    bc = bar_color(ratio)
    b_attr = attr if selected else curses.color_pair(bc)
    _safe_addnstr(stdscr, row, bar_col, "[", 1, attr)
    _safe_addnstr(
        stdscr, row, bar_col + 1, bar, bar_width,
        b_attr | curses.A_BOLD,
    )
    _safe_addnstr(stdscr, row, bar_col + 1 + bar_width, "]", 1, attr)

    if available > 0:
        if selected:
            name_attr = curses.color_pair(COLOR_SELECTED) | curses.A_BOLD
        elif entry["error"]:
            name_attr = curses.color_pair(COLOR_ERROR)
        elif entry["is_symlink"]:
            name_attr = curses.color_pair(COLOR_SYMLINK)
        elif entry["is_dir"]:
            name_attr = curses.color_pair(COLOR_DIR) | curses.A_BOLD
        else:
            name_attr = curses.color_pair(COLOR_FILE)
        _safe_addnstr(stdscr, row, name_col, name, available, name_attr)


def draw_status(stdscr, row, scanner, entries, cursor, max_x):
    entry = entries[cursor] if entries else None
    dirs = scanner.dirs_count
    files = scanner.files_count

    left = f" {dirs} dirs, {files} files"
    if not scanner.listing_done:
        left += " [listing...]"
    elif scanner.is_scanning:
        done = scanner.dirs_sized
        left += f" [{done}/{dirs} sized]"

    right = ""
    if entry:
        name = entry['name']
        if entry['is_dir']:
            name += '/'
        right = f" {name} {format_size(entry['size'])} "

    pad = max(0, max_x - len(left) - len(right))
    line = (left + " " * pad + right)[:max_x]

    stdscr.attron(curses.color_pair(COLOR_STATUS))
    _safe_addnstr(stdscr, row, 0, line.ljust(max_x), max_x)
    stdscr.attroff(curses.color_pair(COLOR_STATUS))


def draw_help(stdscr, row, max_x):
    keys = (" q:quit  jk:nav  l/enter:open"
            "  h:back  d:del  r:refresh  s:sort  p:pause  space:search"
            "  [/]:top/bottom")
    _safe_addnstr(stdscr, row, 0, keys[:max_x], max_x, curses.A_DIM)


def draw_search_bar(stdscr, row, query, max_x):
    prompt = "/"
    bar = f"{prompt}{query}"
    # Draw highlighted background across the whole row
    stdscr.attron(curses.color_pair(COLOR_STATUS))
    _safe_addnstr(stdscr, row, 0, " " * max_x, max_x)
    stdscr.attroff(curses.color_pair(COLOR_STATUS))
    _safe_addnstr(stdscr, row, 0, bar[:max_x], max_x,
        curses.color_pair(COLOR_STATUS) | curses.A_BOLD)
    # Show cursor position
    cursor_col = min(len(bar), max_x - 1)
    try:
        stdscr.move(row, cursor_col)
    except curses.error:
        pass


def _wait_listing(scanner, stdscr, path, max_x):
    """Wait briefly for listing phase so we can locate the old cursor entry.
    Shows spinner while waiting, gives up after 500ms."""
    deadline = time.monotonic() + 0.5
    t = 0
    while not scanner.listing_done:
        if time.monotonic() > deadline:
            break
        t += 1
        spin = _SPINNER[t % len(_SPINNER)]
        header = f" pyle: {path}"
        right = f"[{spin}] listing... "
        pad = max(0, max_x - len(header) - len(right))
        line = (header + " " * pad + right)[:max_x]
        try:
            stdscr.addnstr(0, 0, line.ljust(max_x), max_x)
            stdscr.refresh()
        except curses.error:
            pass
        time.sleep(0.05)


def _draw_confirm_dialog(stdscr, name, max_y, max_x):
    """Draw ncdu-style centered delete confirmation dialog.
    Returns: 'yes', 'no', or 'never'."""
    title = " Confirm delete "
    question = f'Are you sure you want to delete "{name}"?'
    options = ["yes", "no", "don't ask me again"]

    box_w = max(len(question) + 4, 44)
    box_h = 7
    top = (max_y - box_h) // 2
    left = (max_x - box_w) // 2

    selected = 1

    stdscr.timeout(-1)

    while True:
        win = curses.newwin(box_h, box_w, top, left)
        win.erase()
        win.border()

        tl = (box_w - len(title)) // 2
        try:
            win.addnstr(0, tl, title, len(title), curses.A_BOLD)
        except curses.error:
            pass

        ql = (box_w - len(question)) // 2
        try:
            win.addnstr(2, ql, question, len(question))
        except curses.error:
            pass

        col = 4
        for i, label in enumerate(options):
            if i == selected:
                attr = curses.A_REVERSE | curses.A_BOLD
            else:
                attr = curses.A_NORMAL
            try:
                win.addnstr(4, col, label, len(label), attr)
            except curses.error:
                pass
            col += len(label) + 4

        win.refresh()

        key = stdscr.getch()
        if key == curses.KEY_LEFT or key == ord("h"):
            selected = (selected - 1) % len(options)
        elif key == curses.KEY_RIGHT or key == ord("l"):
            selected = (selected + 1) % len(options)
        elif key == ord("\t"):
            selected = (selected + 1) % len(options)
        elif key in (ord("\n"), curses.KEY_ENTER, ord(" ")):
            break
        elif key == ord("y") or key == ord("Y"):
            selected = 0
            break
        elif key == ord("n") or key == ord("N") or key == 27:
            selected = 1
            break

    stdscr.timeout(100)
    del win

    return ["yes", "no", "never"][selected]


def _sort_entries(entries, by_name):
    if by_name:
        entries.sort(key=lambda e: e["name"].lower())
    else:
        entries.sort(key=lambda e: e["size"], reverse=True)


def run_ui(stdscr, start_path):
    curses.curs_set(0)
    init_colors()
    stdscr.timeout(100)

    history = []
    current_path = Path(start_path).resolve()
    scanner = LazyScanner(current_path)
    entries = scanner.entries
    all_entries = entries          # unfiltered reference
    disk_total = shutil.disk_usage(current_path).total
    total = 0
    cursor = 0
    scroll_offset = 0
    sort_by_name = False
    skip_confirm = False
    tick = 0

    # Search state
    search_mode = False
    search_query = ""
    filtered_entries = None       # None = no active filter

    while True:
        tick += 1

        if scanner.dirty.is_set():
            scanner.dirty.clear()
            total = min(
                sum(e["size"] for e in all_entries if e["size"] > 0),
                disk_total,
            )
            _sort_entries(all_entries, sort_by_name)
            if search_query:
                filtered_entries = [
                    e for e in all_entries
                    if search_query.lower() in e["name"].lower()
                ]
                entries = filtered_entries
            else:
                entries = all_entries

        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        if max_y < 5 or max_x < 40:
            _safe_addnstr(stdscr, 0, 0, "Terminal too small", 18)
            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord("q"), ord("Q")):
                scanner.stop()
                break
            continue

        bar_width = min(20, max(8, (max_x - 30) // 3))

        draw_header(stdscr, str(current_path), total, max_x, scanner, tick)

        content_start = 1
        content_end = max_y - 2
        visible_rows = content_end - content_start

        if cursor >= len(entries) and entries:
            cursor = len(entries) - 1

        if cursor < scroll_offset:
            scroll_offset = cursor
        elif cursor >= scroll_offset + visible_rows:
            scroll_offset = cursor - visible_rows + 1

        if not entries:
            if scanner.listing_done:
                msg = "(empty directory)"
            else:
                spin = _SPINNER[tick % len(_SPINNER)]
                msg = f"[{spin}] loading..."
            _safe_addnstr(
                stdscr, content_start, 2,
                msg, len(msg), curses.A_DIM,
            )
        else:
            for i in range(visible_rows):
                idx = scroll_offset + i
                if idx >= len(entries):
                    break
                draw_entry(
                    stdscr, content_start + i, entries[idx],
                    total, idx == cursor, max_x, bar_width,
                )

        draw_status(stdscr, max_y - 2, scanner, entries, cursor, max_x)
        if search_mode:
            curses.curs_set(1)
            draw_search_bar(stdscr, max_y - 1, search_query, max_x)
        else:
            curses.curs_set(0)
            draw_help(stdscr, max_y - 1, max_x)

        stdscr.refresh()

        key = stdscr.getch()

        if key == -1:
            continue

        # ── Search mode input ─────────────────────────────────────────────
        if search_mode:
            if key in (27, curses.KEY_F1):          # Esc — clear and exit
                search_mode = False
                search_query = ""
                entries = all_entries
                cursor = 0
                scroll_offset = 0
            elif key in (ord("\n"), curses.KEY_ENTER):  # Enter — confirm
                search_mode = False
                cursor = 0
                scroll_offset = 0
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                search_query = search_query[:-1]
                entries = [
                    e for e in all_entries
                    if search_query.lower() in e["name"].lower()
                ] if search_query else all_entries
                cursor = 0
                scroll_offset = 0
            elif 32 <= key <= 126:                  # printable char
                search_query += chr(key)
                entries = [
                    e for e in all_entries
                    if search_query.lower() in e["name"].lower()
                ]
                cursor = 0
                scroll_offset = 0
            continue
        # ── Normal mode input ─────────────────────────────────────────────

        if key in (ord("q"), ord("Q"), 27):
            scanner.stop()
            break

        elif key == ord(" "):          # spacebar — open/close search
            search_mode = not search_mode
            if search_mode:
                search_query = ""
                entries = all_entries
                cursor = 0
                scroll_offset = 0
            else:
                # closing without Enter clears the filter
                search_query = ""
                entries = all_entries
                cursor = 0
                scroll_offset = 0

        elif key == curses.KEY_UP or key == ord("k"):
            if cursor > 0:
                cursor -= 1

        elif key == curses.KEY_DOWN or key == ord("j"):
            if entries and cursor < len(entries) - 1:
                cursor += 1

        elif key in (
            curses.KEY_RIGHT, ord("l"), ord("\n"), curses.KEY_ENTER,
        ):
            if (entries and cursor < len(entries)
                    and entries[cursor]["is_dir"]
                    and not entries[cursor]["error"]):
                scanner.stop()
                history.append((
                    current_path, cursor, scroll_offset,
                    scanner, all_entries, total, disk_total,
                ))
                current_path = entries[cursor]["path"]
                disk_total = shutil.disk_usage(current_path).total
                scanner = LazyScanner(current_path)
                all_entries = scanner.entries
                entries = all_entries
                total = 0
                cursor = 0
                scroll_offset = 0
                search_mode = False
                search_query = ""

        elif key == curses.KEY_LEFT or key == ord("h"):
            if history:
                scanner.stop()
                prev = history.pop()
                current_path = prev[0]
                cursor = prev[1]
                scroll_offset = prev[2]
                scanner = prev[3]
                all_entries = prev[4]
                entries = all_entries
                total = prev[5]
                disk_total = prev[6]
                search_mode = False
                search_query = ""
            elif current_path.parent != current_path:
                scanner.stop()
                old_name = current_path.name
                current_path = current_path.parent
                disk_total = shutil.disk_usage(current_path).total
                scanner = LazyScanner(current_path)
                all_entries = scanner.entries
                entries = all_entries
                total = 0
                search_mode = False
                search_query = ""
                _wait_listing(scanner, stdscr, current_path, max_x)
                _sort_entries(entries, sort_by_name)
                cursor = 0
                for i, e in enumerate(entries):
                    if e["name"] == old_name:
                        cursor = i
                        break
                scroll_offset = max(0, cursor - visible_rows // 2)

        elif key == ord("r"):
            scanner.stop()
            invalidate_cache(str(current_path))
            disk_total = shutil.disk_usage(current_path).total
            scanner = LazyScanner(current_path)
            all_entries = scanner.entries
            entries = all_entries
            total = 0
            search_mode = False
            search_query = ""
            if cursor >= len(entries):
                cursor = max(0, len(entries) - 1)

        elif key == ord("s"):
            sort_by_name = not sort_by_name
            _sort_entries(all_entries, sort_by_name)
            if search_query:
                entries = [
                    e for e in all_entries
                    if search_query.lower() in e["name"].lower()
                ]

        elif key == ord("p"):
            scanner.toggle_pause()

        elif key == ord("d"):
            if entries and cursor < len(entries):
                entry = entries[cursor]
                target = entry["path"]
                if skip_confirm:
                    choice = "yes"
                else:
                    choice = _draw_confirm_dialog(
                        stdscr, entry["name"], max_y, max_x,
                    )
                if choice == "never":
                    skip_confirm = True
                    choice = "yes"
                if choice == "yes":
                    deleter = _AsyncDelete(target)
                    dt = 0
                    while not deleter.done:
                        dt += 1
                        spin = _SPINNER[dt % len(_SPINNER)]
                        with deleter._lock:
                            cur = deleter.current
                        if len(cur) > max_x - 30:
                            cur = cur[:max_x - 33] + "..."
                        msg = (
                            f" [{spin}] Deleting... "
                            f"{deleter.count} removed  {cur}"
                        )
                        stdscr.move(max_y - 1, 0)
                        stdscr.clrtoeol()
                        _safe_addnstr(
                            stdscr, max_y - 1, 0,
                            msg.ljust(max_x)[:max_x], max_x,
                            curses.color_pair(COLOR_ERROR),
                        )
                        stdscr.refresh()
                        time.sleep(0.05)
                    if deleter.error is None:
                        removed = entries.pop(cursor)
                        # Also remove from the unfiltered list if filtering
                        if entries is not all_entries:
                            try:
                                all_entries.remove(removed)
                            except ValueError:
                                pass
                        if removed["is_dir"]:
                            scanner.dirs_count -= 1
                        else:
                            scanner.files_count -= 1
                        if removed["size"] > 0:
                            total -= removed["size"]
                        invalidate_cache(str(target))
                        if cursor >= len(entries) and entries:
                            cursor = len(entries) - 1

        elif key == curses.KEY_PPAGE:
            cursor = max(0, cursor - visible_rows)

        elif key == curses.KEY_NPAGE:
            if entries:
                cursor = min(len(entries) - 1, cursor + visible_rows)

        elif key == curses.KEY_HOME or key == ord("g") or key == ord("["):
            cursor = 0
            scroll_offset = 0

        elif key == ord("G") or key == ord("]"):
            if entries:
                cursor = max(0, len(entries) - 1)


import threading


class _AsyncDelete:
    """Delete a path in a background thread with progress tracking."""

    def __init__(self, path):
        self.path = path
        self.count = 0
        self.current = ""
        self.done = False
        self.error = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run, daemon=True,
        )
        self._thread.start()

    def _run(self):
        try:
            if self.path.is_file() or self.path.is_symlink():
                with self._lock:
                    self.current = self.path.name
                self.path.unlink()
                self.count = 1
            elif self.path.is_dir():
                self._rmtree(self.path)
        except OSError as exc:
            self.error = str(exc)
        self.done = True

    def _rmtree(self, path):
        try:
            for child in path.iterdir():
                if child.is_dir() and not child.is_symlink():
                    self._rmtree(child)
                else:
                    with self._lock:
                        self.current = child.name
                    try:
                        child.unlink()
                        self.count += 1
                    except OSError:
                        pass
            path.rmdir()
        except OSError:
            pass
