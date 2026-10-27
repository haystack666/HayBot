import json
from pathlib import Path
import pytest
from android_runtime.gapps import validate_manifest, valid_file


def test_gapps_manifest_is_pinned_and_rejects_paths_or_unpinned_downloads(tmp_path):
    value=json.loads((Path(__file__).parents[1]/'gapps_manifest.json').read_text())
    assert validate_manifest(value)['architecture']=='arm64'
    unsafe=json.loads(json.dumps(value));unsafe['files'][0]['source']='../escape'
    with pytest.raises(ValueError):validate_manifest(unsafe)
    unsafe=json.loads(json.dumps(value));unsafe['commit']='sigma'
    with pytest.raises(ValueError):validate_manifest(unsafe)
    target=tmp_path/'download.apk';target.write_bytes(b'corrupt package')
    assert not valid_file(target,value['files'][0]['sha256'])
