"""Tests for the bounds applied to any child process that runs the code under test."""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from drydock.child_sandbox import CaptureOverflow, child_limits, run_bounded


class TestRunBounded:
    def test_it_returns_output_and_exit_status_for_an_ordinary_child(self, tmp_path):
        completed = run_bounded(
            [sys.executable, "-c", "import sys; print('out'); sys.stderr.write('err')"],
            cwd=tmp_path,
            timeout=30,
        )

        assert completed.returncode == 0
        assert "out" in completed.stdout
        assert "err" in completed.stderr

    def test_it_preserves_a_nonzero_exit_status(self, tmp_path):
        completed = run_bounded(
            [sys.executable, "-c", "raise SystemExit(3)"], cwd=tmp_path, timeout=30
        )

        assert completed.returncode == 3

    def test_it_raises_capture_overflow_rather_than_growing_without_bound(self, tmp_path):
        with pytest.raises(CaptureOverflow) as caught:
            run_bounded(
                [sys.executable, "-c", "import sys\nwhile True: sys.stdout.write('x' * 65536)"],
                cwd=tmp_path,
                timeout=60,
                capture_limit_bytes=256 * 1024,
            )

        assert caught.value.stream == "stdout"
        # What was captured is bounded; a chunk in flight when the ceiling was crossed is fine.
        assert len(caught.value.stdout) <= 256 * 1024 + 65536

    def test_the_overflow_carries_the_output_captured_before_the_ceiling(self, tmp_path):
        with pytest.raises(CaptureOverflow) as caught:
            run_bounded(
                [
                    sys.executable,
                    "-c",
                    "import sys\nsys.stdout.write('MARKER\\n')\n"
                    "sys.stdout.flush()\nwhile True: sys.stdout.write('x' * 65536)",
                ],
                cwd=tmp_path,
                timeout=60,
                capture_limit_bytes=128 * 1024,
            )

        # The truncated head is the evidence; without it the failure names no cause.
        assert "MARKER" in caught.value.stdout

    def test_a_flooding_child_is_stopped_promptly(self, tmp_path):
        started = time.monotonic()
        with pytest.raises(CaptureOverflow):
            run_bounded(
                [sys.executable, "-c", "import sys\nwhile True: sys.stdout.write('x' * 65536)"],
                cwd=tmp_path,
                timeout=120,
                capture_limit_bytes=64 * 1024,
            )

        # The point of the ceiling is that it ends the child, not that it waits for the timeout.
        assert time.monotonic() - started < 30

    def test_a_zero_capture_limit_lifts_the_output_bound(self, tmp_path):
        completed = run_bounded(
            [sys.executable, "-c", "print('x' * 300000)"],
            cwd=tmp_path,
            timeout=60,
            capture_limit_bytes=0,
        )

        assert len(completed.stdout) > 200000

    def test_it_times_out_and_reports_the_output_so_far(self, tmp_path):
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            run_bounded(
                [
                    sys.executable,
                    "-c",
                    "import sys, time\nprint('before', flush=True)\ntime.sleep(30)",
                ],
                cwd=tmp_path,
                timeout=2,
            )

        assert "before" in (caught.value.output or "")

    @pytest.mark.skipif(sys.platform == "win32", reason="RLIMIT_AS is POSIX-only")
    def test_the_address_space_ceiling_stops_the_child_not_drydock(self, tmp_path):
        completed = run_bounded(
            [sys.executable, "-c", "x = bytearray(2 * 1024 * 1024 * 1024)"],
            cwd=tmp_path,
            timeout=120,
            limit_mb=256,
        )

        assert completed.returncode != 0

    @pytest.mark.skipif(sys.platform == "win32", reason="RLIMIT_AS is POSIX-only")
    def test_the_ceiling_is_inherited_by_grandchildren(self, tmp_path):
        # The runaway is rarely the harness Drydock starts; it is what the harness invokes.
        script = (
            "import subprocess, sys\n"
            "p = subprocess.run([sys.executable, '-c', 'x = bytearray(2*1024*1024*1024)'])\n"
            "raise SystemExit(0 if p.returncode == 0 else 7)\n"
        )
        completed = run_bounded(
            [sys.executable, "-c", script], cwd=tmp_path, timeout=120, limit_mb=512
        )

        assert completed.returncode == 7


class TestChildLimits:
    def test_a_nonpositive_limit_installs_no_preexec_hook(self):
        assert child_limits(0) is None
        assert child_limits(-1) is None

    @pytest.mark.skipif(sys.platform == "win32", reason="RLIMIT_AS is POSIX-only")
    def test_a_positive_limit_installs_one(self):
        assert child_limits(512) is not None
