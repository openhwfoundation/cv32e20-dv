#!/usr/bin/env python3
# Copyright (c) 2026 Eclipse Foundation
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
"""
Run the cleaned-up directed test-programs (C and assembly) on a CV32E20
testbench and print a pass/fail summary.  Either testbench can be selected
with --tb:

    core   the Verilator core testbench in sim/core            (default)
    uvmt   the UVM testbench in sim/uvmt, run with SIMULATOR=vsim

For each selected test the script invokes `make test TEST=<name> ...` in the
chosen testbench's sim directory, then parses the per-test log it leaves behind
for the verdict banner:

    core : sim/core/simulation_results/<name>/<run>/test_program/<name>.log
           "ALL TESTS PASSED"   -> PASS   (tb/core/tb_top.sv)
           "TEST(S) FAILED!"    -> FAIL

    uvmt : sim/uvmt/vsim_results/<cfg>/<name>/<run>/vsim-<name>.log
           "SIMULATION PASSED"  -> PASS   (tb/uvmt/uvmt_cv32e20_tb.sv;
                                           includes "PASSED with WARNINGS")
           "SIMULATION FAILED"  -> FAIL

Anything else (no banner, build error, timeout) is reported as ERROR.
The process exit code is 0 only if every test that was run reported PASS.

corev-dv tests (see COREV_DV_TESTS below) additionally need `make corev-dv`
run once beforehand to clone and compile the corev-dv/riscv-dv packages
(uvmt only). Whenever the selected set includes any corev-dv test, this
script runs `make corev-dv` itself before running any tests, and aborts if
that setup step fails.

For corev-dv tests, --run-index also selects which generated program directory
is used: run_test() passes it through as both RUN_INDEX (where the build/run
step looks for the program) and GEN_START_INDEX (where gen_corev-dv writes it).
run_test() also passes SEED=random for every corev-dv test's gen_corev-dv step
(GEN_SEED; corev-dv/uvmt only -- there's no "generate" step for a hand-written
test, so GEN_SEED is always "-" for those), so each invocation uses a fresh
RNDSEED (mk/uvmt/uvmt.mk derives it from `date +%N`) for the corev-dv
generator -- re-running the same --run-index does NOT reproduce the same
generated program/stimulus anymore.

run_test() also passes a RUN_SEED (env-level randomization, e.g. OBI stall
knobs) for EVERY test, corev-dv or not, on both testbenches -- 'random' by
default. uvmt resolves SEED=random itself (mk/uvmt/uvmt.mk, `date +%N`,
same as GEN_SEED above); core's Makefile passes SEED straight through as
+verilator+seed+<value>, and Verilator's own convention already treats 0 as
"pick a random seed" (see verilated.cpp), so run_test() maps the script's
'random' sentinel to the literal 0 Verilator special-cases. Either way the
actual seed used is recovered from that run's own output for later replay
via --run-seed=<value>: uvmt prints it as `-sv_seed <value>` (vsim-<name>.log
header); core prints it via tb_top.sv's $display of
$get_initial_random_seed() ("Simulation running with seed: <value>").

Usage
-----
The script needs no arguments and can be run from anywhere (paths are resolved
relative to its own location in <repo>/bin).  A working RISC-V toolchain plus
the relevant simulator (Verilator for core, Questa vsim for uvmt) must be on
PATH, as for a normal `make test`.

    # Run the full self-checking set (C + assembly) on the core TB:
    bin/run_tests.py
    python3 bin/run_tests.py                    # equivalent

    # Run the same set on the UVM testbench (vsim), plus UVMT_TESTS (directed
    # tests that only make sense under uvmt, e.g. nmi_test):
    bin/run_tests.py --tb uvmt
    # (equivalent to `make test TEST=<name> SIMULATOR=vsim` per test; the
    #  script sets SIMULATOR=vsim for you, so no need to export it yourself.)

    # Run only specific tests (by directory name under tests/programs/custom):
    bin/run_tests.py fibonacci misalign
    bin/run_tests.py --tb uvmt hello-world

    # Also run the parked tests (step-compare / debug; meaningful under --tb uvmt):
    bin/run_tests.py --include-parked
    bin/run_tests.py --tb uvmt --include-parked

    # Also run the passing corev-dv generated regression tests (uvmt only):
    bin/run_tests.py --tb uvmt --include-corev-dv

    # Run ONLY the corev-dv generated regression tests (uvmt only):
    bin/run_tests.py --tb uvmt --corev-dv-only

    # Skip simulation; just re-summarize logs from a previous run:
    bin/run_tests.py --parse-only
    bin/run_tests.py --tb uvmt --parse-only

    # Run up to 4 tests concurrently (uvmt only is verified safe -- see below):
    bin/run_tests.py --tb uvmt --corev-dv-only --jobs 4

    # Replay a specific prior corev-dv run from its logged seeds (gen_corev-dv
    # and test are independent UVM environments/vsim invocations, each with
    # their own seed -- see the summary table's GEN_SEED/RUN_SEED columns):
    bin/run_tests.py --tb uvmt --gen-seed 363891135 --run-seed 354410829 \
        corev_rand_instr_and_data_stalls

    # Replay a specific prior run's env-level randomization (e.g. OBI stall
    # knobs) for a hand-written test -- there's no --gen-seed here, since
    # hand-written tests have no generation step, only the run itself:
    bin/run_tests.py --run-seed 12345 misalign

    # Collect code coverage (uvmt only; equivalent to `make test ... COV=1` per test):
    bin/run_tests.py --tb uvmt --cov hello-world

    # Run in tandem with the Spike ISS, comparing every retired instruction
    # (core only; equivalent to `make test ... SPIKE_TANDEM=1` per test; see
    # reference/spike-tandem.md):
    bin/run_tests.py --spike-tandem

    # Run the ACT4 compliance-ELF sweep (core only; equivalent to
    # `make certify` in sim/core) instead of the named test set:
    bin/run_tests.py --certify

    # Same, but with every compliance ELF checked against Spike in tandem
    # (equivalent to `make certify SPIKE_TANDEM=1`):
    bin/run_tests.py --certify --spike-tandem

    # Narrow the certify sweep to one extension subdirectory (passed through
    # as FILTER=... to `make certify`; see sim/core/Makefile):
    bin/run_tests.py --certify --filter rv32i/Zicsr

    # Other options:
    #   --cfg NAME      uvmt config subdirectory                (default: default)
    #   --run-index N   RUN_INDEX subdirectory                  (default: 0)
    #   --gen-seed SEED corev-dv generator SEED ('random' or a literal
    #                   value); no effect on hand-written tests (no
    #                   generation step exists for them)
    #   --run-seed SEED test-step SEED ('random' or a literal value);
    #                   applies to every test, on both testbenches
    #   --timeout SECS  per-test timeout                        (default: 1800)
    #   --jobs N, -j N  run up to N tests concurrently           (default: 1)
    #   --cov           collect code coverage (uvmt only)
    #   --spike-tandem  run in tandem with Spike, comparing every retired
    #                   instruction (core only; see reference/spike-tandem.md).
    #                   Builds Spike via `make spike_lib` first if needed --
    #                   can take several minutes the first time.
    #   --certify       run the ACT4 compliance-ELF sweep (`make certify`,
    #                   core only) instead of the named test set; combine
    #                   with --spike-tandem to certify in tandem with Spike
    #   --filter PATH   narrow --certify to one extension subdirectory
    #                   (passed through as FILTER=PATH to `make certify`)
    #   --quiet         suppress per-test simulation banners
    #   -h / --help     full option help

Exit status is 0 only when every selected test PASSED, so the script is
suitable for use as a CI gate.

Concurrency (--jobs)
--------------------
By default (--jobs 1) each test runs its own `make test`/`make gen_corev-dv
test`, which recompiles the design every time (VSIM_RUN_PREREQ=opt unless
COMP=NO is passed). Running that concurrently would race multiple vlog/vopt
invocations against the same shared vsim work library
(sim/uvmt/vsim_results/<cfg>/work) -- a previously-confirmed hazard (lock
contention or "already an optimized design" errors).

With --jobs > 1 and --tb uvmt, this script instead compiles the design ONCE
up front (`make comp`, serialized, in addition to the existing one-time `make
corev-dv` setup for corev-dv tests) and then passes COMP=NO to every test in
the parallel batch, so workers only run `vsim` against the already-compiled
design. If --cov is also given, that one-time compile is done with COV=1 too
(otherwise the shared design has no +cover instrumentation and every
worker's .ucdb ends up with assertions/covergroups but zero statement/
branch/condition coverage, since COMP=NO skips each worker's own vopt) --
each worker runs in its own per-test/run-index run directory
(sim/uvmt/vsim_results/<cfg>/<test>/<run_index>/), which `make`'s `run`
target `vmap`s back to the shared read-only compiled library. Many `vsim`
processes reading one compiled snapshot concurrently is a standard, safe
regression-farm pattern; it's concurrent *compilation* that isn't safe.

Caveat: the corev-dv random-program *generation* step (gen_corev-dv) itself
runs vsim from within a directory shared by all corev-dv tests
(vsim_results/<cfg>/corev-dv/), unlike the isolated per-test run directories
above. This looks benign under concurrency (per-test/idx log files don't
collide, and the shared `vmap` writes identical content regardless of which
process wins the race) but has not been independently stress-tested at high
--jobs counts. Keep an eye on it if you push --jobs high for corev-dv-heavy
batches.

--tb core (Verilator) has NOT been verified race-free under --jobs > 1: `make
test` for the core TB also recompiles into a shared directory
(sim/core/cobj_dir) on every invocation, and no COMP=NO-equivalent skip-flag
was found for it. Prefer --jobs 1 there unless you've confirmed otherwise.

Also keep the vsim license pool in mind (`lmutil lmstat`) -- each concurrent
uvmt worker holds its own set of Questa feature licenses (msimhdlsim,
svverification, mtiverification, ...) for the duration of its run.
"""

