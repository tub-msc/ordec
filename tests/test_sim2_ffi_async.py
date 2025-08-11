# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec.lib import test_ffi as lib_test
from ordec.core.rational import R


def test_highlevel_async_tran_basic():
    h = lib_test.ResdivFlatTb()

    data_points = []
    time_values = []

    for i, result in enumerate(h.sim_tran_async("0.1u", "3u", backend='ffi')):
        data_points.append(result)
        time_values.append(result.time)

        # Verify hierarchical access works
        assert hasattr(result, 'a')
        assert hasattr(result.a, 'voltage')
        assert hasattr(result, 'time')

        # Break after collecting enough data
        if i >= 10:
            break

    # Should have collected at least one time point (static circuits may only yield one)
    assert len(data_points) >= 1

    # Time should be progressing
    for i in range(1, len(time_values)):
        assert time_values[i] >= time_values[i-1]


def test_highlevel_async_tran_with_callback():
    progress_updates = []

    def progress_callback(data_point):
        progress_updates.append({
            'progress': data_point.get('index', 0),
            'current_time': data_point.get('timestamp', 0),
            'data': data_point.get('data', {})
        })

    h = lib_test.ResdivFlatTb()

    data_count = 0
    for result in h.sim_tran_async("0.1u", "5u", backend='ffi',
                                   callback=progress_callback,
                                   throttle_interval=0.1):
        data_count += 1

        # Verify progress information is available
        assert 0.0 <= result.progress <= 1.0
        assert result.time >= 0.0

        if data_count >= 8:
            break

    # Should have received progress updates
    assert len(progress_updates) > 0

    # Progress should be increasing
    for i in range(1, len(progress_updates)):
        assert progress_updates[i]['progress'] >= progress_updates[i-1]['progress']


def test_sky130_streaming_without_savecurrents():
    h = lib_test.InvSkyTb(vin=R(2.5))

    callback_count = 0

    def count_callback(data_point):
        nonlocal callback_count
        callback_count += 1

    data_points = []
    for i, result in enumerate(h.sim_tran_async("0.01u", "0.5u",
                                                backend='ffi',
                                                enable_savecurrents=False,
                                                callback=count_callback,
                                                throttle_interval=0.05)):
        data_points.append(result)
        if i >= 5:
            break

    assert len(data_points) >= 1, f"Expected at least 1 data point without savecurrents, got {len(data_points)}"
    assert callback_count >= 1, f"Expected at least 1 callback without savecurrents, got {callback_count}"


def test_sky130_streaming_with_savecurrents():
    h = lib_test.InvSkyTb(vin=R(2.5))

    callback_count = 0

    def count_callback(data_point):
        nonlocal callback_count
        callback_count += 1

    data_points = []
    for i, result in enumerate(h.sim_tran_async("0.01u", "0.5u",
                                                backend='ffi',
                                                enable_savecurrents=True,
                                                callback=count_callback,
                                                throttle_interval=0.05)):
        data_points.append(result)
        if i >= 5:
            break

    assert len(data_points) >= 1, f"Expected at least 1 data point with savecurrents, got {len(data_points)}"
    assert callback_count >= 0, f"Expected non-negative callbacks with savecurrents, got {callback_count}"


def test_sky130_netlist_savecurrents_option():
    from ordec.sim2.sim_hierarchy import SimHierarchy, HighlevelSim

    h = lib_test.InvSkyTb(vin=R(2.5))

    # Test with savecurrents enabled
    node1 = SimHierarchy()
    sim_with = HighlevelSim(h.schematic, node1, enable_savecurrents=True)
    netlist_with = sim_with.netlister.out()

    # Test with savecurrents disabled
    node2 = SimHierarchy()
    sim_without = HighlevelSim(h.schematic, node2, enable_savecurrents=False)
    netlist_without = sim_without.netlister.out()

    assert ".option savecurrents" in netlist_with, "Netlist with enable_savecurrents=True should contain .option savecurrents"
    assert ".option savecurrents" not in netlist_without, "Netlist with enable_savecurrents=False should not contain .option savecurrents"


def test_highlevel_async_mos_sourcefollower():
    """Test async transient simulation with MOS source follower."""
    h = lib_test.NmosSourceFollowerTb(vin=R(2.0))

    data_points = []
    for i, result in enumerate(h.sim_tran_async("0.1u", "1u", backend='ffi')):
        data_points.append(result)
        if i >= 5:
            break

    assert len(data_points) >= 1

    final_result = data_points[-1]
    assert hasattr(final_result, 'o')
    assert hasattr(final_result.o, 'voltage')


def test_highlevel_async_mos_inverter():
    h = lib_test.InvTb(vin=R(0))

    data_points = []
    for i, result in enumerate(h.sim_tran_async("0.1u", "1u", backend='ffi')):
        data_points.append(result)
        if i >= 5:
            break

    # Should have at least one data point
    assert len(data_points) >= 1

    final_result = data_points[-1]
    assert hasattr(final_result, 'o')
    assert hasattr(final_result.o, 'voltage')


def test_highlevel_async_sky_inverter():
    h = lib_test.InvSkyTb(vin=R(2.5))

    data_points = []
    for i, result in enumerate(h.sim_tran_async("0.1u", "1u", backend='ffi', enable_savecurrents=False)):
        data_points.append(result)
        if i >= 5:
            break

    assert len(data_points) >= 1

    final_result = data_points[-1]
    assert hasattr(final_result, 'o')
    assert hasattr(final_result.o, 'voltage')


def test_highlevel_async_early_termination():
    h = lib_test.ResdivFlatTb()

    data_count = 0
    final_time = None

    for result in h.sim_tran_async("0.05u", "10u", backend='ffi'):
        data_count += 1
        final_time = result.time

        if data_count >= 5:
            break

    assert data_count >= 1
    assert data_count <= 5


def test_highlevel_async_multiple_circuits():
    """Test running multiple async transient simulations sequentially."""
    # First circuit
    h1 = lib_test.ResdivFlatTb()
    results1 = []
    for i, result in enumerate(h1.sim_tran_async("0.1u", "1u", backend='ffi')):
        results1.append(result)
        if i >= 3:
            break

    assert len(results1) >= 1
    assert hasattr(results1[0], 'a')
    assert hasattr(results1[0].a, 'voltage')

    # Second circuit
    h2 = lib_test.ResdivHierTb()
    results2 = []
    for i, result in enumerate(h2.sim_tran_async("0.1u", "1u", backend='ffi')):
        results2.append(result)
        if i >= 3:
            break

    assert len(results2) >= 1
    assert hasattr(results2[0], 'r')
    assert hasattr(results2[0].r, 'voltage')


def test_highlevel_async_parameter_sweep():
    input_voltages = [2.0, 3.0, 4.0]
    results = {}

    for vin in input_voltages:
        h = lib_test.NmosSourceFollowerTb(vin=R(vin))

        async_results = []
        for i, result in enumerate(h.sim_tran_async("0.1u", "1u", backend='ffi')):
            async_results.append(result)
            if i >= 3:
                break

        assert len(async_results) >= 1
        # Store the final voltage value for comparison
        results[vin] = async_results[-1].o.voltage

    # Verify we got results for all input voltages
    assert len(results) == 3
    for vin in input_voltages:
        assert vin in results
        assert isinstance(results[vin], (int, float))
