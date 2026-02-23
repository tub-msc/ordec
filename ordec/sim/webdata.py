# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
This module implements the webdata() method of SimHierarchy for the different
simulation types. Directly looking at SimHierarchies this way in the webui is
a bit inflexible, as the user has little control about how data is shown. It
only makes sense for small simulations. For anything "serious" where you want
to customize the output and control which signals are grouped together in which
plots, use the Report class.

At some point, it might want to replace the custom renderers for each sim_type
here and instead generate something that looks like a Report to the webui in
every case. This would reduce code duplication on the frontend.
"""

from public import public
import re
from ..core import *

def get_sim_data(sh: SimHierarchy, voltage_attr, current_attr, top_level_only=True):
        """Helper to extract voltage and current data for different simulation types."""
        voltages = {}
        for sn in sh.all(SimNet):
            if top_level_only and sn.parent_inst is not None:
                continue
            if (voltage_val := getattr(sn, voltage_attr, None)) is not None:
                voltages[sn.full_path_str()] = voltage_val
        currents = {}
        for si in sh.all(SimInstance):
            if top_level_only and si.parent_inst is not None:
                continue
            if (current_val := getattr(si, current_attr, None)) is not None:
                currents[si.full_path_str()] = current_val
        return voltages, currents

def json_seq(values):
    if values is None:
        return None
    return tuple(values)

@public
def webdata(sh: SimHierarchy):
    if sh.sim_type == SimType.TRAN:
        voltages, currents = get_sim_data(sh, 'trans_voltage', 'trans_current')
        voltages = {k: json_seq(v) for k, v in voltages.items()}
        currents = {k: json_seq(v) for k, v in currents.items()}
        return 'transim', {
            'time': json_seq(sh.time),
            'voltages': voltages,
            'currents': currents
        }
    elif sh.sim_type == SimType.AC:
        voltages, currents = get_sim_data(sh, 'ac_voltage', 'ac_current')
        # Convert complex tuples to [real, imag] pairs for JSON
        def complex_to_pairs(vals):
            if vals is None:
                return None
            return tuple((v.real, v.imag) for v in vals)
        voltages = {k: complex_to_pairs(v) for k, v in voltages.items()}
        currents = {k: complex_to_pairs(v) for k, v in currents.items()}
        return 'acsim', {
            'freq': json_seq(sh.freq),
            'voltages': voltages,
            'currents': currents
        }
    elif sh.sim_type == SimType.DCSWEEP:
        if sh.sim_data is None or sh.sweep_field is None:
            return "dcsweep", {
                "sweep": None,
                "sweep_name": sh.sweep_field,
                "voltages": {},
                "currents": {},
            }
        voltages, currents = get_sim_data(sh, "dc_sweep_voltage", "dc_sweep_current")
        voltages = {k: json_seq(v) for k, v in voltages.items()}
        currents = {k: json_seq(v) for k, v in currents.items()}
        return "dcsweep", {
            "sweep": json_seq(sh.sim_data.column(sh.sweep_field)),
            "sweep_name": sh.sweep_field,
            "voltages": voltages,
            "currents": currents,
        }
    elif sh.sim_type == SimType.DC:
        def fmt_float(val, unit):
            x=str(R(f"{val:.03e}"))+unit
            x=re.sub(r"([0-9])([a-zA-Z])", r"\1 \2", x)
            x=x.replace("u", "μ")
            x=re.sub(r"e([+-]?[0-9]+)", r"×10<sup>\1</sup>", x)
            return x

        dc_voltages = []
        for sn in sh.all(SimNet):
            if sn.dc_voltage is None:
                continue
            dc_voltages.append([sn.full_path_str(), fmt_float(sn.dc_voltage, "V")])
        dc_currents = []
        for si in sh.all(SimInstance):
            if si.dc_current is None:
                continue
            dc_currents.append([si.full_path_str(), fmt_float(si.dc_current, "A")])
        return 'dcsim', {'dc_voltages': dc_voltages, 'dc_currents': dc_currents}
    else:
        return 'nosim', {}