import argparse
import concurrent.futures
import os
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path

# Repository layout: this script lives in <repo>/bin.
SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent

# Serializes stdout so concurrent --jobs workers don't interleave output.
_print_lock = threading.Lock()

# Per-testbench config: sim dir, extra make args, pass/fail banners, log markers.
TESTBENCHES = {
    "core": {
        "sim_dir": REPO / "sim" / "core",
        "make_args": [],
        "pass_banner": "ALL TESTS PASSED",
        "fail_banner": "TEST(S) FAILED!",
        # Progress lines worth echoing while a test runs.
        "markers": ("tb_top]", "SUCCESS", "FAIL"),
    },
    "uvmt": {
        "sim_dir": REPO / "sim" / "uvmt",
        "make_args": ["SIMULATOR=vsim", "USE_ISS=NO"],
        "pass_banner": "SIMULATION PASSED",
        "fail_banner": "SIMULATION FAILED",
        "markers": ("SIMULATION PASSED", "SIMULATION FAILED",
                    "UVM_ERROR :", "UVM_FATAL :", "TEST PASSED", "TEST FAILED"),
    },
}

# Self-checking C test-programs.
C_TESTS = [
    "hello-world",
    "fibonacci",
    "branch_zero",
    "coremark",
    "dhrystone",
#    "all_csr_por",
    "csr_instructions",
    "hpmcounter_basic_test",
    "illegal",
    "misalign",
    "interrupt_test",
    "interrupt_bootstrap",
    "debug_test",
]

