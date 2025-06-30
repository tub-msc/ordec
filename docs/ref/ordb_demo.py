# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.16.4
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# (ordb_demo)=

# # ORDB Demo

# This Jupyter notebook demonstrates the five main principles of ORDB, which is ORDeC's data model layer. In addition, it briefly introduces ORDeC's Cell-and-@generate pattern.

# ## Principle 1: schema-based

# All ORDB data must conform to some predefined schema. Usually, we would use the Node and SubgraphHead subclasses defined in {ref}`data-schema` (which are for IC design data), but for this example we will define a small example schema describing a planet with airports and flights that connect airports.

# +
from ordec.ordb import *
class Planet(SubgraphHead):
    diameter = Attr(float)

class Airport(Node):
    label = Attr(str)
    year_opened = Attr(int)
    
class Flight(Node):
    flight_code = Attr(str)
    duration = Attr(int)
    origin = LocalRef(Airport)
    destination = LocalRef(Airport)
    
    origin_idx = Index(origin) # will be discussed later
    destination_idx = Index(destination) # will be discussed later


# -

# We can now create a planet and add some airports and flights to it:

earth = Planet(diameter=12756)
earth.ber = Airport(label="Berlin Brandenburg Airport", year_opened=2012)
earth.cdg = Airport(label="Paris Charles de Gaulle Airport", year_opened=1974)
earth.lax = Airport(label="Los Angeles International Airport", year_opened=1928)
earth.nrt = Airport(label="Narita International Airport", year_opened=1978)

# We added the airport nodes using the "." oprator directly to earth. They can subsequently be accessed using the same operator. For example, we can figure out some attribute of the LAX airpot:

earth.lax.year_opened

# Note that earth.lax gives us a ORDB Cursor. The underlying database tuple (Node / row) is hidden in earth.lax.node.

earth.lax

earth.lax.node

# Notice that a **node ID (nid)** was automatically assigned to each node/Airport. The node ID is unique to the subgraph (in this case, planet):

earth.ber.nid, earth.cdg.nid, earth.lax.nid, earth.nrt.nid

# We can also update attributes of nodes after insertion. This does not change their nid.

earth.ber.year_opened = 2020
earth.ber

# Using the "%" modulo operator, we can add anonymous nodes to the database. These anonymous nodes cannot be accessed as a named child of "earth", but the modulo operator returns Cursor references that we can save in variables. Let's add a few flights as anonymous nodes:

abc123 = earth % Flight(flight_code="ABC123", origin=earth.ber, destination=earth.cdg, duration=60)
abc124 = earth % Flight(flight_code="ABC124", origin=earth.cdg, destination=earth.ber, duration=60)
earth % Flight(flight_code="XYZ50", origin=earth.cdg, destination=earth.nrt, duration=700)
earth % Flight(flight_code="XYZ51", origin=earth.nrt, destination=earth.cdg, duration=650)
earth % Flight(flight_code="XYZ60", origin=earth.nrt, destination=earth.lax, duration=510)
xyz90 = earth % Flight(flight_code="XYZ90", origin=earth.lax, destination=earth.cdg, duration=900)

# We can retrieve data from the anonymous node Cursors and also follow their references (origin and destination) transparently:

print(f"Flight {xyz90.flight_code} goes from {xyz90.origin.label} to {xyz90.destination.label}.")

# In the underlying database tuples, the origin and destination attributes are stored as nid references: 

xyz90.node

# Using the Subgraph.tables method, we can view our data in tabular form:

print(earth.tables())

# Furthermore, Subgraph.dump() exports the subgraph as Python expression, which we can use to reconstruct the subgraph:

print(earth.dump())

# In many cases, we want to iterate over all nodes of a specific type. This can be done using the method Subgraph.all():

for airport in earth.all(Airport):
    print(airport)

# ## Principle 2: Relational queries

# Each airport can be the origin of multiple flights, but each flight originates at exactly one airport (1:n relation). While the ORDB cursor directly supports navigation from flight to its origin airport, the opposite direction is a bit more challenging, because the airport tuple does not store the nids of the flights originating there. For this type of query, an index is required. Fortunately, we have already defined indices for origin (origin_idx) and destination (destination_idx) in the schema definition of Flight above.
#
# We can use these indices to query all flights originating at a particular airport:

