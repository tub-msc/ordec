# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

from setuptools import setup, find_packages, Extension
from setuptools.command.build_py import build_py
from setuptools.command.build import build
import subprocess
from pathlib import Path
import time
import shutil

# Optional Cython extension for accelerated A* routing
# .venv/bin/python3.12 setup.py build_ext --inplace
try:
    from Cython.Build import cythonize
    import numpy as np
    ext_modules = cythonize(
        [Extension(
            "ordec.schematic._routing_fast",
            ["ordec/schematic/_routing_fast.pyx"],
            include_dirs=[np.get_include()],
        )],
        compiler_directives={'language_level': '3'},
    )
except ImportError:
    ext_modules = []

class NpmBuild(build):
    def run(self):
        subprocess.check_call(['npm', '--prefix', 'web/', 'ci'])
        subprocess.check_call(['npm', '--prefix', 'web/', 'run', 'build'])
        subprocess.check_call(['tar', 'cvf', 'ordec/webdist.tar', '-C', 'web/dist', '.'])
        build.run(self)

setup(
    cmdclass={
        'build': NpmBuild
    },
    ext_modules=ext_modules
)
