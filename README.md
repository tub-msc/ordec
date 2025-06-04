![ORDeC](docs/ordec_logo.svg)

**ORDeC** (Open Rapid Design Composer) is an open-source **custom IC design platform**. Its goal is to provide an accessible and streamlined interface to design and analyze analog, mixed-signal and custom digital integrated circuits from schematic to layout. ORDeC consists of:

- the ORD hardware description language (HDL) for design entry,
- a data model and data structures for representing IC design data (such as schematics),
- external tool integration (e.g. to Ngspice for simulation),
- a web interface for immediate graphical feedback during the design process.

ORDeC is developed by the [Mixed Signal Circuit Design Group](https://www.tu.berlin/msc) at Technische Universität Berlin. 

The development of ORDeC is currently at an early, experimental stage. The main branch of this repository provides a **working demo of some basic features and ideas**:

## Getting Started

The easiest way to get started is via docker:

```
docker build . -t ordec
docker run -p 127.0.0.1:8100:8100 -it ordec
```

Then, visit http://localhost:8100 to access the web interface and try out examples.

Further documentation of ORDeC is found in the *docs/* folder and will also shortly be available online.

## Motivation

ORDeC's goal is to provide an accessible and streamlined interface to design and analyze analog, mixed-signal and custom digital integrated circuits from schematic to layout.

Established open-source interfaces for IC design are mostly based on old-fashioned technologies (Tcl/Tk, C etc.) and lack a coherent experience across design stages such as schematic entry, simulation and layout. ORDeC aims to provide a coherent experience across design stages using an interactive web interface. In the future, a public web-based ORDeC instance might enable users to get started without any local setup. Furthermore, ORDeC's core is written in Python and designed to allow analyzing and transforming design data with ease.

Why a textual hardware description language (HDL) instead of a WYSIWYG interface? The motivation is to make custom IC design more software-like. Design data is made transparent and suitable for software-style version control (e.g. Git), which improves maintainability and makes it possible to adapt workflows from software engineering.

Further goals of ORDeC are: built-in support for open PDKs, and visualizing silicon area, energy efficiency as sustainability design parameters. 

## Contact

Questions and feedback via GitHub issues are welcome. Alternatively, feel free to email Tobias Kaiser (kaiser@tu-berlin.de).

## Acknowledgements

This work is supported by the German Federal Ministry of Research, Technology and Space (BMFTR) under grant [16ME0996 (DI-ORDeC)](https://www.elektronikforschung.de/projekte/di-ordec).
