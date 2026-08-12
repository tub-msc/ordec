:mod:`ordec.core.cell` --- Parametrizable cells and view generators
===================================================================

.. automodule:: ordec.core.cell

This module offers the :class:`Cell` class, which acts as base class for user-defined design cells (modules) in ORDeC. Cell subclasses typically define view generator methods through ``@viewgen`` (what ORD's ``viewgen`` keyword compiles to) or ``@viewgen_noctx``. Cell subclasses can be parametrized through :class:`Parameter`.

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

        @viewgen_noctx
        def schematic(self):
            print("param1 is", self.param1)
            print("param2 is", self.param2)
            print("param3 is", self.param3)
            # ...

    SomeCell('100k', 123, 'string parameter').schematic

.. autoexception:: ParameterError

View generators
---------------

.. admonition:: Changed behavior

    These decorators replace the former ``@generate`` (method form) and
    ``@generate_func`` (function form), which are gone without aliases. The
    old pair was split by *placement*; the new pair is split by *body
    protocol*, with placement handled by usage dispatch — one decorator
    instance works both as a Cell class attribute and as a plain function.
    The motivation: the protocol a body follows should be declared by the
    author, never inferred by the runtime. ``@viewgen_noctx`` is also
    stricter than ``@generate`` was: a stray node operation in its body now
    raises instead of silently leaking into an enclosing viewgen's view.

There are two view generator decorators, distinguished by the **protocol of
the body**:

- ``@viewgen`` — the body populates an implicit, context-managed view root
  (established via ``. = ...`` adoption or the return annotation) and must
  not return a value. This is what the ORD ``viewgen`` keyword emits.
- ``@viewgen_noctx`` — the body is a plain function that builds and returns
  the finished view. No viewgen context is installed, so a stray node
  operation raises instead of leaking into an enclosing viewgen; the return
  annotation is never consulted.

The protocol is always declared by the decorator, never inferred from the
body. Both decorators support the same two **usage forms**, dispatched by
usage: bound as a Cell class attribute, the decorated body is a method (its
receiver parameter binds the cell instance) and the view is cached per cell
instance; used as a plain function, the body must be parameterless and the
view is cached on the generator itself.

.. autodecorator:: viewgen

  Example (ORD keyword and explicit decorator are equivalent):

  .. code-block:: python

    class SomeCell(Cell):
        @viewgen
        def schematic(self) -> Schematic:
            net a, b   # ORD node statements populate the implicit root
            # ...

.. autodecorator:: viewgen_noctx

  Example:

  .. code-block:: python

    class SomeCell(Cell):
        @viewgen_noctx
        def schematic(self):
            s = Schematic(cell=self)
            s.my_net = Net()
            # ...
            return s

  Function form (no receiver parameter):

  .. code-block:: python

    @viewgen_noctx
    def schematic():
        s = Schematic()
        s.my_net = Net()
        # ...
        return s

Both decorators accept optional parameters. To disable automatic refreshing
in the web interface (e.g. for long simulations):

.. code-block:: python

    class SomeCell(Cell):
        @viewgen_noctx(auto_refresh=False)
        def schematic(self):
            # ...

Re-decorating a view generator reconfigures it instead of nesting: the outer
decorator takes over the wrapped body and picks the protocol. This is how
``@viewgen(auto_refresh=False)`` stacks on an ORD ``viewgen`` statement.

.. note::

  ``viewgen`` (the keyword) and ``@viewgen_noctx`` are two first-class
  protocols, in ``.py`` as well as in ``.ord`` files. Neither style is
  deprecated. See :doc:`ord` for the keyword's semantics (adoption,
  materialization from the annotation, postprocessing).

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
        @viewgen_noctx
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
