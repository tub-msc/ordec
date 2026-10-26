# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
Reading LayoutStyles from TOML files, and applying the user's customization.

A style file sets the LayoutStyle attributes at its top level, defines fill
patterns in a [patterns] table, and has a [layers] table with one entry per
layer, named by its path in the LayerStack ("Metal1", "Metal1.noqrc",
"Metal1.pin" for the pin layer of Metal1)::

    background = "#000000"
    blend = "additive"

    [patterns]
    dots = [
        "*...*...*...*...",
        "................",
        # 16 rows of 16 pixels in total, '*' set, '.' unset
    ]

    [layers]
    Activ = { fill = "#00ff00", pattern = "dots" }
    Cont = { stroke = "#00ffff", cross = true }

The order of [layers] is the drawing order, bottom first. Layers without
pattern are filled solid. The user's file ~/.config/ordec/layout/<key>.toml,
with the key the technology passes to read_layout_style, has the same format.
It replaces the top-level attributes it sets, and the patterns and layer
entries it lists as a whole (layer attributes left out fall back to the
LayoutStyleLayer defaults, not to the default style); it can use the patterns
of the default style. Layers missing in the default style go on top. Unknown
layers, patterns or attributes are errors in either file.

The web viewer edits the user's file through update_customization, which
keeps the rest of the file (including comments) as it is.
"""

import re
import tomllib
from pathlib import Path
import tomlkit
from public import public

from ..core import *
from ..config import config_home, update_toml

KEY_RE = re.compile(r'[a-z0-9][a-z0-9_-]*')
COLOR_RE = re.compile(r'#[0-9a-fA-F]{6}')

def _color(v):
    if not (isinstance(v, str) and COLOR_RE.fullmatch(v)):
        raise ValueError(f"expected a color like '#0012ef', got {v!r}")
    return rgb_color(v)

def _number(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"expected a number, got {v!r}")
    return float(v)

def _bool(v):
    if not isinstance(v, bool):
        raise ValueError(f"expected true or false, got {v!r}")
    return v

def _enum(cls):
    def conv(v):
        try:
            return cls(v)
        except ValueError:
            choices = ', '.join(repr(m.value) for m in cls)
            raise ValueError(f"expected one of {choices}, got {v!r}") from None
    return conv

# TOML key -> conversion; the keys are the attribute names.
STYLE_ATTRS = {
    'background': _color,
    'blend': _enum(LayoutBlend),
    'opacity': _number,
}
def _str(v):
    if not isinstance(v, str):
        raise ValueError(f"expected a string, got {v!r}")
    return v

LAYER_ATTRS = {
    'fill': _color,
    'stroke': _color,
    'cross': _bool,
    'pattern': _str, # pattern name, resolved by _apply
}

PATTERN_ROW_RE = re.compile(r'[*.]{16}')

def _pattern_bits(rows, where) -> bytes:
    """The bits (see LayoutStylePattern) of a pattern given as rows."""
    if not (isinstance(rows, list) and len(rows) == 16):
        raise ValueError(f"{where}: expected a list of 16 rows")
    bits = b''
    for y, row in enumerate(rows):
        if not (isinstance(row, str) and PATTERN_ROW_RE.fullmatch(row)):
            raise ValueError(f"{where}: row {y + 1}: expected 16 characters '*' or '.', got {row!r}")
        bits += int(row.replace('*', '1').replace('.', '0'), 2).to_bytes(2, 'big')
    return bits

def _convert(table, attrs, where):
    result = {}
    for name, value in table.items():
        if name not in attrs:
            raise ValueError(f"{where}: unknown attribute {name!r}")
        try:
            result[name] = attrs[name](value)
        except ValueError as e:
            raise ValueError(f"{where}: {name}: {e}") from None
    return result

@public
def layer_name(layer: Layer) -> str:
    """
    The name of a layer in style files and in the web viewer: its path in
    the LayerStack, or for anonymous pin layers the path of the layer they
    belong to plus ".pin".
    """
    try:
        return layer.full_path_str()
    except TypeError:
        parent = layer.root.one(Layer.pin_idx.query(layer))
        return parent.full_path_str() + ".pin"

def _resolve_layer(ref_layers: LayerStack, name: str) -> Layer:
    """Inverse of layer_name."""
    node = ref_layers
    for part in name.split('.'):
        try:
            node = node[part]
        except QueryException:
            if part == 'pin' and isinstance(node, Layer) and node.pin is not None:
                node = node.pin
            else:
                raise ValueError(f"unknown layer {name!r}") from None
    if not isinstance(node, Layer):
        raise ValueError(f"unknown layer {name!r}")
    return node

def _parse(data: dict, ref_layers: LayerStack, source, known_patterns=()):
    """
    Returns the style attributes, the patterns (name -> bits) and a list of
    (Layer, attributes). The layers' patterns are names of the file's
    patterns or of known_patterns.
    """
    data = dict(data)
    layers = data.pop('layers', {})
    patterns = data.pop('patterns', {})
    attrs = _convert(data, STYLE_ATTRS, source)
    if not isinstance(patterns, dict):
        raise ValueError(f"{source}: 'patterns' must be a table")
    bits = {name: _pattern_bits(rows, f"{source}: pattern {name!r}")
        for name, rows in patterns.items()}
    if not isinstance(layers, dict):
        raise ValueError(f"{source}: 'layers' must be a table")
    entries = []
    for name, table in layers.items():
        where = f"{source}: layer {name!r}"
        if not isinstance(table, dict):
            raise ValueError(f"{where}: expected a table")
        try:
            layer = _resolve_layer(ref_layers, name)
        except ValueError as e:
            raise ValueError(f"{source}: {e}") from None
        layer_attrs = _convert(table, LAYER_ATTRS, where)
        pattern = layer_attrs.get('pattern')
        if pattern is not None and pattern not in bits and pattern not in known_patterns:
            raise ValueError(f"{where}: unknown pattern {pattern!r}")
        entries.append((layer, layer_attrs))
    return attrs, bits, entries

def _apply(s: LayoutStyle.Mutable, bits: dict, entries: list):
    """Adds the patterns and layer entries of _parse to s, replacing the ones
    with the same name or layer."""
    for name, b in bits.items():
        node = LayoutStylePattern(name=name, bits=b)
        existing = list(s.all(LayoutStylePattern.name_index.query(name)))
        if existing:
            # Reusing the nid keeps the references of layers to it.
            existing[0].replace(node)
        else:
            s % node
    for layer, layer_attrs in entries:
        if 'pattern' in layer_attrs:
            layer_attrs = dict(layer_attrs,
                pattern=s.one(LayoutStylePattern.name_index.query(layer_attrs['pattern'])))
        node = LayoutStyleLayer(layer=layer, **layer_attrs)
        existing = list(s.all(LayoutStyleLayer.layer_index.query(layer)))
        if existing:
            # Reusing the nid keeps the layer's place in the drawing order.
            existing[0].replace(node)
        else:
            s % node

def _pattern_names(style: LayoutStyle) -> set:
    return {p.name for p in style.all(LayoutStylePattern)}

def _load(text: str, source) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{source}: {e}") from None

@public
def read_layout_style(ref_layers: LayerStack, path, key: str) -> LayoutStyle:
    """
    Reads a technology's default LayoutStyle from a TOML file.

    Args:
        ref_layers: The LayerStack whose layers the file names.
        path: Path or importlib.resources Traversable of the file.
        key: Globally unique name of the style (e.g. 'ihp-sg13g2'), naming
            the user's customization file.
    """
    if not KEY_RE.fullmatch(key):
        raise ValueError(f"LayoutStyle key {key!r} does not match {KEY_RE.pattern}.")
    data = _load(path.read_text(encoding='utf-8'), path)
    attrs, bits, entries = _parse(data, ref_layers, path)
    style = LayoutStyle(ref_layers=ref_layers, key=key, **attrs)
    _apply(style, bits, entries)
    return style.freeze()

@public
def default_style(ref_layers: LayerStack) -> LayoutStyle | None:
    """
    The default LayoutStyle of ref_layers: the layout_style viewgen of its
    technology cell, or None if there is none (e.g. for LayerStacks built in
    tests).
    """
    cell = ref_layers.cell
    if cell is None or not hasattr(type(cell), 'layout_style'):
        return None
    style = cell.layout_style
    if style.ref_layers.subgraph != ref_layers.subgraph:
        raise ValueError(f"{cell}.layout_style refers to a different LayerStack.")
    return style

@public
def user_style_path(key: str) -> Path:
    """Path of the user's customization file for a LayoutStyle key."""
    return config_home() / 'layout' / f'{key}.toml'

