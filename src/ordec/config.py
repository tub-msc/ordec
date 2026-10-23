# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
The user's configuration file ~/.config/ordec/config.toml: global viewer
preferences of the web UI, in one table per view family::

    [schematic]
    crossings = "bridge-h"

Preferences that depend on the technology are in the LayoutStyle
customization files instead (see ordec.layout.style). View generators never
read the configuration, so that views do not depend on the user. Unknown
settings or values are errors.

The web UI edits the file through update_config, which keeps the rest of
the file (including comments) as it is.
"""

import os
import threading
import tomllib
from pathlib import Path
import tomlkit
from public import public

from .schematic.render import SchematicRenderer

#: Settings: (table, name) -> allowed values.
SETTINGS = {
    ('schematic', 'crossings'): SchematicRenderer.crossing_styles,
}

@public
def config_home() -> Path:
    """ORDeC's directory in the user's configuration directory."""
    config = os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config'
    return Path(config) / 'ordec'

@public
def config_path() -> Path:
    return config_home() / 'config.toml'

def _check(text: str, path: Path) -> dict:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{path}: {e}") from None
    for table, entries in data.items():
        if not isinstance(entries, dict):
            raise ValueError(f"{path}: {table!r} is not a table.")
        for name, value in entries.items():
            allowed = SETTINGS.get((table, name))
            if allowed is None:
                raise ValueError(f"{path}: unknown setting {table}.{name}.")
            if value not in allowed:
                raise ValueError(f"{path}: {table}.{name} is {value!r}, "
                    f"expected one of {', '.join(map(repr, allowed))}.")
    return data

@public
def read_config() -> dict:
    """The parsed content of the user's configuration file, {} if there is
    no such file."""
    path = config_path()
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return {}
    return _check(text, path)

# Serializes the read-modify-write cycles of update_config.
_update_lock = threading.Lock()

@public
def update_config(table: str, name: str, value):
    """
    Changes a setting in the user's configuration file, keeping the rest of
    the file (including comments) as it is. With value None, the setting is
    removed, so that the default applies again.

    Raises:
        ValueError: The changed file would be invalid; it is left unchanged.
    """
    path = config_path()
    with _update_lock:
        try:
            doc = tomlkit.parse(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            doc = tomlkit.document()
        if value is None:
            if table in doc:
                doc[table].pop(name, None)
                if not doc[table]:
                    del doc[table]
        else:
            if table not in doc:
                doc[table] = tomlkit.table()
            doc[table][name] = value
        text = tomlkit.dumps(doc)
        _check(text, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Replaced atomically, so that concurrent readers see the old or the
        # new file, never a partial one.
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(text, encoding='utf-8')
        os.replace(tmp, path)
