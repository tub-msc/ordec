# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec.config import config_path, read_config, update_config

def test_config(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    assert read_config() == {}
    config_path().parent.mkdir(parents=True)
    # Settings of other versions are ignored and kept.
    config_path().write_text('# mine\n[future]\nx = 1\n')
    update_config('schematic', 'crossings', 'gap-v')
    assert read_config() == {'future': {'x': 1}, 'schematic': {'crossings': 'gap-v'}}
    # Invalid changes leave the file unchanged.
    with pytest.raises(ValueError, match='expected a str'):
        update_config('schematic', 'crossings', 1)
    with pytest.raises(ValueError, match='Unknown setting'):
        update_config('schematic', 'color', 'plain')
    assert read_config()['schematic'] == {'crossings': 'gap-v'}
    update_config('schematic', 'crossings', None)
    assert read_config() == {'future': {'x': 1}}
    assert config_path().read_text().startswith('# mine\n[future]\n')
