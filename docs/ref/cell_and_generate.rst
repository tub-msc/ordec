:mod:`ordec.core.cell` --- Parametrizable cells and @generate
=============================================================

.. automodule:: ordec.core.cell

This module offers the :class:`Cell` class, which acts as base class for user-defined design cells (modules) in ORDeC. Cell subclasses typically define view generator methods through ``@generate``. Cell subclasses can be parametrized through :class:`Parameter`.

Parametrizable cells
--------------------

.. autoclass:: Cell
  :members:

:class:`Cell` subclasses can be parametrized by adding :class:`Parameter` instances as class attributes.

.. autoclass:: Parameter

  Example:

  .. code-block:: python

    class SomeCell(Cell):
        param1 = Parameter(R)
        param2 = Parameter(int)
        param3 = Parameter(str)

        @generate
        def schematic(self):
            print("param1 is", self.param1)
            print("param2 is", self.param2)
            print("param3 is", self.param3)
            # ...

    SomeCell('100k', 123, 'string parameter').schematic

.. autoexception:: ParameterError

View generators
----------------------

.. autodecorator:: generate

  Example:

  .. code-block:: python

    class SomeCell(Cell):
        @generate
        def schematic(self):
            s = Schematic(cell=self)
            s.my_net = Net()
            # ...
            return s

  To disable automatic refreshing in the web interface (e.g. for long simulations):

  .. code-block:: python

    class SomeCell(Cell):
        @generate(auto_refresh=False)
        def schematic(self):
            # ...

.. autodecorator:: generate_func

  Example:

  .. code-block:: python

    @generate_func
    def schematic():
        s = Schematic()
        s.my_net = Net()
        # ...
        return s

  ``@generate_func`` supports the same optional parameters as ``@generate``, for example:

  .. code-block:: python

    @generate_func(auto_refresh=False)
    def schematic():
        s = Schematic()
        s.my_net = Net()
        # ...
        return s

.. note::

  ORD's ``viewgen`` statement compiles to these decorators (method form to
  ``@generate``, function form to ``@generate_func``), with the view root
  managed by a view context instead of built and returned by the body.
  ``viewgen`` is the ORD-native spelling; ``@generate``/``@generate_func``
  remain the spelling for plain-Python view generators, in ``.py`` as well as
  in ``.ord`` files. Neither style is deprecated.

.. _progress-and-cancellation:

Progress reporting and cancellation
-----------------------------------

Long-running view generators can report progress to the web interface and
offer safe cancellation points via :mod:`ordec.core.genrun`:

.. autofunction:: ordec.core.genrun.progress

.. autofunction:: ordec.core.genrun.checkpoint

.. autofunction:: ordec.core.genrun.cancelable_subprocess

.. autoexception:: ordec.core.genrun.GenCancelled

Example:

.. code-block:: python

    from ordec.core import progress

    class SomeCell(Cell):
        @generate
        def report(self):
            progress("Preparing testbench")
            # ...
            progress("Crunching numbers", 0.5)  # 50% for the progress bar
            # ...
            progress("Sweeping", 0.5, detail=f"corner {i} of {n}")

All three functions are exact no-ops outside the web server (pytest, plain
scripts), so library code can call them unconditionally. Simulation runs
via :class:`ordec.sim.simulator.Simulator` report progress automatically:
transient analyses even include a progress fraction (simulated time /
tstop) and the simulated time itself, derived from the growing ngspice
rawfile — no ``progress()`` calls are needed in the view generator for that.

Put anything that changes on *every* update in ``detail`` rather than in
``status``: progress messages are rate-limited, and only a changed
``status`` bypasses that limit.

Cancellation (triggered from the web UI) raises :class:`GenCancelled`
at the next ``progress()``/``checkpoint()`` call, kills subprocesses
registered with ``cancelable_subprocess()``, and — on CPython — can even
interrupt view generators that never reach a checkpoint. Cancelled (and
failed) generations are not cached; only successful view results are.

:class:`GenCancelled` derives from ``BaseException``, not ``Exception``:
it is out-of-band control flow rather than an error, much like
``KeyboardInterrupt`` and ``SystemExit``. A view generator's
``except Exception:`` therefore cannot swallow a cancellation, but a bare
``except:`` (or ``except BaseException:``) can — the generator then keeps
running to completion, and the web UI reports the request as cancelled
regardless.
