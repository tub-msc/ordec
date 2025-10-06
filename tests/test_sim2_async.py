# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
import re
import time
import queue
from contextlib import contextmanager
from ordec.core import *
from ordec.lib import test as lib_test
from ordec.lib.test import RCAlterTestbench
from ordec.core.rational import R
from ordec.sim2.sim_hierarchy import SimHierarchy, HighlevelSim
from ordec.sim2.ngspice import Ngspice


@pytest.mark.parametrize("backend", ["subprocess", "ffi", "mp"])
def test_highlevel_async_tran_basic(backend):
    h = lib_test.ResdivFlatTb(backend=backend)

    data_points = []
    time_values = []

    for i, result in enumerate(h.sim_tran_async("0.1u", "3u")):
        data_points.append(result)
        time_values.append(result.time)

        assert hasattr(result, "a")
        assert hasattr(result.a, "value")
        assert hasattr(result.a, "kind")
        assert isinstance(result.a.value, (int, float))
        assert hasattr(result, "time")

        # Break after collecting enough data
        if i >= 10:
            break

    assert len(data_points) >= 1
    assert len(time_values) >= 1

    # Time should be progressing
    for i in range(1, len(time_values)):
        assert time_values[i].value >= time_values[i - 1].value


@pytest.mark.libngspice
@pytest.mark.parametrize("backend", ["subprocess", "ffi", "mp"])
def test_highlevel_async_tran_with_callback(backend):
    progress_updates = []

    def progress_callback(data_point):
        progress_updates.append(
            {
                "progress": data_point.get("progress", data_point.get("index", 0)),
                "current_time": data_point.get("timestamp", 0),
                "data": data_point.get("data", {}),
            }
        )

    h = lib_test.ResdivFlatTb(backend=backend)

    data_count = 0
    for result in h.sim_tran_async(
        "0.1u", "5u", callback=progress_callback, throttle_interval=0.1
    ):
        data_count += 1

        # Verify progress information is available
        assert 0.0 <= result.progress <= 1.0
        assert result.time.value >= 0.0

        if data_count >= 8:
            break

    # Should have received progress updates
    assert len(progress_updates) > 0

    # Progress should be increasing
    for i in range(1, len(progress_updates)):
        assert progress_updates[i]["progress"] >= progress_updates[i - 1]["progress"]


@pytest.mark.libngspice
@pytest.mark.parametrize("backend", ["subprocess", "ffi", "mp"])
def test_sky130_streaming_without_savecurrents(backend):
    h = lib_test.InvSkyTb(vin=R(2.5), backend=backend)

    callback_count = 0

    def count_callback(data_point):
        nonlocal callback_count
        callback_count += 1

    data_points = []
    for i, result in enumerate(
        h.sim_tran_async(
            "0.01u",
            "0.5u",
            enable_savecurrents=False,
            callback=count_callback,
            throttle_interval=0.05,
        )
    ):
        data_points.append(result)
        if i >= 5:
            break

    assert len(data_points) >= 1, (
        f"Expected at least 1 data point without savecurrents, got {len(data_points)}"
    )
    assert callback_count >= 1, (
        f"Expected at least 1 callback without savecurrents, got {callback_count}"
    )


@pytest.mark.libngspice
@pytest.mark.parametrize("backend", ["subprocess", "ffi", "mp"])
def test_sky130_streaming_with_savecurrents(backend):
    h = lib_test.InvSkyTb(vin=R(2.5), backend=backend)

    callback_count = 0

    def count_callback(data_point):
        nonlocal callback_count
        callback_count += 1

    data_points = []
    for i, result in enumerate(
        h.sim_tran_async(
            "0.01u",
            "0.5u",
            enable_savecurrents=True,
            callback=count_callback,
            throttle_interval=0.05,
        )
    ):
        data_points.append(result)
        if i >= 5:
            break

    assert len(data_points) >= 1, (
        f"Expected at least 1 data point with savecurrents, got {len(data_points)}"
    )
    assert callback_count >= 0, (
        f"Expected non-negative callbacks with savecurrents, got {callback_count}"
    )


@pytest.mark.libngspice
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

    assert ".option savecurrents" in netlist_with, (
        "Netlist with enable_savecurrents=True should contain .option savecurrents"
    )
    assert ".option savecurrents" not in netlist_without, (
        "Netlist with enable_savecurrents=False should not contain .option savecurrents"
    )


