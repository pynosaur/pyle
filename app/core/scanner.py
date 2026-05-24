#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: @spacemany2k38
# 2026-04-08

import os
import subprocess
import threading
from pathlib import Path

_size_cache = {}
_cache_lock = threading.Lock()

_mount_points = None
_mount_lock = threading.Lock()


def _get_mount_points():
    """Parse system mount table to get actual mount points.
    Cached after first call."""
    global _mount_points
    if _mount_points is not None:
        return _mount_points
    with _mount_lock:
        if _mount_points is not None:
            return _mount_points
        mounts = set()
        try:
            output = subprocess.check_output(
                ["mount"], text=True, timeout=5, stderr=subprocess.DEVNULL,
            )
            for line in output.splitlines():
                parts = line.split(" on ", 1)
                if len(parts) == 2:
                    paren_idx = parts[1].rfind(" (")
                    if paren_idx > 0:
                        mounts.add(parts[1][:paren_idx])
        except (subprocess.SubprocessError, OSError):
            pass
        _mount_points = mounts
        return _mount_points


def _is_mount_point(path):
    """Check if path is a mount point using the system mount table."""
    mounts = _get_mount_points()
    return path in mounts or str(path) in mounts


def _disk_usage(st):
    """Return actual disk usage from a stat result.
    Uses st_blocks (512-byte units) on Unix; falls back to st_size."""
    try:
        return st.st_blocks * 512
    except AttributeError:
        return st.st_size


def invalidate_cache(path=None):
    with _cache_lock:
        if path is None:
            _size_cache.clear()
        else:
            key = str(path)
            to_remove = [k for k in _size_cache if k.startswith(key)]
            for k in to_remove:
                del _size_cache[k]


def format_size(size_bytes):
    if size_bytes < 0:
        return "..."
    if size_bytes >= 1024 ** 4:
        return f"{size_bytes / (1024 ** 4):.1f}T"
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.1f}G"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.1f}M"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f}K"
    return f"{size_bytes}B"


def size_ratio(size, total):
    if total <= 0 or size < 0:
        return 0.0
    return size / total


def bar_string(ratio, width):
    filled = int(ratio * width)
    return "#" * filled + " " * (width - filled)


def dir_size(path, _depth=0, _max_depth=50, _cancel=None):
    """Recursive directory size using os.scandir (C-backed).
    Stops at _max_depth to prevent hangs on circular or very deep trees.
    Skips mount points to avoid counting other filesystems.
    Checks _cancel event between entries to allow early exit."""
    if _depth > _max_depth:
        return 0
    if _cancel is not None and _cancel.is_set():
        return 0
    if _depth > 0 and _is_mount_point(path):
        return 0

    key = str(path)
    with _cache_lock:
        if key in _size_cache:
            return _size_cache[key]

    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                if _cancel is not None and _cancel.is_set():
                    return 0
                try:
                    if entry.is_symlink():
                        total += _disk_usage(entry.stat(follow_symlinks=False))
                    elif entry.is_file(follow_symlinks=False):
                        total += _disk_usage(entry.stat(follow_symlinks=False))
                    elif entry.is_dir(follow_symlinks=False):
                        total += dir_size(
                            entry.path, _depth + 1, _max_depth,
                            _cancel,
                        )
                except (PermissionError, OSError):
                    continue
    except (PermissionError, OSError):
        pass

    if _cancel is not None and _cancel.is_set():
        return 0

    with _cache_lock:
        _size_cache[key] = total
    return total


def scan_entry(path):
    """Scan a single path for size info."""
    path = Path(path)
    try:
        if path.is_symlink():
            st = path.lstat()
            return {
                "path": path,
                "name": path.name,
                "size": _disk_usage(st),
                "is_dir": False,
                "is_symlink": True,
                "error": None,
            }
        if path.is_file():
            return {
                "path": path,
                "name": path.name,
                "size": _disk_usage(path.stat()),
                "is_dir": False,
                "is_symlink": False,
                "error": None,
            }
        if path.is_dir():
            return {
                "path": path,
                "name": path.name,
                "size": dir_size(str(path)),
                "is_dir": True,
                "is_symlink": False,
                "error": None,
            }
    except PermissionError:
        return {
            "path": path,
            "name": path.name,
            "size": 0,
            "is_dir": False,
            "is_symlink": False,
            "error": "permission denied",
        }
    except OSError as e:
        return {
            "path": path,
            "name": path.name,
            "size": 0,
            "is_dir": False,
            "is_symlink": False,
            "error": str(e),
        }
    return {
        "path": path,
        "name": path.name,
        "size": 0,
        "is_dir": False,
        "is_symlink": False,
        "error": "unknown type",
    }