# Self-checking assembly test-programs.
ASM_TESTS = [
    "load_store_rs1_zero",
    "illegal_instr_test",
    "generic_exception_test",
    "csr_instr_asm",
]

# Default (core TB) selection: every self-checking test, C and assembly.
TESTS = C_TESTS + ASM_TESTS

# Tests that build and run but aren't meaningfully self-checking on the core
# TB (pass vacuously, or FAIL outright for debug_test variants since debug
# mode needs uvmt stimulus) -- real verification needs --tb uvmt. Opt-in via
# --include-parked.
PARKED = [
    "riscv_arithmetic_basic_test_0",
    "riscv_arithmetic_basic_test_1",
    "csr_instr_asm",
    "riscv_csr",
    "perf_counters_instructions",
    "debug_test_boot_set",
    "debug_test_reset",
    "debug_test_known_miscompares",
    "debug_test_trigger",
]

# uvmt-only directed tests (not opt-in like PARKED) -- need stimulus with no
# core-TB equivalent (e.g. nmi_test's +nmi_assert), so added automatically
# only when --tb uvmt is selected (see main()).
UVMT_TESTS = [
    "nmi_test",
]

# corev-dv generated regression templates (tests/programs/corev-dv/) -- need
# `make gen_corev-dv test` instead of plain `make test` (run_test() handles
# this), and `make corev-dv` run once first (main() does this automatically).
# uvmt only; opt-in via --include-corev-dv/--corev-dv-only.
COREV_DV_TESTS = [
    "corev_rand_arithmetic_base_test",
    "corev_rand_instr_test",
    "corev_rand_interrupt",
    "corev_rand_interrupt_debug",
    "corev_rand_interrupt_exception",
    "corev_rand_interrupt_nested",
    "corev_rand_interrupt_wfi",
    "corev_rand_interrupt_wfi_mem_stress",
    "corev_rand_jump_stress_test",
    "corev_rand_debug",
    "corev_rand_debug_ebreak",
    "corev_rand_debug_single_step",
    "corev_rand_illegal_instr_test",
    "corev_rand_instr_long_stall",
    "corev_rand_instr_and_data_stalls",
]


def log_path(tb, test, run_index, cfg):
    """Location of the per-test simulation log for the given testbench."""
    sim_dir = TESTBENCHES[tb]["sim_dir"]
    if tb == "core":
        return (sim_dir / "simulation_results" / test / str(run_index)
                / "test_program" / f"{test}.log")
    # uvmt / vsim
    return (sim_dir / "vsim_results" / cfg / test / str(run_index)
            / f"vsim-{test}.log")


def gen_log_path(tb, test, run_index, cfg):
    """Location of the corev-dv generation step's own log (a separate vsim
    run from the test's own log, hence its own seed). "_1" is
    GEN_NUM_TESTS's unoverridden Makefile default."""
    sim_dir = TESTBENCHES[tb]["sim_dir"]
    return (sim_dir / "vsim_results" / cfg / "corev-dv" / test
            / f"{test}_{run_index}_1.log")


_SEED_RE = re.compile(r"-sv_seed\s+(\S+)")
_CORE_SEED_RE = re.compile(r"Simulation running with seed:\s+(\S+)")


