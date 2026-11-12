# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import logging
import os
import shlex
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def run(script, cwd, rcfile, capture=None, env=None, **kwargs):
    """
    Run magic Tcl script 'script' in directory 'cwd' with the technology
    that the startup file 'rcfile' loads. The keyword args are set as Tcl
    variables before the script runs.

    Args:
        capture: Optional file name (relative to cwd) to which stdout and
            stderr are redirected.
        env: Optional environment variables in addition to the inherited
            ones, e.g. for the startup file to find the PDK.

    Raises:
        subprocess.CalledProcessError: if the script raises a Tcl error.
    """
    cmdline = ['magic', '-dnull', '-noconsole', '-rcfile', str(rcfile)]
    # Magic exits with 0 when a script given on its command line fails, so
    # the script is sourced from stdin, where a Tcl error exits with 1.
    commands = ['set %s {%s}' % (k, v) for k, v in kwargs.items()]
    commands += [
        'if {[catch {source {%s}}]} {puts stderr $::errorInfo; exit 1}' % script,
        'quit -noprompt',
    ]
    stdin = '\n'.join(commands) + '\n'
    env = os.environ | (env or {})
    logger.debug("%s %s", cwd, shlex.join(cmdline))
    if capture is None:
        subprocess.run(cmdline, cwd=cwd, input=stdin, text=True, env=env, check=True)
    else:
        with open(Path(cwd) / capture, 'w') as f:
            subprocess.run(cmdline, cwd=cwd, input=stdin, text=True, env=env, check=True,
                stdout=f, stderr=subprocess.STDOUT)
