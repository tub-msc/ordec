# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from setuptools import setup
from setuptools.command.build_py import build_py
import subprocess
import os

class NpmBuildPy(build_py):
    """
    build_py that additionally builds the web frontend and places
    webdist.tar directly into the build directory, keeping the source
    tree free of build artifacts. Editable installs skip the frontend
    build (as before): they have no webdist.tar, which ordec.server
    reports with a pointer to the dev workflow.
    """
    def run(self):
        super().run()
        if self.editable_mode:
            return
        subprocess.check_call(['npm', '--prefix', 'web/', 'ci'])
        subprocess.check_call(['npm', '--prefix', 'web/', 'run', 'build'])
        webdist_tar = os.path.join(self.build_lib, 'ordec', 'webdist.tar')
        subprocess.check_call(['tar', 'cvf', webdist_tar, '-C', 'web/dist', '.'])

setup(
    cmdclass={
        'build_py': NpmBuildPy
    },
)
