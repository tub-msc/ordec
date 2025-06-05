# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest

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