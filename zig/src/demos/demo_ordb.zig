// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

//! Port of docs/ref/ordb_demo.py: demonstrates the five main principles of
//! ORDB on a small example schema (a planet with airports and flights that
//! connect airports), plus references between subgraphs (flight tickets).
//!
//! Divergences from the Python notebook:
//! - float attrs become R (the port has no floats; canonical CBOR excludes them)
//! - "earth.ber = Airport(...)" becomes put("ber", ...); "earth % Flight(...)"
//!   becomes insert(...); attribute reads become cursor field()/deref()
//! - earth.copy() becomes freeze() + thaw(): the persistent structure is the
//!   delta chain, so the thawed generation shares all parent storage
//! - the Cell-and-@generate section is not ported (the Cell layer is
//!   deliberately outside this port's scope)
//!
//! Run with: zig build demo-ordb

const std = @import("std");
const ordb = @import("ordb");
const meta = ordb.meta;
const Nid = ordb.Nid;
const Str = ordb.Str;
const R = ordb.R;
const idx = ordb.idx;

// Principle 1: schema-based
// -------------------------
// All ORDB data must conform to a predefined schema. The schema is elaborated
// at compile time: a root struct lists its member node types in ordb_nodes.

const Planet = struct {
    diameter: ?R = null,
    pub const ordb_nodes = .{ Airport, Flight };
};

const Airport = struct {
    label: ?Str = null,
    year_opened: ?i32 = null,
};

const Flight = struct {
    flight_code: ?Str = null,
    duration: ?i32 = null,
    origin: meta.LocalRef(.{Airport}, .{}) = .none,
    destination: meta.LocalRef(.{Airport}, .{}) = .none,
    pub const ordb_indexes = .{
        .origin_idx = idx(&.{"origin"}, .{}), // discussed under principle 2
        .destination_idx = idx(&.{"destination"}, .{}),
    };
};

const PlanetSG = ordb.Subgraph(Planet);

// References between subgraphs: a second subgraph type for flight tickets.

fn ofRootPlanet(view: anytype, nid: Nid) ?*meta.FrozenHeader {
    _ = nid;
    return view.rootValue().planet.ptr;
}

const Ticket = struct {
    price: ?R = null,
    planet: meta.SubgraphRef(Planet, .{}) = .none,
    pub const ordb_nodes = .{TicketSegment};
};

const TicketSegment = struct {
    flight: meta.ExternalRef(Planet, .{Flight}, ofRootPlanet, .{}) = .none,
    seat: ?Str = null,
};

const TicketSG = ordb.Subgraph(Ticket);

/// Python's count_flights(): counts flights but accidentally removes them as
/// a side effect — the motivating example for frozen subgraphs.
fn countFlights(view: PlanetSG.View, alloc: std.mem.Allocator) !usize {
    const flights = try view.all(Flight, alloc);
    defer alloc.free(flights);
    for (flights) |f| try f.remove();
    return flights.len;
}

