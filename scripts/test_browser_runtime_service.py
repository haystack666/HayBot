"""Lifecycle checks without stopping the real app or opening Chrome."""
import unittest
from unittest.mock import Mock, patch

import browser_runtime_service as service


class RuntimeServiceTests(unittest.TestCase):
    def test_tracks_container_start_and_stop(self):
        child = Mock()
        child.poll.return_value = None
        with patch.object(service, 'app_running', side_effect=[True, False, KeyboardInterrupt]), \
             patch.object(service, 'running', return_value=False), \
             patch.object(service.subprocess, 'Popen', return_value=child) as spawn, \
             patch.object(service.signal, 'signal'), patch.object(service.time, 'sleep'):
            with self.assertRaises(KeyboardInterrupt):
                service.supervise('/docker', '/node')
        spawn.assert_called_once()
        child.terminate.assert_called_once()
        child.wait.assert_called_once_with(timeout=20)

    def test_docker_outage_preserves_running_child(self):
        child = Mock()
        child.poll.return_value = None
        with patch.object(service, 'app_running', side_effect=[True, OSError, True, KeyboardInterrupt]), \
             patch.object(service, 'running', return_value=False), \
             patch.object(service.subprocess, 'Popen', return_value=child) as spawn, \
             patch.object(service.signal, 'signal'), patch.object(service.time, 'sleep'):
            with self.assertRaises(KeyboardInterrupt):
                service.supervise('/docker', '/node')
        spawn.assert_called_once()
        # Only final shutdown terminates the child, not the transient Docker outage.
        child.terminate.assert_called_once()

    def test_does_not_take_over_manually_started_runtime(self):
        with patch.object(service, 'app_running', side_effect=[True, False, KeyboardInterrupt]), \
             patch.object(service, 'running', return_value=True), \
             patch.object(service.subprocess, 'Popen') as spawn, \
             patch.object(service.signal, 'signal'), patch.object(service.time, 'sleep'):
            with self.assertRaises(KeyboardInterrupt):
                service.supervise('/docker', '/node')
        spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
