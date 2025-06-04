# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pickle
import numpy as np
from numpy.testing import assert_allclose, assert_equal
from pathlib import Path
import pytest
from ordec.sim import SimulatorResult, DCResult, ACResult, TransientResult

REFERENCE_DIR = Path(__file__).parent / "reference"
REFERENCE_DIR.mkdir(exist_ok=True)

# Default tolerances for comparisons
DEFAULT_RTOL = 1e-5
DEFAULT_ATOL = 1e-8

def extract_simulation_data(result: SimulatorResult) -> dict:
    """Extracts simulation data into a serializable dictionary."""
    data = {}
    primary_data_key = None
    primary_data_values = None
    primary_data_unit = None # Store unit for primary data if applicable

    if isinstance(result, ACResult):
        primary_data_key = 'frequency'
        primary_data_values = result.get_frequency()
        primary_data_unit = 'Hz' # Assuming Hz
    elif isinstance(result, TransientResult):
        primary_data_key = 'time'
        primary_data_values = result.get_time()
        primary_data_unit = 's' # Assuming s
    elif isinstance(result, DCResult):
        analysis_nodes = dict([(a.name, (str(a.unit), a.tolist())) for a in result.analysis.nodes.values()])
        sweep_key = next((key for key in analysis_nodes if key.endswith('-sweep')), None)
        if not sweep_key:
            raise ValueError("Could not automatically identify DC sweep variable.")
        primary_data_key = sweep_key
        primary_data_values = np.array(analysis_nodes[sweep_key][1])
        primary_data_unit = analysis_nodes[sweep_key][0]
    elif isinstance(result, SimulatorResult): # Operating point
         primary_data_key = 'operating_point'
         primary_data_values = np.array([0.0]) # Single point representation
         primary_data_unit = '' # No sweep unit
    else:
        raise TypeError(f"Unsupported result type: {type(result)}")

    if primary_data_key:
        data['primary_data_key'] = primary_data_key
        data['primary_data_values'] = primary_data_values
        data['primary_data_unit'] = primary_data_unit

    signals_data = {}
    try:
        signal_paths = result.list_signals()
        for path in signal_paths:
            str_path = str(path)
            signals_data[str_path] = {
                'values': result.get_signal(path),
                'unit': result.get_unit(path)
            }
    except AttributeError: # Handle OP case
         if primary_data_key == 'operating_point':
             op_data = dict([(a.name, (str(a.unit), a.tolist())) for a in result.analysis.nodes.values()])
             signals_data = {name: {'values': np.array(val_list), 'unit': unit} for name, (unit, val_list) in op_data.items()}
         else:
             raise

    data['signals'] = signals_data
    return data


def compare_simulation_data(golden_data: dict, current_data: dict, rtol: float, atol: float):
    """Compares two simulation data dictionaries."""
    assert golden_data.get('primary_data_key') == current_data.get('primary_data_key'), \
        "Primary data key mismatch."
    assert golden_data.get('primary_data_unit') == current_data.get('primary_data_unit'), \
        f"Primary data unit mismatch for '{golden_data.get('primary_data_key')}'."

    if 'primary_data_values' in golden_data and 'primary_data_values' in current_data:
        assert_allclose(
            golden_data['primary_data_values'],
            current_data['primary_data_values'],
            rtol=rtol, atol=atol,
            err_msg=f"Primary data values ('{golden_data.get('primary_data_key')}') do not match golden file."
        )

    golden_signals = golden_data.get('signals', {})
    current_signals = current_data.get('signals', {})
    golden_signal_keys = set(golden_signals.keys())
    current_signal_keys = set(current_signals.keys())

    assert golden_signal_keys == current_signal_keys, \
        (f"Signal path/name keys mismatch.\n"
         f"  Only in Golden: {golden_signal_keys - current_signal_keys}\n"
         f"  Only in Current: {current_signal_keys - golden_signal_keys}")

    for key in golden_signal_keys:
        golden_signal_info = golden_signals[key]
        current_signal_info = current_signals[key]

        assert golden_signal_info['unit'] == current_signal_info['unit'], \
            f"Unit mismatch for signal '{key}'. Golden: '{golden_signal_info['unit']}', Current: '{current_signal_info['unit']}'"

        assert_allclose(
            golden_signal_info['values'],
            current_signal_info['values'],
            rtol=rtol, atol=atol,
            err_msg=f"Signal '{key}' data does not match golden file."
        )


def assert_result_matches_golden(
    result: SimulatorResult,
    golden_file_name: str,
    update_golden: bool,
    rtol: float = DEFAULT_RTOL,
    atol: float = DEFAULT_ATOL
):
    """
    Extracts data from a simulation result, compares it to a golden pickle file.

    Args:
        result: The ordec.sim.SimulatorResult object from a simulation run.
        golden_file_name: Base name of the golden file (e.g., 'my_test_ac.pkl').
        update_golden: Boolean flag from the pytest fixture.
        rtol: Relative tolerance for numpy.testing.assert_allclose.
        atol: Absolute tolerance for numpy.testing.assert_allclose.
    """
    golden_file_path = REFERENCE_DIR / golden_file_name

    try:
        current_data = extract_simulation_data(result)
    except Exception as e:
        pytest.fail(f"Failed to extract data from simulation result: {e}")

    if update_golden:
        print(f"\nUpdating golden file: {golden_file_path}")
        with open(golden_file_path, "wb") as f:
            pickle.dump(current_data, f, pickle.HIGHEST_PROTOCOL)
        pytest.skip("Golden file updated. Skipping comparison.")
    else:
        if not golden_file_path.exists():
            pytest.fail(f"Golden file not found: {golden_file_path}. "
                        "Run test with --update-golden-files flag to create it.")

        print(f"\nComparing against golden file: {golden_file_path}")
        with open(golden_file_path, "rb") as f:
            golden_data = pickle.load(f)

        try:
            compare_simulation_data(golden_data, current_data, rtol=rtol, atol=atol)
        except AssertionError as e:
            fail_path = REFERENCE_DIR / (golden_file_path.stem + "_FAIL.pkl")
            with open(fail_path, "wb") as f:
                 pickle.dump(current_data, f, pickle.HIGHEST_PROTOCOL)
            print(f"Comparison failed. Current data saved to: {fail_path}")
            pytest.fail(str(e))
        except Exception as e:
            pytest.fail(f"Unexpected error during comparison: {e}")