pub fn main() !void {
    var gpa_state: std.heap.DebugAllocator(.{}) = .init;
    defer _ = gpa_state.deinit();
    const gpa = gpa_state.allocator();
    const print = std.debug.print;

    print("== Principle 1: schema-based ==\n", .{});

    var earth = try PlanetSG.Mutable.init(gpa, .{ .diameter = try R.parse("1275.6") });
    defer earth.deinit();

    // Named nodes (Python: earth.ber = Airport(...)):
    const ber = try earth.put("ber", Airport{ .label = "Berlin Brandenburg Airport", .year_opened = 2012 });
    const cdg = try earth.put("cdg", Airport{ .label = "Paris Charles de Gaulle Airport", .year_opened = 1974 });
    const lax = try earth.put("lax", Airport{ .label = "Los Angeles International Airport", .year_opened = 1928 });
    const nrt = try earth.put("nrt", Airport{ .label = "Narita International Airport", .year_opened = 1978 });

    // ...accessible again by name (Python: earth.lax.year_opened):
    const lax_again = try (try earth.root().at("lax")).as(Airport);
    print("earth.lax.year_opened = {?d}\n", .{lax_again.field(.year_opened)});

    // A node ID (nid) was automatically assigned to each airport, unique
    // within the subgraph:
    print("nids: ber={d} cdg={d} lax={d} nrt={d}\n", .{ ber.nid, cdg.nid, lax.nid, nrt.nid });

    // Attributes can be updated after insertion; the nid does not change:
    try ber.set(.year_opened, 2020);
    print("after update: ber.year_opened={?d} (nid still {d})\n", .{ ber.field(.year_opened), ber.nid });

    // Anonymous nodes (Python: earth % Flight(...)); insert() returns a
    // cursor we can keep in a variable:
    _ = try earth.insert(Flight{ .flight_code = "ABC123", .origin = .to(ber), .destination = .to(cdg), .duration = 60 });
    _ = try earth.insert(Flight{ .flight_code = "ABC124", .origin = .to(cdg), .destination = .to(ber), .duration = 60 });
    _ = try earth.insert(Flight{ .flight_code = "XYZ50", .origin = .to(cdg), .destination = .to(nrt), .duration = 700 });
    _ = try earth.insert(Flight{ .flight_code = "XYZ51", .origin = .to(nrt), .destination = .to(cdg), .duration = 650 });
    _ = try earth.insert(Flight{ .flight_code = "XYZ60", .origin = .to(nrt), .destination = .to(lax), .duration = 510 });
    const xyz90 = try earth.insert(Flight{ .flight_code = "XYZ90", .origin = .to(lax), .destination = .to(cdg), .duration = 900 });

    // References (origin, destination) can be followed transparently:
    const org = try xyz90.deref(.origin);
    const dst = try xyz90.deref(.destination);
    print("Flight {?s} goes from {?s} to {?s}.\n", .{ xyz90.field(.flight_code), org.field(.label), dst.field(.label) });

    // In the underlying node value, references are stored as nids:
    const tuple = xyz90.get();
    print("xyz90 node value: flight_code={?s} origin={?d} destination={?d}\n", .{ tuple.flight_code, tuple.origin.nid, tuple.destination.nid });

    // Iterating over all nodes of one type (Python: earth.all(Airport)):
    print("\nAirports (diameter of planet: {f}):\n", .{earth.view().rootValue().diameter.?});
    const airports = try earth.view().all(Airport, gpa);
    defer gpa.free(airports);
    for (airports) |a| {
        print("  nid={d} label={?s} year_opened={?d}\n", .{ a.nid, a.field(.label), a.field(.year_opened) });
    }

    print("\n== Principle 2: relational queries ==\n", .{});

    // Flight -> origin airport is direct navigation; airport -> flights
    // originating there (the 1:n reverse direction) needs an index. We
    // declared origin_idx and destination_idx in the schema above:
    const from_cdg = try earth.view().allBy(Flight, "origin_idx", .{@as(?Nid, cdg.nid)}, gpa);
    defer gpa.free(from_cdg);
    print("flights originating at CDG:\n", .{});
    for (from_cdg) |f| {
        print("  {?s} (duration {?d} min)\n", .{ f.field(.flight_code), f.field(.duration) });
    }

    print("\n== Principle 3: hierarchical tree organization ==\n", .{});

    // NPath nodes form a naming tree over the flat node storage. putPath()
    // creates intermediate layers (Python: earth.united_kingdom = PathNode()):
    const uk = try earth.root().putPath("united_kingdom");
    const man = try uk.put("man", Airport{ .label = "Manchester Airport", .year_opened = 1938 });
    const man_path = try man.fullPathStr(gpa);
    defer gpa.free(man_path);
    print("added {s}: {?s}\n", .{ man_path, man.field(.label) });

    // Beyond the root, integers can be used as path segments:
    const london = try uk.putPath("london");
    _ = try london.put(0, Airport{ .label = "Heathrow Airport", .year_opened = 1929 });
    _ = try london.put(1, Airport{ .label = "London City Airport", .year_opened = 1987 });

    const lhr = try (try (try earth.root().at("united_kingdom")).at("london")).at(0);
    const lhr_path = try lhr.fullPathStr(gpa);
    defer gpa.free(lhr_path);
    print("{s}: {?s}\n", .{ lhr_path, (try lhr.as(Airport)).field(.label) });

    // parent() helps navigating the tree (Python: x.parent[1]):
    const lcy = try (try (try lhr.parent()).at(1)).as(Airport);
    print("sibling via parent(): {?s}\n", .{lcy.field(.label)});

    print("\n== Principle 4: persistent data structure ==\n", .{});

    // Python demonstrates this with earth.copy() on the shared PMap. Here the
    // persistent structure is the delta chain: freeze() the current
    // generation (O(1)), then thaw() a new mutable generation on top of it.
    // Nothing is copied — the new generation references the frozen parent and
    // records only its own delta.
    const earth_v1 = try earth.freeze();
    defer earth_v1.release();

    var earth2 = try earth_v1.thaw();
    defer earth2.deinit();
    print("earth2 references earth_v1 as its parent (no node copies): {}\n", .{earth2.parents[0].frozen == earth_v1});

    _ = try earth2.insert(Flight{ .flight_code = "ABC100", .origin = .to(man), .destination = .to(cdg), .duration = 45 });

    // The new flight is part of earth2, but not of the frozen earth_v1:
    const from_man2 = try earth2.view().allBy(Flight, "origin_idx", .{@as(?Nid, man.nid)}, gpa);
    defer gpa.free(from_man2);
    const from_man1 = try earth_v1.view().allBy(Flight, "origin_idx", .{@as(?Nid, man.nid)}, gpa);
    defer gpa.free(from_man1);
    print("flights from Manchester: earth2={d}, earth_v1={d}\n", .{ from_man2.len, from_man1.len });

    print("\n== Principle 5: mutable and immutable interfaces ==\n", .{});

    // Passing a mutable subgraph to a function risks accidental modification:
    print("countFlights(earth2) = {d}\n", .{try countFlights(earth2.view(), gpa)});
    print("countFlights(earth2) = {d}  <- whoops, the first call deleted them all!\n", .{try countFlights(earth2.view(), gpa)});

    // Frozen subgraphs prevent this: any modification attempt fails.
    if (countFlights(earth_v1.view(), gpa)) |_| {
        unreachable;
    } else |err| {
        print("countFlights(earth_frozen) fails with error.{s}\n", .{@errorName(err)});
    }

    print("\n== References between subgraphs ==\n", .{});

    // Ticket.planet is a SubgraphRef(Planet). Unlike Python (runtime
    // TypeError), referencing a mutable subgraph is impossible by
    // construction here: SubgraphRef .of() only accepts a frozen subgraph.
    var myticket = try TicketSG.Mutable.init(gpa, .{ .price = try R.parse("1999"), .planet = .of(earth_v1) });
    defer myticket.deinit();

    // Find the LAX->CDG and CDG->BER flights on the frozen planet:
    const flights = try earth_v1.view().all(Flight, gpa);
    defer gpa.free(flights);
    var f1: ?PlanetSG.Cursor(Flight) = null;
    var f2: ?PlanetSG.Cursor(Flight) = null;
    for (flights) |f| {
        const n = f.get();
        const o = n.origin.nid orelse continue;
        const d = n.destination.nid orelse continue;
        if (o == lax.nid and d == cdg.nid) f1 = f;
        if (o == cdg.nid and d == ber.nid) f2 = f;
    }

    _ = try myticket.insert(TicketSegment{ .flight = .to(f1.?.nid), .seat = "15C" });
    _ = try myticket.insert(TicketSegment{ .flight = .to(f2.?.nid), .seat = "39B" });

    // Cursors work beyond the boundaries of the ticket subgraph:
    const segs = try myticket.view().all(TicketSegment, gpa);
    defer gpa.free(segs);
    var total: i32 = 0;
    for (segs) |seg| {
        const fl = try seg.derefExternal(.flight);
        print("segment seat {?s}: flight {?s}, {?d} min\n", .{ seg.field(.seat), fl.field(.flight_code), fl.field(.duration) });
        total += fl.field(.duration).?;
    }
    print("total flight duration of ticket (price {f}): {d} min\n", .{ myticket.view().rootValue().price.?, total });
}
