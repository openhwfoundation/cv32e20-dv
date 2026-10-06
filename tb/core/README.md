# CORE testbench for CV32E20

A simple, Verilator-based, non-UVM testbench for the CV32E20.  `tb_top.sv`
loads a test-program (Verilog-hex) into the `mm_ram` memory model and runs it
on the core instantiated by `cv32e20_tb_wrapper.sv`.  Test status is reported
via the mm_ram virtual peripherals (test status, exit value, print).

## Spike tandem mode

The testbench can run the Spike ISS in lock-step with the RTL, comparing
every retired instruction via the core's RVFI interface:

```
cd ../../sim/core
make test TEST=hello-world SPIKE_TANDEM=1
```

Components:
- `spike_tandem_pkg.sv` - DPI-C imports and the st_rvfi exchange type.
- `spike_tandem.sv` - configures Spike and compares each retirement.

See `../../reference/spike-tandem.md` for the architecture, usage details,
plusargs, and current limitations.
