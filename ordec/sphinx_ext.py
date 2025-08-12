# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import sphinx.util.inspect
import inspect
from sphinx.ext.autodoc import Documenter, PropertyDocumenter, ClassDocumenter, _get_render_mode
from sphinx.util.typing import get_type_hints, restify, stringify_annotation

from .core import *
from .core.cell import ViewGenerator
from .render import render
from .version import version

# See: https://www.sphinx-doc.org/en/master/development/tutorials/autodoc_ext.html

class ViewgenDocumenter(Documenter):
    """
    Documents @generate methods as Python properties.

    For @generate methods that are annotated to return a Symbol, the Symbol is
    generated and inserted into the documentation. This requires that there
    is at least one discoverable instance of the Cell.
    """
    objtype = 'viewgen'
    directivetype = PropertyDocumenter.objtype
    priority = PropertyDocumenter.priority + 1
    option_spec = dict(PropertyDocumenter.option_spec)

    @classmethod
    def can_document_member(cls, member, membername, isattr, parent) -> bool:
        if isinstance(parent, ClassDocumenter):
            return isinstance(member, ViewGenerator)
        else:
            return False

    def import_object(self, raiseerror: bool = False) -> bool:
        ret = Documenter.import_object(self, raiseerror)
        return ret

    def _return_annotation(self):
        func = self.object.func
        signature = sphinx.util.inspect.signature(
            func, type_aliases=self.config.autodoc_type_aliases
        )
        return signature.return_annotation

    def add_directive_header(self, sig: str) -> None:
        Documenter.add_directive_header(self, sig)
        sourcename = self.get_sourcename()

        rettype = self._return_annotation()
        if rettype is not inspect.Parameter.empty:
            mode = _get_render_mode(self.config.autodoc_typehints_format)
            short_literals = self.config.python_display_short_literal_types
            objrepr = stringify_annotation(rettype, mode, short_literals=short_literals)
            self.add_line('   :type: ' + objrepr, sourcename)

    def document_members(self, all_members: bool = False) -> None:
        pass

    def resolve_name(self, modname, parents, path, base):
        return PropertyDocumenter.resolve_name(self, modname, parents, path, base)

    def add_content(self, more_content: 'StringList | None') -> None:
        sourcename = self.get_sourcename()

        insts = self.parent.discoverable_instances()
        if issubclass(self._return_annotation(), Symbol) and len(insts) > 0:
            subgraph = getattr(self.parent.discoverable_instances()[0], self.objpath[-1])

            self.add_line('   .. raw:: html', sourcename)
            self.add_line('', sourcename)
            for line in render(subgraph).svg().decode('utf-8').split('\n'):
                self.add_line(f"      {line}", sourcename)
            self.add_line('', sourcename)

        super().add_content(more_content)

def setup(app):
    app.setup_extension('sphinx.ext.autodoc')
    app.add_autodocumenter(ViewgenDocumenter)

    return {
        'version': version,
        'parallel_read_safe': True,
        'parallel_write_safe': True,
    }   
