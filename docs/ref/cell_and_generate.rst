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

  To disable automatic refreshing in the web interface (e.g. for long simulations):

  .. code-block:: python

      @generate(auto_refresh=False)
      def schematic(self):
          # ...
