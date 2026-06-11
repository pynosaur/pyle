#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: @spacemany2k38
# 2026-04-08

import os
import queue
import threading
from pathlib import Path

_size_cache = {}
_cache_lock = threading.Lock()

_MAX_DEPTH = 50
_WORKERS = 16
# Directories at or above this depth are enqueued as separate work items
# so all workers share the load; deeper subtrees are sized inline with
# the recursive fast path to avoid per-directory queue overhead.
_SPLIT_DEPTH = 2

def _is_cross_device(path, root_dev):
    """Check if path is on a different filesystem than root_dev.
    This catches mount points, macOS firmlinks, and APFS volume boundaries
    without needing to parse mount tables."""
    if root_dev is None:
        return False
    try:
        return os.lstat(path).st_dev != root_dev
    except (OSError, ValueError):
        return False


def _get_dev(path):
    """Get the device ID for a path."""
    try:
        return os.lstat(path).st_dev
    except OSError:
        return None


def _disk_usage(st):
    """Return actual disk usage from a stat result.
    Uses st_blocks (512-byte units) on Unix; falls back to st_size."""
    try:
        return st.st_blocks * 512
    except AttributeError:
        return st.st_size


def invalidate_cache(path=None):
    """Drop cached sizes for path and everything beneath it.
    Matches on path-component boundaries so '/a/b' does not
    accidentally invalidate '/a/bc'."""
    with _cache_lock:
        if path is None:
            _size_cache.clear()
        else:
            key = str(path)
            prefix = key.rstrip(os.sep) + os.sep
            to_remove = [
                k for k in _size_cache
                if k == key or k.startswith(prefix)
            ]
            for k in to_remove:
                del _size_cache[k]


def invalidate_ancestors(path):
    """Drop cached totals for path's ancestors (exact keys only).
    Used after a delete: every parent total is stale, but sibling
    subtrees are still valid and should keep their caches."""
    p = Path(path)
    with _cache_lock:
        while True:
            _size_cache.pop(str(p), None)
            if p.parent == p:
                break
            p = p.parent


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


def dir_size(
    path, _depth=0, _max_depth=_MAX_DEPTH, _cancel=None, _root_dev=None,
):
    """Recursive directory size using os.scandir (C-backed).
    Stops at _max_depth to prevent hangs on circular or very deep trees.
    Skips directories on different filesystems (detects mount points,
    macOS firmlinks, and APFS volume boundaries via st_dev comparison).
    Checks _cancel event between entries to allow early exit."""
    if _depth > _max_depth:
        return 0
    if _cancel is not None and _cancel.is_set():
        return 0

    if _root_dev is None:
        _root_dev = _get_dev(path)

    if _depth > 0 and _is_cross_device(path, _root_dev):
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
                            _cancel, _root_dev,
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


class _DirNode:
    """One directory in the sizing work queue.
    Tracks its running total and how many child directories are still
    being sized, so finished totals can propagate to the parent."""

    __slots__ = ("path", "parent", "entry", "depth", "total", "pending")

    def __init__(self, path, parent, entry, depth):
        self.path = path
        self.parent = parent
        self.entry = entry
        self.depth = depth
        self.total = 0
        self.pending = 0


class LazyScanner:
    """Streams directory entries + sizes in background threads.
    Phase 1: list entries (files get instant sizes, dirs get -1).
    Phase 2: size all pending directories via a shared work queue
    spanning the whole tree (see _phase_sizes).
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
        """Size all pending directories with a shared work queue.

        Every worker pulls directories from anywhere in the tree, so a
        single huge subdirectory no longer pins one thread while the
        rest sit idle. Totals are aggregated bottom-up through _DirNode
        parents, which keeps the per-directory size cache populated for
        instant navigation."""
        snapshot = [e for e in self.entries if e["is_dir"] and e["size"] < 0]
        if not snapshot:
            self.sizing_done = True
            self.dirty.set()
            return

        root_dev = _get_dev(self.path)
        work = queue.Queue()
        agg_lock = threading.Lock()
        outstanding = [0]
        all_done = threading.Event()

        def _push(node):
            with agg_lock:
                outstanding[0] += 1
            work.put(node)

        def _task_done():
            with agg_lock:
                outstanding[0] -= 1
                if outstanding[0] == 0:
                    all_done.set()

        def _finalize_locked(node):
            """Walk finished totals up the tree (agg_lock held).
            Caches each completed directory and snaps the top-level
            entry to its exact total once its whole subtree is done."""
            while node is not None:
                with _cache_lock:
                    _size_cache[node.path] = node.total
                parent = node.parent
                if parent is None:
                    node.entry["size"] = node.total
                    self.dirs_sized += 1
                    break
                parent.total += node.total
                parent.pending -= 1
                if parent.pending > 0:
                    break
                node = parent

        def _process(node):
            self._wait_if_paused()
            if self.cancel.is_set():
                return

            split = node.depth < _SPLIT_DEPTH
            local = 0
            children = []
            cached_sum = 0
            try:
                with os.scandir(node.path) as it:
                    for child in it:
                        if self.cancel.is_set():
                            return
                        try:
                            if child.is_dir(follow_symlinks=False):
                                if node.depth + 1 > _MAX_DEPTH:
                                    continue
                                if not split:
                                    sub = dir_size(
                                        child.path,
                                        _depth=node.depth + 1,
                                        _cancel=self.cancel,
                                        _root_dev=root_dev,
                                    )
                                    local += sub
                                    continue
                                st = child.stat(follow_symlinks=False)
                                if root_dev is not None \
                                        and st.st_dev != root_dev:
                                    continue
                                with _cache_lock:
                                    cached = _size_cache.get(child.path)
                                if cached is not None:
                                    cached_sum += cached
                                else:
                                    children.append(child.path)
                            else:
                                local += _disk_usage(
                                    child.stat(follow_symlinks=False),
                                )
                        except (PermissionError, OSError):
                            continue
            except (PermissionError, OSError):
                pass

            with agg_lock:
                node.total = local + cached_sum
                node.pending = len(children)
                if node.entry["size"] < 0:
                    node.entry["size"] = 0
                node.entry["size"] += local + cached_sum
                if node.pending == 0:
                    _finalize_locked(node)
                for child_path in children:
                    outstanding[0] += 1
                    work.put(_DirNode(
                        child_path, node, node.entry, node.depth + 1,
                    ))
            self.dirty.set()

        def _worker():
            while not self.cancel.is_set() and not all_done.is_set():
                try:
                    node = work.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    _process(node)
                finally:
                    _task_done()

        for entry in snapshot:
            _push(_DirNode(str(entry["path"]), None, entry, 1))

        workers = [
            threading.Thread(target=_worker, daemon=True)
            for _ in range(_WORKERS)
        ]
        for t in workers:
            t.start()

        while not all_done.is_set():
            if self.cancel.is_set():
                return
            all_done.wait(0.1)

        if self.cancel.is_set():
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


def compute_sizes_async(entries, callback, cancel=None, root_dev=None):
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
                if _is_cross_device(p, root_dev):
                    entry["size"] = 0
                    callback()
                    continue
                size = dir_size(p, _cancel=cancel, _root_dev=root_dev)
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
