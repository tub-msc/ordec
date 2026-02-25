#!/usr/bin/env python3
import ordec.importer
from vco_pseudodiff import *

with open("out.gds", "wb") as f:
    write_gds(VcoRing().layout, f)
    #write_gds(VcoHalfStage().layout, f)

os.system("python3 $ORDEC_PDK_IHP_SG13G2/libs.tech/klayout/tech/drc/run_drc.py --path out.gds --no_density --run_dir=drc_out")
os.system("klayout out.gds -m drc_out/out_vcoring_full.lyrdb")
#os.system("klayout out.gds -m drc_out/out_vcohalfstage_width_300n_length_130n_full.lyrdb")
