:mod:`ordec.core.cell` --- Cell and @generate
=============================================

.. automodule:: ordec.core.cell

.. autoclass:: Cell
  :members:

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