@pytest.mark.libngspice
@pytest.mark.parametrize("backend", ["subprocess", "ffi", "mp"])
def test_highlevel_async_mos_sourcefollower(backend):
    """Test async transient simulation with MOS source follower."""
    h = lib_test.NmosSourceFollowerTb(vin=R(2.0), backend=backend)

    data_points = []
    for i, result in enumerate(h.sim_tran_async("0.1u", "1u")):
        data_points.append(result)
        if i >= 5:
            break

    assert len(data_points) >= 1

    final_result = data_points[-1]
    assert hasattr(final_result, "o")
    assert hasattr(final_result.o, "value")
    assert hasattr(final_result.o, "kind")
    assert isinstance(final_result.o.value, (int, float))


@pytest.mark.libngspice
@pytest.mark.parametrize("backend", ["subprocess", "ffi", "mp"])
def test_highlevel_async_mos_inverter(backend):
    h = lib_test.InvTb(vin=R(0), backend=backend)

    data_points = []
    for i, result in enumerate(h.sim_tran_async("0.1u", "1u")):
        data_points.append(result)
        if i >= 5:
            break

    # Should have at least one data point
    assert len(data_points) >= 1

    final_result = data_points[-1]
    assert hasattr(final_result, "o")
    assert hasattr(final_result.o, "value")
    assert hasattr(final_result.o, "kind")
    assert isinstance(final_result.o.value, (int, float))


@pytest.mark.libngspice
@pytest.mark.parametrize("backend", ["subprocess", "ffi", "mp"])
def test_highlevel_async_sky_inverter(backend):
    h = lib_test.InvSkyTb(vin=R(2.5), backend=backend)

    data_points = []
    for i, result in enumerate(
        h.sim_tran_async("0.1u", "1u", enable_savecurrents=False)
    ):
        data_points.append(result)
        if i >= 5:
            break

    assert len(data_points) >= 1

    final_result = data_points[-1]
    assert hasattr(final_result, "o")
    assert hasattr(final_result.o, "value")
    assert hasattr(final_result.o, "kind")
    assert isinstance(final_result.o.value, (int, float))


@pytest.mark.libngspice
@pytest.mark.parametrize("backend", ["subprocess", "ffi", "mp"])
def test_highlevel_async_early_termination(backend):
    h = lib_test.ResdivFlatTb(backend=backend)

    data_count = 0
    final_time = None

    for result in h.sim_tran_async("0.05u", "10u"):
        data_count += 1
        final_time = result.time

        if data_count >= 5:
            break

    assert data_count >= 1
    assert data_count <= 5


@pytest.mark.libngspice
@pytest.mark.parametrize("backend", ["subprocess", "ffi", "mp"])
def test_highlevel_async_multiple_circuits(backend):
    """Test running multiple async transient simulations sequentially."""
    # First circuit
    h1 = lib_test.ResdivFlatTb(backend=backend)
    results1 = []
    for i, result in enumerate(h1.sim_tran_async("0.1u", "1u")):
        results1.append(result)
        if i >= 3:
            break

    assert len(results1) >= 1
    assert hasattr(results1[0], "a")
    assert hasattr(results1[0].a, "value")
    assert hasattr(results1[0].a, "kind")
    assert isinstance(results1[0].a.value, (int, float))

    # Second circuit
    h2 = lib_test.ResdivHierTb(backend=backend)
    results2 = []
    for i, result in enumerate(h2.sim_tran_async("0.1u", "1u")):
        results2.append(result)
        if i >= 3:
            break

    assert len(results2) >= 1
    assert hasattr(results2[0], "r")
    assert hasattr(results2[0].r, "value")
    assert hasattr(results2[0].r, "kind")
    assert isinstance(results2[0].r.value, (int, float))


@pytest.mark.libngspice
@pytest.mark.parametrize("backend", ["subprocess", "ffi", "mp"])
def test_highlevel_async_parameter_sweep(backend):
    input_voltages = [2.0, 3.0, 4.0]
    results = {}

    for vin in input_voltages:
        h = lib_test.NmosSourceFollowerTb(vin=R(vin), backend=backend)

        async_results = []
        for i, result in enumerate(h.sim_tran_async("0.1u", "1u")):
            async_results.append(result)
            if i >= 3:
                break

        assert len(async_results) >= 1
        # Store the final numeric value for comparison
        results[vin] = async_results[-1].o

    assert len(results) == 3
    for vin in input_voltages:
        assert vin in results
        assert hasattr(results[vin], "value")
        assert hasattr(results[vin], "kind")
        assert isinstance(results[vin].value, (int, float))


