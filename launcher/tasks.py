# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Long jobs that can be stopped, and the time they have left."""

import ctypes
import os
import re
import signal
import subprocess
import threading
import time
from collections import deque
from contextlib import contextmanager

WINDOWS = os.name == "nt"


class Stopped(Exception):
    """The player stopped the job. Its text is for them."""


class ProcessTree:
    """A process started with everything it will start itself (compilers, translators), to end all of it at once."""

    def __init__(self, args, **options):
        self.job = None
        if WINDOWS:
            options["creationflags"] = options.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW   # the launcher has no console
        else:
            options["start_new_session"] = True
        self.process = subprocess.Popen(args, **options)
        if WINDOWS:
            self._into_job()

    def _into_job(self):
        kernel = ctypes.WinDLL("kernel32")
        kernel.CreateJobObjectW.restype = ctypes.c_void_p
        kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
        for name, arguments in (("AssignProcessToJobObject", (ctypes.c_void_p, ctypes.c_void_p)),
                                ("TerminateJobObject", (ctypes.c_void_p, ctypes.c_uint)), ("CloseHandle", (ctypes.c_void_p,))):
            getattr(kernel, name).argtypes = arguments
        self.kernel = kernel
        job = kernel.CreateJobObjectW(None, None)
        if job and kernel.AssignProcessToJobObject(job, int(self.process._handle)):
            self.job = job
        elif job:
            kernel.CloseHandle(job)

    def end(self):
        if WINDOWS:
            if not (self.job and self.kernel.TerminateJobObject(self.job, 1)):
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.process.pid)], capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            return
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
            threading.Timer(5, self._insist).start()
        except ProcessLookupError:
            pass

    def _insist(self):
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    def close(self):
        if self.job:
            self.kernel.CloseHandle(self.job)
            self.job = None


class Task:
    """A job's stop switch. The job runs its processes through process(), and holds the stop while it must not be cut short: a
    step that would be taken for done the next time although its files are not all there."""

    def __init__(self):
        self.lock = threading.Lock()
        self.tree = None
        self.stopped = self.held = False

    def stop(self):
        with self.lock:
            self.stopped = True
            self._end()

    def hold(self, on):
        with self.lock:
            self.held = on
            if self.stopped:
                self._end()

    def _end(self):
        if self.tree and not self.held:
            self.tree.end()

    def check(self, text="Stopped."):
        if self.stopped and not self.held:
            raise Stopped(text)

    @contextmanager
    def process(self, args, **options):
        self.check()
        tree = ProcessTree(args, **options)
        with self.lock:
            self.tree = tree
            if self.stopped:
                self._end()
        try:
            with tree.process:
                yield tree.process
        finally:
            with self.lock:
                self.tree = None
            tree.close()


class Pace:
    """The time left of a counted job, from its pace over the last minutes."""
    WINDOW, LEAST = 180, 15   # seconds looked back; seconds needed before saying anything

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.samples = deque()
        self.total = 0

    def feed(self, done, total):
        if self.samples and (done < self.samples[-1][1] or total != self.total):
            self.samples.clear()   # another count
        self.total = total
        if not self.samples or done != self.samples[-1][1]:
            self.samples.append((self.clock(), done))
        while len(self.samples) > 2 and self.samples[-1][0] - self.samples[0][0] > self.WINDOW:
            self.samples.popleft()

    def forget(self):
        self.samples.clear()

    def left(self):
        """Seconds, or None while it cannot be told."""
        if len(self.samples) < 2:
            return None
        (t0, d0), (t1, d1) = self.samples[0], self.samples[-1]
        if t1 - t0 < self.LEAST:
            return None
        return max(0.0, (self.total - d1) * (t1 - t0) / (d1 - d0) - (self.clock() - t1))

    def text(self):
        elapsed, left = self.clock() - self.started, self.left()
        said = f"{minutes(elapsed)} elapsed"
        if left is not None:
            said += " · less than a minute left" if left < 60 else f" · about {minutes(left)} left"
        return said


def minutes(seconds):
    if seconds < 60:
        return f"{int(seconds)} s"
    whole = int(seconds // 60)
    return f"{whole} min" if whole < 60 else f"{whole // 60} h {whole % 60:02d} min"


def counted(text):
    """(done, total) of switchrecomp.py's "compiled N/M" line, or None."""
    match = re.search(r"compiled (\d+)/(\d+)", str(text or ""))
    return (int(match[1]), int(match[2])) if match else None
