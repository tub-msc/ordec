# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import re

# ordec imports
from .model import AnalysisPosition, trailing_identifier

# Longest backwards scan for the innermost unclosed call parenthesis. Calls
# longer than this simply lose signature help instead of slowing typing down.
CALL_SCAN_LIMIT = 4000

KEYWORD_ARGUMENT_RE = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)")

PARAM_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def position_offset(text: str, position: AnalysisPosition):
    """Convert a one-based analysis position to a character offset."""
    offset = 0
    line = 1
    while line < position.line:
        newline = text.find("\n", offset)
        if newline < 0:
            return len(text)
        offset = newline + 1
        line += 1

    line_end = text.find("\n", offset)
    if line_end < 0:
        line_end = len(text)
    return min(offset + position.character - 1, line_end)


def offset_position(text: str, offset: int):
    """Convert a character offset to a one-based analysis position."""
    offset = max(0, min(offset, len(text)))
    line = text.count("\n", 0, offset) + 1
    line_start = text.rfind("\n", 0, offset) + 1
    return AnalysisPosition(line, offset - line_start + 1)


def signature_param_name(label: str):
    """Return the parameter name inside a signature parameter label."""
    match = PARAM_NAME_RE.search(label)
    if match is None:
        return label
    return match.group(0)


class SignatureHelpMixin:
    """Signature help built on definition resolution and member indexes."""
    def call_context(self, uri: str, position: AnalysisPosition):
        """Locate the innermost call surrounding a position, or None.

        The backwards scan tracks bracket nesting only; string literals that
        contain unbalanced brackets can mislead it, which matches the
        lightweight nature of the rest of the analysis.
        """
        uri = self.canonical_uri(uri)
        if not self.ensure_document(uri):
            return None

        text = self.documents[uri]["text"]
        offset = position_offset(text, position)
        scan_start = max(0, offset - CALL_SCAN_LIMIT)

        depth = 0
        open_paren = None
        index = offset - 1
        while index >= scan_start:
            char = text[index]
            if char in ")]}":
                depth += 1
            elif char in "([{":
                if depth == 0:
                    if char == "(":
                        open_paren = index
                    break
                depth -= 1
            index -= 1

        if open_paren is None:
            return None

        callee_end = open_paren
        while callee_end > scan_start and text[callee_end - 1] in " \t":
            callee_end -= 1

        callee_name = trailing_identifier(text[scan_start:callee_end])
        if callee_name is None:
            return None

        return {
            "callee_name": callee_name,
            "callee_position": offset_position(text, callee_end - len(callee_name)),
            "arguments_text": text[open_paren + 1:offset],
        }

    def ord_function_parameters(self, definition):
        """Return parameter records for a function defined in ORD source."""
        analysis = self.analyze(definition["uri"])
        for scope in analysis.scopes.values():
            if scope["selection_range"] != definition["selection_range"]:
                continue

            parameters = []
            for binding_id in scope["bindings"]:
                binding = analysis.binding_map.get(binding_id)
                if binding is None or binding["kind"] != "parameter":
                    continue
                parameters.append({
                    "label": binding["name"],
                    "name": binding["name"],
                })
            return parameters

        return None

    def cell_parameters(self, definition):
        """Return declared cell parameters of a class definition."""
        parameters = []
        for name, member in self.type_members(definition).items():
            if member.get("kind") != "parameter":
                continue

            label = name
            if member.get("default"):
                label = "{}={}".format(name, member["default"])
            parameters.append({
                "label": label,
                "name": name,
            })
        return parameters

    def callable_signature(self, uri: str, definition):
        """Build a signature description for a callable definition, or None."""
        if definition is None:
            return None

        kind = definition.get("kind")
        if kind == "class":
            parameters = self.cell_parameters(definition)
        elif kind == "function":
            signature = definition.get("signature")
            if signature is not None:
                parameters = [
                    {
                        "label": param,
                        "name": signature_param_name(param),
                    }
                    for param in signature["params"]
                ]
            elif self.is_ord_uri(definition["uri"]):
                parameters = self.ord_function_parameters(definition)
                if parameters is None:
                    return None
            else:
                return None
        else:
            return None

        return {
            "name": definition["name"],
            "label": "{}({})".format(
                definition["name"],
                ", ".join(parameter["label"] for parameter in parameters),
            ),
            "parameters": parameters,
            "documentation": definition.get("docstring"),
        }

    def active_parameter_index(self, arguments_text: str, parameters):
        """Return the active parameter index for typed call arguments."""
        depth = 0
        count = 0
        segment_start = 0
        for index, char in enumerate(arguments_text):
            if char in "([{":
                depth += 1
            elif char in ")]}":
                depth = max(0, depth - 1)
            elif char == "," and depth == 0:
                count += 1
                segment_start = index + 1

        match = KEYWORD_ARGUMENT_RE.match(arguments_text[segment_start:])
        if match is not None:
            for index, parameter in enumerate(parameters):
                if parameter["name"] == match.group(1):
                    return index

        if not parameters:
            return None

        return min(count, len(parameters) - 1)

    def signature_help(self, uri: str, position: AnalysisPosition):
        """Return signature help for the call surrounding a position."""
        uri = self.canonical_uri(uri)
        context = self.call_context(uri, position)
        if context is None:
            return None

        definition = self.definition(uri, context["callee_position"])
        signature = self.callable_signature(uri, definition)
        if signature is None:
            return None

        signature["active_parameter"] = self.active_parameter_index(
            context["arguments_text"],
            signature["parameters"],
        )
        return signature
