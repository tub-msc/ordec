:mod:`ordec.core.cell` --- Cell and @generate
=============================================

.. automodule:: ordec.core.cell

.. autoclass:: Cell
  :members:

.. py:decorator:: generate

  Decorator for view generator methods. Example:

  .. code-block:: python

    class SomeCell(Cell):
        @generate
        def schematic(self):
            s = Schematic(cell=self)
            s.my_net = Net()
            # ...
            return s
