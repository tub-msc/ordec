// SPDX-FileCopyrightText: 2026 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});

    const mod = b.addModule("ordb", .{
        .root_source_file = b.path("src/root.zig"),
        .target = target,
        .optimize = optimize,
    });

    const mod_tests = b.addTest(.{ .root_module = mod });
    const run_mod_tests = b.addRunArtifact(mod_tests);
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&run_mod_tests.step);

    // Demo executables: zig build demo-placer / zig build demo-ordb
    const demos = [_]struct { name: []const u8, src: []const u8, desc: []const u8 }{
        .{ .name = "demo-placer", .src = "src/demos/demo_placer.zig", .desc = "Run the standard-cell placer demo" },
        .{ .name = "demo-ordb", .src = "src/demos/demo_ordb.zig", .desc = "Run the ORDB principles demo (port of docs/ref/ordb_demo.py)" },
    };
    for (demos) |d| {
        const exe = b.addExecutable(.{
            .name = d.name,
            .root_module = b.createModule(.{
                .root_source_file = b.path(d.src),
                .target = target,
                .optimize = optimize,
                .imports = &.{
                    .{ .name = "ordb", .module = mod },
                },
            }),
        });
        const run_cmd = b.addRunArtifact(exe);
        b.step(d.name, d.desc).dependOn(&run_cmd.step);
    }
}
