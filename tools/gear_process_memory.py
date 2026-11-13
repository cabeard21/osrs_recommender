"""Separate Windows process-tree working-set sampling, without external packages.

The sampled sum includes shared pages in each process and may miss short peaks.
It is RSS (working set), not private committed bytes or an OS high-water mark.
"""

from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass, field
from threading import Event, Thread
from time import perf_counter


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class _MemoryCounters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
        (name, ctypes.c_size_t)
        for name in (
            "PeakWorkingSetSize",
            "WorkingSetSize",
            "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage",
            "QuotaNonPagedPoolUsage",
            "PagefileUsage",
            "PeakPagefileUsage",
            "PrivateUsage",
        )
    ]


def _descendants(parents: dict[int, int], root: int) -> set[int]:
    selected = {root}
    while True:
        expanded = selected | {pid for pid, parent in parents.items() if parent in selected}
        if expanded == selected:
            return selected
        selected = expanded


def windows_tree_rss(root: int) -> int:
    """Sum current working sets; any inaccessible selected process fails the sample."""
    if sys.platform != "win32":
        raise OSError("Process-tree RSS sampling currently requires Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = kernel.Process32FirstW.argtypes
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_MemoryCounters),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    parents = {}
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel.Process32FirstW(snapshot, ctypes.byref(entry)):
            raise ctypes.WinError(ctypes.get_last_error())
        while True:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            if not kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                error = ctypes.get_last_error()
                if error != 18:  # ERROR_NO_MORE_FILES
                    raise ctypes.WinError(error)
                break
    finally:
        kernel.CloseHandle(snapshot)
    if root not in parents:
        raise OSError("Root process was absent from process snapshot")
    total = 0
    for pid in _descendants(parents, root):
        handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            counters = _MemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            total += counters.WorkingSetSize
        finally:
            kernel.CloseHandle(handle)
    return total


@dataclass
class MemoryStats:
    sampled_peak_rss_bytes: int = 0
    samples: int = 0
    failures: int = 0
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def sample(self, sampler: Callable[[int], int], pid: int) -> None:
        try:
            value = sampler(pid)
            if value <= 0:
                raise ValueError("RSS sample must be positive")
            self.sampled_peak_rss_bytes = max(self.sampled_peak_rss_bytes, value)
            self.samples += 1
        except Exception as exc:
            self.failures += 1
            self.errors.append(type(exc).__name__)

    def report(self) -> dict:
        return {
            "kind": "sampled_process_tree_working_set",
            "includes_descendants": True,
            "sampled_peak_rss_bytes": self.sampled_peak_rss_bytes,
            "samples": self.samples,
            "failures": self.failures,
            "error_types": list(self.errors),
            "elapsed_seconds": self.elapsed_seconds,
            "complete": self.failures == 0 and self.samples > 0,
        }


@contextmanager
def measure_process_tree(
    *,
    pid: int | None = None,
    interval: float = 0.05,
    sampler: Callable[[int], int] = windows_tree_rss,
) -> Iterator[MemoryStats]:
    """Measure separately from latency; reject failed or incomplete measurements."""
    if interval <= 0:
        raise ValueError("Sampling interval must be positive")
    root = os.getpid() if pid is None else pid
    stats = MemoryStats()
    stopped = Event()
    started = perf_counter()
    stats.sample(sampler, root)
    if stats.failures:
        raise RuntimeError("Process-tree memory measurement incomplete: initial sample failed")

    def poll() -> None:
        while not stopped.wait(interval):
            stats.sample(sampler, root)

    thread = Thread(target=poll, daemon=True)
    thread.start()
    try:
        yield stats
    finally:
        stopped.set()
        thread.join()
        stats.sample(sampler, root)
        stats.elapsed_seconds = perf_counter() - started
        if stats.failures and sys.exc_info()[0] is None:
            raise RuntimeError("Process-tree memory measurement incomplete: sampling failed")
