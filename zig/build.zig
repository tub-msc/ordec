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

    // C-ABI shared library for the Python bridge (ordec/zigbridge/):
    const capi_mod = b.createModule(.{
        .root_source_file = b.path("src/capi.zig"),
        .target = target,
        .optimize = optimize,
        .imports = &.{
            .{ .name = "ordb", .module = mod },
        },
        .link_libc = true,
    });
    const lib = b.addLibrary(.{
        .name = "ordec_zig",
        .linkage = .dynamic,
        .root_module = capi_mod,
    });
    b.installArtifact(lib);

    const mod_tests = b.addTest(.{ .root_module = mod });
    const run_mod_tests = b.addRunArtifact(mod_tests);
    const capi_tests = b.addTest(.{ .root_module = capi_mod });
    const run_capi_tests = b.addRunArtifact(capi_tests);
    const test_step = b.step("test", "Run unit tests");
    test_step.dependOn(&run_mod_tests.step);
    test_step.dependOn(&run_capi_tests.step);

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
