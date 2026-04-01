# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import types
import pytest
from ordec.core import Subgraph
from ordec.language import compile_ord


class OrdFile(pytest.File):
    """Collect test_* functions from .ord files."""

    def collect(self):
        source = self.path.read_text()
        mod = types.ModuleType(self.path.stem)
        mod.__file__ = str(self.path)
        try:
            code = compile_ord(source, mod.__dict__, str(self.path))
            exec(code, mod.__dict__)
        except Exception as exc:
            # Report compilation failure as a single failing test item
            # so that other test files are still collected and run.
            yield OrdCompileError.from_parent(self, name="compile", error=exc)
            return
        for name, obj in mod.__dict__.items():
            if name.startswith("test_") and callable(obj):
                yield pytest.Function.from_parent(self, name=name, callobj=obj)


class OrdCompileError(pytest.Item):
    """A test item that fails with the .ord file's compilation error."""

    def __init__(self, name, parent, error):
        super().__init__(name, parent)
        self.error = error

    def runtest(self):
        raise self.error

    def repr_failure(self, excinfo):
        return str(excinfo.value)

    def reportinfo(self):
        return self.path, None, f"{self.path}::compile"

def pytest_collect_file(file_path, parent):
    if file_path.suffix == ".ord" and file_path.stem.startswith("test_"):
        return OrdFile.from_parent(parent, path=file_path)

# TODO: --upgrade-golden-files and --update-ord-files are currently not used.

def pytest_addoption(parser):
    parser.addoption(
        "--update-ref",
        action="store_true",
        default=False,
        help="Update reference files, e.g. for renderview_ref.",
    )

@pytest.fixture
def update_ref(request):
    """Fixture to check if --update-golden-files flag is set."""
    return request.config.getoption("--update-ref")

def pytest_assertrepr_compare(op, left, right):
    if isinstance(left, Subgraph) and isinstance(right, Subgraph) and op == "==":
        # TODO: This currently only works if nids match, which is not required for Subgraph.__eq__.
        left_d = left.node_dict()
        right_d = right.node_dict()
        ret = []
        nids_missing_right = left_d.keys() - right_d.keys()
        nids_missing_left = right_d.keys() - left_d.keys()
        nids_common = left_d.keys() & right_d.keys()
        for nid in nids_missing_left:
            ret.append(f"Missing left nid={nid}: {right_d[nid]}")
        for nid in nids_missing_right:
            ret.append(f"Missing right nid={nid}: {left_d[nid]}")
        for nid in nids_common:
            if left_d[nid] == right_d[nid]:
                continue
            ret.append(f"Mismatch nid={nid}:")
            ret.append(f"\tleft: {left_d[nid]}")
            ret.append(f"\tright: {right_d[nid]}")
        return ret