def scan_directory_shallow(path):
    """Scan directory WITHOUT computing subdirectory sizes.
    Dirs get size=-1 (pending). Returns (entries, total_known)."""
    resolved = str(Path(path).resolve())
    entries = []
    try:
        with os.scandir(resolved) as it:
            for de in it:
                try:
                    if de.is_symlink():
                        st = de.stat(follow_symlinks=False)
                        entries.append({
                            "path": Path(de.path),
                            "name": de.name,
                            "size": _disk_usage(st),
                            "is_dir": False,
                            "is_symlink": True,
                            "error": None,
                        })
                    elif de.is_file(follow_symlinks=False):
                        st = de.stat(follow_symlinks=False)
                        entries.append({
                            "path": Path(de.path),
                            "name": de.name,
                            "size": _disk_usage(st),
                            "is_dir": False,
                            "is_symlink": False,
                            "error": None,
                        })
                    elif de.is_dir(follow_symlinks=False):
                        cached = _size_cache.get(de.path)
                        entries.append({
                            "path": Path(de.path),
                            "name": de.name,
                            "size": cached if cached is not None else -1,
                            "is_dir": True,
                            "is_symlink": False,
                            "error": None,
                        })
                except PermissionError:
                    entries.append({
                        "path": Path(de.path),
                        "name": de.name,
                        "size": 0,
                        "is_dir": False,
                        "is_symlink": False,
                        "error": "permission denied",
                    })
                except OSError as e:
                    entries.append({
                        "path": Path(de.path),
                        "name": de.name,
                        "size": 0,
                        "is_dir": False,
                        "is_symlink": False,
                        "error": str(e),
                    })
    except (PermissionError, OSError):
        return [], 0

    total = sum(e["size"] for e in entries if e["size"] > 0)
    return entries, total


