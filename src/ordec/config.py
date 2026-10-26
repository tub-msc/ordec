# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
The user's configuration file ~/.config/ordec/config.toml: global viewer
preferences of the web UI, in one table per view family::

    [schematic]
    crossings = "bridge-h"

Preferences that depend on the technology are in the LayoutStyle
customization files instead (see ordec.layout.style). View generators never
read the configuration, so that views do not depend on the user. Settings
unknown to this version (e.g. written by a newer one) are ignored and kept,
values of the wrong type are errors. The web UI, which applies the settings,
knows their allowed values and uses the default for others.

The web UI edits the file through update_config, which keeps the rest of
the file (including comments) as it is.
"""

import fcntl
import os
import tomllib
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
import tomlkit
from public import public

#: Settings: (table, name) -> type of value.
SETTINGS = {
    ('schematic', 'crossings'): str,
}

@public
def config_home() -> Path:
    """ORDeC's directory in the user's configuration directory."""
    config = os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config'
    return Path(config) / 'ordec'

@public
@contextmanager
def update_toml(path: Path, check: Callable[[str], None]):
    """
    Changes the TOML file path in config_home(), keeping the rest of the file
    (including comments) as it is: yields its tomlkit document (empty if
    there is no file) for the with block to change, then writes it back.

    Args:
        check: Validates the new file content (text) and raises ValueError
            if it is invalid. If check or the with block raises, the file is
            left unchanged.

    Updates are serialized across threads and processes by flock on
    config_home(). It is the directory that is locked, because the file is
    replaced on every write.
    """
    home = config_home()
    home.mkdir(parents=True, exist_ok=True)
    fd = os.open(home, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            doc = tomlkit.parse(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            doc = tomlkit.document()
        yield doc
        text = tomlkit.dumps(doc)
        check(text)
        # Replaced atomically, so that readers see the old or the new file,
        # never a partial one. The lock also protects the temporary file.
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(text, encoding='utf-8')
        os.replace(tmp, path)
    finally:
        os.close(fd)

@public
def config_path() -> Path:
    return config_home() / 'config.toml'

def _check(text: str, path: Path) -> dict:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{path}: {e}") from None
    for (table, name), kind in SETTINGS.items():
        entries = data.get(table, {})
        if not isinstance(entries, dict):
            raise ValueError(f"{path}: {table!r} is not a table.")
        if name in entries and not isinstance(entries[name], kind):
            raise ValueError(f"{path}: {table}.{name} is {entries[name]!r}, "
                f"expected a {kind.__name__}.")
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

@public
def update_config(table: str, name: str, value):
    """
    Changes a setting in the user's configuration file, keeping the rest of
    the file (including comments) as it is. With value None, the setting is
    removed, so that the default applies again.

    Raises:
        ValueError: The changed file would be invalid; it is left unchanged.
    """
    if (table, name) not in SETTINGS:
        raise ValueError(f"Unknown setting {table}.{name}.")
    path = config_path()
    with update_toml(path, lambda text: _check(text, path)) as doc:
        if value is None:
            if table in doc:
                doc[table].pop(name, None)
                if not doc[table]:
                    del doc[table]
        else:
            if table not in doc:
                doc[table] = tomlkit.table()
            doc[table][name] = value
