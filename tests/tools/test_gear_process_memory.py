"""Sampling rejects partial observations instead of reporting a false low peak."""

from time import sleep

import pytest

from tools.gear_process_memory import measure_process_tree


def test_sampling_reports_peak_and_stops():
    calls = []

    def sample(pid):
        calls.append(pid)
        return 100 + len(calls)

    with measure_process_tree(pid=123, interval=0.001, sampler=sample) as stats:
        sleep(0.005)
    report = stats.report()
    assert report["sampled_peak_rss_bytes"] >= 102
    assert report["samples"] >= 2
    assert report["failures"] == 0
    assert report["includes_descendants"] is True
    assert calls == [123] * len(calls)
    assert stats.report() == report


@pytest.mark.parametrize("value", [0, -1])
def test_reject_nonpositive_sample(value):
    with (
        pytest.raises(RuntimeError, match="incomplete"),
        measure_process_tree(sampler=lambda _: value),
    ):
        pass


def test_background_failure_is_not_swallowed():
    calls = []

    def sample(pid):
        calls.append(pid)
        if len(calls) > 1:
            raise OSError("failure")
        return 100

    with (
        pytest.raises(RuntimeError, match="incomplete"),
        measure_process_tree(interval=0.001, sampler=sample),
    ):
        sleep(0.005)


def test_invalid_interval():
    with pytest.raises(ValueError), measure_process_tree(interval=0, sampler=lambda _: 1):
        pass


def test_descendant_selection_includes_grandchildren():
    from tools.gear_process_memory import _descendants

    assert _descendants({1: 0, 2: 1, 3: 2, 4: 0}, 1) == {1, 2, 3}


def test_native_windows_sampling_includes_child():
    import os
    import subprocess
    import sys

    from tools.gear_process_memory import windows_tree_rss

    if sys.platform != "win32":
        pytest.skip("Windows native RSS sampler")
    before = windows_tree_rss(os.getpid())
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; x=bytearray(24*1024*1024); print('ready',flush=True); time.sleep(15)",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "ready"
        assert windows_tree_rss(os.getpid()) > before + 16 * 1024 * 1024
        with measure_process_tree(interval=0.01) as stats:
            sleep(0.02)
        assert stats.report()["complete"]
    finally:
        child.terminate()
        child.wait(timeout=5)
        child.stdout.close()
