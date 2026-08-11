# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# ordec imports
from .model import AnalysisPosition, is_identifier


class RenameMixin:
    """Rename helpers that reuse definition and reference analysis."""
    def prepare_rename(self, uri: str, position: AnalysisPosition):
        """Return the rename range and placeholder, or None if rename is not valid."""
        if self.analyze(uri).has_errors():
            return None

        if self.member_occurrence_at_position(uri, position) is not None:
            return None

        name_info = self.name_at_position(uri, position)
        if name_info is None:
            return None

        definition = self.definition(uri, position)
        if definition is None:
            return None

        if definition["kind"] == "module":
            if not self.import_alias_binds(uri, name_info["name"]):
                return None
        elif (
            name_info["name"] == definition["name"]
            and self.file_uri_suffix(definition["uri"]) == ".py"
        ):
            return None

        return {
            "range": name_info["range"],
            "placeholder": name_info["name"],
        }

    def import_alias_binds(self, uri: str, name: str):
        """Return whether ``name`` is bound as the alias of an import.

        Renaming an unaliased import would rewrite the import statement
        itself while the module on disk keeps its name, breaking the
        import, so only alias names are renamable.
        """
        analysis = self.analyze(uri)
        for entry in analysis.import_entries:
            if entry.local_name != name:
                continue
            if entry.is_alias:
                return True
        return False

    def rename(self, uri: str, position: AnalysisPosition, new_name: str):
        """Build workspace edits for renaming the symbol at ``position``.

        Returns a {uri: [edit, ...]} mapping, or None when rename is not valid.
        Raises ``ValueError`` if ``new_name`` is not a valid Python identifier.
        """
        if not is_identifier(new_name):
            raise ValueError("Invalid identifier: {}".format(new_name))

        # Edits are built from analysis ranges: a document with syntax
        # errors is served from its last error-free analysis, whose ranges
        # may no longer match the current text, so refuse rather than
        # corrupt the buffer.
        if self.analyze(uri).has_errors():
            raise ValueError("Rename requires a document without syntax errors.")

        if self.member_occurrence_at_position(uri, position) is not None:
            return None

        name_info = self.name_at_position(uri, position)
        if name_info is None:
            return None

        definition = self.definition(uri, position)
        if definition is None:
            return None

        if (
            definition["kind"] == "module"
            and not self.import_alias_binds(uri, name_info["name"])
        ):
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

        # A workspace-wide rename would rewrite the imported name everywhere
        # but cannot touch its Python definition, breaking the import.
        # Aliased usages take the local branch above and stay valid.
        if self.file_uri_suffix(definition["uri"]) == ".py":
            return None

        changes = dict()
        for reference in references:
            # Alias tokens of from-imports reference the same definition
            # under a different name and must keep their spelling.
            if reference["name"] != definition["name"]:
                continue

            changes.setdefault(reference["uri"], []).append({
                "range": reference["range"],
                "new_text": new_name,
            })

        if not changes:
            return None

        # The stale-analysis refusal above applies to every edited
        # document, not just the one where rename was invoked.
        for change_uri in changes:
            if self.analyze(change_uri).has_errors():
                raise ValueError(
                    "Rename requires documents without syntax errors: {}".format(
                        self.display_uri(change_uri)
                    )
                )

        return changes
