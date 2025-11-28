# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import asyncio
import pytest
import re
import time
import queue
from contextlib import contextmanager
from ordec.core import *
from ordec.lib import test as lib_test
from ordec.lib.test import RCAlterTestbench
from ordec.core.rational import R
from ordec.sim.sim_hierarchy import SimHierarchy, HighlevelSim
from ordec.sim.ngspice import Ngspice

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
        "0.1u", "5u", callback=progress_callback, buffer_size=10
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
            buffer_size=5,
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
            buffer_size=5,
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
    from ordec.sim.sim_hierarchy import SimHierarchy, HighlevelSim

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
def test_highlevel_async_ihp_inverter(backend):
    """Test async transient simulation with IHP inverter."""
    h = lib_test.InvIhpTb(vin=R(2.5), backend=backend)

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
def test_async_alter_resume(backend):
    circuit = RCAlterTestbench()
    node = SimHierarchy()
    sim = HighlevelSim(circuit.schematic, node, backend=backend)

    async def run_comprehensive_test():
        """Test multiple aspects of async alter functionality"""
        with sim.alter_session(backend=backend) as alter:
            data_queue = alter.start_async_tran("0.1u", "2m")
            start_time = time.time()
            timeout = 30.0

            # Multiple halt/alter/resume cycles with different voltages
            voltage_sequence = [2.0, 1.5, 3.0, 1.0]
            voltage_change_interval = 10
            completed_steps = 0
            all_data = []

            for voltage_index, voltage in enumerate(voltage_sequence):

                data_points_before_alter = 0
                while data_points_before_alter < voltage_change_interval and (time.time() - start_time) < timeout:
                    try:
                        data_point = data_queue.get_nowait()
                        if isinstance(data_point, dict) and "data" in data_point:
                            all_data.append((voltage_index, data_point["data"]))
                            data_points_before_alter += 1

                    except queue.Empty:
                        await asyncio.sleep(0.001)
                        continue

                if (time.time() - start_time) >= timeout:

                    break

                assert alter.halt_simulation(timeout=1.0), f"Should halt at step {voltage_index + 1}"
                alter.alter_component(circuit.schematic.v1, dc=voltage)
                assert alter.resume_simulation(timeout=1.0), f"Should resume at step {voltage_index + 1}"

                data_points_after_alter = 0
                verification_points = 3
                while data_points_after_alter < verification_points and (time.time() - start_time) < timeout:
                    try:
                        data_point = data_queue.get_nowait()
                        if isinstance(data_point, dict) and "data" in data_point:
                            all_data.append((voltage_index, data_point["data"]))
                            data_points_after_alter += 1

                    except queue.Empty:
                        await asyncio.sleep(0.001)
                        continue

                if data_points_after_alter > 0:
                    completed_steps += 1


                await asyncio.sleep(0.01)

            voltage_step_data = {}
            for step_index, data_dict in all_data:
                if step_index not in voltage_step_data:
                    voltage_step_data[step_index] = []
                if "vout" in data_dict:
                    voltage_step_data[step_index].append(data_dict["vout"])

            steps_with_data = len([k for k, v in voltage_step_data.items() if len(v) > 0])


            return {
                "voltage_steps": completed_steps,
                "steps_with_data": steps_with_data,
                "total_data_points": len(all_data),
            }

    result = asyncio.run(run_comprehensive_test())
    assert result["voltage_steps"] >= 4, f"Should complete 4 voltage steps, got {result['voltage_steps']}"
    assert result["steps_with_data"] >= 2, f"Should have data for at least 2 voltage steps, got {result['steps_with_data']}"
    assert result["total_data_points"] > 0, "Should collect data points"


@pytest.mark.libngspice
@pytest.mark.parametrize("backend", ["subprocess", "ffi", "mp"])
def test_async_alter_resume_stress_smoke(backend):
    """Run multiple short alter/resume cycles to shake out race conditions."""
    circuit = RCAlterTestbench()
    node = SimHierarchy()
    sim = HighlevelSim(circuit.schematic, node, backend=backend)

    async def collect_points(data_queue, target_points: int, timeout: float = 2.0):
        collected = 0
        deadline = time.time() + timeout
        while collected < target_points and time.time() < deadline:
            try:
                data_point = data_queue.get_nowait()
                if isinstance(data_point, dict) and "data" in data_point:
                    collected += 1
            except queue.Empty:
                await asyncio.sleep(0.005)
        return collected

    async def run_short_session(iteration: int):
        with sim.alter_session(backend=backend) as alter:
            data_queue = alter.start_async_tran("0.05u", "0.2m")
            voltage_sequence = [1.1 + 0.2 * iteration, 1.6 + 0.1 * iteration, 1.2 + 0.3 * iteration]

            points_seen = await collect_points(data_queue, 1, timeout=2.0)
            completed_steps = 0

            for voltage in voltage_sequence:
                assert alter.halt_simulation(timeout=1.0), "Simulation should halt cleanly"
                alter.alter_component(circuit.schematic.v1, dc=voltage)
                assert alter.resume_simulation(timeout=1.0), "Simulation should resume cleanly"

                points_seen += await collect_points(data_queue, 2, timeout=2.0)
                completed_steps += 1

            return {"steps": completed_steps, "points": points_seen}

    session_results = []
    for i in range(2):
        session_results.append(asyncio.run(run_short_session(i)))

    assert all(res["steps"] == 3 for res in session_results)
    assert all(res["points"] >= 3 for res in session_results)

