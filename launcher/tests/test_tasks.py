# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Stopping long jobs (launcher/tasks.py and its use in core.py), and the time left."""
import json
import sys
import tempfile
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

    @unittest.skipUnless(core.WINDOWS, "Windows PowerShell")
    def test_stop_includes_powershell_and_its_child(self):
        task, ticks = Task(), self.root / "ticks with spaces"
        child = self.root / "child.ps1"
        child.write_text("param($Ticks)\nwhile ($true) { [IO.File]::AppendAllText($Ticks, 'x'); Start-Sleep -Milliseconds 50 }\n")
        parent = self.root / "parent.ps1"
        parent.write_text("param($Child, $Ticks)\n& (Join-Path $PSHOME 'powershell.exe') -NoProfile -ExecutionPolicy Bypass -File $Child $Ticks\n")
        with task.process(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(parent),
                           str(child), str(ticks)]) as process:
            deadline = time.monotonic() + 10
            while not ticks.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            try:
                self.assertTrue(ticks.exists())
                self.assertTrue(self.alive(ticks))
            finally:
                task.stop()
                process.wait(10)
        self.assertFalse(self.alive(ticks))

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
        name_part = self.root / (name + ".part")
        name_part.write_bytes(b"another download's partial data")
        with self.assertRaises(Stopped):
            core.download_update(info, self.root, on_progress=lambda done, total: task.stop(), opener=opener, task=task)
        self.assertEqual(list(self.root.iterdir()), [name_part])
        self.assertEqual(name_part.read_bytes(), b"another download's partial data")


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
        (tools / "nxs_kraken.py").touch()
        event = json.dumps({"phase": "translate", "discovered": 100, "cached": 0, "translated": 10, "failed": 0, "todo": 100})
        (tools / "nxs_prepare.py").write_text(f"import time\nprint({event!r}, flush=True)\ntime.sleep(30)\n", encoding="utf-8")
        task = Task()
        profiles = core.Profiles(root / "launcher")
        with patch.object(core, "shader_decoder", return_value=root / "decoder"), \
                patch.object(core, "linux_shader_deps", side_effect=lambda profiles, tools, env, *_: (env, None)):
            with self.assertRaisesRegex(Stopped, "translations are kept"):
                core.prepare_shaders(core.installation(native), profiles, on_progress=lambda _: task.stop(), task=task)

    def test_shader_publication_finishes_even_if_stop_is_requested(self):
        from launcher.tests.test_launcher import build_fixture

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        native = root / "game"
        build_fixture(native)
        tools = native / "nxshader"
        tools.mkdir()
        (tools / "nxs_live.py").touch()
        (tools / "nxs_kraken.py").touch()
        (tools / "nxs_prepare.py").write_text(
            "import os, time\nfrom pathlib import Path\n"
            f"gate = Path(os.environ[{core.SHADER_PUBLISH_GATE!r}])\n"
            "print('{\"phase\": \"publish_wait\"}', flush=True)\n"
            "deadline = time.monotonic() + 10\n"
            "while not gate.is_file():\n"
            "    assert time.monotonic() < deadline\n"
            "    time.sleep(0.03)\n"
            "time.sleep(0.1)\nprint('{\"phase\": \"done\", \"validated\": 1}', flush=True)\n")
        task = Task()
        game = core.installation(native)
        profiles = core.Profiles(root / "launcher")
        self.assertTrue(core.shader_stop_available(game))

        def stop_in_publish(event):
            if event["phase"] == "publish_wait":
                task.stop()

        with patch.object(core, "shader_decoder", return_value=root / "decoder"), \
                patch.object(core, "linux_shader_deps", side_effect=lambda profiles, tools, env, *_: (env, None)):
            result = core.prepare_shaders(game, profiles, on_progress=stop_in_publish, task=task)
        self.assertEqual(result["validated"], 1)


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
