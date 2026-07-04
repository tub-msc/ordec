# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from importlib.metadata import version, PackageNotFoundError

try:
    version = version("ordec")
except PackageNotFoundError:
    version = 'unknown'

def doc_url(page: str='') -> str:
    """
    Returns the URL of a documentation page (e.g. 'webui.html') matching the
    installed ORDeC version. For development versions, whose documentation is
    not on Read the Docs, the latest documentation is referenced instead.
    """
    if version == 'unknown' or '.dev' in version:
        slug = 'latest'
    else:
        slug = 'v' + version
    return f'https://ordec.readthedocs.io/en/{slug}/{page}'
