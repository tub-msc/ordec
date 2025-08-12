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

    @generate
    def schematic():
        s = Schematic()
        s.my_net = Net()
        # ...
        return s

  ``@generate_func`` supports the same optional parameters as ``@generate``, for example:

  .. code-block:: python
  
    @generate(auto_refresh=False)
    def schematic():
        s = Schematic()
        s.my_net = Net()
        # ...
        return s
