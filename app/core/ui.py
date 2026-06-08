#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: @spacemany2k38
# 2026-04-08

import curses
import os
import shutil
import stat
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


def draw_header(stdscr, current_path, total_size, max_x, scanner, tick=0,
                disk_used=None, disk_total=None):
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
    elif disk_used is not None and disk_total is not None:
        total_str = (
            f"Size: {format_size(total_size)}  "
            f"Disk: {format_size(disk_used)}/{format_size(disk_total)} "
        )
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
            "  b:bubble  [/]:top/bottom")
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


# ── Bubble (treemap) view ──────────────────────────────────────────────────

COLOR_BUBBLE_1 = 12
COLOR_BUBBLE_2 = 13
COLOR_BUBBLE_3 = 14
COLOR_BUBBLE_4 = 15
COLOR_BUBBLE_5 = 16
COLOR_BUBBLE_6 = 17
COLOR_BUBBLE_SEL = 18

_BUBBLE_PALETTE = [
    COLOR_BUBBLE_1, COLOR_BUBBLE_2, COLOR_BUBBLE_3,
    COLOR_BUBBLE_4, COLOR_BUBBLE_5, COLOR_BUBBLE_6,
]


def _init_bubble_colors():
    curses.init_pair(COLOR_BUBBLE_1, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(COLOR_BUBBLE_2, curses.COLOR_WHITE, curses.COLOR_GREEN)
    curses.init_pair(COLOR_BUBBLE_3, curses.COLOR_BLACK, curses.COLOR_YELLOW)
    curses.init_pair(COLOR_BUBBLE_4, curses.COLOR_WHITE, curses.COLOR_MAGENTA)
    curses.init_pair(COLOR_BUBBLE_5, curses.COLOR_WHITE, curses.COLOR_CYAN)
    curses.init_pair(COLOR_BUBBLE_6, curses.COLOR_WHITE, curses.COLOR_RED)
    curses.init_pair(
        COLOR_BUBBLE_SEL, curses.COLOR_BLACK, curses.COLOR_WHITE,
    )


def _squarify(items, x, y, w, h):
    """Squarified treemap layout.

    *items* is a list of (entry, area) sorted descending by area.
    Returns a list of (entry, rx, ry, rw, rh) rectangles that tile
    the (x, y, w, h) region with aspect ratios as close to 1:1 as
    possible.
    """
    if not items or w < 1 or h < 1:
        return []

    total = sum(a for _, a in items)
    if total <= 0:
        return []

    results = []
    remaining = list(items)

    while remaining:
        if w < 1 or h < 1:
            break

        vertical = h >= w
        span = h if vertical else w

        row = []
        row_area = 0
        best_worst = float('inf')

        for ent, area in remaining:
            trial = row + [(ent, area)]
            trial_area = row_area + area
            trial_span = span * trial_area / total if total else span

            if trial_span < 1:
                row = trial
                row_area = trial_area
                continue

            worst = 0
            for _, a in trial:
                frac = a / trial_area if trial_area else 0
                cell_len = frac * span
                cell_w_d = trial_span
                if cell_len > 0 and cell_w_d > 0:
                    aspect = max(cell_len / cell_w_d, cell_w_d / cell_len)
                    worst = max(worst, aspect)

            if worst <= best_worst:
                best_worst = worst
                row = trial
                row_area = trial_area
            else:
                break

        if not row:
            row = [remaining[0]]
            row_area = remaining[0][1]

        row_frac = row_area / total if total else 0
        if vertical:
            row_h = max(1, round(h * row_frac))
            cx = x
            for ent, area in row:
                frac = area / row_area if row_area else 0
                cell_w = max(1, round(w * frac))
                if cx + cell_w > x + w:
                    cell_w = x + w - cx
                results.append((ent, cx, y, cell_w, row_h))
                cx += cell_w
            y += row_h
            h -= row_h
        else:
            row_w = max(1, round(w * row_frac))
            cy = y
            for ent, area in row:
                frac = area / row_area if row_area else 0
                cell_h = max(1, round(h * frac))
                if cy + cell_h > y + h:
                    cell_h = y + h - cy
                results.append((ent, x, cy, row_w, cell_h))
                cy += cell_h
            x += row_w
            w -= row_w

        remaining = remaining[len(row):]
        total -= row_area

    return results


def _draw_bubble_rect(stdscr, entry, rx, ry, rw, rh, color, max_y, max_x):
    """Fill a rectangle with a background color and draw the entry label."""
    attr = curses.color_pair(color)
    fill = ' ' * rw

    for row in range(ry, min(ry + rh, max_y)):
        _safe_addnstr(stdscr, row, rx, fill, min(rw, max_x - rx), attr)

    if rh < 1 or rw < 3:
        return

    name = entry["name"]
    if entry["is_dir"]:
        name += "/"
    size_str = format_size(entry["size"])

    label = name
    if rw >= len(name) + len(size_str) + 2:
        label = f"{name} {size_str}"
    elif len(name) > rw - 2:
        label = name[:max(1, rw - 3)] + "~"

    label = label[:max(0, rw - 2)]
    lx = rx + 1
    ly = ry + rh // 2

    if ly < max_y and lx + len(label) <= max_x:
        _safe_addnstr(stdscr, ly, lx, label, len(label), attr | curses.A_BOLD)


def _draw_bubble_selection(stdscr, rx, ry, rw, rh, max_y, max_x):
    """Draw a highlighted border around the selected bubble."""
    attr = curses.color_pair(COLOR_BUBBLE_SEL) | curses.A_BOLD

    if ry < max_y and rw >= 1:
        border_top = '+' + '-' * max(0, rw - 2) + '+'
        _safe_addnstr(
            stdscr, ry, rx,
            border_top[:min(rw, max_x - rx)],
            min(rw, max_x - rx), attr,
        )

    if ry + rh - 1 < max_y and ry + rh - 1 != ry and rw >= 1:
        border_bot = '+' + '-' * max(0, rw - 2) + '+'
        _safe_addnstr(
            stdscr, ry + rh - 1, rx,
            border_bot[:min(rw, max_x - rx)],
            min(rw, max_x - rx), attr,
        )

    for row in range(ry + 1, min(ry + rh - 1, max_y)):
        if rx < max_x:
            _safe_addnstr(stdscr, row, rx, '|', 1, attr)
        if rx + rw - 1 < max_x and rw > 1:
            _safe_addnstr(stdscr, row, rx + rw - 1, '|', 1, attr)


def _bubble_nav_closest(rects, cur_idx, direction):
    """Find the nearest rectangle in the given direction.
    direction: 'up', 'down', 'left', 'right'."""
    if not rects or cur_idx >= len(rects):
        return cur_idx

    _, cx, cy, cw, ch = rects[cur_idx]
    cmx = cx + cw / 2
    cmy = cy + ch / 2

    best = cur_idx
    best_dist = float('inf')

    for i, (_, rx, ry, rw, rh) in enumerate(rects):
        if i == cur_idx:
            continue
        mx = rx + rw / 2
        my = ry + rh / 2

        ok = False
        if direction == 'up' and my < cmy:
            ok = True
        elif direction == 'down' and my > cmy:
            ok = True
        elif direction == 'left' and mx < cmx:
            ok = True
        elif direction == 'right' and mx > cmx:
            ok = True

        if ok:
            dx = mx - cmx
            dy = my - cmy
            dist = dx * dx + dy * dy
            if dist < best_dist:
                best_dist = dist
                best = i

    return best


def draw_bubble_help(stdscr, row, max_x):
    keys = (" q:quit  arrows:nav  enter:open"
            "  h/left:back  b:list view  r:refresh")
    _safe_addnstr(stdscr, row, 0, keys[:max_x], max_x, curses.A_DIM)


def run_ui(stdscr, start_path):
    curses.curs_set(0)
    init_colors()
    _init_bubble_colors()
    stdscr.timeout(100)

    history = []
    current_path = Path(start_path).resolve()
    scanner = LazyScanner(current_path)
    entries = scanner.entries
    all_entries = entries          # unfiltered reference
    _du = shutil.disk_usage(current_path)
    disk_total = _du.total
    disk_used = _du.used
    total = 0
    cursor = 0
    scroll_offset = 0
    sort_by_name = False
    skip_confirm = False
    tick = 0
    last_recompute = 0.0          # throttle dirty-driven recompute

    # Search state
    search_mode = False
    search_query = ""
    filtered_entries = None       # None = no active filter

    # Bubble view state
    bubble_mode = False
    bubble_cursor = 0
    bubble_rects = []

    while True:
        tick += 1

        # Recompute total + sort only ~4x/sec while scanning. The scanner
        # fires `dirty` after every child file across many threads; doing a
        # full re-sum and re-sort on each event pins the UI thread and makes
        # large scans feel like they "load forever". Always do a final pass
        # once sizing finishes so the numbers settle exactly.
        now = time.monotonic()
        if scanner.dirty.is_set() and (
            now - last_recompute > 0.25 or scanner.sizing_done
        ):
            scanner.dirty.clear()
            last_recompute = now
            total = sum(e["size"] for e in all_entries if e["size"] > 0)
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

        # Refresh real disk usage for the current path's volume (cheap stat).
        try:
            _du = shutil.disk_usage(current_path)
            disk_total = _du.total
            disk_used = _du.used
        except OSError:
            pass

        draw_header(
            stdscr, str(current_path), total, max_x, scanner, tick,
            disk_used, disk_total,
        )

        content_start = 1
        content_end = max_y - 2
        visible_rows = content_end - content_start

        if bubble_mode:
            # ── Bubble (treemap) rendering ──────────────────────────
            sized = [
                e for e in entries if e["size"] > 0
            ]
            if not sized:
                if scanner.listing_done:
                    msg = "(empty directory)"
                else:
                    spin = _SPINNER[tick % len(_SPINNER)]
                    msg = f"[{spin}] loading..."
                _safe_addnstr(
                    stdscr, content_start, 2,
                    msg, len(msg), curses.A_DIM,
                )
                bubble_rects = []
            else:
                sized.sort(key=lambda e: e["size"], reverse=True)
                items = [(e, e["size"]) for e in sized]
                bx = 0
                by = content_start
                bw = max_x
                bh = visible_rows
                bubble_rects = _squarify(items, bx, by, bw, bh)

                if bubble_cursor >= len(bubble_rects):
                    bubble_cursor = max(0, len(bubble_rects) - 1)

                for i, (ent, rx, ry, rw, rh) in enumerate(bubble_rects):
                    ci = i % len(_BUBBLE_PALETTE)
                    _draw_bubble_rect(
                        stdscr, ent, rx, ry, rw, rh,
                        _BUBBLE_PALETTE[ci], max_y, max_x,
                    )

                if bubble_rects:
                    _, sx, sy, sw, sh = bubble_rects[bubble_cursor]
                    _draw_bubble_selection(
                        stdscr, sx, sy, sw, sh, max_y, max_x,
                    )

            sel_entry = None
            if bubble_rects and bubble_cursor < len(bubble_rects):
                sel_entry = bubble_rects[bubble_cursor][0]

            left_info = f" {len(entries)} items"
            right_info = ""
            if sel_entry:
                sn = sel_entry['name']
                if sel_entry['is_dir']:
                    sn += '/'
                right_info = f" {sn} {format_size(sel_entry['size'])} "
            pad = max(0, max_x - len(left_info) - len(right_info))
            stat_line = (left_info + " " * pad + right_info)[:max_x]
            stdscr.attron(curses.color_pair(COLOR_STATUS))
            _safe_addnstr(
                stdscr, max_y - 2, 0, stat_line.ljust(max_x), max_x,
            )
            stdscr.attroff(curses.color_pair(COLOR_STATUS))

            curses.curs_set(0)
            draw_bubble_help(stdscr, max_y - 1, max_x)

        else:
            # ── List view rendering ─────────────────────────────────
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

            draw_status(
                stdscr, max_y - 2, scanner, entries, cursor, max_x,
            )
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

        # ── Bubble mode input ─────────────────────────────────────────────
        if bubble_mode:
            if key in (ord("q"), ord("Q"), 27):
                scanner.stop()
                break

            elif key == ord("b"):
                bubble_mode = False

            elif key == curses.KEY_UP or key == ord("k"):
                bubble_cursor = _bubble_nav_closest(
                    bubble_rects, bubble_cursor, 'up',
                )

            elif key == curses.KEY_DOWN or key == ord("j"):
                bubble_cursor = _bubble_nav_closest(
                    bubble_rects, bubble_cursor, 'down',
                )

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
                    bubble_cursor = 0
                elif current_path.parent != current_path:
                    scanner.stop()
                    current_path = current_path.parent
                    disk_total = shutil.disk_usage(current_path).total
                    scanner = LazyScanner(current_path)
                    all_entries = scanner.entries
                    entries = all_entries
                    total = 0
                    search_mode = False
                    search_query = ""
                    bubble_cursor = 0
                else:
                    bubble_cursor = _bubble_nav_closest(
                        bubble_rects, bubble_cursor, 'left',
                    )

            elif key == curses.KEY_RIGHT:
                bubble_cursor = _bubble_nav_closest(
                    bubble_rects, bubble_cursor, 'right',
                )

            elif key in (ord("l"), ord("\n"), curses.KEY_ENTER):
                if (bubble_rects
                        and bubble_cursor < len(bubble_rects)):
                    sel = bubble_rects[bubble_cursor][0]
                    if sel["is_dir"] and not sel["error"]:
                        scanner.stop()
                        history.append((
                            current_path, cursor, scroll_offset,
                            scanner, all_entries, total, disk_total,
                        ))
                        current_path = sel["path"]
                        disk_total = shutil.disk_usage(
                            current_path,
                        ).total
                        scanner = LazyScanner(current_path)
                        all_entries = scanner.entries
                        entries = all_entries
                        total = 0
                        cursor = 0
                        scroll_offset = 0
                        bubble_cursor = 0
                        search_mode = False
                        search_query = ""

            elif key == ord("r"):
                scanner.stop()
                invalidate_cache(str(current_path))
                disk_total = shutil.disk_usage(current_path).total
                scanner = LazyScanner(current_path)
                all_entries = scanner.entries
                entries = all_entries
                total = 0
                bubble_cursor = 0
                search_mode = False
                search_query = ""

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

        elif key == ord("b"):
            bubble_mode = True
            bubble_cursor = 0

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
                        # Invalidate the deleted path AND the current dir so
                        # stale parent sizes recompute on the next rescan.
                        invalidate_cache(str(target))
                        invalidate_cache(str(current_path))
                        if cursor >= len(entries) and entries:
                            cursor = len(entries) - 1
                    else:
                        # Delete failed: keep the entry and tell the user why
                        # so it doesn't silently "reappear" later.
                        detail = deleter.error or ""
                        hint = ""
                        if ("Permission denied" in detail
                                or "Errno 13" in detail
                                or "Errno 1" in detail
                                or "not permitted" in detail):
                            hint = "  (root-owned/protected: try sudo pyle)"
                        err = f" delete failed: {detail}{hint} "
                        stdscr.move(max_y - 1, 0)
                        stdscr.clrtoeol()
                        _safe_addnstr(
                            stdscr, max_y - 1, 0,
                            err.ljust(max_x)[:max_x], max_x,
                            curses.color_pair(COLOR_ERROR) | curses.A_BOLD,
                        )
                        stdscr.refresh()
                        stdscr.timeout(-1)
                        stdscr.getch()
                        stdscr.timeout(100)

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
            if self.path.is_symlink() or self.path.is_file():
                with self._lock:
                    self.current = self.path.name
                self._force_unlink(self.path)
            elif self.path.is_dir():
                self._rmtree(self.path)
        except OSError as exc:
            if self.error is None:
                self.error = str(exc)

        # Verify the target is actually gone. A swallowed permission error
        # deeper in the tree would otherwise look like success and the entry
        # would wrongly disappear from the UI then reappear on rescan.
        try:
            still_there = self.path.exists() or self.path.is_symlink()
        except OSError:
            still_there = True
        if still_there and self.error is None:
            self.error = "could not delete (permission denied?)"

        self.done = True

    def _ensure_writable(self, path):
        """Add owner write+exec so a dir's children can be removed.
        Removing an entry needs write+exec on its PARENT directory, so this
        is called on directories before unlinking their contents. Best
        effort: chmod itself fails on root-owned paths (needs sudo)."""
        try:
            mode = os.lstat(path).st_mode
            if not (mode & stat.S_IWUSR) or not (mode & stat.S_IXUSR):
                os.chmod(path, mode | stat.S_IRWXU)
        except OSError:
            pass

    def _force_unlink(self, child):
        """Unlink a file/symlink; on failure make the parent dir writable
        and retry once before giving up."""
        try:
            child.unlink()
            self.count += 1
            return
        except OSError:
            self._ensure_writable(child.parent)
            try:
                child.unlink()
                self.count += 1
            except OSError as exc:
                if self.error is None:
                    self.error = str(exc)

    def _force_rmdir(self, path):
        try:
            path.rmdir()
            return
        except OSError:
            self._ensure_writable(path.parent)
            try:
                path.rmdir()
            except OSError as exc:
                if self.error is None:
                    self.error = str(exc)

    def _rmtree(self, path):
        # Need write+exec on this dir to list and remove its children.
        self._ensure_writable(path)
        try:
            for child in path.iterdir():
                if child.is_dir() and not child.is_symlink():
                    self._rmtree(child)
                else:
                    with self._lock:
                        self.current = child.name
                    self._force_unlink(child)
        except OSError as exc:
            if self.error is None:
                self.error = str(exc)
        self._force_rmdir(path)
