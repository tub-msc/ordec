# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.16.7
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# # Data model demo

# ## A simple schema and a Cell with Views
#
# The following example demonstrates basic ideas of a data schema, nodes, cells and views.
# In this example, we consider bags of fruits, whose outside appearances and contents can be inspected.
# For its real application of IC design, ORDeC defines a more complex {ref}`data-schema`.
#
# To start, we define a data schema:

# +
from ordec import Cell, View, Node, attr, generate
from collections.abc import Mapping

class BagOutside(View):
    color = attr(type=str|type(None))
    volume = attr(type=int|type(None))
    price_tag = attr(type=int|type(None))

class Fruit(Node):
    color = attr(type=str|type(None))

class BagContent(View):
    children: Mapping[str|int, Fruit]
    total_weight = attr(type=int|type(None))


# -
# Notice the distinction between attributes and children in BagContent.
#
# Now we can define a specific sort of FruitBag:

class FruitBag(Cell):
    @generate(BagOutside)
    def outside(self, view):
        view.volume = 1500
        view.price_tag = 2
        view.color = 'brown'

    @generate(BagContent)
    def content(self, view):
        view.apple = Fruit()
        # An attribute can be set after the node is created:
        view.apple.color = 'red'
        # Or during node creation:
        view.pear = Fruit(color='green')
        view.banana = Fruit(color='yellow')
        # total_weight is an attribute of "content" itself:
        view.total_weight = 100


# FruitBag is a {class}`Cell` subclass and therefore behaves differently than a regular Python class. For example, every instantiation of FruitBag returns the identical object:

fb = FruitBag()
fb2 = FruitBag()
fb is fb2 # beyond a and b being equal (==), they reference the same object.

# In Cell instances, **views are accessed like attributes**. Their first access causes the view method to be evaluated, which is known as lazy evaluation:

bag_1 = fb.outside
print(bag_1.tree())


# We see that bag_1 is a View with the attributes volume, price\_tag and color.
#
# After the view method has been called, the result is saved. On subsequent accesses, the same view is returned without repeated evaluation: 

bag_2 = fb.outside
bag_1 is bag_2 # beyond bag_1 and bag_2 being equal (==), they reference the same object.

# {class}`Node` and {class}`View` objects can have **attributes** and **child nodes**. In the above example, FruitBag().outside has three attributes and no children. FruitBag().content returns a view with three children (apple, pear, banana) and one attribute (total_weight):

print(fb.content.tree())

# Attributes and children can be accessed in the following way:

fb.content.total_weight, fb.content.apple, fb.content.apple.color


# ## Parametric Cells
#
# Cells can have parameters:

class ParametricFruitBag(Cell):
    @generate(BagOutside)
    def outside(self, view):
        if self.params.size == 'large':
            view.volume = 1500
            view.price = 3
        else:
            view.volume = 1000
            view.price = 2
        view.color = 'brown'

    @generate(BagContent)
    def content(self, view):
        view.apple = Fruit(color='red')
        view.pear = Fruit(color='green')
        view.total_weight = 70
        if self.params.size == 'large':
            view.banana = Fruit(color='yellow')
            view.total_weight += 30


# Cell objects with identical parameters are references to the same underlying object:

ParametricFruitBag(size='large') is ParametricFruitBag(size='large')

# When parameters differ, different Cell objects are created:

ParametricFruitBag(size='small') is ParametricFruitBag(size='large')

# Views can vary based on parameters:

print(ParametricFruitBag(size='small').content.tree())
print(ParametricFruitBag(size='large').content.tree())

# ## Node trees
#
# Each {class}`Cell` object forms the root of a tree of {class}`Node` objects. 
# The immediate children of the {class}`Cell` are {class}`View` objects. ({class}`View` is a subclass of {class}`Node`.)
#
# After a View is generated, its Node subtree is **frozen**, i.e. made immutable. Mutable objects such as Python dicts or lists must be converted into immutable objects, e.g. using [pyrsistent](https://pyrsistent.readthedocs.io/). In this freezing process, the subgraph can be checked for integrity rules. Due to this freezing, all nodes outside the View tree that is currently being generated are guaranteed immutable and stable.
#
# As mentioned, nodes can have **attributes** and **child nodes**.
# A child *mychild* can be accessed using {code}`node.children['mychild']` or {code}`node.mychild`.
# An attribute *myattr* can be accessed using {code}`node.myattr`.
# Care must be taken to make sure that no name collision between children and attributes occur. Example:

fb = FruitBag()
apple_color = fb.children['content'].children['apple'].color
apple_color2 = fb.content.apple.color
apple_color, apple_color2

# Parent nodes can be accessed using {code}`node.parent`:

fb.content.apple.parent is fb.content, \
    fb.content.apple.parent.parent is fb

# Each node can be identified by its path:

fb.content.apple.path(), str(fb.content.apple.path())


# When a node is created, it must be attached to the parent node in one of three ways:
#
# * using Python's attribute assignment operator ({code}`.childname =`, as shown in the examples above), in which case the node is assigned a string name from the perspective of the parent.
# * using Python's item assignment operator (brackets)
# * using Node.anonymous() or "%" for anonymous node attachment.
#
# This example shows all three options:

# +
class NewFruitBag(Cell):
    @generate(BagContent)
    def content(self, view):
        view.apple = Fruit(color='red') # attach by str name
        view[1] = Fruit(color='green') # attach by int name
        view % Fruit(color='yellow') # attach by anonymous str name

print(NewFruitBag().content.tree())
# -

# For the anonymous node, the name "anon_2" was automatically chosen.
#
# ## Attribute references
#
# In addition to this core node tree, Nodes can reference other Nodes in their attributes. This makes it possible to build complex **graphs**. Such **attribute references** can be:
#
# * to other Nodes within the same View or
# * to another View or nodes of another View of the same Cell object (e.g. schematic links to symbol) or
# * to another Cell object or
# * to a View or nodes of a View of another Cell object.
#
# Due to Views being immutable after generation, it follows that Views form a **directed acyclic graph** (DAG). (Cells are not necessarily in a DAG relation, as different Views between Cells can have criss-crossing relations.)
#
# The attribute reference graph can have **cycles**, but cycles must be limited within one View tree.
#
# For most designs, Cell classes must relate to each other. Example: An oscillator cell contains an inverter, which contains nmos and pmos transistors. Typical design tools use sets of design libraries or a flat global library to give a context for relations between Cells. In ORDeC, the Python namespace and import system currently fills this role.

# ## Deprecated: type annotation instead of @generate decorator
#
# It is possible but deprecated to define view methods just by annotating the node type instead of using the @generate decorator:

# +
from ordec import generate

class AnotherFruitBag(Cell):
    def content1(self, view) -> BagContent:
        view.apple = Fruit(color='red')

    @generate(BagContent)
    def content2(self, view):
        view.apple = Fruit(color='red')
        
print(AnotherFruitBag().content1.tree())
print(AnotherFruitBag().content2.tree())
# -

# This type annotation view method is shorter but does not adhere to the commonly assumed semantics of Python type annotations.
