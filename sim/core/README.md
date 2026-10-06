Simulation Directory for CV32E20 Core Testbench
================================================
This is the directory in which you should run all tests of the Core Testbench.
The testbench itself is located at `../../tb/core` and the test-programs are at
`../../tests`.  See the README in those directories for more information.

Supported SystemVerilog Simulators
----------------------------------
To run the core testbench you will need Verilator, version v5.042 or later and RISC-V GCC compiler.
Support for additional SystemVerilog simulators will be added on an as-needed basis.
If you would like to contribute an update to support your favorite simulator, please see CONTRIBUTING.

RISC-V GCC Compiler "Toolchain"
-------------------------------
Pointers to the recommended toolchain for CV32E20 are in `../TOOLCHAIN`.

Running the testbench with [verilator](https://www.veripool.org/wiki/verilator)
----------------------
Point your environment variable `RISCV` to your RISC-V toolchain. Call `make`
to run the default test (hello_world).

Running your own C or Assembler test-programs
---------------------
Manually written test-programs are located in the `custom` folder. The relevant sections
in the Makefile on how to compile and link this program can be found under `Running
custom programs`.  Make sure you have a working C compiler (see above) and keep in
mind that you are running on a very basic machine.
Try the following:<br>
```
make test TEST=dhrystone
make test TEST=misalign
make test TEST=fibonacci
make test TEST=illegal
make test TEST=riscv_ebreak_test_0
```

Running with the Spike reference model in lock-step ("tandem")
--------------------------------------------------------------
Any custom test can also be run with the Spike ISS verifying every retired
instruction against the RTL via the core's RVFI interface:
```
make test TEST=hello-world SPIKE_TANDEM=1
```
The first tandem run builds the tandem-patched Spike from the core-v-verif
vendor tree into `../../reference/spike` (see the `spike_lib` target).  On
success the log ends with `[spike_tandem] <N> instructions verified in
tandem with Spike`; any divergence stops the simulation with a
`TANDEM MISMATCH` report.  Details and current limitations:
`../../reference/spike-tandem.md`.

Running RISC-V Architectural Certification Tests (ACT4)
-------------------------------------------------------
CV32E20-DV supports the RISC-V Architectural Certification Tests (ACT4). The ACT4 repository is
fetched on demand via a Make target — it is **not** a git submodule.

### Prerequisites
- **RISC-V GCC toolchain** (`riscv64-unknown-elf-gcc`): upstream GCC with RISC-V multi-lib support.
  See `../TOOLCHAIN.md`. Set `CV_SW_TOOLCHAIN` and `CV_SW_PREFIX` in your environment, e.g.:
  ```
  export CV_SW_TOOLCHAIN=/opt/riscv
  export CV_SW_PREFIX=riscv64-unknown-elf-
  ```
- **Sail RISC-V reference model v0.10** (`sail_riscv_sim` on `$PATH`): required version is 0.10.
  Download the pre-built binary from https://github.com/riscv/sail-riscv/releases/tag/0.10,
  extract to a directory of your choice (e.g. `~/.local/bin` or `/usr/local/bin`), and ensure
  that directory is on your `$PATH` (add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc`
  if needed).
- **Python uv** package manager: https://docs.astral.sh/uv/getting-started/installation/
- **Verilator** v5.042 or later.

### Steps

ACT4 is fetched automatically when you first run `make gen` or `make gen-certify`.
Run the full certification flow:
```
make gen-certify
```
Or separately:
```
make gen       # clone ACT4 (if needed) + generate ELFs via Sail reference model
make certify   # run ELFs through Verilator DUT
```

Results are written to:
`simulation_results/certification/test_program/bsp/certification_summary.txt`

### Prebuilt ELF flow (CI / fast iteration)

`make gen` is slow: it clones ACT4 (~1.2 GB) and runs Sail-based test
generation (~30 min, requires `uv` and `sail_riscv_sim`). The ELFs are
deterministic in their inputs, so they can be produced once and reused.

Targets:
```
make elfs-package      # tar+gzip ELFs to tests/act4/act4-elfs-cv32e20.tar.gz
make certify-prebuilt  # extract that tarball and run certify (skips `gen`)
```

Maintainer flow (publish a new tarball):
```
make gen           # generate ELFs via ACT4 + Sail
make elfs-package  # produce tests/act4/act4-elfs-cv32e20.tar.gz
```

CI flow (consume an existing tarball):
```
# tests/act4/act4-elfs-cv32e20.tar.gz must be present
# (committed, downloaded as a release artifact, or restored from cache)
make certify-prebuilt
```

<!--
Running the testbench with Metrics [dsim](https://metrics.ca)
----------------------
Point your environment variable `RISCV` to your RISC-V toolchain. Call
`make dsim-sanity` to build and run the testbench with the hello_world
test in the custom directory. Other test targets of interest:<br>
```
make dsim-test TEST=dhrystone
make dsim-test TEST=misalign
make dsim-test TEST=fibonacci
make dsim-test TEST=illegal
make dsim-test TEST=riscv_ebreak_test_0
```
FIXME
* `make dsim-cv32_riscv_tests` to build and run the testbench with all the testcases in the riscv_tests directory.
* `make dsim-cv32_riscv_compliance_tests` to build and run the tests in riscv_compliance_tests.
* `make dsim-firmware` to build and run the testbench with all the testcases in the riscv_tests and riscv_compliance_tests directories.
<br><br>The Makefile now supports running individual assembler tests from either
the riscv_tests or riscv_compliance_tests directories. For example, to run the ADD IMMEDIATE test from riscv_tests:
* `make dsim-unit-test addi`
<br>To run I-LBU-01.S from the riscv_compliance_tests:
* `make dsim-unit-test I_LBU_01`
<br>You can clean up the mess you made with `make dsim-clean`.

Running the testbench with Cadence Xcelium [xrun](https://www.cadence.com/en_US/home/tools/system-design-and-verification/simulation-and-testbench-verification/xcelium-parallel-simulator.html)
----------------------
**Note:** This testbench is known to require Xcelium 19.09 or later.  See [Issue 11](https://github.com/openhwgroup/core-v-verif/issues/11) for more info.
Point your environment variable `RISCV` to your RISC-V toolchain. Call
`make xrun-test` to build and run the testbench with the hello_world
test in the custom directory, or you can provide the TEST variable on the
command line as shown for the dsim targets (e.g. make xrun-test TEST=misalign).
-->
<!--
FIXME
Other rules of interest:
* `make xrun-firmware` to build and run the testbench with all the testcases in the riscv_tests/ and riscv_compliance_tests/ directories.
* Clean up your mess: `make xsim-clean` (deletes xsim intermediate files) and `xrun-clean-all` (deletes xsim intermedaites and all testcase object files).
-->

<!--
Running the testbench with Questa (vsim)
---------------------------------------------------------
FIXME
Point your environment variable `RISCV` to your RISC-V toolchain. Call `make
firmware-vsim-run` to build the testbench and the firmware, and run it. Use
`VSIM_FLAGS` to configure the simulator e.g. `make firmware-vsim-run
VSIM_FLAGS="-gui -debugdb"`.
<br>The Makefile also supports running individual assembler tests from either
the riscv_tests or riscv_compliance_tests directories using vsim. For example,
to run the ADD IMMEDIATE test from riscv_tests:
* `make questa-unit-test addi`
<br>To run I-LBU-01.S from the riscv_compliance_tests:
* `make questa-unit-test I_LBU_01`

If you have a C or assembly program in `../../tests/programs/custom`
then the following _should_ work with Questa (note that this
has not been tested):<br>
```
make questa-test TEST=hello-world
make questa-test TEST=dhrystone
make questa-test TEST=coremark
make questa-test TEST=fibonacci
```

Running the testbench with VCS (vcs)
----------------------
Point your environment variable `RISCV` to your RISC-V toolchain.
Call `make firmware-vcs-run` to build the testbench and the firmware, and run it.
Use `SIMV_FLAGS` or `VCS_FLAGS` to configure the simulator and build respectively e.g.
`make firmware-vcs-run VCS_FLAGS+="-cm line+cond+fsm+tgl+branch" SIMV_FLAGS+="-cm line+cond+fsm+tgl+branch"`

Running the testbench with Riviera-PRO (riviera)
----------------------
Point you environment variable `RISCV` to your RISC-V toolchain. Call `make
riviera-hello-world` to build the testbench and the firmware, and run it. Use
`ASIM_FLAGS` to configure the simulator e.g. `make custom-asim-run
ASIM_FLAGS="-gui"`.
-->

<!--
Options
-------
A few plusarg options are supported:
* `+verbose` to show all memory read and writes and other miscellaneous information.
-->
