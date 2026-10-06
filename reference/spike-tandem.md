<!--
Copyright 2026, Eclipse Foundation
SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
-->
# Spike Tandem Verification for the CV32E20 Core Testbench


The "core" testbench (`tb/core`) can optionally run the Spike instruction-set simulator
in lock-step ("tandem") with the CV32E20 RTL.  Every instruction retired by
the core (as reported on its RISC-V Formal Interface, RVFI) causes Spike to
step by exactly one instruction, and the architectural state changes reported
by the two models are compared.  Any divergence stops the simulation with a
mismatch report.

## Architecture

```
              +---------------------- tb_top -----------------------+
              |                                                     |
              |  +----------- cv32e20_tb_wrapper ----------------+  |
              |  |                                               |  |
   test.hex --+--+--> mm_ram <--OBI--> cve2_top (CV32E20)        |  |
              |  |                        |                      |  |
              |  |                        | RVFI (retirements)   |  |
              |  |                        v                      |  |
              |  |                  spike_tandem  <--------------+--+-- +elf_file=test.elf
              |  |                        ^                      |  |
              |  |                        |                      |  |
              |  +------------------------+----------------------+  |
              |                           |                         |
              +---------------------------+-------------------------+
                                          | DPI-C (spike_create/spike_step)
                                          v
                            libriscv.so (tandem-patched Spike)
```

Spike-tandem module is comprised of the following components:

- **`tb/core/spike_tandem_pkg.sv`** - DPI-C imports and the `st_rvfi`
  exchange type.  The struct layout must match `riscv/Types.h` of the
  tandem-patched Spike word-for-word (34 scalar 64-bit fields followed by six
  4096-entry CSR arrays).
- **`tb/core/spike_tandem.sv`** - the checker (also known as the scoreboard).
  Configures Spike at time 0
  (ISA, privilege modes, memory map, CV32E20-specific CSR reset values /
  ID registers), then on every RVFI retirement calls `spike_step_svLogic()`
  and compares PC, instruction word, trap flag, privilege mode, and rd
  writeback (address and data).

The implementation of **`libriscv.so`**, the "tandem-patched Spike" in the figure above,
is documented in spike-implementation.md.

## Operation

The same test-program image is given to both models: the testbench loads the
Verilog-hex file into `mm_ram` (`+test_program=`), and Spike loads the ELF the
hex was generated from (`+elf_file=`, added automatically by the Makefile).

<!--
TODO: add discussion about:
- DPI-C interface
- step/compare loop
-->

## Usage

```bash
cd sim/core
make test TEST=hello-world SPIKE_TANDEM=1
```

`SPIKE_TANDEM=1`:

- builds the Spike libraries first if they are missing (`spike_lib` target;
  requires the core-v-verif clone in `vendor_lib`, see the `core-v-verif`
  target),
- compiles the RTL with `+define+RVFI` so `cve2_top` exposes its RVFI ports,
- compiles `spike_tandem_pkg.sv`/`spike_tandem.sv` into the testbench and
  links the Spike libraries,
- passes `+elf_file=<test>.elf` to the simulation.

On success the simulation ends with the usual test status plus:

```
[spike_tandem] <N> instructions verified in tandem with Spike
```

On divergence the simulation stops immediately:

```
[spike_tandem] MISMATCH rd_wdata: rtl=0x12345678 spike=0x9abcdef0 (rd=x10)
[spike_tandem] @ t=...: TANDEM MISMATCH at retirement <N> (1 field(s) differ)
[spike_tandem]   rtl:   pc=... insn=... rd=... rd_wdata=... trap=... mode=...
[spike_tandem]   spike: pc=... insn=... rd=... rd_wdata=... trap=... mode=...
```

### Plusargs

| Plusarg                   | Purpose                                              |
| ------------------------- | ---------------------------------------------------- |
| `+elf_file=<path>`        | ELF for Spike (set automatically by the Makefile)    |
| `+tandem_trace`           | Print every retirement as it is verified             |
| `+tandem_inject_error=<n>`| Self-test: corrupt the RTL rd value at retirement n  |

