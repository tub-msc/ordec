# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
import re

# ordec imports
from .model import AnalysisPosition


class RenameMixin:
    def prepare_rename(self, uri: str, position: AnalysisPosition):
        if self.member_occurrence_at_position(uri, position) is not None:
            return None

        name_info = self.name_at_position(uri, position)
        if name_info is None:
            return None

        if self.definition(uri, position) is None:
            return None

        return {
            "range": name_info["range"],
            "placeholder": name_info["name"],
        }

    def rename(self, uri: str, position: AnalysisPosition, new_name: str):
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", new_name) is None:
            raise ValueError("Invalid identifier: {}".format(new_name))

        if self.member_occurrence_at_position(uri, position) is not None:
            return None

        name_info = self.name_at_position(uri, position)
        if name_info is None:
            return None

        definition = self.definition(uri, position)
        if definition is None:
            return None

        references = self.references(uri, position)
        if definition["kind"] == "module" or name_info["name"] != definition["name"]:
            changes = []
            for reference in references:
                if reference["uri"] != uri or reference["name"] != name_info["name"]:
                    continue

                changes.append({
                    "range": reference["range"],
                    "new_text": new_name,
                })

            if not changes:
                return None

            return {
                uri: changes,
            }

        changes = dict()
        for reference in references:
            changes.setdefault(reference["uri"], []).append({
                "range": reference["range"],
                "new_text": new_name,
            })

        if not changes:
            return None

        return changes
