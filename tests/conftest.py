# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec.ordb import Subgraph

def pytest_addoption(parser):
    parser.addoption(
        "--update-golden-files",
        action="store_true",
        default=False,
        help="Update the golden files for snapshot tests.",
    )
    parser.addoption(
        "--update-ord-files",
        action="store_true",
        default=False,
        help="Update the converted ORD schematics."
    )

@pytest.fixture
def update_golden(request):
    """Fixture to check if --update-golden-files flag is set."""
    return request.config.getoption("--update-golden-files")


@pytest.fixture
def update_ord(request):
    """Fixture to check if --update-ord-files flag is set."""
    return request.config.getoption("--update-ord-files")

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
