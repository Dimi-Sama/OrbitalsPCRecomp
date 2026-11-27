# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Long jobs that can be stopped, and the time they have left."""

import ctypes
import os
import re
import signal
import subprocess
import sys
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
        self.kill_timer = None
        if not WINDOWS:
            self.process = subprocess.Popen(args, **(options | {"start_new_session": True}))
            return

        # A gated interpreter cannot spawn the real command until it is in our Job Object.
        # Task commands do not consume input, so use the interpreter's private stdin for the gate.
        if options.pop("stdin", None) not in (None, subprocess.DEVNULL):
            raise ValueError("a Windows task does not accept standard input")
        flags = options.pop("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        gate = ("import subprocess, sys\n"
                "if sys.stdin.buffer.read(1) != b'1': sys.exit(1)\n"
                "sys.exit(subprocess.call(sys.argv[1:], stdin=subprocess.DEVNULL, "
                "creationflags=subprocess.CREATE_NO_WINDOW))\n")
        self.process = subprocess.Popen([sys.executable, "-I", "-B", "-c", gate, *args],
                                        stdin=subprocess.PIPE, creationflags=flags, **options)
        try:
            self._into_job()
            gate_stream = getattr(self.process.stdin, "buffer", self.process.stdin)
            gate_stream.write(b"1")
            self.process.stdin.close()
        except BaseException:
            self.process.kill()
            self.process.wait()
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                if stream is not None:
                    stream.close()
            self.close()
            raise
        self.process.stdin = None

    def _into_job(self):
        class JobLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", ctypes.c_uint32), ("minimum_working_set", ctypes.c_size_t),
                        ("maximum_working_set", ctypes.c_size_t), ("active_processes", ctypes.c_uint32),
                        ("affinity", ctypes.c_size_t), ("priority", ctypes.c_uint32), ("scheduling", ctypes.c_uint32)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", JobLimits), ("io", ctypes.c_uint64 * 6), ("memory", ctypes.c_size_t * 4)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = ctypes.c_void_p
        kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
        for name, arguments in (("AssignProcessToJobObject", (ctypes.c_void_p, ctypes.c_void_p)),
                                ("TerminateJobObject", (ctypes.c_void_p, ctypes.c_uint)), ("CloseHandle", (ctypes.c_void_p,)),
                                ("SetInformationJobObject", (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint))):
            getattr(kernel, name).argtypes = arguments
        self.kernel = kernel
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        self.job = job
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())  # JobObjectExtendedLimitInformation
        if not kernel.AssignProcessToJobObject(job, int(self.process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def end(self):
        if WINDOWS:
            if self.job and not self.kernel.TerminateJobObject(self.job, 1):
                raise ctypes.WinError(ctypes.get_last_error())
            return
        if self.kill_timer is not None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
            self.kill_timer = threading.Timer(5, self._insist)
            self.kill_timer.daemon = True
            self.kill_timer.start()
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
        if self.kill_timer is not None:
            try:
                os.killpg(self.process.pid, 0)
            except ProcessLookupError:
                self.kill_timer.cancel()


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

    def finish_without_stop(self, text):
        """Leave a cooperative phase without losing a stop requested just before the transition."""
        with self.lock:
            self.check(text)
            self.held = True

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
