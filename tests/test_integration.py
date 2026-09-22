"""Unit tests for v10 integration: generators, installers, idempotency, honesty."""
import os
import plistlib
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, ".")

from jarvis.integrate import (Integrator, MARK, END, autostart_desktop,
                              detect_os, launchd_plist, report_text,
                              shell_shim, systemd_unit, termux_boot_script)


class TestGenerators(unittest.TestCase):
    def test_systemd_unit(self):
        u = systemd_unit("/opt/jarvis", "/usr/bin/python3", 8595)
        self.assertIn("ExecStart=/usr/bin/python3 -u run.py --port 8595 --headless", u)
        self.assertIn("WorkingDirectory=/opt/jarvis", u)
        self.assertIn("WantedBy=default.target", u)
        self.assertIn("Restart=on-failure", u)

    def test_launchd_plist_is_valid_xml(self):
        xml = launchd_plist("/opt/jarvis", "/usr/bin/python3", 8595).encode()
        d = plistlib.loads(xml)
        self.assertEqual(d["Label"], "ai.jarvis.core")
        self.assertTrue(d["RunAtLoad"])
        self.assertIn("--headless", " ".join(d["ProgramArguments"]))

    def test_desktop_and_termux(self):
        self.assertIn("X-GNOME-Autostart-enabled=true",
                      autostart_desktop("/r", "/p", 1))
        t = termux_boot_script("/r", "/p", "ws://h:8595", "phone", "tok")
        self.assertIn("termux-wake-lock", t)
        self.assertIn("--token tok", t)
        self.assertTrue(t.startswith("#!/data/data/com.termux"))

    def test_shim_points_at_repo(self):
        sh = shell_shim("/opt/jarvis", "/usr/bin/python3", 8595)
        self.assertIn("sys.path.insert(0, '/opt/jarvis')", sh)
        self.assertIn("from jarvis.cli import main", sh)

    def test_termux_detection(self):
        env = {"TERMUX_VERSION": "0.133"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(detect_os(), "termux")


class TestInstall(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        Path(self.home, ".bashrc").write_text("# my shell\nexport EDITOR=vim\n")
        self.ini = Integrator(root="/opt/jarvis", port=8595, os_name="linux",
                              home=self.home)

    def _ok_run(self, cmd, **kw):
        return mock.Mock(returncode=0, stdout="", stderr="")

    def test_plan_files(self):
        paths = [p for p, _, _ in self.plan()]
        self.assertIn(os.path.join(self.home, ".local/bin/jarvis"), paths)
        self.assertIn(os.path.join(self.home, ".config/systemd/user/jarvis.service"),
                      paths)
        self.assertIn(os.path.join(self.home, ".config/autostart/jarvis.desktop"),
                      paths)

    def plan(self):
        with mock.patch.object(Integrator, "_enable_cmds", lambda s: []):
            return self.ini.plan()

    def test_install_writes_files_and_enables_service(self):
        seen = []

        def fake_run(cmd, **kw):
            seen.append(cmd)
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("jarvis.integrate.subprocess.run", fake_run):
            rep = self.ini.install()
        shim = Path(self.home, ".local/bin/jarvis")
        unit = Path(self.home, ".config/systemd/user/jarvis.service")
        self.assertTrue(shim.exists() and unit.exists())
        self.assertTrue(shim.stat().st_mode & stat.S_IXUSR)
        self.assertTrue(shim.read_text().startswith("#!/"))
        self.assertIn("systemctl --user daemon-reload", seen)
        self.assertIn("systemctl --user enable --now jarvis.service", seen)
        self.assertNotIn("warnings", rep)
        # shell rc got exactly one marker block, original content kept
        rc = Path(self.home, ".bashrc").read_text()
        self.assertEqual(rc.count(MARK), 1)
        self.assertIn("export EDITOR=vim", rc)

    def test_install_is_idempotent(self):
        with mock.patch("jarvis.integrate.subprocess.run", self._ok_run):
            self.ini.install()
            rep2 = self.ini.install()
        rc = Path(self.home, ".bashrc").read_text()
        self.assertEqual(rc.count(MARK), 1)
        self.assertTrue(any("already integrated" in r for r in rep2["rc"]))

    def test_service_failure_reported_honestly(self):
        def fail_run(cmd, **kw):
            return mock.Mock(returncode=1, stdout="",
                             stderr="Failed to connect to bus")
        with mock.patch("jarvis.integrate.subprocess.run", fail_run):
            rep = self.ini.install()
        self.assertTrue(rep.get("warnings"))
        self.assertIn("Failed to connect to bus", rep["warnings"][0])
        # ...but the files are still there, usable by hand
        self.assertTrue(Path(self.home, ".local/bin/jarvis").exists())
        self.assertIn("dry run", report_text({"os": "linux", "dry_run": True,
                                              "files": [], "rc": [],
                                              "commands": []}))

    def test_dry_run_writes_nothing(self):
        rep = self.ini.install(dry=True)
        self.assertFalse(Path(self.home, ".local/bin/jarvis").exists())
        self.assertFalse(Path(self.home, ".config").exists())
        self.assertEqual(len(rep["files"]), 3)
        self.assertIn("dry run", report_text(rep))

    def test_uninstall_removes_only_its_own(self):
        with mock.patch("jarvis.integrate.subprocess.run", self._ok_run):
            self.ini.install()
            rep = self.ini.uninstall()
        self.assertFalse(Path(self.home, ".local/bin/jarvis").exists())
        self.assertFalse(Path(self.home, ".config/systemd/user/jarvis.service").exists())
        rc = Path(self.home, ".bashrc").read_text()
        self.assertNotIn(MARK, rc)
        self.assertNotIn(END, rc)
        self.assertIn("export EDITOR=vim", rc)  # user content untouched
        self.assertEqual(len(rep["removed"]), 3)

    def test_never_creates_missing_rc_files(self):
        ini = Integrator(root="/opt/jarvis", port=8595, os_name="macos",
                         home=self.home)
        with mock.patch("jarvis.integrate.subprocess.run", self._ok_run):
            ini.install()
        self.assertFalse(Path(self.home, ".zshrc").exists())  # absent stays absent
        self.assertTrue(Path(self.home,
                              "Library/LaunchAgents/ai.jarvis.core.plist").exists())

    def test_status_reports_absence_and_presence(self):
        st = self.ini.status()
        self.assertEqual(st["os"], "linux")
        self.assertTrue(all(v == "absent" for v in st["files"].values()))
        with mock.patch("jarvis.integrate.subprocess.run", self._ok_run):
            self.ini.install()
        st2 = self.ini.status()
        self.assertTrue(all(v == "installed" for v in st2["files"].values()))

    def test_windows_and_termux_plans(self):
        w = Integrator(root="/opt/j", port=8595, os_name="windows", home=self.home)
        self.assertTrue(any(p.endswith("jarvis-core.bat") for p, _, _ in w.plan()))
        t = Integrator(root="/opt/j", port=8595, os_name="termux", home=self.home)
        self.assertTrue(any(".termux/boot" in p for p, _, _ in t.plan()))


class TestCli(unittest.TestCase):
    def test_api_base_respects_env(self):
        from jarvis import cli
        with mock.patch.dict(os.environ, {"JARVIS_HOST": "10.0.0.9"}):
            self.assertEqual(cli._api_base(8595), "http://10.0.0.9:8595")

    def test_empty_args_prints_help(self):
        from jarvis.cli import main
        self.assertEqual(main([]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
