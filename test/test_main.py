#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent

from app.core.scanner import (
    format_size,
    size_ratio,
    bar_string,
    scan_entry,
    scan_directory_shallow,
    dir_size,
    count_items,
    invalidate_cache,
    invalidate_ancestors,
    LazyScanner,
)
from app.core.scanner import _size_cache, _cache_lock


class TestFormatSize(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(format_size(0), "0B")
        self.assertEqual(format_size(512), "512B")
        self.assertEqual(format_size(1023), "1023B")

    def test_kilobytes(self):
        self.assertEqual(format_size(1024), "1.0K")
        self.assertEqual(format_size(2048), "2.0K")
        self.assertEqual(format_size(1536), "1.5K")

    def test_megabytes(self):
        self.assertEqual(format_size(1024 ** 2), "1.0M")
        self.assertEqual(format_size(5 * 1024 ** 2), "5.0M")

    def test_gigabytes(self):
        self.assertEqual(format_size(1024 ** 3), "1.0G")
        self.assertEqual(format_size(3 * 1024 ** 3), "3.0G")

    def test_terabytes(self):
        self.assertEqual(format_size(1024 ** 4), "1.0T")
        self.assertEqual(format_size(2 * 1024 ** 4), "2.0T")


class TestSizeRatio(unittest.TestCase):
    def test_zero_total(self):
        self.assertEqual(size_ratio(100, 0), 0.0)

    def test_full(self):
        self.assertAlmostEqual(size_ratio(100, 100), 1.0)

    def test_half(self):
        self.assertAlmostEqual(size_ratio(50, 100), 0.5)

    def test_quarter(self):
        self.assertAlmostEqual(size_ratio(25, 100), 0.25)


class TestBarString(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(bar_string(0.0, 10), "          ")

    def test_full(self):
        self.assertEqual(bar_string(1.0, 10), "##########")

    def test_half(self):
        self.assertEqual(bar_string(0.5, 10), "#####     ")

    def test_width(self):
        result = bar_string(0.3, 20)
        self.assertEqual(len(result), 20)


class TestScanEntry(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.test_file = Path(self.tmpdir) / "test.txt"
        self.test_file.write_text("hello world")
        self.test_dir = Path(self.tmpdir) / "subdir"
        self.test_dir.mkdir()
        self.nested_file = self.test_dir / "nested.txt"
        self.nested_file.write_text("nested content")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_scan_file(self):
        entry = scan_entry(self.test_file)
        self.assertEqual(entry["name"], "test.txt")
        self.assertFalse(entry["is_dir"])
        self.assertFalse(entry["is_symlink"])
        self.assertGreater(entry["size"], 0)
        self.assertIsNone(entry["error"])

    def test_scan_directory(self):
        entry = scan_entry(self.test_dir)
        self.assertEqual(entry["name"], "subdir")
        self.assertTrue(entry["is_dir"])
        self.assertGreater(entry["size"], 0)
        self.assertIsNone(entry["error"])

    def test_scan_symlink(self):
        link = Path(self.tmpdir) / "link.txt"
        link.symlink_to(self.test_file)
        entry = scan_entry(link)
        self.assertEqual(entry["name"], "link.txt")
        self.assertTrue(entry["is_symlink"])
        self.assertIsNone(entry["error"])


class TestDirSize(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        Path(self.tmpdir, "a.txt").write_text("aaaa")
        Path(self.tmpdir, "b.txt").write_text("bb")
        sub = Path(self.tmpdir, "sub")
        sub.mkdir()
        Path(sub, "c.txt").write_text("cccccc")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _file_disk_usage(self, path):
        st = os.stat(path)
        try:
            return st.st_blocks * 512
        except AttributeError:
            return st.st_size

    def test_total_size(self):
        expected = (
            self._file_disk_usage(Path(self.tmpdir, "a.txt"))
            + self._file_disk_usage(Path(self.tmpdir, "b.txt"))
            + self._file_disk_usage(Path(self.tmpdir, "sub", "c.txt"))
        )
        total = dir_size(Path(self.tmpdir))
        self.assertEqual(total, expected)

    def test_empty_dir(self):
        empty = Path(self.tmpdir) / "empty"
        empty.mkdir()
        self.assertEqual(dir_size(empty), 0)


class TestScanDirectory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        Path(self.tmpdir, "big.bin").write_bytes(b"x" * 1000)
        Path(self.tmpdir, "small.txt").write_text("hi")
        sub = Path(self.tmpdir, "subdir")
        sub.mkdir()
        Path(sub, "inner.txt").write_text("content")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_returns_sorted_by_size(self):
        entries, total = scan_directory_shallow(self.tmpdir)
        known = [e["size"] for e in entries if e["size"] >= 0]
        self.assertEqual(known, sorted(known, reverse=True))

    def test_total_matches_known_sum(self):
        entries, total = scan_directory_shallow(self.tmpdir)
        known_sum = sum(e["size"] for e in entries if e["size"] >= 0)
        self.assertEqual(total, known_sum)

    def test_entry_count(self):
        entries, _ = scan_directory_shallow(self.tmpdir)
        self.assertEqual(len(entries), 3)

    def test_nonexistent_directory(self):
        entries, total = scan_directory_shallow("/nonexistent/path/xyz123")
        self.assertEqual(entries, [])
        self.assertEqual(total, 0)


class TestCountItems(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        Path(self.tmpdir, "f1.txt").write_text("a")
        Path(self.tmpdir, "f2.txt").write_text("b")
        Path(self.tmpdir, "d1").mkdir()
        Path(self.tmpdir, "d2").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_count(self):
        files, dirs = count_items(self.tmpdir)
        self.assertEqual(files, 2)
        self.assertEqual(dirs, 2)

    def test_count_empty(self):
        empty = Path(self.tmpdir) / "empty"
        empty.mkdir()
        files, dirs = count_items(empty)
        self.assertEqual(files, 0)
        self.assertEqual(dirs, 0)


class TestInvalidateCache(unittest.TestCase):
    def setUp(self):
        with _cache_lock:
            self._saved = dict(_size_cache)
            _size_cache.clear()

    def tearDown(self):
        with _cache_lock:
            _size_cache.clear()
            _size_cache.update(self._saved)

    def test_prefix_does_not_hit_siblings(self):
        with _cache_lock:
            _size_cache["/a/b"] = 1
            _size_cache["/a/b/c"] = 2
            _size_cache["/a/bc"] = 3
        invalidate_cache("/a/b")
        with _cache_lock:
            self.assertNotIn("/a/b", _size_cache)
            self.assertNotIn("/a/b/c", _size_cache)
            self.assertIn("/a/bc", _size_cache)

    def test_invalidate_ancestors_keeps_siblings(self):
        with _cache_lock:
            _size_cache["/a"] = 1
            _size_cache["/a/b"] = 2
            _size_cache["/a/b/c"] = 3
            _size_cache["/a/sibling"] = 4
        invalidate_ancestors("/a/b")
        with _cache_lock:
            self.assertNotIn("/a", _size_cache)
            self.assertNotIn("/a/b", _size_cache)
            self.assertIn("/a/b/c", _size_cache)
            self.assertIn("/a/sibling", _size_cache)


class TestLazyScanner(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        invalidate_cache(self.tmpdir)
        for name in ("d1", "d2"):
            d = Path(self.tmpdir, name)
            d.mkdir()
            Path(d, "f.bin").write_bytes(b"x" * 2048)
            nested = d / "nested"
            nested.mkdir()
            Path(nested, "g.bin").write_bytes(b"y" * 4096)
        Path(self.tmpdir, "top.txt").write_text("top")
        self.resolved = str(Path(self.tmpdir).resolve())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)
        invalidate_cache(self.tmpdir)
        invalidate_cache(self.resolved)

    def _wait(self, scanner, timeout=10.0):
        import time
        deadline = time.monotonic() + timeout
        while not scanner.sizing_done:
            if time.monotonic() > deadline:
                self.fail("scanner did not finish in time")
            time.sleep(0.01)

    def test_sizes_match_dir_size(self):
        scanner = LazyScanner(self.tmpdir)
        self._wait(scanner)
        by_name = {e["name"]: e for e in scanner.entries}
        self.assertEqual(scanner.dirs_count, 2)
        self.assertEqual(scanner.files_count, 1)
        self.assertEqual(scanner.dirs_sized, 2)
        for name in ("d1", "d2"):
            expected = dir_size(str(Path(self.tmpdir, name)))
            self.assertEqual(by_name[name]["size"], expected)
            self.assertGreater(by_name[name]["size"], 0)

    def test_caches_nested_dirs(self):
        scanner = LazyScanner(self.tmpdir)
        self._wait(scanner)
        nested = str(Path(self.resolved, "d1", "nested"))
        with _cache_lock:
            self.assertIn(nested, _size_cache)


class TestAsyncDelete(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        for root, dirs, _ in os.walk(self.tmpdir):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o755)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _wait(self, deleter, timeout=10.0):
        import time
        deadline = time.monotonic() + timeout
        while not deleter.done:
            if time.monotonic() > deadline:
                self.fail("delete did not finish in time")
            time.sleep(0.01)

    def test_delete_file(self):
        from app.core.ui import _AsyncDelete
        target = Path(self.tmpdir, "victim.txt")
        target.write_text("bye")
        deleter = _AsyncDelete(target)
        self._wait(deleter)
        self.assertIsNone(deleter.error)
        self.assertFalse(target.exists())

    def test_delete_read_only_tree(self):
        from app.core.ui import _AsyncDelete
        top = Path(self.tmpdir, "ro")
        inner = top / "inner"
        inner.mkdir(parents=True)
        Path(inner, "f.txt").write_text("data")
        os.chmod(inner, 0o555)
        os.chmod(top, 0o555)
        deleter = _AsyncDelete(top)
        self._wait(deleter)
        self.assertIsNone(deleter.error)
        self.assertFalse(top.exists())


class TestVersionConsistency(unittest.TestCase):
    """All version references must match. CI catches drift."""

    def _read_program_version(self):
        text = (REPO_ROOT / ".program").read_text()
        for line in text.splitlines():
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip()
        self.fail(".program has no version field")

    def _read_doc_version(self):
        doc_file = REPO_ROOT / "doc" / "pyle.yaml"
        text = doc_file.read_text()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("VERSION:"):
                val = stripped.split(":", 1)[1].strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                return val
        self.fail("doc/pyle.yaml has no VERSION field")

    def _read_readme_version(self):
        readme = REPO_ROOT / "README.md"
        if not readme.exists():
            return None
        text = readme.read_text()
        match = re.search(r'^Version:\s*(.+)$', text, re.MULTILINE)
        return match.group(1).strip() if match else None

    def test_all_versions_match(self):
        program_v = self._read_program_version()
        doc_v = self._read_doc_version()
        readme_v = self._read_readme_version()
        init_v = __version__

        self.assertEqual(
            init_v, program_v,
            f"__init__.py ({init_v}) != .program ({program_v})",
        )
        self.assertEqual(
            init_v, doc_v,
            f"__init__.py ({init_v}) != doc yaml ({doc_v})",
        )
        if readme_v is not None:
            self.assertEqual(
                init_v, readme_v,
                f"__init__.py ({init_v}) != README.md ({readme_v})",
            )


if __name__ == "__main__":
    unittest.main()
