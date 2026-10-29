import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('browser_launcher', Path(__file__).with_name('browser_runtime.py'))
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def test_missing_or_old_node_is_not_treated_as_ready(self):
        with patch.object(launcher.shutil, 'which', return_value=None), patch.object(launcher.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertEqual(launcher.node_status(), (None, None))
        with patch.object(launcher.shutil, 'which', return_value='/fake/node'), patch.object(launcher.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'v20.19.0\n', '')):
            self.assertEqual(launcher.node_status(), (None, None))

    def test_finder_path_fallback_accepts_current_node(self):
        with patch.object(launcher.shutil, 'which', return_value=None), patch.object(launcher.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'v22.23.4\n', '')):
            self.assertEqual(launcher.node_status(), ('/usr/local/bin/node', 'v22.23.4'))

    def test_install_then_retry_before_starting_service(self):
        with patch.object(launcher.sys, 'platform', 'darwin'), patch.object(launcher, 'node_status', side_effect=[(None, None), ('/fake/node', 'v22.23.4')]), patch.object(launcher.webbrowser, 'open') as browser, patch('builtins.input', return_value=''), patch.object(launcher, 'running', return_value=True), patch.object(launcher.subprocess, 'call') as start:
            self.assertEqual(launcher.main(), 0)
            browser.assert_called_once_with(launcher.DOWNLOAD)
            start.assert_not_called()

    def test_abort_installation_does_not_start_or_install(self):
        with patch.object(launcher.sys, 'platform', 'darwin'), patch.object(launcher, 'node_status', return_value=(None, None)), patch.object(launcher.webbrowser, 'open'), patch('builtins.input', return_value='q'), patch.object(launcher.subprocess, 'call') as start:
            self.assertEqual(launcher.main(), 0)
            start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
