# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Stopping long jobs (launcher/tasks.py and its use in core.py), and the time left."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from launcher import core
from launcher.tasks import Pace, Stopped, Task, counted, minutes

# a process that starts another one, which writes to a file as long as it lives
TREE = """
import subprocess, sys, time
child = "import sys, time\\nwhile True: open(sys.argv[1], 'a').write('x'); time.sleep(0.05)"
subprocess.Popen([sys.executable, "-c", child, sys.argv[1]])
print("[3/5] started", flush=True)
time.sleep(60)
"""


class StopTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()

    def alive(self, path):
        size = path.stat().st_size
        time.sleep(0.4)
        return path.stat().st_size > size

    def test_stop_ends_what_the_process_started_too(self):
        task, ticks = Task(), self.root / "ticks"
        with task.process([sys.executable, "-c", TREE, str(ticks)], stdout=-1) as process:
            process.stdout.readline()
            while not ticks.exists():
                time.sleep(0.05)
            self.assertTrue(self.alive(ticks))
            began = time.monotonic()
            task.stop()
            process.wait(10)
        self.assertLess(time.monotonic() - began, 8)
        self.assertFalse(self.alive(ticks))
        with self.assertRaises(Stopped):
            task.check()

    def test_a_held_task_stops_when_it_is_let_go(self):
        task = Task()
        with task.process([sys.executable, "-c", "import time; time.sleep(30)"]) as process:
            task.hold(True)
            task.stop()
            time.sleep(0.3)
            self.assertIsNone(process.poll())
            task.hold(False)
            process.wait(10)

    def test_a_task_stopped_before_it_starts_runs_nothing(self):
        task = Task()
        task.stop()
        with self.assertRaises(Stopped), task.process([sys.executable, "-c", "pass"]):
            self.fail("started")

    def source(self):
        source = self.root / "copy"
        (source / "exefs").mkdir(parents=True); (source / "romfs").mkdir()
        (source / "exefs/main").write_bytes(b"x"); (source / "exefs/main.npdm").write_bytes(b"x")
        return source

    def install(self, script, stop_at):
        """Run a stand-in setup; stop it at its first line with stop_at. Returns what was raised."""
        task, raised = Task(), []

        def on_progress(step, total, text):
            if stop_at in text and not task.stopped:
                threading.Timer(0.3, task.stop).start()

        try:
            core.install_from_files(self.source(), self.root / "games", on_progress, command=[sys.executable, "-u", "-c", script], task=task)
        except (Stopped, core.LauncherError) as error:
            raised.append(error)
        return raised[0] if raised else None

    def test_a_stop_while_linking_discards_the_unfinished_module(self):
        module = self.root / "games/Orbitals" / core.MODULE
        script = (f"import os, time\nprint('[4/5] Recompiling', flush=True)\nos.makedirs({str(module.parent)!r})\n"
                  f"open({str(module)!r}, 'wb').write(b'half')\nprint('linking', flush=True)\ntime.sleep(30)")
        self.assertIsInstance(self.install(script, "linking"), Stopped)
        self.assertFalse(module.exists(), "the setup would take it for a finished one")

    def test_a_stop_before_linking_leaves_the_module_of_before(self):
        module = self.root / "games/Orbitals" / core.MODULE
        module.parent.mkdir(parents=True)
        module.write_bytes(b"whole")
        old = time.time() - 3600
        os.utime(module, (old, old))
        script = "import time\nprint('[4/5] Recompiling', flush=True)\nprint('  compiled 10/400 (3s)', flush=True)\ntime.sleep(30)"
        self.assertIsInstance(self.install(script, "compiled 10/400"), Stopped)
        self.assertEqual(module.read_bytes(), b"whole")

    def test_the_first_step_is_not_cut_short(self):
        done = self.root / "unpacked"
        script = (f"import time\nprint('[1/5] Python and GCC', flush=True)\ntime.sleep(1.2)\nopen({str(done)!r}, 'w').write('all of it')\n"
                  "print('[2/5] More', flush=True)\ntime.sleep(30)")
        self.assertIsInstance(self.install(script, "Python and GCC"), Stopped)
        self.assertEqual(done.read_text(), "all of it")

    def test_a_failed_setup_is_not_taken_for_a_stopped_one(self):
        error = self.install("print('[2/5] More', flush=True)\nraise SystemExit(3)", "never")
        self.assertIsInstance(error, core.LauncherError)
        self.assertIn("code 3", str(error))

    def test_stopped_download_leaves_nothing(self):
        task = Task()
        name = core.kit_archive("9.9.9")

        class Response:
            headers = {"Content-Length": "4194304"}

            def __init__(self, data):
                self.data = data

            def read(self, size):
                chunk, self.data = self.data[:size], self.data[size:]
                return chunk

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        def opener(request, timeout):
            return Response(f"{'0' * 64}  {name}\n".encode() if request.full_url.endswith("SUMS") else bytes(1 << 22))

        info = {"latest": "v9.9.9", "assets": {name: "https://github.com/x/kit", "SHA256SUMS.txt": "https://github.com/x/SUMS"}}
        with self.assertRaises(Stopped):
            core.download_update(info, self.root, on_progress=lambda done, total: task.stop(), opener=opener, task=task)
        self.assertEqual(list(self.root.iterdir()), [])


class ShaderStopTest(unittest.TestCase):
    def test_stopped_preparation_says_that_it_can_continue(self):
        from launcher.tests.test_launcher import build_fixture
        directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        native = root / "game"
        build_fixture(native)
        tools = native / "nxshader"
        tools.mkdir()
        (tools / "nxs_live.py").write_text("", encoding="utf-8")
        event = json.dumps({"phase": "translate", "discovered": 100, "cached": 0, "translated": 10, "failed": 0, "todo": 100})
        (tools / "nxs_prepare.py").write_text(f"import time\nprint({event!r}, flush=True)\ntime.sleep(30)\n", encoding="utf-8")
        task = Task()
        profiles = core.Profiles(root / "launcher")
        with patch.object(core, "shader_decoder", return_value=root / "decoder"), \
                patch.object(core, "linux_shader_deps", side_effect=lambda profiles, tools, env, *_: (env, None)):
            with self.assertRaisesRegex(Stopped, "preparing again does the rest"):
                core.prepare_shaders(core.installation(native), profiles, on_progress=lambda _: task.stop(), task=task)


class PaceTest(unittest.TestCase):
    def test_time_left_follows_the_recent_pace(self):
        now = [0.0]
        pace = Pace(clock=lambda: now[0])
        pace.feed(0, 400)
        self.assertIsNone(pace.left())
        for step in range(1, 11):
            now[0] = step * 10
            pace.feed(step * 10, 400)   # one a second
        self.assertAlmostEqual(pace.left(), 300, delta=1)
        self.assertEqual(pace.text(), "1 min elapsed · about 5 min left")
        now[0] += 30   # nothing new for a while: the time still goes down
        self.assertAlmostEqual(pace.left(), 270, delta=1)

    def test_another_count_starts_again(self):
        now = [0.0]
        pace = Pace(clock=lambda: now[0])
        for step in range(5):
            now[0] = step * 10
            pace.feed(step, 100)
        pace.feed(0, 5000)
        self.assertIsNone(pace.left())

    def test_counts_and_words(self):
        self.assertEqual(counted("  compiled 120/412 (33s)"), (120, 412))
        self.assertIsNone(counted("Linking"))
        self.assertEqual([minutes(n) for n in (5, 61, 3600, 3720)], ["5 s", "1 min", "1 h 00 min", "1 h 02 min"])


if __name__ == "__main__":
    unittest.main()