for flight in earth.all(Flight.origin_idx.query(earth.cdg.nid)):
    print(flight)

# ## Principle 3: Hierarchical tree organization

# You might have already noted that our subgraph "earth" was automatically populated with some NPath nodes. These NPath nodes define a hierarchical tree structure for named nodes. When we added the airports, NPath nodes were added at the root of this tree (parent=None).
#
# Using Subgraph.mkpath(), we can create arbitrary intermediate layers in this path tree. Let's add some airports with hierarchical organization:

earth.mkpath("united_kingdom")
earth.united_kingdom.man = Airport(label="Manchester Airport", year_opened=1938)
x = earth.united_kingdom.man
print(x)

# We can retrieve the full path from a cursor using the Cursor.full_path_str() method:

x.full_path_str()

# At the root of the tree, path segments mut be strings starting with a letter. Beyond the root, integers can also be used. In this context, the paths must be accessed using the item operator "[]" in Python:

earth.united_kingdom.mkpath('london')
earth.united_kingdom.london[0] = Airport(label="Heathrow Airport", year_opened=1929)
earth.united_kingdom.london[1] = Airport(label="London City Airport", year_opened=1987)
x = earth.united_kingdom.london[0]
print(x)

# Cursor.parent helps navigating the tree:

print(x.parent[1])

# Note that the paths are primarily a naming convenience. The underlying nodes are still store in a flat structure. In the context on IC design, paths are useful for array and struct instances and for designs with hierarchical subunits.

# ## Principle 4: Persistent data structure
#
# So far, we wrote and read various nodes of our subgraph "earth". Internally, the nodes are stored in a persistent map data structure (pyrsistent.PMap):

print(earth.nodes)

# Persistent data structures are immutable and never need to be copied. Creating a copy of earth gives us a new Python object, but this new earth2 references the identical underlying PMap:

earth2 = earth.copy()
earth2.nodes is earth.nodes

# Once we modify earth2, its "nodes" PMap in earth2 is replaced with a new one.

earth2 % Flight(flight_code="ABC100", origin=earth.united_kingdom.man, destination=earth.cdg, duration=45)
earth2.nodes is earth.nodes

# The new flight is part of earth2, but not of the original earth:

list(earth2.all(Flight.origin_idx.query(earth.united_kingdom.man.nid)))


# list(earth.all(Flight.origin_idx.query(earth.united_kingdom.man.nid)))

# One critical part of the persistent data structure PMap is that the insertion of the new flight into the nodes PMap created the new PMap earth2.nodes (1) without copying the entire previous earth.nodes and (2) while still preserving the immutability of earth.nodes.
#
# ## Principle 5: Mutable and immutable interfaces
#
# So far, the "earth" and "earth2" objects that we have operated on were MutableSubgraphs. If we pass a MutableSubgraph to a function, there is a danger that we accidentally modify it. This could lead to undesirable side effects outside the function!

def count_flights(planet):
    count = 0
    for flight in planet.all(Flight):
        count += 1
        flight.delete()
    return count


count_flights(earth2)

count_flights(earth2)

# Whoops! We have accidentally deleted all flights from earth2, even though we only passed it as an argument to count_flights(). This is really undesirable behavior!
#
# To prevent this, we can freeze subgraphs, which makes them immutable. Attempts to modify a FrozenSubgraph will lead to a TypeError:

earth_frozen = earth.freeze()

try:
    count_flights(earth_frozen)
except TypeError as e:
    print("This led to an exception:", e)


# FrozenSubgraphs are conveniently used at function boundaries, preventing unintended side effects.

# ## References between subgraphs

# Another important part of ORDB are references between subgraphs. To explore this, let's define a second type of subgraph for flight tickets:

# +
class Ticket(SubgraphHead):
    price = Attr(float)
    planet = Attr(Planet)

class TicketSegment(Node):
    flight = ExternalRef(Flight, of_subgraph=lambda c: c.subgraph.planet)
    seat = Attr(str)
    
myticket = Ticket(price=1999, planet=earth_frozen)

f1 = [f for f in earth_frozen.all(Flight) if f.origin==earth_frozen.lax and f.destination==earth_frozen.cdg][0]
f2 = [f for f in earth_frozen.all(Flight) if f.origin==earth_frozen.cdg and f.destination==earth_frozen.ber][0]