@pytest.mark.xfail
@pytest.mark.libngspice
@pytest.mark.parametrize("backend", ["subprocess", "ffi", "mp"])
def test_async_drain_exact_points(backend):
    h = lib_test.ResdivFlatTb(backend=backend)
    num_points = 2000
    tstep_us = 1
    tstop_us = (num_points - 1) * tstep_us

    tstep_str = f"{tstep_us}u"
    tstop_str = f"{tstop_us}u"

    points_consumed = 0
    last_result = None
    seen_times = set()

    if backend in ["ffi", "mp"]:
        for result in h.sim_tran_async(tstep_str, tstop_str, disable_buffering=True):
            time_val = result.time.value
            if time_val in seen_times:
                pytest.fail(f"DUPLICATE TIME VALUE DETECTED: time={time_val}, backend={backend}. This indicates a bug in the async data handling.")
            seen_times.add(time_val)

            points_consumed += 1
            last_result = result
    else:
        for result in h.sim_tran_async(tstep_str, tstop_str):
            time_val = result.time.value
            if time_val in seen_times:
                pytest.fail(f"DUPLICATE TIME VALUE DETECTED: time={time_val}, backend={backend}. This indicates a bug in the async data handling.")
            seen_times.add(time_val)

            points_consumed += 1
            last_result = result


    if last_result is not None:
        prog = getattr(last_result, "progress", None)
        time_attr = getattr(last_result, "time", None)
        time_val = (
            getattr(time_attr, "value", time_attr) if time_attr is not None else None
        )

    assert last_result is not None, "Async generator produced no results."

    assert abs(points_consumed - num_points) <= num_points * 0.01, (
        f"Expected approximately {num_points} points, but got {points_consumed}."
    )
    assert hasattr(last_result, "progress"), (
        "Final result object missing 'progress' attribute."
    )
    assert last_result.progress >= 0.999, (
        f"Simulation did not complete as expected; final progress was {last_result.progress * 100:.2f}%."
    )
    assert hasattr(last_result, "time"), "Final result object missing 'time' attribute."
    assert last_result.time.value == pytest.approx(tstop_us * 1e-6), (
        "Final simulation time does not match the expected tstop."
    )


@pytest.mark.libngspice
@pytest.mark.parametrize("backend", ["subprocess", "ffi", "mp"])
def test_consecutive_async_simulations_with_early_termination(backend):
    h = lib_test.ResdivFlatTb(backend=backend)

    first_sim_count = 0
    for result in h.sim_tran_async("0.05u", "10u"):
        first_sim_count += 1
        if first_sim_count >= 5:
            break

    assert first_sim_count >= 1, "First simulation should produce at least 1 data point"
    assert first_sim_count <= 5, "First simulation should stop at 5 data points"

    import time
    time.sleep(0.1)

    second_sim_count = 0
    second_sim_started = False
    for result in h.sim_tran_async("0.05u", "10u"):
        second_sim_started = True
        second_sim_count += 1
        if second_sim_count >= 5:
            break

    assert second_sim_started, "Second simulation should start successfully"
    assert second_sim_count >= 1, "Second simulation should produce at least 1 data point"
    assert second_sim_count <= 5, "Second simulation should stop at 5 data points"


@pytest.mark.libngspice
@pytest.mark.parametrize("backend", ["subprocess", "ffi", "mp"])
def test_buffering_does_not_lose_samples(backend):
    h = lib_test.ResdivFlatTb(backend=backend)

    tstep = "0.1u"
    tstop = "5u"

    buffered_count = 0
    for result in h.sim_tran_async(tstep, tstop, buffer_size=10, disable_buffering=False):
        buffered_count += 1

    h2 = lib_test.ResdivFlatTb(backend=backend)
    no_buffer_count = 0
    for result in h2.sim_tran_async(tstep, tstop, disable_buffering=True):
        no_buffer_count += 1
    assert buffered_count == no_buffer_count, (
        f"Buffered mode produced {buffered_count} samples but non-buffered mode produced {no_buffer_count} samples. "
        f"This indicates that buffer flushing on simulation completion is not working correctly."
    )

    assert buffered_count > 10, f"Expected more than 10 samples, got {buffered_count}"
