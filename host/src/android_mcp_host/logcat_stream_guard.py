"""Independent finite synthetic-fixture guard; never a real ADB execution path.

Launched as the dedicated process-group leader by the trusted test-only
Logcat reader. This separate process checks its originating Host PID and
a monotonic deadline, so even SIGKILL/Host crashes cannot leave the fixture
running indefinitely. The parent still caps output and kills its group.
"""

from __future__ import annotations

import math
import os
import signal
import subprocess
import sys
import time


def _kill_own_group() -> None:
    """Terminate this isolated group, even if its fixture blocks forever."""
    if os.getpgrp() == os.getpid():
        try:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        except ProcessLookupError:
            pass
    os._exit(124)


def main(args: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if args is None else args
    if len(arguments) != 3:
        return 125
    script, expected_parent_text, deadline_text = arguments
    try:
        expected_parent = int(expected_parent_text)
        deadline = float(deadline_text)
    except (TypeError, ValueError, OverflowError):
        return 125
    remaining = deadline - time.monotonic()
    if (
        expected_parent < 2
        or os.getpgrp() != os.getpid()
        or os.getppid() != expected_parent
        or not math.isfinite(remaining)
        or not 0 < remaining <= 3.0
        or not os.path.isabs(script)
    ):
        return 125

    fixture = subprocess.Popen(
        [sys.executable, script, "--mcp-synthetic-logcat-v1"],
        stdin=subprocess.DEVNULL,
        # The fixture inherits only the guarded stdout pipe and process group.
        # The Host separately validates UTF-8, strict tags and byte caps.
        stdout=None,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=False,
    )
    while True:
        if os.getppid() != expected_parent or time.monotonic() >= deadline:
            _kill_own_group()
        result = fixture.poll()
        if result is not None:
            return int(result)
        time.sleep(0.02)


if __name__ == "__main__":
    raise SystemExit(main())