def extract_seed(text):
    """Pull the actual seed a run used from its output/log -- needed when
    SEED=random (uvmt) or SEED=0 (core; Verilator's own "pick a random
    seed" convention), since neither is the literal value actually used.
    uvmt prints it via vsim's own -sv_seed banner; core via tb_top.sv's
    $display of $get_initial_random_seed()."""
    m = _SEED_RE.search(text)
    if m:
        return m.group(1)
    m = _CORE_SEED_RE.search(text)
    return m.group(1) if m else None


def classify(text, tbcfg):
    """Return 'PASS', 'FAIL', or 'ERROR' for a chunk of log/console text."""
    if tbcfg["pass_banner"] in text:
        return "PASS"
    if tbcfg["fail_banner"] in text:
        return "FAIL"
    return "ERROR"


def make_env(tbcfg):
    """os.environ plus tbcfg's make_args mirrored in (e.g. SIMULATOR=vsim), so
    sub-make/shell reads of the variable match the command line."""
    env = os.environ.copy()
    for arg in tbcfg["make_args"]:
        key, _, val = arg.partition("=")
        if val:
            env[key] = val
    return env


def _run(cmd, cwd, env, timeout, capture):
    """Run cmd in its own process group so a timeout kills the whole tree,
    not just `make` -- otherwise its child (e.g. vsim) orphans and keeps
    running in the background."""
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        start_new_session=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.communicate()
        raise
    return proc.returncode, stdout, stderr


def setup_corev_dv(tb, timeout):
    """Run `make corev-dv` once (clones+compiles corev-dv/riscv-dv); aborts
    the script on failure since no COREV_DV_TESTS entry can build without it."""
    tbcfg = TESTBENCHES[tb]
    cmd = ["make", "corev-dv"] + tbcfg["make_args"]
    env = make_env(tbcfg)

    print(f"[Setup/{tb}] make corev-dv ...")
    try:
        returncode, _, _ = _run(cmd, tbcfg["sim_dir"], env, timeout, capture=False)
    except subprocess.TimeoutExpired:
        sys.exit(f"error: 'make corev-dv' timed out after {timeout}s")
    except OSError as exc:
        sys.exit(f"error: could not launch 'make corev-dv': {exc}")

    if returncode != 0:
        sys.exit(f"error: 'make corev-dv' failed (exit {returncode}); "
                  "no corev-dv test can build without it")


def setup_spike_lib(tb, timeout):
    """Run `make spike_lib` once so --spike-tandem builds show a real
    diagnostic on failure instead of the opaque "make exited N" that
    run_test()/run_certify() report -- otherwise a first-time (or broken)
    Spike build only surfaces via the make test/certify -> verilate ->
    spike_lib dependency, with its output swallowed by capture=True."""
    tbcfg = TESTBENCHES[tb]
    cmd = ["make", "spike_lib"] + tbcfg["make_args"]
    env = make_env(tbcfg)

    print(f"[Setup/{tb}] make spike_lib (tandem-patched Spike; see "
          "reference/spike-tandem.md) ...")
    try:
        returncode, _, _ = _run(cmd, tbcfg["sim_dir"], env, timeout, capture=False)
    except subprocess.TimeoutExpired:
        sys.exit(f"error: 'make spike_lib' timed out after {timeout}s")
    except OSError as exc:
        sys.exit(f"error: could not launch 'make spike_lib': {exc}")

    if returncode != 0:
        sys.exit(f"error: 'make spike_lib' failed (exit {returncode}); "
                  "no --spike-tandem run can build without it")


def setup_comp(tb, timeout, cov=False):
    """Run `make comp` once so a --jobs > 1 batch can safely pass COMP=NO --
    otherwise workers race to compile the shared work library themselves.

    cov: also pass COV=1, or workers reusing this compile get no statement/
    branch/condition coverage in their .ucdb (assertions/covergroups only)."""
    tbcfg = TESTBENCHES[tb]
    cmd = ["make", "comp"] + tbcfg["make_args"]
    if cov:
        cmd.append("COV=1")
    env = make_env(tbcfg)

    print(f"[Setup/{tb}] make comp (one-time compile for --jobs > 1) ...")
    try:
        returncode, _, _ = _run(cmd, tbcfg["sim_dir"], env, timeout, capture=False)
    except subprocess.TimeoutExpired:
        sys.exit(f"error: 'make comp' timed out after {timeout}s")
    except OSError as exc:
        sys.exit(f"error: could not launch 'make comp': {exc}")

    if returncode != 0:
        sys.exit(f"error: 'make comp' failed (exit {returncode}); "
                  "no test can build without it")


