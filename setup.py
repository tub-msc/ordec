# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from setuptools import setup, find_packages
from setuptools.command.build_py import build_py
from setuptools.command.build import build
import subprocess
from pathlib import Path
import time
import shutil

class NpmBuild(build):
    def run(self):
        subprocess.check_call(['npm', '--prefix', 'web/', 'install'])
        subprocess.check_call(['npm', '--prefix', 'web/', 'run', 'build'])
        subprocess.check_call(['tar', 'cvf', 'ordec/webdist.tar', '-C', 'web/dist', '.'])
        build.run(self)

setup(
    cmdclass={
        'build': NpmBuild
    },
)
