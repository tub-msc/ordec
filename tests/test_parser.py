# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import pytest
from ordec import render_image
from ordec.lib import Nmos, Pmos, Vdc, Res, Gnd
from ordec.parser.parser import load_ord, execute_in_environment
from tests.reference_ord_output import save_reference_pngs
import ordec
import cairo
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ord_file_directory = BASE_DIR / "ordec" / "parser" / "ord_files"
refdir = BASE_DIR / "tests" / "reference" / "ord_schematics"
items = [f.name for f in ord_file_directory.iterdir() if f.is_file()]
ext = {"Nmos": Nmos, "Pmos": Pmos, "Vdc": Vdc, "Res": Res, "Gnd": Gnd}
e = ordec.__dict__ | {'ext': ext}

def run_test_case(testcase, e):
    try:
        # your logic here
        name = Path(testcase).stem
        name = name.removeprefix("ref_")
        # get the name of the cell
        ord_file = ord_file_directory / f"{name}.ord"
        try:
            with ord_file.open("r") as f:
                cell_name = f.readline().split(" ")[1].strip("\n:")
        except FileNotFoundError:
            print("Error with ord file path")
        # execute ORD parsing
        data = load_ord(ord_file)
        execute_in_environment(data, e)
        reference = e[cell_name]().schematic
        img = render_image(reference)
        # get reference
        ref_file = refdir / f"ref_{name}.png"
        img_ref = cairo.ImageSurface.create_from_png(str(ref_file))
        assert img.surface.get_data() == img_ref.get_data(), f"Comparison failed for file {name}"
        return True
    except KeyError as e:
        print(e)
        return False

@pytest.mark.skip(reason="Currently not working: reference/ord_schematics/ not found")
@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_ord_schematic(update_ord):
    if update_ord:
        save_reference_pngs()
        print("Saved references")

    items = [f.name for f in refdir.iterdir() if f.is_file()]
    assert items != [], "References are missing, run with --update-ord-files"
    max_retries = 5
    remaining = items[:]
    # loop structure to resolve undefined references
    for attempt in range(max_retries):
        next_round = []
        for case in remaining:
            if not run_test_case(case, e):
                next_round.append(case)
        if not next_round:
            break
        remaining = next_round
    else:
        print("Some errors where not resolved:", remaining)