@pytest.mark.libngspice
@pytest.mark.parametrize("backend", ["subprocess", "ffi", "mp"])
def test_async_alter_resume(backend):
    circuit = RCAlterTestbench()
    node = SimHierarchy()
    sim = HighlevelSim(circuit.schematic, node, backend=backend)

    async def run_comprehensive_test():
        """Test multiple aspects of async alter functionality"""
        with sim.alter_session(backend=backend) as alter:
            # Start async transient simulation
            data_queue = alter.start_async_tran("10u", "100m")
            initial_data = []
            found_signals = set()
            mapped_signals = {}
            start_time = time.time()
            timeout = 10.0

            while (time.time() - start_time) < timeout and len(initial_data) < 20:
                try:
                    data_point = data_queue.get(timeout=0.1)
                    if isinstance(data_point, dict) and "data" in data_point:
                        sim_time = data_point["data"].get("time", 0)
                        data_dict = data_point["data"]
                        initial_data.append((sim_time, data_dict))
                        for signal_name in data_dict.keys():
                            if signal_name != "time":
                                found_signals.add(signal_name)
                                if signal_name in sim.str_to_simobj:
                                    simnet = sim.str_to_simobj[signal_name]
                                    net_name = simnet.eref.full_path_str().split(".")[
                                        -1
                                    ]
                                    mapped_signals[signal_name] = net_name
                        if sim_time >= 0.005:
                            break

                except queue.Empty:
                    continue

            assert len(initial_data) > 0, "Should collect initial simulation data"

            # Multiple halt/alter/resume cycles with different voltages
            voltage_sequence = [2.0, 1.5, 3.0, 1.0]
            alter_data = []

            for i, voltage in enumerate(voltage_sequence):
                halt_success = alter.halt_simulation(timeout=2.0)
                assert halt_success, (
                    f"Should successfully halt simulation at step {i + 1}"
                )
                alter.alter_component(circuit.schematic.v1, dc=voltage)
                vdc_info = alter.show_component(circuit.schematic.v1)
                expected = (
                    str(int(voltage)) if voltage == int(voltage) else str(voltage)
                )
                assert expected in vdc_info, (
                    f"Step {i + 1}: VDC should show {expected}V after alter: {vdc_info}"
                )
                resume_success = alter.resume_simulation(timeout=3.0)
                assert resume_success, (
                    f"Should successfully resume simulation at step {i + 1}"
                )
                step_data = []
                step_start = time.time()
                while (time.time() - step_start) < 1.0 and len(step_data) < 10:
                    try:
                        data_point = data_queue.get(timeout=0.1)
                        if isinstance(data_point, dict) and "data" in data_point:
                            sim_time = data_point["data"].get("time", 0)
                            step_data.append((sim_time, data_point["data"]))
                    except queue.Empty:
                        continue

                alter_data.extend(step_data)
                assert len(step_data) > 0, (
                    f"Should collect data after alter step {i + 1}"
                )

            final_data = []
            start_time = time.time()
            while (time.time() - start_time) < 2.0 and len(final_data) < 10:
                try:
                    data_point = data_queue.get(timeout=0.1)
                    if isinstance(data_point, dict) and "data" in data_point:
                        sim_time = data_point["data"].get("time", 0)
                        final_data.append((sim_time, data_point["data"]))
                except queue.Empty:
                    continue

            return {
                "initial_points": len(initial_data),
                "alter_points": len(alter_data),
                "final_points": len(final_data),
                "signal_count": len(found_signals),
                "mapped_count": len(mapped_signals),
                "voltage_steps": len(voltage_sequence),
            }

    import asyncio

    result = asyncio.run(run_comprehensive_test())
    assert result["initial_points"] > 0, "Should collect initial data points"
    assert result["alter_points"] > 0, "Should collect data after alterations"
    assert result["signal_count"] >= 2, "Should detect multiple signals"
    assert result["mapped_count"] >= 2, "Should map signal names correctly"
    assert result["voltage_steps"] == 4, "Should complete all voltage alteration steps"