@public
def read_customization(key: str) -> dict | None:
    """The parsed content of the user's customization file for key, or None
    if there is no such file."""
    path = user_style_path(key)
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return None
    return _load(text, path)

@public
def apply_customization(style: LayoutStyle, data: dict) -> LayoutStyle:
    """Applies a customization (see read_customization) to style."""
    attrs, bits, entries = _parse(data, style.ref_layers, user_style_path(style.key),
        _pattern_names(style))
    s = style.mutable_copy()
    s.update(**attrs)
    _apply(s, bits, entries)
    return s.freeze()

@public
def customized(style: LayoutStyle) -> LayoutStyle:
    """
    Applies the user's customization file for style.key (see module
    docstring), returning style itself if there is none. The file is read on
    every call, so changes apply without restart. Not to be used inside
    viewgens, as the result depends on the file.
    """
    data = read_customization(style.key)
    return style if data is None else apply_customization(style, data)

@public
def update_customization(style: LayoutStyle, settings: dict, layers: dict):
    """
    Changes the user's customization file of style.key, keeping the rest of
    the file (including comments) as it is.

    Args:
        style: The default style.
        settings: Top-level attribute (TOML name) -> value, or None to remove
            the attribute from the file, so that the default applies again.
        layers: Layer name -> table replacing the layer's entry, or None to
            remove the entry.

    Raises:
        ValueError: The changed file would be invalid; it is left unchanged.
    """
    path = user_style_path(style.key)
    def check(text):
        # Validate the result the way customized() will read it.
        _parse(_load(text, path), style.ref_layers, path, _pattern_names(style))
    with update_toml(path, check) as doc:
        for name, value in settings.items():
            if value is None:
                doc.pop(name, None)
            else:
                doc[name] = value
        if layers:
            if 'layers' not in doc:
                doc['layers'] = tomlkit.table()
            table = doc['layers']
            for name, entry in layers.items():
                if entry is None:
                    table.pop(name, None)
                else:
                    inline = tomlkit.inline_table()
                    inline.update(entry)
                    table[name] = inline
            if not table:
                del doc['layers']
