from pathlib import Path
import pytest
from android_runtime.bootstrap import qemu_arguments, cloud_config, write_environment


def test_windows_vm_is_dedicated_and_only_forwards_loopback_ssh(tmp_path):
    args = qemu_arguments(tmp_path, 'Windows', 'AMD64')
    assert '-accel' in args and args[args.index('-accel') + 1] == 'whpx'
    network = args[args.index('-netdev') + 1]
    assert 'hostfwd=tcp:127.0.0.1:17322-:22' in network
    assert not any('virtfs' in s or '/Users/' in s or '5555' in s for s in args)
    with pytest.raises(ValueError): qemu_arguments(tmp_path, 'Windows', 'ARM64')


def test_cloud_seed_installs_binder_and_manager_never_uses_global_wsl_config():
    config = cloud_config('ssh-ed25519 AAAAtestkey haybot')
    assert 'binder_linux' in config and 'linux-modules-extra' in config
    assert 'docker.io' in config and 'uiautomator2' in config
    assert '.wslconfig' not in config


def test_runtime_environment_persists_token_without_printing(tmp_path):
    token = write_environment(tmp_path, 'lima')
    assert len(token) >= 32
    assert write_environment(tmp_path, 'lima') == token
    assert 'host.docker.internal:17321' in (tmp_path / 'haybot.env').read_text()
    assert token in (tmp_path / 'haybot.env').read_text()

def test_linux_manager_binds_docker_bridge_without_lan_listener(monkeypatch):
    from android_runtime.bootstrap import manager_bind
    from unittest.mock import Mock
    monkeypatch.setattr('subprocess.check_output',Mock(return_value=b'172.17.0.1\n'))
    assert manager_bind('Linux')=='172.17.0.1'
    assert manager_bind('Darwin')=='127.0.0.1'