def run_test(tb, test, run_index, cfg, timeout, quiet, extra_make_args=None,
             label=None, gen_seed="random", run_seed="random", cov=False,
             spike_tandem=False):
    """Build+run one test; return (outcome, detail, gen_seed_used, run_seed_used).

    corev-dv tests run gen_corev-dv and test as two independent vsim
    invocations with independent seeds (SEED=random re-derives per step, so
    one combined seed couldn't replay a run where the two steps differed).
    gen_seed_used/run_seed_used are the actual -sv_seed each step used; both
    None for non-corev-dv tests.
    extra_make_args: extra make args appended (e.g. ["COMP=NO"] after setup_comp()).
    cov: COV=1 for the firmware build+run only -- skipped for gen_corev-dv,
    which is unrelated to the DUT.
    label: prefixes output when --jobs > 1 so workers stay distinguishable.
    spike_tandem: SPIKE_TANDEM=1, core only -- see reference/spike-tandem.md.
    """
    tbcfg = TESTBENCHES[tb]
    env = make_env(tbcfg)
    gen_seed_used = None

    if test in COREV_DV_TESTS:
        # gen_corev-dv writes into GEN_START_INDEX, independent of RUN_INDEX
        # (the build/run step's own dir) -- without this, a nonzero
        # --run-index would build from an empty dir with no generated program.
        gen_cmd = (["make", "gen_corev-dv", f"TEST={test}",
                     f"GEN_START_INDEX={run_index}", f"SEED={gen_seed}"]
                    + tbcfg["make_args"])
        if extra_make_args:
            gen_cmd += extra_make_args

        try:
            returncode, gstdout, gstderr = _run(gen_cmd, tbcfg["sim_dir"], env,
                                                 timeout, capture=True)
        except subprocess.TimeoutExpired:
            return "ERROR", f"gen_corev-dv timed out after {timeout}s", None, None
        except OSError as exc:
            return "ERROR", f"could not launch gen_corev-dv make: {exc}", None, None

        gen_seed_used = extract_seed(gstdout + gstderr)
        if gen_seed_used is None:
            gpath = gen_log_path(tb, test, run_index, cfg)
            if gpath.is_file():
                gen_seed_used = extract_seed(gpath.read_text(errors="replace"))

        if returncode != 0:
            return ("ERROR", f"gen_corev-dv failed (exit {returncode})",
                    gen_seed_used, None)

    cmd = ["make", "test", f"TEST={test}", f"RUN_INDEX={run_index}"]
    if tb == "core":
        # sim/core/Makefile passes SEED straight through as
        # +verilator+seed+<value>, and Verilator's own convention (not a
        # Makefile-side thing) already treats 0 as "pick a random seed"
        # (see verilated.cpp) -- unlike uvmt.mk's SEED=random, which needs
        # Make-side resolution via `date +%N`. So map the script's "random"
        # sentinel to the literal 0 Verilator already special-cases, and
        # pass any other (replay) value straight through.
        cmd.append(f"SEED={0 if run_seed == 'random' else run_seed}")
    else:
        cmd.append(f"SEED={run_seed}")
    if cov:
        cmd.append("COV=1")
    if spike_tandem:
        cmd.append("SPIKE_TANDEM=1")
    cmd += tbcfg["make_args"]
    if extra_make_args:
        cmd += extra_make_args

    try:
        returncode, stdout, stderr = _run(cmd, tbcfg["sim_dir"], env, timeout, capture=True)
    except subprocess.TimeoutExpired:
        return "ERROR", f"timed out after {timeout}s", gen_seed_used, None
    except OSError as exc:
        return "ERROR", f"could not launch make: {exc}", gen_seed_used, None

    if not quiet:
        lines = [line for line in stdout.splitlines()
                 if any(m in line for m in tbcfg["markers"])]
        if lines:
            prefix = f"    [{label}] " if label else "    "
            with _print_lock:
                for line in lines:
                    print(prefix + line)

    # Prefer console output; fall back to the on-disk log if no banner reached stdout.
    console = stdout + stderr
    run_seed_used = extract_seed(console)
    outcome = classify(console, tbcfg)
    if outcome == "ERROR" or run_seed_used is None:
        path = log_path(tb, test, run_index, cfg)
        if path.is_file():
            log_text = path.read_text(errors="replace")
            if outcome == "ERROR":
                outcome = classify(log_text, tbcfg)
            if run_seed_used is None:
                run_seed_used = extract_seed(log_text)

    if outcome != "ERROR":
        return outcome, "", gen_seed_used, run_seed_used
    if returncode != 0:
        return "ERROR", f"make exited {returncode}", gen_seed_used, run_seed_used
    return "ERROR", "no verdict banner", gen_seed_used, run_seed_used


def parse_only(tb, test, run_index, cfg):
    """Read an existing log file without re-running the simulation; return
    (outcome, detail, gen_seed_used, run_seed_used), same shape as run_test()."""
    path = log_path(tb, test, run_index, cfg)
    if not path.is_file():
        return "ERROR", "no log file", None, None

    text = path.read_text(errors="replace")
    run_seed_used = extract_seed(text)
    gen_seed_used = None
    if test in COREV_DV_TESTS:
        gpath = gen_log_path(tb, test, run_index, cfg)
        if gpath.is_file():
            gen_seed_used = extract_seed(gpath.read_text(errors="replace"))

    return classify(text, TESTBENCHES[tb]), "", gen_seed_used, run_seed_used


