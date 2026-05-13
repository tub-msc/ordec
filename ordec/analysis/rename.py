# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# ordec imports
from .model import AnalysisPosition, is_identifier


class RenameMixin:
    """Rename helpers that reuse definition and reference analysis."""

    def prepare_rename(self, uri: str, position: AnalysisPosition):
        """Return the rename range and placeholder for a valid symbol.

        Args:
            uri: Document URI containing the request.
            position: One-based analysis position.

        Returns:
            LSP prepare-rename result, or None when rename is not valid.
        """
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
        """Build workspace edits for renaming the symbol at a position.

        Args:
            uri: Document URI containing the rename request.
            position: One-based analysis position.
            new_name: Replacement identifier.

        Returns:
            Mapping of document URIs to text edits, or None when rename is not
            valid at the requested position.

        Raises:
            ValueError: If ``new_name`` is not a valid Python identifier.
        """
        if not is_identifier(new_name):
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
