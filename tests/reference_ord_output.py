# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

#from ordec import render_image
from ordec.lib import Nmos, Pmos, Vdc, Res, Gnd
from ordec.parser.parser import execute_in_environment, load_ord
import ordec
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ord_file_directory = BASE_DIR / "ordec" / "parser" / "ord_files"
refdir = BASE_DIR / "tests" / "reference" / "ord_schematics"
items = [f.name for f in ord_file_directory.iterdir() if f.is_file()]
ext = {"Nmos": Nmos, "Pmos": Pmos, "Vdc": Vdc, "Res": Res, "Gnd": Gnd}
e = ordec.__dict__ | {'ext': ext}

def build_and_save_reference(case, e):
    refdir.mkdir(parents=True, exist_ok=True)
    try:
        # get the name of the cell
        ord_file = ord_file_directory / case
        try:
            with ord_file.open("r") as f:
                cell_name = f.readline().split(" ")[1].strip("\n:")
        except FileNotFoundError:
            print("Error with ord file path")
        # load and execute
        data = load_ord(ord_file)
        execute_in_environment(data, e)
        reference = e[cell_name]().schematic
        img = render_image(reference)
        #img = ordec.render_svg(reference)
        # save reference in file
        name, _ = os.path.splitext(case)
        ref_file = refdir / f"ref_{name}.png"
        try:
            with ref_file.open("wb") as f:
                f.write(img.as_png())
                #f.write(img.outbuf.getvalue())
        except FileExistsError:
            print("Reference already exists")
        return True
    except Exception as e:
        return False

def save_reference_pngs():
    max_retries = 5
    remaining = items[:]
    # multiple attempts for key errors due to missing cells
    for attempt in range(max_retries):
        next_round = []
        for case in remaining:
            if not build_and_save_reference(case, e):
                next_round.append(case)
        if not next_round:
            break
        remaining = next_round
    else:
        print("Some references could not be build:", remaining)