_CERTIFY_SUMMARY_RE = re.compile(r"TOTAL=(\d+)\s+PASS=(\d+)\s+FAIL=(\d+)")


def certify_summary_path(run_index):
    """Location of certification_summary.txt (certify hardwires
    TEST=certification, so this path isn't parameterized by tb/test/cfg)."""
    return (TESTBENCHES["core"]["sim_dir"] / "simulation_results"
            / "certification" / str(run_index) / "test_program"
            / "certification_summary.txt")


def classify_certify_summary(summary_path):
    """Parse certify's aggregate 'TOTAL=n PASS=n FAIL=n' line into (outcome,
    detail) -- there's no single pass/fail banner for the whole sweep."""
    if not summary_path.is_file():
        return "ERROR", f"no summary at {summary_path}"
    text = summary_path.read_text(errors="replace")
    m = _CERTIFY_SUMMARY_RE.search(text)
    if not m:
        return "ERROR", f"could not parse {summary_path}"
    total, npass, nfail = (int(g) for g in m.groups())
    if total > 0 and npass == total and nfail == 0:
        return "PASS", f"{npass}/{total} compliance ELFs passed"
    return "FAIL", (f"{npass}/{total} compliance ELFs passed, {nfail} "
                     f"failed -- see {summary_path}")