class LazyScanner:
    """Streams directory entries + sizes in background threads.
    Phase 1: list entries (files get instant sizes, dirs get -1).
    Phase 2: compute dir sizes one by one.
    The UI polls .entries, .listing_done, .sizing_done each tick."""

    def __init__(self, path, cancel=None):
        self.path = str(Path(path).resolve())
        self.entries = []
        self._lock = threading.Lock()
        self.cancel = cancel or threading.Event()
        self.paused = threading.Event()
        self.dirty = threading.Event()
        self.listing_done = False
        self.sizing_done = False
        self.files_count = 0
        self.dirs_count = 0
        self.dirs_sized = 0
        self._thread = threading.Thread(
            target=self._run, daemon=True,
        )
        self._thread.start()

    def _run(self):
        self._phase_list()
        if not self.cancel.is_set():
            self._phase_sizes()

    def _wait_if_paused(self):
        while self.paused.is_set() and not self.cancel.is_set():
            self.cancel.wait(0.1)

    def _phase_list(self):
        batch = []
        dirs = 0
        files = 0
        try:
            with os.scandir(self.path) as it:
                for de in it:
                    if self.cancel.is_set():
                        return
                    entry = self._make_entry(de)
                    if entry is None:
                        continue
                    batch.append(entry)
                    if entry["is_dir"]:
                        dirs += 1
                    else:
                        files += 1
        except (PermissionError, OSError):
            pass
        # Expose all entries at once
        with self._lock:
            self.entries.extend(batch)
            self.dirs_count = dirs
            self.files_count = files
        self.listing_done = True
        self.dirty.set()

    def _make_entry(self, de):
        try:
            if de.is_symlink():
                st = de.stat(follow_symlinks=False)
                return {
                    "path": Path(de.path),
                    "name": de.name,
                    "size": _disk_usage(st),
                    "is_dir": False,
                    "is_symlink": True,
                    "error": None,
                }
            if de.is_file(follow_symlinks=False):
                st = de.stat(follow_symlinks=False)
                return {
                    "path": Path(de.path),
                    "name": de.name,
                    "size": _disk_usage(st),
                    "is_dir": False,
                    "is_symlink": False,
                    "error": None,
                }
            if de.is_dir(follow_symlinks=False):
                cached = _size_cache.get(de.path)
                return {
                    "path": Path(de.path),
                    "name": de.name,
                    "size": cached if cached is not None else -1,
                    "is_dir": True,
                    "is_symlink": False,
                    "error": None,
                }
        except PermissionError:
            return {
                "path": Path(de.path),
                "name": de.name,
                "size": 0,
                "is_dir": False,
                "is_symlink": False,
                "error": "permission denied",
            }
        except OSError as exc:
            return {
                "path": Path(de.path),
                "name": de.name,
                "size": 0,
                "is_dir": False,
                "is_symlink": False,
                "error": str(exc),
            }
        return None

    def _phase_sizes(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed

        snapshot = [e for e in self.entries if e["is_dir"] and e["size"] < 0]
        if not snapshot:
            self.sizing_done = True
            self.dirty.set()
            return

        workers = min(8, len(snapshot))

        def _size_one(entry):
            """Size a directory incrementally: walk its immediate children
            one by one, updating the entry after each so the UI shows
            the size growing in real time."""
            self._wait_if_paused()
            if self.cancel.is_set():
                return

            if _is_mount_point(str(entry["path"])):
                entry["size"] = 0
                self.dirs_sized += 1
                self.dirty.set()
                return

            entry["size"] = 0
            self.dirty.set()
            try:
                with os.scandir(str(entry["path"])) as it:
                    for child in it:
                        self._wait_if_paused()
                        if self.cancel.is_set():
                            return
                        try:
                            if child.is_symlink():
                                entry["size"] += _disk_usage(
                                    child.stat(follow_symlinks=False),
                                )
                            elif child.is_file(follow_symlinks=False):
                                entry["size"] += _disk_usage(
                                    child.stat(follow_symlinks=False),
                                )
                            elif child.is_dir(follow_symlinks=False):
                                entry["size"] += dir_size(
                                    child.path, _depth=1,
                                    _cancel=self.cancel,
                                )
                        except (PermissionError, OSError):
                            continue
                        if self.cancel.is_set():
                            return
                        self.dirty.set()
            except (PermissionError, OSError):
                pass
            # Cache the final result
            with _cache_lock:
                _size_cache[str(entry["path"])] = entry["size"]
            self.dirs_sized += 1
            self.dirty.set()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_size_one, e): e for e in snapshot}
            for fut in as_completed(futures):
                if self.cancel.is_set():
                    pool.shutdown(wait=False, cancel_futures=True)
                    return

        self.sizing_done = True
        self.dirty.set()

    def stop(self):
        self.cancel.set()

    def pause(self):
        self.paused.set()

    def resume(self):
        self.paused.clear()

    def toggle_pause(self):
        if self.paused.is_set():
            self.paused.clear()
        else:
            self.paused.set()

    @property
    def is_paused(self):
        return self.paused.is_set()

    @property
    def is_scanning(self):
        if self.paused.is_set():
            return False
        return not self.sizing_done


def compute_sizes_async(entries, callback, cancel=None):
    """Compute dir sizes in background thread.
    Calls callback() after each entry is resolved.
    Returns (thread, cancel_event) so caller can stop stale scans."""
    if cancel is None:
        cancel = threading.Event()

    def _worker():
        for entry in entries:
            if cancel.is_set():
                return
            if entry["is_dir"] and entry["size"] < 0:
                p = str(entry["path"])
                if _is_mount_point(p):
                    entry["size"] = 0
                    callback()
                    continue
                size = dir_size(p, _cancel=cancel)
                if cancel.is_set():
                    return
                entry["size"] = size
                callback()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t, cancel


def count_items(path):
    """Fast item count using os.scandir."""
    files = 0
    dirs = 0
    try:
        with os.scandir(str(path)) as it:
            for entry in it:
                try:
                    if entry.is_symlink():
                        files += 1
                    elif entry.is_file(follow_symlinks=False):
                        files += 1
                    elif entry.is_dir(follow_symlinks=False):
                        dirs += 1
                except (PermissionError, OSError):
                    continue
    except (PermissionError, OSError):
        pass
    return files, dirs