The error-injection plusarg deliberately falsifies the RTL-side rd write
value presented to the comparator and must always produce a TANDEM MISMATCH
(provided retirement *n* writes a register other than x0).  Use it to verify
that the checker is armed.

## Spike configuration details

The "spike_tandem" module at `tb/core/spike_tandem.sv` (also refered to as "the checker")
mirrors the RTL configuration in `spike_tandem_init()`:

- **ISA / priv**: `rv32imc_zicsr_zifencei`, M-mode only.  This reproduces the
  RTL `misa` value 0x40001104 (`UmodeEnabled=0` in cve2_cs_registers.sv, so no
  U bit).
- **mstatus write mask**: `mstatus_write_mask=0x88` (MIE/MPIE only).  With
  `UmodeEnabled=0`, the RTL ANDs writes to MPRV and TW with `umode_control`
  (always 0 here) and clamps any non-M value written to MPP back to M, so
  those bits are effectively hardwired; without this mask Spike accepts
  writes to them and diverges on the next readback.
- **Boot address**: Spike's PC after reset is set to `{BOOT_ADDR[31:2],2'b00}`
  (the CVE2 fetches its first instruction at the boot address directly; there
  is no Spike boot ROM in this configuration).
- **Memory map**: a single sparse memory region `[0x0, 0x2100_0000)` covering
  the 4 MiB testbench RAM and all mm_ram virtual peripheral addresses
  (print @0x1000_0000, test status @0x2000_00xx, timers, debugger sections),
  so that stores to peripherals do not fault in Spike.
- **ID CSRs**: `mvendorid=0x602`, `marchid=35`, `mimpid=0`, `mhartid=HART_ID`
  via Spike CSR override parameters (values from `cve2_pkg.sv`).
- **mtvec**: reset value `{BOOT_ADDR[31:8], 8'h01}` (vectored mode), write
  mask `0xFFFFFF00` - matching the CVE2, where mtvec writes update only
  [31:8] and the low byte always reads 0x01.
- **mstatus**: reset value 0x1800 (MPP=M).
- **Trigger module**: one trigger, `tdata1` reset value 0x28001048, tdata1
  writes suppressed, `tinfo` not present (values from the proven `cve2`
  profile in core-v-verif's `rvfi_spike.sv`).
- **Counter CSR reads**: `csr_counters_injection` makes Spike adopt the RTL
  value when the program reads free-running counters (cycle/mcycle), so
  these do not cause false mismatches.

## HPM counter/event injection

`csr_counters_injection` (see "Spike configuration details" above)
originally only covered `cycle`/`mcycle`/`mip` reads: the vendored
tandem-patched Spike's `Proc.cc` gated the injection logic behind a
`switch (read_csr)` whose only cases were `CSR_MIP`, `cycle`, `cycleh`,
`mcycle`, and `mcycleh`. Reads of the general programmable HPM
counters/events (`mhpmcounter3..31`, `mhpmcounter3h..31h`,
`mhpmevent3..31` - each a contiguous CSR-address range) fell through to
`default: break;` and compared against Spike's own, differently-counted
value instead of the RTL's. Fixed by replacing that `switch` with a
`counter_csr` boolean covering the same five fixed addresses plus
range-checks against `CSR_MHPMCOUNTER3..CSR_MHPMCOUNTER31`,
`CSR_MHPMCOUNTER3H..CSR_MHPMCOUNTER31H`, and `CSR_MHPMEVENT3..CSR_MHPMEVENT31`
(`encoding.h` defines each range's bounds; the addresses in between are
unused/reserved but never referenced by real CVE2 test programs, so no gap
matters in practice).

**Coverage note:** injection means Spike *accepts* the RTL's counter value
rather than independently computing one, so a bug in the RTL's counting
logic itself cannot be caught this way. This is unavoidable for
`mcycle`/`NumCycles` and the other cycle/stall-timing events
(`NumCyclesLSU`, `NumCyclesIF`, `NumCyclesWFI`, `NumCyclesDivWait` -
`mhpmcounter3/4/11/12`), which depend on pipeline/memory timing a functional
ISS has no model of - these stay forwarded.
- `mhpmcounter3/4(h)` and `mhpmevent11..31(h)` and `mhpmevent3..31`
are forwarded via `counter_csr`.

## HPM counter/event independent modeling (mhpmcounter5..10)

`mhpmcounter5..10` (`NumLoads`, `NumStores`, `NumJumps`, `NumBranches`,
`NumBranchesTaken`, `NumInstrRetC` - CVE2's hardwired event assignment per
the CVE2 Performance Counter spec) are computed independently by
Spike instead of being forwarded from the RTL.

<!--
TODO: deside if these details are worth keeping in this document...

- **Why `rs1`/`rs2` are populated but not compared**: `st_rvfi` carries
  `rs1_addr`/`rs1_rdata`/`rs2_addr`/`rs2_rdata` (`spike_tandem.sv:277-280` on
  the RTL side, `Proc.cc:219-222` on Spike's side), because the struct layout
  has to match Spike's own `Types.h` word-for-word regardless of what the
  checker uses - but `compare_retirement()` never checks them. No comment or
  prior design note explains this, so treat the following as inferred
  reasoning, not a documented decision: `rd_wdata` is checked on every
  retirement, and since both models start from identical architectural state,
  a register's content is entirely determined by the writes made to it -  so
  for most instructions a corrupted source operand would already show up
  indirectly as a wrong computed result on that same instruction, making an
  explicit rs1/rs2 check mostly redundant. The real gap this leaves is
  instructions whose operands don't feed a GPR write at all - **stores**
  (`rs2` = the data being stored) and, more weakly, **branches** (the PC
  comparison already catches a wrong branch decision, just not via rs1/rs2
  directly). Since memory-write address/data isn't compared either, a
  corrupted store-data operand specifically could slip through undetected
  today - a narrow, currently-open corner of phase-1 scope, not a known bug.
- **Backing storage**: each of the 6 counters gets a real `basic_csr_t`
  register (installed into `csrmap` in `Processor`'s constructor,
  wrapped in `rv32_low_csr_t`/`rv32_high_csr_t` for the RV32 32-bit-half
  split, the same pattern the base Spike uses for `mcycle`/`minstret`),
  replacing the `const_csr_t(0)` the unmodified base installs. `mcountinhibit`
  (`0x320`) also gets a real `basic_csr_t` (base Spike hardwires it to a
  read-only 0), so software's per-counter inhibit bits are honored.
  **Registered after `this->reset()` runs**, not before: registering earlier
  in the constructor was silently clobbered by `processor_t::reset()`
  rebuilding `csrmap`, leaving the `Processor`'s own `shared_ptr` members
  pointing at an orphaned register while `csrmap` held a fresh
  `const_csr_t(0)` again.
- **Why `basic_csr_t`, not `wide_counter_csr_t`** (the class `mcycle`/
  `minstret` use): `wide_counter_csr_t::unlogged_write()` deliberately writes
  the given value then immediately decrements it by 1, to compensate for the
  unconditional `bump()` that `mcycle`/`minstret` always receive once per
  step in `execute.cc`. These counters only get bumped conditionally (on a
  qualifying event), so that compensation doesn't apply - it corrupted every
  software reset (`csrwi 0xB05, 0`) into -1 instead of 0. `basic_csr_t` has
  no such assumption baked in.
- **Event detection**: opcode match/mask against `rvfi.insn`, not
  `log_mem_read`/`log_mem_write` (Spike's MMU access log) - those are only
  populated when `get_log_commits_enabled()` is set, which this DPI
  co-simulation flow never turns on, so `NumLoads`/`NumStores` are detected
  the same way as jumps/branches: `encoding.h`'s existing `MATCH_*`/`MASK_*`
  constants, covering both base and compressed forms. Does not implement the
  "misaligned counted as two accesses" rule from
  `doc/03_reference/performance_counters.rst` - not exercised by any current
  test, but a known simplification.
- **Branch-taken detection**: NOT `next_pc != fall-through_pc`. A branch
  whose target coincides with the fall-through address - `beq x0, x0, 1f`
  immediately followed by `1:`, exactly what `hpmcounter_basic_test` does -
  is still taken even though the PC doesn't visibly change; the PC-based
  heuristic silently miscounted this as not-taken. Fixed by evaluating the
  actual funct3-selected comparison (`BEQ`/`BNE`/`BLT`/`BGE`/`BLTU`/`BGEU`)
  against Spike's own operand values, for base-ISA branches. Compressed
  `C.BEQZ`/`C.BNEZ` still use the PC-comparison heuristic - not exercised by
  any current test, another known simplification.
- **Increment without contaminating the current retirement's CSR trace**:
  `write(val, /*log=*/false)` - `openhw::reg::write()`'s log parameter -
  keeps a background bump (a side effect of an unrelated retiring
  instruction, e.g. an `lw`) out of `log_reg_write`, so it can never look
  like that unrelated instruction wrote a CSR. (In practice this specific
  concern turned out moot - `spike_tandem.sv`'s `compare_retirement()` never
  compares `csr_valid`/`csr_wdata` at all, only `rd1_wdata` - but the
  unlogged write is correct regardless and costs nothing.)
-->

## Interrupt injection

Asynchronous interrupts are injected into Spike (`interrupts_injection=1`) so
that tests using the mm_ram interrupt peripherals match the first taken interrupt.

CVE2's RVFI interface truncates away the info Spike needs for this: its
top-level 1-bit `rvfi_intr` port is assigned from an internal 9-bit
`rvfi_stage_intr[RVFI_STAGES-1]` value (`cve2_core.sv`) encoding
`{mcause[5:0], 3'b101}` for an asynchronous-interrupt-entry retirement (or
`3'b011` for a synchronous exception entry), but only its LSB reaches the
module boundary. `cv32e20_tb_wrapper.sv` recovers the full value with a
whitebox hierarchical probe (`cv32e20_top_inst.u_cve2_core.rvfi_stage_intr[0]`
- valid since `RVFI_STAGES=1` for this core, so the signal is exactly
time-aligned with `rvfi_valid`) and passes it into `spike_tandem` as
`rvfi_intr_cause[8:0]`. On an interrupt-entry retirement, `spike_tandem.sv`
sets the RTL-side `st_rvfi.intr` field to `0b101` and populates
`csr_rdata[CSR_MCAUSE]`; `openhw::Processor::step()` (`Proc.cc`) checks for
that pattern, reads the injected mcause, converts it to a `mip` bit via
`mcause_to_mip()`, and backdoor-writes Spike's `mip` so it takes the same
interrupt the RTL just did.

This also requires `unified_traps=1`. Without it, the DPI call that injects
the interrupt only takes the trap (redirecting Spike's PC to the handler) and
returns immediately, without fetching the handler's first instruction -
leaving that instruction's RVFI info misaligned by one DPI call relative to
the RTL's single retirement. `unified_traps=1` makes Spike's step loop
continue past the trap-taking to actually retire the handler's first
instruction in the same call.

**Note**: the `mcause_to_mip()` backdoor-write above is purely a
control-flow synchronization mechanism - it tells Spike *when* and *which*
interrupt to take, so its own trap entry lands on the same instruction
boundary as the RTL's. It does not verify `mip`'s value; that is a separate
mechanism, described next.

## Debug-mode entry independent verification

The CVE2 has four ways to enter debug mode.
Of those, the three below are fully supported by Spike:

- **`ebreak` with `dcsr.ebreakm` set** (`DCSR_CAUSE_SWBP`) and **single-step**
  (`dcsr.step`, `DCSR_CAUSE_STEP`) are fully self-contained in Spike's own
  `execute.cc` - triggered purely by Spike's own instruction execution and its
  own `dcsr` state, no RTL forwarding involved, unaffected by this change.
- **External halt request** (`DCSR_CAUSE_HALTREQ`) is asynchronous and
  testbench-injected (`mm_ram`'s virtual "debugger" register drives
  `debug_req_o`, an `mm_ram.sv` peripheral feature, not DUT logic) - this is
  the one cause this fix actually forwards, in the same "testbench peripheral,
  costs nothing to forward" category as the timer/RNG registers.
- **Hardware trigger match** (`DCSR_CAUSE_TRIGGER`) is real DUT logic
  (`cve2_cs_registers.sv`'s `tselect`/`tdata1`/`tdata2` trigger-match block),
  forwarded the same way as haltreq below; whether Spike's own trigger-module
  (`TM`) CSR modeling is complete enough to make this independently verifiable
  the way `mip` was is unexplored - not attempted here.


Asserting `debug_req` to the RTL model is not visible to Spike, so we use
the same whitebox-probe technique already established for
mcause (`rvfi_stage_intr[0]`, "Interrupt injection" above):

- `cve2_core.sv` computes a genuine one-shot debug-entry cause tag internally:
  `rvfi_dbg <= captured_debug_valid ? captured_debug_cause : 0`, gated by
  `debug_csr_save` in `cve2_controller.sv` and cleared as soon as the next
  instruction enters ID - asserted for exactly the entry retirement, never
  held. Its cause encoding (`cve2_pkg.sv`: `DBG_CAUSE_EBREAK=1,
  DBG_CAUSE_TRIGGER=2, DBG_CAUSE_HALTREQ=3, DBG_CAUSE_STEP=4`) is numerically
  identical to Spike's own `DCSR_CAUSE_*` in `encoding.h`, so it forwards
  verbatim with no remapping.
- `cv32e20_tb_wrapper.sv` probes this hierarchically as `rvfi_dbg_cause =
  cv32e20_top_inst.u_cve2_core.rvfi_stage_dbg[0]` (`RVFI_STAGES=1`, so index
  `[0]` is exactly time-aligned with the retirement, same reasoning as
  `rvfi_intr_cause`), and also probes `debug_mode` directly as
  `rvfi_dbg_mode` for the new comparison below.
- `spike_tandem.sv`'s `tandem_step()` assigns `s_core.dbg = {60'b0,
  rvfi_dbg_cause}` every step - `st_rvfi.dbg` is a dedicated struct field (not
  smuggled through `csr_rdata[]` like mcause/mip), and `Proc.cc:58-66` already
  reads it directly (`if (reference->dbg && !debug_mode && debug_injection &&
  !halted()) enter_debug_mode(reference->dbg)`) - no C++ changes were needed
  for this fix.
- `compare_retirement()` gained a new check: `s_ref.dbg_mode[0] !==
  rvfi_dbg_mode`. `Proc.cc:100` already populates `rvfi.dbg_mode =
  this->get_state()->debug_mode` as an output, but nothing compared it to the
  RTL before - this is a genuine independent cross-check that Spike and the
  RTL agree on debug-mode occupancy at every retirement, not just at entry.

## mm_ram TICKS peripheral forwarding (fixed) - coremark now fully passes

In order to support the `coremark` test program, it is necessary to forward
the "TICKS" platform CSR implemented in the `mm_ram` to the `mcycle` CSR.

## Store verification (datapath check + actual-memory-landed check)

`compare_retirement()` also checks stores now, closing a real gap: nothing
previously verified that a store computed the right address/data, or that
the write actually reached memory -- a bug there has no register-writeback
footprint to catch it (a load's returned value is already covered
indirectly via the existing `rd_wdata` check, so loads are out of scope
here).

Two independent checks, not one, because a single RVFI-based comparison
structurally can't catch everything:

- **Datapath check**: `Proc.cc` independently computes the store
  address/mask/data from Spike's own decode and register file (SB/SH/SW via
  the S-type immediate, C.SW via CS-format, C.SWSP via CSS-format with an
  implicit `x2` base -- architecturally hardwired by the ISA, not a
  calling-convention assumption), deliberately mirroring CVE2's own RVFI
  convention: a size-only mask and raw, unshifted `rs2` value, not the real
  bus's offset-rotated byte-enables/data. This is compared against the
  RTL's self-reported `rvfi_mem_addr`/`rvfi_mem_wmask`/`rvfi_mem_wdata`.
- **Landed check**: a whitebox probe in `cv32e20_tb_wrapper.sv` (mirroring
  `mm_ram.sv`'s own signature-dump technique) reads the testbench RAM's
  actual post-write byte contents directly and compares them against
  Spike's same independently-computed expected value -- gated to the real
  RAM address range, since peripherals aren't backed by that array.

The landed check exists because CVE2's RVFI mem_* signals are captured
*pre-LSU* (the ALU adder result and raw `rs2`), not tapped from the actual
OBI bus wires, which are separately byte-rotated by offset inside the
load-store unit. A bug in that rotation/byte-enable logic is invisible to
the datapath check -- both RVFI's self-report and Spike's independent
recompute mirror the same pre-LSU convention and would agree with each
other regardless -- but corrupts what's actually written, which only a
real memory readback can catch.

One real bug was found and fixed via this work: `Proc.cc`'s internal
multi-iteration trap-handling loop only clears its RVFI-mirroring struct
once before the loop, not per iteration, so a non-store instruction retired
on a later iteration (e.g. a jump following a trap handler's epilogue
store) was inheriting a stale nonzero store address/mask/data from an
earlier iteration's real store. Fixed by explicitly zeroing these fields on
the non-store path instead of relying on the outer clear.

## Random OBI stalls and random Interrupt injection

- Random OBI data/instruction-phase stalls can be enabled by default for any test.
  This implies that each run of any test will be distinct, even for a static
  test-program.
- `riscv_random_interrupt_generator` (a (non-UVM) class-based `.randomize() with
  {...}` constrained-random interrupt generator, instantiated in
  `mm_ram.sv`) is unguarded too.
- Legacy, entirely unreferenced RI5CY/Zeroriscy-era files
  have been moved to `tb_riscv/deprecated/`.

## Relationship to the RVVI-API

We re-use the CVA6-style `spike_create()`/`spike_step()`
DPI interface that ships with the tandem-patched Spike.  The longer-term goal
of the SPIKE_TANDEM project is to wrap the Spike reference model behind the
standard [RVVI-API](https://github.com/riscv-verification/RVVI) so that the
testbench-side protocol is reference-model agnostic.  The spike_tandem module was
written so that only `spike_tandem_init()` and `tandem_step()` need to change.

## Rebuilding Spike

```bash
cd sim/core
make spike_lib            # builds into <repo>/reference/spike/{lib,include}
```

The Spike build needs `svdpi.h`; the Makefile locates it from the Verilator
in `$PATH` (`verilator --getenv VERILATOR_ROOT`).

`spike_lib`'s targets are plain files (`reference/spike/lib/{libriscv,libfesvr}.so`)
with no dependency on Spike's own sources, so it only rebuilds when those
`.so`s don't exist yet -- editing `Proc.cc` and re-running `make spike_lib`
does nothing.  Force a rebuild either by removing the `.so`s first:

```bash
make clean-spike
make spike_lib
```

or by invoking the underlying build directly, which always recompiles
whatever changed:

```bash
make -C vendor_lib/openhwgroup_core-v-verif/vendor/riscv/riscv-isa-sim/build/ \
    -j8 EDA_INCLUDES="-I$(verilator --getenv VERILATOR_ROOT)/include/vltstd" install
```

If `vendor_lib/openhwgroup_core-v-verif` itself is missing (e.g. a fresh
checkout, or `tools/` and the vendor clone were wiped -- both are
`.gitignore`'d, so this is silent), re-clone it at the pinned hash first:

```bash
cd sim/core
make core-v-verif         # re-clones vendor_lib/openhwgroup_core-v-verif
                          # at the hash pinned in sim/ExternalRepos.mk
make spike_lib
```

`bin/run_tests.py --spike-tandem` runs `make spike_lib` itself before any
test/certify run, so the common case (Spike already built) is a fast no-op;
a first-time or post-wipe build can take several minutes.

### Spike Compile-time Consideratons

When `SPIKE_TANDEM` is defined to be anything other than 0 the sources will be compiled into a shared object ("dot-so") file,
unless it already exists. There are some compile-time considerations to be aware of:
- The package must precede its importers in compile order.
- `libriscv.so` does not record dependencies on its sister libraries, so name them all.
- the `st_rvfi` struct is large, so `-Wno-WIDTHCONCAT` suppress Verilator's replication limit.
- `--no-as-needed` force-loads DT_NEEDED entries
- `--allow-shlib-undefined` suppresses errors due to deliberately excluded libraries see the EDA_INCLUDES in mk/Common.mk.