def run_certify(run_index, timeout, quiet, spike_tandem=False, filter_=None):
    """Run `make certify` (the ACT4 compliance-ELF sweep); return (outcome,
    detail). Unlike run_test(), one `make` invocation runs every ELF and
    self-reports to certification_summary.txt (see classify_certify_summary()).

    spike_tandem: SPIKE_TANDEM=1 -- see the certify target's own comment in
    sim/core/Makefile for why +elf_file ordering matters there.
    filter_: passed through as FILTER=... to narrow the ELF scan.
    """
    tbcfg = TESTBENCHES["core"]
    env = make_env(tbcfg)
    cmd = ["make", "certify", f"RUN_INDEX={run_index}"]
    if spike_tandem:
        cmd.append("SPIKE_TANDEM=1")
    if filter_:
        cmd.append(f"FILTER={filter_}")
    cmd += tbcfg["make_args"]

    try:
        returncode, stdout, stderr = _run(cmd, tbcfg["sim_dir"], env, timeout, capture=True)
    except subprocess.TimeoutExpired:
        return "ERROR", f"timed out after {timeout}s"
    except OSError as exc:
        return "ERROR", f"could not launch make: {exc}"

    if not quiet:
        # Echo certify's own PASS/FAIL/TOTAL= lines, not the make/verilator noise.
        lines = [line for line in stdout.splitlines()
                 if line.startswith(("PASS", "FAIL", "TOTAL="))]
        if lines:
            with _print_lock:
                for line in lines:
                    print("    " + line)
        elif returncode != 0:
            # certify bailed before the loop (e.g. no ELFs found) -- that
            # message wouldn't match the filter above, so echo raw output.
            console = (stdout + stderr).rstrip()
            if console:
                with _print_lock:
                    print(f"    [certify make output]\n{console}")

    summary_path = certify_summary_path(run_index)
    if not summary_path.is_file() and returncode != 0:
        return "ERROR", f"make certify exited {returncode} (no summary written)"
    if returncode != 0 and "No .elf files found" in stdout:
        return "ERROR", (f"make certify exited {returncode}: no compliance "
                          "ELFs found -- run `make gen` or `make gen-certify` "
                          "in sim/core first")
    return classify_certify_summary(summary_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tests", nargs="*",
                    help="specific test names to run (default: the full cleaned-up set)")
    ap.add_argument("--tb", choices=sorted(TESTBENCHES), default="core",
                    help="testbench to run on: 'core' (Verilator) or 'uvmt' (vsim) "
                         "(default: core)")
    ap.add_argument("--include-parked", action="store_true",
                    help="also run the parked tests (step-compare arithmetic/CSR and "
                         "debug variants; meaningful under --tb uvmt)")
    ap.add_argument("--include-corev-dv", action="store_true",
                    help="also run the passing corev-dv generated regression tests "
                         "(uvmt only; each needs an extra gen_corev-dv step)")
    ap.add_argument("--corev-dv-only", action="store_true",
                    help="run ONLY the corev-dv generated regression tests (uvmt "
                         "only); cannot be combined with test names, "
                         "--include-parked, or --include-corev-dv")
    ap.add_argument("--parse-only", action="store_true",
                    help="do not run; just parse existing logs in the results directory")
    ap.add_argument("--cfg", default="default",
                    help="uvmt config subdirectory under vsim_results (default: default)")
    ap.add_argument("--run-index", type=int, default=0,
                    help="RUN_INDEX subdirectory to use (default: 0)")
    ap.add_argument("--timeout", type=int, default=1800,
                    help="per-test timeout in seconds (default: 1800; the "
                         "interrupt-heavy corev-dv templates routinely take "
                         "10-15 minutes including compile)")
    ap.add_argument("--gen-seed", default="random",
                    help="SEED for the corev-dv generation step (gen_corev-dv; "
                         "the random-instruction-stream generator). 'random' "
                         "(default) or a literal value to replay a specific "
                         "prior run -- see --run-seed, a fully independent "
                         "knob (gen_corev-dv and test are separate UVM "
                         "environments/vsim invocations, each seeded "
                         "separately). No effect on non-corev-dv tests.")
    ap.add_argument("--run-seed", default="random",
                    help="SEED for the test step (the actual firmware run's "
                         "env-level randomization, e.g. OBI stall knobs). "
                         "'random' (default) or a literal value to replay a "
                         "specific prior run. Applies to every test, on "
                         "both testbenches -- unlike --gen-seed, there's no "
                         "corev-dv-only restriction (a hand-written test has "
                         "no generation step, but its own run is still "
                         "randomized and seedable).")
    ap.add_argument("--cov", action="store_true",
                    help="collect code coverage (uvmt only; equivalent to "
                         "`make test ... COV=1` per test). Requires "
                         "sim/tools/vsim/cov.tcl to exist, or Questa silently "
                         "collects nothing -- see docs/COVERAGE-MAKE-TARGETS.md "
                         "for the report targets (cov, cov_txt, cov_holes, "
                         "cov_holes_details) that consume the resulting .ucdb.")
    ap.add_argument("--spike-tandem", action="store_true",
                    help="run in tandem with the Spike ISS, comparing every "
                         "retired instruction (core only; equivalent to "
                         "`make test ... SPIKE_TANDEM=1` per test) -- see "
                         "reference/spike-tandem.md. Combine with --certify to "
                         "run the ACT4 compliance-ELF sweep in tandem too.")
    ap.add_argument("--certify", action="store_true",
                    help="run the ACT4 compliance-ELF sweep (core only; "
                         "equivalent to `make certify`) instead of the named "
                         "test set -- every prebuilt compliance ELF runs in "
                         "its own verilator_executable invocation and the "
                         "result is read back from certification_summary.txt. "
                         "Combine with --spike-tandem to check every ELF "
                         "against Spike in tandem (`make certify "
                         "SPIKE_TANDEM=1`); cannot be combined with test "
                         "names, --corev-dv-only, --include-parked, or "
                         "--include-corev-dv.")
    ap.add_argument("--filter", default=None,
                    help="narrow --certify to one extension subdirectory "
                         "(e.g. 'rv32i/Zicsr'), passed through as FILTER=... "
                         "to `make certify` -- see sim/core/Makefile. No "
                         "effect without --certify.")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress per-test simulation banner output")
    ap.add_argument("--jobs", "-j", type=int, default=1,
                    help="run up to N tests concurrently (default: 1, sequential). "
                         "See the 'Concurrency' section of --help for the safety "
                         "model (uvmt only is verified race-free; core is not).")
    args = ap.parse_args()

    if args.jobs < 1:
        ap.error("--jobs must be >= 1")

    if args.cov and args.tb != "uvmt":
        ap.error("--cov requires --tb uvmt (Questa coverage; the core "
                  "Verilator testbench has no COV support)")

    if args.spike_tandem and args.tb != "core":
        ap.error("--spike-tandem requires --tb core (SPIKE_TANDEM is a "
                  "sim/core Makefile setting; the uvmt testbench has its "
                  "own separate Spike/RVVI integration)")

    if args.certify:
        if args.tb != "core":
            ap.error("--certify requires --tb core (make certify is a "
                      "sim/core-only target)")
        if args.tests or args.corev_dv_only or args.include_parked or args.include_corev_dv:
            ap.error("--certify cannot be combined with test names, "
                      "--corev-dv-only, --include-parked, or "
                      "--include-corev-dv (certify runs its own fixed ELF "
                      "sweep, not the named test set)")
    elif args.filter:
        ap.error("--filter has no effect without --certify")

    if args.corev_dv_only:
        if args.tests or args.include_parked or args.include_corev_dv:
            ap.error("--corev-dv-only cannot be combined with test names, "
                      "--include-parked, or --include-corev-dv")
        selected = list(COREV_DV_TESTS)
    elif args.tests:
        selected = args.tests
    else:
        selected = list(TESTS)
        if args.tb == "uvmt":
            selected += UVMT_TESTS
        if args.include_parked:
            selected += PARKED
        if args.include_corev_dv:
            selected += COREV_DV_TESTS

    sim_dir = TESTBENCHES[args.tb]["sim_dir"]
    if not sim_dir.is_dir():
        sys.exit(f"error: sim directory for --tb {args.tb} not found at {sim_dir}")

    if args.spike_tandem and not args.parse_only:
        setup_spike_lib(args.tb, args.timeout)

    if args.certify:
        # Own fixed ELF sweep -- short-circuit the rest of main().
        action = "Parsing" if args.parse_only else "Running"
        print(f"[{action}/core] certify"
              + (" (spike-tandem)" if args.spike_tandem else "")
              + (f" FILTER={args.filter}" if args.filter else "") + " ...")
        if args.parse_only:
            outcome, detail = classify_certify_summary(
                certify_summary_path(args.run_index))
        else:
            outcome, detail = run_certify(
                args.run_index, args.timeout, args.quiet,
                spike_tandem=args.spike_tandem, filter_=args.filter)
        print()
        print(f"certify: {outcome} {detail}".rstrip())
        sys.exit(0 if outcome == "PASS" else 1)

    needs_corev_dv = any(test in COREV_DV_TESTS for test in selected)
    if needs_corev_dv and not args.parse_only:
        if args.tb != "uvmt":
            sys.exit("error: corev-dv tests require --tb uvmt")
        setup_corev_dv(args.tb, args.timeout)

    extra_make_args = []
    if args.jobs > 1 and not args.parse_only:
        if args.tb == "uvmt":
            # One-time compile so the batch below can pass COMP=NO safely --
            # see the module docstring's "Concurrency" section.
            setup_comp(args.tb, args.timeout, cov=args.cov)
            extra_make_args = ["COMP=NO"]
        else:
            print(f"warning: --jobs {args.jobs} with --tb core has not been "
                  "verified race-free against the shared Verilator build "
                  "directory (sim/core/cobj_dir); proceeding anyway, but "
                  "prefer --jobs 1 unless you've confirmed it's safe.")

    def run_one(test):
        action = "Parsing" if args.parse_only else "Running"
        with _print_lock:
            print(f"[{action}/{args.tb}] {test} ...")
        if args.parse_only:
            outcome, detail, gen_seed, run_seed = parse_only(
                args.tb, test, args.run_index, args.cfg)
        else:
            outcome, detail, gen_seed, run_seed = run_test(
                args.tb, test, args.run_index, args.cfg,
                args.timeout, args.quiet,
                extra_make_args=extra_make_args,
                label=test if args.jobs > 1 else None,
                gen_seed=args.gen_seed, run_seed=args.run_seed,
                cov=args.cov, spike_tandem=args.spike_tandem)
        if args.jobs > 1:
            done = "Parsed" if args.parse_only else "Done"
            with _print_lock:
                print(f"[{done}/{args.tb}] {test}: {outcome} {detail}".rstrip())
        return test, outcome, detail, gen_seed, run_seed

    width = max(len(t) for t in selected)
    if args.jobs == 1:
        results = [run_one(test) for test in selected]
    else:
        outcomes = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [pool.submit(run_one, test) for test in selected]
            for future in concurrent.futures.as_completed(futures):
                test, outcome, detail, gen_seed, run_seed = future.result()
                outcomes[test] = (test, outcome, detail, gen_seed, run_seed)
        # Report in the original --selected order regardless of completion order.
        results = [outcomes[test] for test in selected]

    # GEN_SEED is "-" for non-corev-dv tests (no generate step -- see
    # run_test()); RUN_SEED is populated for every test now. Either column
    # can still show "-" if extract_seed() couldn't find a banner (e.g. a
    # build failure before the run ever printed one).
    def _fmt_seed(s):
        return s if s is not None else "-"

    gen_width = max([len("GEN_SEED")] + [len(_fmt_seed(r[3])) for r in results])
    run_width = max([len("RUN_SEED")] + [len(_fmt_seed(r[4])) for r in results])
    header = (f"{'TEST'.ljust(width)}   RESULT   "
              f"{'GEN_SEED'.ljust(gen_width)}   {'RUN_SEED'.ljust(run_width)}   DETAIL")
    sep_width = len(header)

    print()
    print("=" * sep_width)
    print(f"testbench: {args.tb}")
    print("-" * sep_width)
    print(header)
    print("-" * sep_width)
    counts = {"PASS": 0, "FAIL": 0, "ERROR": 0}
    for test, outcome, detail, gen_seed, run_seed in results:
        counts[outcome] = counts.get(outcome, 0) + 1
        print(f"{test.ljust(width)}   {outcome:<6}   "
              f"{_fmt_seed(gen_seed).ljust(gen_width)}   "
              f"{_fmt_seed(run_seed).ljust(run_width)}   {detail}")
    print("=" * sep_width)
    total = len(results)
    print(f"{total} test(s): {counts['PASS']} passed, "
          f"{counts['FAIL']} failed, {counts['ERROR']} error(s)")

    # Exit non-zero unless everything ran and passed.
    sys.exit(0 if counts["PASS"] == total else 1)


if __name__ == "__main__":
    main()