myticket % TicketSegment(flight=f1, seat="15C")
myticket % TicketSegment(flight=f2, seat="39B")

print(myticket.tables())
# -

# Our cursors now also work beyond the boundaries of the "myticket" subgraph:

sum([segment.flight.duration for segment in myticket.all(TicketSegment)])

# Note that subgraph references such as Ticket.planet must always point to FrozenSubgraphs. Here, a MutableSubgraph leads to a TypeError:

try:
    another_ticket = Ticket(price=1999, planet=earth)
except TypeError as e:
    print("This led to an exception:", e)

# ## Cell and @generate
#
# ORDeC organizes IC design data in Cell subclasses. These Cell subclasses represent hardware units for which different ORDB subgraphs can be generated, e.g. a symbol, a schematic, a layout, and/or simulation results.

# +
from ordec.base import *
from ordec.lib import Res, Gnd, Vdc

class VoltageDivider(Cell):
    @generate
    def schematic(self):
        print("INFO: Generating the schematic!")
        s = Schematic(cell=self, outline=Rect4R(0, 0, 4, 9))
        s.a = Net()
        s.b = Net()
        s.c = Net()
        
        s.R0 = SchemInstance(Res(r=R(100)).symbol.portmap(m=s.a, p=s.b), pos=Vec2R(0, 0))
        s.R1 = SchemInstance(Res(r=R(100)).symbol.portmap(m=s.b, p=s.c), pos=Vec2R(0, 5))
        
        return s


# -

# All Cell subclasses differ in an important way from regular Python classes: Instantiating them multiple times with identical parameters returns the same instance:

VoltageDivider() is VoltageDivider()

# Methods using the @generate decorator as special "view generators". They have no parameters beside "self" and are accessed like attributes/properties, without "()". Their code is only executed on the first access. 

print(repr(VoltageDivider().schematic))

# The result is internally cached and returned on subsequent accesses:

print(repr(VoltageDivider().schematic))

# This (incomplete) schematic subgraph generated by VoltageDivider.schematic can also be rendered in Jupyter:

VoltageDivider().schematic

# Cells can be **parametrized**. Cell-level parameters can be accessed under "self.params" by the view generators:

# +
from ordec.base import *
from ordec.lib import Res, Gnd, Vdc

class ParamVDiv(Cell):
    @generate
    def schematic(self):
        print("INFO: Generating the schematic!")
        s = Schematic(cell=self, outline=Rect4R(0, 0, 4, 9))
        s.a = Net()
        s.b = Net()
        s.c = Net()
        
        s.R0 = SchemInstance(Res(r=self.params.r / 2).symbol.portmap(m=s.a, p=s.b), pos=Vec2R(0, 0))
        s.R1 = SchemInstance(Res(r=self.params.r / 2).symbol.portmap(m=s.b, p=s.c), pos=Vec2R(0, 5))
        
        return s


# -

# Whenever parameters differ, distinct Cells are generated:

ParamVDiv(r=R(200)) is not ParamVDiv(r=R(100))

# In the example above, the parameter "r" is used to calculate the resistance of both resistors of the ParamVDiv.schmatic. In the example below, setting the parameter to 456 leads to resistances of 228 Ω for both resistors:

ParamVDiv(r=R(456)).schematic


# ### Legacy @generate
#
# The old way to use the @generate is shown in the following example:

# +
class ParamVDiv(Cell):
    @generate(Schematic)
    def schematic(self, s):
        print("INFO: Generating the schematic!")
        s.outline = Rect4R(0, 0, 4, 9)
        
        s.a = Net()
        s.b = Net()
        s.c = Net()
        
        s.R0 = SchemInstance(Res(r=self.params.r / 2).symbol.portmap(m=s.a, p=s.b), pos=Vec2R(0, 0))
        s.R1 = SchemInstance(Res(r=self.params.r / 2).symbol.portmap(m=s.b, p=s.c), pos=Vec2R(0, 5))

ParamVDiv(r=R(456)).schematic
# -

# This way of using @generate is discouraged now and will at some point be removed from the code. Currently, it is still heavily used throughout the codebase.
