# XENON fuse 

[![PyPI version shields.io](https://img.shields.io/pypi/v/xenon-fuse.svg)](https://pypi.python.org/pypi/xenon-fuse/)

**F**ramework for **U**nified **S**imulation of **E**vents

fuse is the refactored version of the XENONnT simulation chain. The goal of this project is to unify [epix](https://github.com/XENONnT/epix) and [WFSim](https://github.com/XENONnT/WFSim) into a single program. fuse is based on the [strax framework](https://github.com/AxFoundation/strax), so that the simulation steps are encoded in plugins with defined inputs and outputs. This allows for a flexible and modular simulation chain.

## Installation

With all requirements fulfilled (e.g., on top of the [XENONnT montecarlo_environment](https://github.com/XENONnT/montecarlo_environment)):
```
python -m pip install xenon-fuse
```
or install from source:

1. `clone https://github.com/XENONnT/fuse`
2. `cd fuse`
3. `python -m pip install . --user`

## Plugin Structure

The full simulation chain in split into multiple plugins. An overview of the simulation structure can be found below.

![fuse plugin structure](docs/source/figures/fuse_simulation_chain.png)
