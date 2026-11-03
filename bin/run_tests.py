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

    core : sim/core/simulation_results/<name>/<seed>/<name>.log
           "ALL TESTS PASSED"   -> PASS   (tb/core/tb_top.sv)
           "TEST(S) FAILED!"    -> FAIL

    uvmt : sim/uvmt/vsim_results/<cfg>/<name>/0/vsim-<name>.log
           "SIMULATION PASSED"  -> PASS   (tb/uvmt/uvmt_cv32e20_tb.sv;
                                           includes "PASSED with WARNINGS")
           "SIMULATION FAILED"  -> FAIL

Anything else (no banner, build error, timeout) is reported as ERROR.
The process exit code is 0 only if every test that was run reported PASS, unless
--allow-failures is given (see below), in which case per-test FAIL/ERROR verdicts
still print and are summarized but do not affect the exit code -- useful when a
coverage/report step must run after the tests regardless of their outcome.

corev-dv tests (see COREV_DV_TESTS below) additionally need `make
comp_corev-dv` run once beforehand to compile the corev-dv/riscv-dv packages
(uvmt only; the pinned vendor clones are reused when already present).
Whenever the selected set includes any corev-dv test, this script runs `make
comp_corev-dv` itself before running any tests, and aborts if that setup step
fails.

Seeds
-----
--seed sets the seed of the test run itself (env-level randomization, e.g.
OBI stall knobs) for every test, on both testbenches: an integer
1..2147483647, or 'random'. The default is 1, so a plain run is reproducible.

core: each run's results go in sim/core/simulation_results/<test>/<seed>/;
re-running a test with the same seed overwrites that directory. The seed is
passed as SEED=<n> (sim/core/Makefile turns it into +verilator+seed+<n>).
With --seed random, this script picks a fresh seed for each test. 0 is not
accepted: Verilator treats +verilator+seed+0 as "pick a random seed", so the
directory name would not identify the seed actually used.

uvmt: the seed is passed through as SEED=<value> (mk/uvmt/uvmt.mk resolves
'random' itself, from `date +%N`); results stay in
vsim_results/<cfg>/<test>/0/ (uvmt's default RUN_INDEX).

corev-dv tests (uvmt only) also have a separate program-generation step
(gen_corev-dv), seeded independently by --gen-seed ('random' by default, so
re-running does NOT reproduce the same generated program unless --gen-seed
is given). Hand-written tests have no generation step, so their GEN_SEED is
always "-".

The summary table's GEN_SEED/RUN_SEED columns show the seed each step
actually used, recovered from the run's own output (uvmt: vsim's
`-sv_seed <value>` banner; core: tb_top.sv's "Simulation running with seed:
<value>"), so any run can be replayed with --gen-seed/--seed.

--parse-only (core) reports every test/seed result directory it finds, one
row each (oldest first), or only one seed's with --seed N.

Usage
-----
The script needs no arguments and can be run from anywhere (paths are resolved
relative to its own location in <repo>/bin).  A working RISC-V toolchain plus
the relevant simulator (Verilator for core, Questa vsim for uvmt) must be on
PATH, as for a normal `make test`.

    # Run a regression testlist -- the curated, named, published way to run a
    # set of tests (regress/*.yaml; see 'Regression testlists' below):
    bin/run_tests.py --testlist regress/cv32e20_sanity.yaml
    bin/run_tests.py --testlist regress/cv32e20_ci_check.yaml --jobs 4

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

    # Skip simulation; just re-summarize existing logs (core: every
    # test/seed result directory, or one seed's with --seed N):
    bin/run_tests.py --parse-only
    bin/run_tests.py --parse-only --seed 12345 misalign
    bin/run_tests.py --tb uvmt --parse-only

    # Run with a fresh random seed per test (default seed is 1):
    bin/run_tests.py --seed random

    # Run up to 4 tests concurrently (uvmt only is verified safe -- see below):
    bin/run_tests.py --tb uvmt --corev-dv-only --jobs 4

    # Replay a specific prior corev-dv run from its logged seeds (gen_corev-dv
    # and test are independent UVM environments/vsim invocations, each with
    # their own seed -- see the summary table's GEN_SEED/RUN_SEED columns):
    bin/run_tests.py --tb uvmt --gen-seed 363891135 --seed 354410829 \
        corev_rand_instr_and_data_stalls

    # Replay a specific prior run's env-level randomization (e.g. OBI stall
    # knobs) for a hand-written test -- there's no --gen-seed here, since
    # hand-written tests have no generation step, only the run itself:
    bin/run_tests.py --seed 12345 misalign

    # Collect code coverage (uvmt only; equivalent to `make test ... COV=1` per test):
    bin/run_tests.py --tb uvmt --cov hello-world

    # Full coverage regression: run the tests with COV=1, merge every PASSing
    # test's .ucdb into sim/uvmt/vsim_results/<cfg>/merged/merged.ucdb and
    # publish the whole report artifact set (see 'Coverage reports' below):
    bin/run_tests.py --tb uvmt --cov-report
    bin/run_tests.py --tb uvmt --all-custom --cov-report   # dynamic discovery variant

    # Regenerate the reports from an already-merged .ucdb, without running anything:
    bin/run_tests.py --tb uvmt --report-only

    # Re-run just the vcover merge for every selected test that already has a
    # .ucdb on disk (verdicts re-parsed from their logs), then regenerate reports:
    bin/run_tests.py --tb uvmt --merge-existing

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
    #   --testlist PATH   run a regress/*.yaml testlist (see below)
    #   --cfg NAME      uvmt config subdirectory                (default: default)
    #   --gen-seed SEED corev-dv generator SEED ('random' or a literal
    #                   value); no effect on hand-written tests (no
    #                   generation step exists for them)
    #   --seed SEED     test-run seed: 1..2147483647 or 'random'
    #                   (default: 1); applies to every test, on both
    #                   testbenches
    #   --timeout SECS  per-test timeout                        (default: 1800)
    #   --jobs N, -j N  run up to N tests concurrently           (default: 1)
    #   --cov           collect code coverage (uvmt only)
    #   --cov-report    --cov + per-test merge + published report set (uvmt only)
    #   --all-custom    select every dir under tests/programs/custom (see below)
    #   --merge-existing  re-merge existing .ucdb files, then regenerate reports
    #   --report-only   skip execution; regenerate reports from existing data
    #   --clean-report  delete coverage_report/ before regenerating it
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
suitable for use as a CI gate -- including the coverage regression, which runs
through the same pass/fail machinery (banner-based classify(), not make's exit
code) and therefore gates CI on test failures too. The one exception is
--report-only, which launches no simulation at all and always exits 0.

Coverage reports (--cov-report, uvmt only)
------------------------------------------
--cov alone only collects per-test .ucdb files; --cov-report adds the rest of
the published artifact set that CI deploys to GitHub Pages:

    coverage_report/index.html          dashboard (copied from templates/)
    coverage_report/common.css          stylesheet shared by both dashboards
    coverage_report/style.css           dashboard stylesheet
    coverage_report/questasim/          vcover -html code report, DUT-scoped
    coverage_report/questasim_func/     vcover -html -cvg report, full hierarchy
    coverage_report/questasim_parked/   the code report rebuilt from merged_parked/
    coverage_report/questasim_func_parked/  the func report from merged_parked/
    coverage_report/analysis/           the coverage analysis as a page: the
                                        viewer, the review sheet and the five
                                        raw dumps it reads
    coverage_report/merged.questasim.xml  Questa XML rollup, whole hierarchy
    coverage_report/dut_rollup.xml      Questa XML rollup, DUT scope
    coverage_report/cobertura.xml       Cobertura XML (questa_xml_to_cobertura)
    coverage_report/merged.ucis.xml     UCIS XML (questa_xml_to_ucis_xml)
    coverage_report/summary.json        metrics consumed by index.html
    coverage_report/trl5_metrics.json   TRL5 line/cond/branch/FSM metrics
    sim/uvmt/test_results.log           plain-text pass/fail list

    Every number in them comes from `vcover report -xml` exports of merged.ucdb --
    never from the generated HTML -- and from two deliberately different scopes:

    * Code coverage (statements, branches, conditions, FSM states/transitions) is
    DUT-scoped, to TESTBENCHES['uvmt']['cov_instance']: the testbench's own
    code is not the deliverable.
    * Functional coverage is covergroup-bin coverage over the whole hierarchy,
    because the environment's covergroups live in packages (/uvme_cv32e20_pkg,
    /uvma_isacov_pkg, /uvma_obi_memory_pkg) outside that instance. A DUT-scoped
    'fc' counts the RTL's cover directives instead, and reported ~100% while
    every env covergroup sat at 0%.

    coverage_report/analysis/ is a publication mirror, and the direction is
    one-way: the committed originals under docs/coverage/ are what the analysis
    tools and the cite checker (bin/coverage_review.py --check-cites) read, and
    no python reads what this script writes there.

    The two HTML reports follow the same split, and it is the one thing in here
    that is easy to break by copy-paste: coverage_report/questasim/ is built
    with -instance=<DUT>. (the dashboard's "Code Coverage" button), while
    coverage_report/questasim_func/ is built with -cvg and *no* -instance at all
    (its "Functional Coverage" button and the functional card both point there).
    Adding -instance to the second, or removing it from the first, makes the two
    buttons show the same wrong number.

The merge step runs once per batch, after the last test, from an explicit list
of this batch's PASSing .ucdb files -- never from a find over
vsim_results/<cfg>, because whatever earlier runs left there used to leak
straight into the published numbers. --cov-report merges twice into sibling
databases: vsim_results/<cfg>/merged/ holds the default scope (non-PARKED
PASSes) and vsim_results/<cfg>/merged_parked/ the same plus the PARKED PASSes,
each keeping a ucdb.list naming its own inputs (mk/uvmt/vsim.mk
COV_MERGE_LIST). Tests without a .ucdb (FAILED/ERROR runs, or a batch without
--cov) are in neither list. A --cov-report run first deletes every per-test
.ucdb under vsim_results/<cfg>, both merge directories, and coverage_report/;
--clean-report only does the last. --merge-existing keeps the historical
"merge everything on disk" behaviour: one default-scope find merge, and no
including-parked database.

--all-custom selects every directory under TESTS_ROOTS instead of the curated
lists above, which is what the coverage CI job uses so a newly added test
program is picked up without editing this script. PARKED and corev-dv names are
still skipped unless --include-parked / --include-corev-dv also ask for them,
and DISCOVERY_EXCLUDES is always skipped.

Regression testlists (--testlist)
--------------------------------
A testlist is the named, reviewable answer to "which tests make up a regression
of this repository?" -- the alternative to a caller re-listing tests in a CI job
or a second script, which is how bin/ci_check and bin/cv_regress drifted until
they stopped running at all (see bin/README.md). They live in regress/ and are
consumed by this script:

    name: cv32e20_sanity           # required; shown on the published dashboard
    description: >                 # required; free text
      Fast blocking sanity on the Questa UVMT testbench.
    tb: uvmt                       # optional; core|uvmt (default core)
    cfg: default                   # optional; the --cfg equivalent
    timeout: 3600                  # optional per-test seconds
    jobs: 4                        # optional --jobs equivalent
    seed: 1                        # optional --seed equivalent (int or random)
    make_args: []                  # optional list appended to every make call
    tests:                         # ordered; each entry:
      - name: hello-world          # required: dir under tests/programs/{custom,corev-dv}
        description: UVM hello-world sanity   # optional; dashboard only
        make_args: []              # optional extra make args for this test

Anything not in those key lists is a hard error rather than silently ignored --
a typo that quietly changed what a regression ran is the failure mode this whole
feature exists to remove. A listed name must be a real test-program directory.
Whether a test needs the gen_corev-dv generation step is read from the tree (its
corev-dv.yaml, see is_corev_dv()), so no list has to be updated in two places.

The file only supplies defaults: --tb/--cfg/--timeout/--jobs/--seed on the
command line still win over it. A test cannot be repeated N times under one
name (the old cv_regress 'num:' key); run the list again with a different
--seed, which is reproducible and keeps the two runs distinguishable in the
results document.

Regression results dashboard (--testlist / every run)
-----------------------------------------------------
Every batch that runs (or parses) tests also writes regression_results.json in
the testbench's sim directory and publishes a dashboard of it under
coverage_report/regression/ -- per-test verdict, generation and run seeds,
duration and a copy of the simulation log, plus the regression-level summary and
the git/host/simulator provenance of the run. Two options are excepted because
neither is a batch of tests in that sense: --report-only launches nothing, and
--certify short-circuits into make certify's own ELF-sweep summary. bin/regression_report.py
owns the document and its template (templates/regression_dashboard/), and can
re-publish an existing document without running anything:

    bin/regression_report.py --results sim/uvmt/regression_results.json \\
                             --out coverage_report/regression

The dashboard is a copy of the verdict table, never a second verdict: nothing
here can turn a FAIL into a pass, and publishing failures (or --parse-only rows
with null durations) is deliberately supported -- the page renders what is
missing as N/A rather than as zero. The summary's wall window obeys the same
rule: it is only published when the batch timed something, so a parsed batch
leaves summary.start/end/duration_s null instead of publishing the couple of
seconds between two timestamps as a regression's wall time. Since a document
describes the batch that wrote it, that same re-summarize replaces whatever
measured window the previous document held -- re-run the batch to measure it
again, or re-publish the older document from the copy it left behind.

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
each worker runs in its own per-test run directory
(sim/uvmt/vsim_results/<cfg>/<test>/0/), which `make`'s `run`
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
(sim/core/simulation_results/cobj_dir) on every invocation, and no COMP=NO-equivalent skip-flag
was found for it. Prefer --jobs 1 there unless you've confirmed otherwise.

Also keep the vsim license pool in mind (`lmutil lmstat`) -- each concurrent
uvmt worker holds its own set of Questa feature licenses (msimhdlsim,
svverification, mtiverification, ...) for the duration of its run.
"""

import argparse
import concurrent.futures
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

# Repository layout: this script lives in <repo>/bin.
SCRIPT_DIR = Path(__file__).resolve().parent
REPO = SCRIPT_DIR.parent

# The coverage-report pipeline reuses the converters that live next to this
# script in <repo>/bin (each of them remains usable stand-alone), and
# regression_report turns this run's verdict rows into the results document and
# dashboard that CI publishes.
sys.path.insert(0, str(SCRIPT_DIR))
from questa_xml_to_cobertura import generate_cobertura_xml  # noqa: E402
from questa_xml_to_ucis_xml import generate_ucis_xml  # noqa: E402
import regression_report  # noqa: E402

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
        # Hierarchy the coverage report and TRL5 metrics are scoped to.
        "cov_instance": "/uvmt_cv32e20_tb/dut_wrap/cv32e20_top_i/u_cve2_top/u_cve2_core",
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
# this), and `make comp_corev-dv` run once first (main() does this
# automatically).
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

# Roots scanned by --all-custom: every immediate subdirectory is taken as a test
# name. The curated lists above remain the default selection; --all-custom is
# the opt-in "run whatever is in the tree" mode used by the coverage CI job.
TESTS_ROOTS = [
    "tests/programs/custom",
    "tests/programs/corev-dv",
]

# Directories under TESTS_ROOTS that --all-custom must never select. Everything
# already covered by PARKED / COREV_DV_TESTS is skipped through those lists (see
# discover_all_custom()), so this only needs the known-broken tests that no
# curated list covers -- the debug_test_* failures excluded by the old
# bin/run_uvm_tests.py all live in PARKED now.
DISCOVERY_EXCLUDES = [
    "isa_fcov_holes",
    "riscv_ebreak_test_0",
]



# Verilator's +verilator+seed+ range; 0 means "pick a random seed" there, so
# it can't name a reproducible result directory.
MAX_SEED = 2**31 - 1
DEFAULT_SEED = 1

# uvmt keeps mk/uvmt/uvmt.mk's default RUN_INDEX/GEN_START_INDEX for now.
UVMT_RUN_INDEX = 0

# Directory of one test's test-program sources, and of the corev-dv generator
# template a generated test adds next to them.
TESTS_PROGRAM_ROOT = REPO / "tests" / "programs"


def is_corev_dv(test):
    """Whether a test needs the gen_corev-dv generation step before it runs.

    The tree is the authority: a test-program directory carrying
    tests/programs/corev-dv/<name>/corev-dv.yaml is exactly what tells
    mk/Common.mk's generation targets (and therefore `make gen_corev-dv`) that
    the program is generated, so a --testlist may name any generation test
    without also editing COREV_DV_TESTS. The curated list is still consulted so
    a generated test with an untracked or renamed corev-dv.yaml keeps running
    the way it always did."""
    return (test in COREV_DV_TESTS
            or (TESTS_PROGRAM_ROOT / "corev-dv" / test / "corev-dv.yaml").is_file())


def seed_arg(text):
    """argparse type for --seed: 'random' or an integer 1..MAX_SEED."""
    if text == "random":
        return text
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid seed {text!r}: expected an integer 1..{MAX_SEED} or 'random'")
    if not 1 <= value <= MAX_SEED:
        why = (" (0 would make Verilator pick an unrecorded random seed)"
               if value == 0 else "")
        raise argparse.ArgumentTypeError(
            f"invalid seed {value}: must be 1..{MAX_SEED}{why}")
    return value


def resolve_seed(seed):
    """Integer seed to run with: a fresh random one for 'random'."""
    if seed == "random":
        return random.randint(1, MAX_SEED)
    return seed


def core_results_dir(test):
    """sim/core results for one test; holds one subdirectory per seed."""
    return TESTBENCHES["core"]["sim_dir"] / "simulation_results" / test


def log_path(tb, test, seed, cfg):
    """Location of the per-test simulation log for the given testbench
    (seed is only used by core; uvmt results aren't keyed by seed)."""
    if tb == "core":
        return core_results_dir(test) / str(seed) / f"{test}.log"
    # uvmt / vsim
    return (TESTBENCHES[tb]["sim_dir"] / "vsim_results" / cfg / test
            / str(UVMT_RUN_INDEX) / f"vsim-{test}.log")


def gen_log_path(tb, test, cfg):
    """Location of the corev-dv generation step's own log (a separate vsim
    run from the test's own log, hence its own seed). "_1" is
    GEN_NUM_TESTS's unoverridden Makefile default."""
    sim_dir = TESTBENCHES[tb]["sim_dir"]
    return (sim_dir / "vsim_results" / cfg / "corev-dv" / test
            / f"{test}_{UVMT_RUN_INDEX}_1.log")


def seed_dirs(results_dir, result_file, seed=None):
    """Seed-named subdirectories of results_dir, oldest first by the
    modification time of result_file (a path relative to each directory) --
    or just seed's, if one is given and it exists."""
    if seed is not None:
        d = results_dir / str(seed)
        return [d] if d.is_dir() else []
    if not results_dir.is_dir():
        return []

    def mtime(d):
        f = d / result_file
        return (f if f.is_file() else d).stat().st_mtime

    dirs = [d for d in results_dir.iterdir() if d.is_dir() and d.name.isdigit()]
    return sorted(dirs, key=mtime)


_SEED_RE = re.compile(r"-sv_seed\s+(\S+)")
_CORE_SEED_RE = re.compile(r"Simulation running with seed:\s+(\S+)")


def extract_seed(text):
    """Pull the actual seed a run used from its output/log -- needed for
    uvmt's SEED=random, which mk/uvmt/uvmt.mk resolves itself. uvmt prints
    it via vsim's own -sv_seed banner; core via tb_top.sv's $display of
    $get_initial_random_seed()."""
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
    """Run `make comp_corev-dv` once (compiles the corev-dv/riscv-dv generator,
    cloning the pinned vendor trees only if they are missing); aborts the script
    on failure since no COREV_DV_TESTS entry can build without it.

    Not `make corev-dv`: that target starts with clean_riscv-dv and re-clones
    riscv-dv (rm -rf + git clone) on every call."""
    tbcfg = TESTBENCHES[tb]
    cmd = ["make", "comp_corev-dv"] + tbcfg["make_args"]
    env = make_env(tbcfg)

    print(f"[Setup/{tb}] make comp_corev-dv ...")
    try:
        returncode, _, _ = _run(cmd, tbcfg["sim_dir"], env, timeout, capture=False)
    except subprocess.TimeoutExpired:
        sys.exit(f"error: 'make comp_corev-dv' timed out after {timeout}s")
    except OSError as exc:
        sys.exit(f"error: could not launch 'make comp_corev-dv': {exc}")

    if returncode != 0:
        sys.exit(f"error: 'make comp_corev-dv' failed (exit {returncode}); "
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


def run_test(tb, test, cfg, timeout, quiet, extra_make_args=None,
             label=None, gen_seed="random", seed=DEFAULT_SEED, cov=False,
             spike_tandem=False):
    """Build+run one test; return (outcome, detail, gen_seed_used, run_seed_used).

    corev-dv tests run gen_corev-dv and test as two independent vsim
    invocations with independent seeds (SEED=random re-derives per step, so
    one combined seed couldn't replay a run where the two steps differed).
    gen_seed_used is None for non-corev-dv tests.
    seed: --seed's value; for core, 'random' is resolved here (one fresh
    seed per call) and results land in simulation_results/<test>/<seed>/.
    extra_make_args: extra make args appended (e.g. ["COMP=NO"] after setup_comp()).
    cov: COV=1 for the firmware build+run only -- skipped for gen_corev-dv,
    which is unrelated to the DUT.
    label: prefixes output when --jobs > 1 so workers stay distinguishable.
    spike_tandem: SPIKE_TANDEM=1, core only -- see reference/spike-tandem.md.
    """
    tbcfg = TESTBENCHES[tb]
    env = make_env(tbcfg)
    gen_seed_used = None

    if is_corev_dv(test):
        gen_cmd = (["make", "gen_corev-dv", f"TEST={test}", f"SEED={gen_seed}"]
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
            gpath = gen_log_path(tb, test, cfg)
            if gpath.is_file():
                gen_seed_used = extract_seed(gpath.read_text(errors="replace"))

        if returncode != 0:
            return ("ERROR", f"gen_corev-dv failed (exit {returncode})",
                    gen_seed_used, None)

    # core resolves 'random' here (the seed names the results directory);
    # uvmt.mk resolves SEED=random itself.
    if tb == "core":
        seed = resolve_seed(seed)
    cmd = ["make", "test", f"TEST={test}", f"SEED={seed}"]
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
        path = log_path(tb, test, seed, cfg)
        if path.is_file():
            log_text = path.read_text(errors="replace")
            if outcome == "ERROR":
                outcome = classify(log_text, tbcfg)
            if run_seed_used is None:
                run_seed_used = extract_seed(log_text)
    if run_seed_used is None and tb == "core":
        run_seed_used = str(seed)

    if outcome != "ERROR":
        return outcome, "", gen_seed_used, run_seed_used
    if returncode != 0:
        return "ERROR", f"make exited {returncode}", gen_seed_used, run_seed_used
    return "ERROR", "no verdict banner", gen_seed_used, run_seed_used


def parse_only(tb, test, cfg, seed=None):
    """Read existing logs without re-running the simulation; return a list
    of (outcome, detail, gen_seed_used, run_seed_used), each the same shape
    as run_test()'s result. core: one entry per seed directory under
    simulation_results/<test>/ (oldest first), or just seed's if given.
    uvmt: a single entry."""
    if tb == "core":
        dirs = seed_dirs(core_results_dir(test), f"{test}.log", seed)
        if not dirs:
            return [("ERROR", "no log file", None,
                     str(seed) if seed is not None else None)]
        return [_parse_log(tb, test, d / f"{test}.log", cfg, d.name)
                for d in dirs]
    return [_parse_log(tb, test, log_path(tb, test, None, cfg), cfg, None)]


def _parse_log(tb, test, path, cfg, dir_seed):
    """One parse_only() row. The seed shown is the one the log reports,
    falling back to its directory's name (core)."""
    if not path.is_file():
        return "ERROR", "no log file", None, dir_seed

    text = path.read_text(errors="replace")
    run_seed_used = extract_seed(text) or dir_seed
    gen_seed_used = None
    if is_corev_dv(test):
        gpath = gen_log_path(tb, test, cfg)
        if gpath.is_file():
            gen_seed_used = extract_seed(gpath.read_text(errors="replace"))

    return classify(text, TESTBENCHES[tb]), "", gen_seed_used, run_seed_used


def discover_all_custom():
    """--all-custom: the immediate subdirectories of each TESTS_ROOTS entry as a
    sorted test-name list -- an opt-in alternative to the curated lists above,
    for callers (the coverage CI job) that want 'whatever is in the tree' rather
    than the same list maintained in two places.

    Skipped: DISCOVERY_EXCLUDES (known-broken and covered by no curated list),
    plus everything already listed in PARKED / COREV_DV_TESTS -- those stay
    opt-in through --include-parked / --include-corev-dv, which still append to
    the result as usual."""
    skip = set(PARKED) | set(COREV_DV_TESTS) | set(DISCOVERY_EXCLUDES)
    found = []
    for root in TESTS_ROOTS:
        root_dir = REPO / root
        if not root_dir.is_dir():
            print(f"warning: test root {root_dir} not found; skipping")
            continue
        found.extend(entry.name for entry in sorted(root_dir.iterdir())
                     if entry.is_dir() and entry.name not in skip)
    return sorted(found)


# Optional keys of a --testlist file, and the keys of one of its test entries.
# Anything else is rejected rather than ignored: a typo silently changing what a
# regression runs is the failure mode this format exists to avoid (the curated
# lists above drifted into exactly that -- csr_instr_asm is both a default test
# and a parked one).
TESTLIST_KEYS = ("name", "description", "tb", "cfg", "timeout", "jobs", "seed",
                 "make_args", "tests")
TESTLIST_TEST_KEYS = ("name", "description", "make_args")


def load_testlist(path):
    """Read a regression testlist; return (meta, entries).

    regress/*.yaml is where bin/README.md has always told people to put
    regression testlists, and this is the format bin/run_tests.py -- the repo's
    one harness -- actually consumes. meta carries the file's run settings (name,
    description, tb, cfg, timeout, jobs, seed, make_args) and entries one dict
    per test, in file order.

    Every listed name must be a real test-program directory under
    tests/programs/{custom,corev-dv}/: catching a renamed or misspelled test at
    load time beats discovering it as an ERROR row two hours into a regression.

    PyYAML is imported here rather than at module scope so the rest of this
    script keeps running on a bare interpreter (bin/requirements.txt declares it,
    and every `make test` already needs it through bin/yaml2make)."""
    try:
        import yaml
    except ImportError:
        sys.exit("error: --testlist requires PyYAML -- "
                 "pip install -r bin/requirements.txt")

    path = Path(path)
    if not path.is_file():
        sys.exit(f"error: testlist not found: {path}")
    try:
        doc = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        sys.exit(f"error: could not read testlist {path}: {exc}")

    def reject_unknown(mapping, allowed, where):
        unknown = [key for key in mapping if key not in allowed]
        if unknown:
            sys.exit(f"error: {path}: unknown key(s) "
                     f"{', '.join(sorted(unknown))} in {where}; "
                     f"allowed: {', '.join(allowed)}")

    if not isinstance(doc, dict):
        sys.exit(f"error: {path}: expected a mapping of testlist settings")
    reject_unknown(doc, TESTLIST_KEYS, "the testlist")
    for key in ("name", "tests"):
        if not doc.get(key):
            sys.exit(f"error: {path}: '{key}' is required")

    tests = doc["tests"]
    if not isinstance(tests, list) or not tests:
        sys.exit(f"error: {path}: 'tests' must be a non-empty list")

    roots = [TESTS_PROGRAM_ROOT / "custom", TESTS_PROGRAM_ROOT / "corev-dv"]
    entries, seen = [], set()
    for position, entry in enumerate(tests):
        where = f"tests[{position}]"
        if not isinstance(entry, dict) or not entry.get("name"):
            sys.exit(f"error: {path}: {where} must be a mapping with a 'name'")
        reject_unknown(entry, TESTLIST_TEST_KEYS, where)
        name = entry["name"]
        if name in seen:
            sys.exit(f"error: {path}: test '{name}' is listed twice")
        seen.add(name)
        if not any((root / name).is_dir() for root in roots):
            where = " or ".join(str(root.relative_to(REPO)) for root in roots)
            sys.exit(f"error: {path}: test '{name}' has no test-program "
                     f"directory under {where}")
        entries.append({"name": name,
                        "description": entry.get("description"),
                        "make_args": list(entry.get("make_args") or [])})

    meta = dict(doc)
    try:
        meta["path"] = str(path.resolve().relative_to(REPO))
    except ValueError:
        meta["path"] = str(path)
    return meta, entries


def regression_document(tb, cfg, results, testlist=None, started=None,
                        finished=None, descriptions=None):
    """This batch's rows as a bin/regression_report.py document.

    rows are (test, verdict, detail, gen_seed, run_seed, duration) tuples, the
    shape main() collects; --parse-only rows carry duration None because nothing
    was timed. Each row also gets its simulation log's repository-relative path
    and whether that log is still on disk -- the published dashboard links to a
    copy of it, so a path that no longer exists must not be offered as one.
    descriptions come from the --testlist file and are the only human-readable
    text a reader of the dashboard gets per test."""
    descriptions = descriptions or {}
    entries = []
    for test, verdict, detail, gen_seed, run_seed, duration in results:
        # Only --tb core keys its log directory by seed, and there the seed is
        # always known (run_test() falls back to the one it was given).
        log = log_path(tb, test, run_seed or DEFAULT_SEED, cfg)
        entries.append(regression_report.test_entry(
            test, verdict, detail=detail, gen_seed=gen_seed, run_seed=run_seed,
            duration_s=duration,
            log=os.path.relpath(log, REPO).replace(os.sep, "/"),
            log_exists=log.is_file(),
            description=descriptions.get(test),
            # The published regression document covers every test this batch
            # ran, parked ones included -- flagged, so the dashboard can badge
            # them and keep the parked failures out of the default verdict.
            parked=test in PARKED))
    return regression_report.build_document(
        entries, tb, cfg, testlist=testlist, started=started, finished=finished)


def test_ucdb_path(tb, test, run_index, cfg):
    """Path of one test's coverage database in this checkout (may be absent --
    a test that never ran with --cov simply has no file here)."""
    tbcfg = TESTBENCHES[tb]
    return (tbcfg["sim_dir"] / "vsim_results" / cfg / test / str(run_index)
            / f"{test}.ucdb")


def batch_ucdb_lists(results, tb, cfg, run_index=UVMT_RUN_INDEX):
    """Split a batch's result rows into the two merge input lists.

    Returns (default_paths, parked_paths): the absolute Paths of the .ucdb
    files of PASSing tests that exist on disk -- parked tests in the second
    list only. The default-scope merge consumes the first list, the
    including-parked merge the two together; a FAILED or ERROR row is in
    neither, because a truncated database says nothing trustworthy about the
    code it stopped reaching."""
    parked = set(PARKED)
    default_paths, parked_paths = [], []
    for test, outcome, *_rest in results:
        if outcome != "PASS":
            continue
        ucdb = test_ucdb_path(tb, test, run_index, cfg)
        if not ucdb.is_file():
            continue
        (parked_paths if test in parked else default_paths).append(str(ucdb))
    return sorted(default_paths), sorted(parked_paths)


def write_ucdb_list(path, ucdb_paths):
    """Write one merge input list (a mk/uvmt/vsim.mk COV_MERGE_LIST file):
    absolute .ucdb paths, one per line. The file lives beside the merged
    database it feeds, so the request that produced a merged.ucdb can be read
    back next to it (make copies it to the directory's ucdb.list)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(str(p) + "\n" for p in ucdb_paths))
    return path


def merge_batch_coverage(tb, cfg, timeout, ucdb_list=None, merge_dir="merged"):
    """Merge a batch of per-test .ucdb files into
    vsim_results/<cfg>/<merge_dir>/merged.ucdb with `make MERGE=YES cov_merge`;
    return whether the merge actually ran.

    cov_merge, not cov: cov is one of Common.mk's TEST_YAML_PARSE_TARGETS, so
    it aborts without a TEST -- and a batch merge has no single test to name.
    cov_merge builds only the database; every report this harness publishes is
    generated from it by generate_coverage_reports() below, never by cov's
    in-tree vsim report.

    ucdb_list: file of .ucdb paths (write_ucdb_list()), passed to
    mk/uvmt/vsim.mk as COV_MERGE_LIST so the merge covers exactly those
    databases -- the same batch can then be merged twice, into two scopes,
    without an unrelated .ucdb on disk leaking into either number. None keeps
    the historical behaviour of merging every .ucdb found under the cfg, which
    is exactly what --merge-existing asks for.

    Unlike the per-test incremental merge this replaced, this runs once per
    batch after the worker pool has joined -- there is no concurrent vcover
    writer left to serialise against."""
    tbcfg = TESTBENCHES[tb]
    merge_dir_path = tbcfg["sim_dir"] / "vsim_results" / cfg / merge_dir
    # CFG names the results tree the mk merge searches when no COV_MERGE_LIST is
    # given (COV_MERGE_FIND walks $(SIM_CFG_RESULTS), and CFG ?= default there),
    # so without it --cfg NAME --merge-existing would merge NAME's output tree
    # full of default's .ucdb files.
    cmd = ["make", "MERGE=YES", f"CFG={cfg}",
           f"VSIM_COV_MERGE_DIR={merge_dir_path}"]
    if ucdb_list is not None:
        cmd.append(f"COV_MERGE_LIST={Path(ucdb_list).absolute()}")
    cmd = cmd + ["cov_merge"] + tbcfg["make_args"]
    env = make_env(tbcfg)
    try:
        returncode, _, stderr = _run(cmd, tbcfg["sim_dir"], env, timeout,
                                     capture=True)
    except subprocess.TimeoutExpired:
        with _print_lock:
            print(f"warning: coverage merge into {merge_dir} timed out after "
                  f"{timeout}s")
        return False
    except OSError as exc:
        with _print_lock:
            print(f"warning: could not launch coverage merge into "
                  f"{merge_dir}: {exc}")
        return False

    if returncode != 0:
        last = (stderr or "").strip().splitlines()
        with _print_lock:
            print(f"warning: coverage merge into {merge_dir} failed (exit "
                  f"{returncode}): {last[-1] if last else 'no output'}")
        return False
    return True


# Coverage metrics come from `vcover report -xml`, whose document is a flat list
# of per-scope rollups:
#
#     <coverage_report><code_coverage_report byInstance="1">
#       <instanceData path="/…/alu_i" du="cve2_alu">
#         <statements active="66" hits="64" percent="96.96"/>   <- per instance
#         <branches …/> <fec_conditions …/> <states …/> <transitions …/>
#         <assertion_successes …/> <cover_directives …/>
#       </instanceData>
#       <instanceData path="/uvme_cv32e20_pkg">
#         <cover_group_types active="109" hits="na" percent="0.00"/>
#         <coverpoints_crosses active="333" …/>                 <- per package
#         <cvgbins active="12695" hits="0" percent="0.00"/>
#       </instanceData>
#
# Both kinds of metric therefore come from one real data source. They used to be
# scraped out of the generated HTML report's files/overalldu.js, which can only
# ever report the scope that HTML was generated for, and whose 'fc' field counts
# the handful of cover *directives* in the RTL rather than the covergroup *bins*
# of the environment -- which is how the dashboard came to advertise 100%
# functional coverage while the env's bins sat at 0%. hits="na" shows up on
# metrics nothing hit and has to be tolerated.

# <element name> -> metric name, for the code rollups of one instance.
_CODE_ROLLUPS = (
    ("statements", "statement"),
    ("branches", "branch"),
    ("fec_conditions", "condition"),
    ("states", "fsm_state"),
    ("transitions", "fsm_transition"),
    ("assertion_successes", "assertion"),
    ("cover_directives", "cover_directive"),
)

# The five metrics OpenHW TRL5 asks for; "code" below is their unweighted mean.
_TRL5_METRICS = ("statement", "branch", "condition", "fsm_state", "fsm_transition")


def _rollup_int(value):
    """A Questa rollup count as int, or None when it does not apply ('na')."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _percent(hits, active):
    """Percentage of active items that were hit, or None when there are none (a
    scope without FSMs has no FSM coverage to report)."""
    return round(100.0 * hits / active, 2) if active else None


def _parse_questa_xml(xml_path):
    """Root of a Questa XML export, or None with a warning when unreadable."""
    try:
        return ET.parse(str(xml_path)).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f"warning: could not read {xml_path}: {exc}")
        return None


def parse_questa_code_rollup(xml_path, scope=None):
    """Sum the code-coverage rollups of a `vcover report -xml` export.

    scope (a hierarchy path, as passed to vcover's -instance) restricts the
    totals to that subtree, which is this project's code-coverage policy -- the
    testbench's own code is not the deliverable. Returns

        {metric: {"active": n, "hits": n, "percent": p}, …, "code": p}

    over _CODE_ROLLUPS plus the derived "code" average, or None when the export
    holds nothing in scope."""
    root = _parse_questa_xml(xml_path)
    if root is None:
        return None

    scope = scope.rstrip(".") if scope else None
    totals = dict((metric, [0, 0]) for _elem, metric in _CODE_ROLLUPS)
    for inst in root.iter("instanceData"):
        path = inst.get("path", "")
        if scope and not (path == scope or path.startswith(scope + "/")):
            continue
        for elem_name, metric in _CODE_ROLLUPS:
            node = inst.find(elem_name)
            if node is None:
                continue
            active = _rollup_int(node.get("active"))
            if active is None:
                continue
            totals[metric][0] += active
            totals[metric][1] += _rollup_int(node.get("hits")) or 0

    metrics = {}
    for metric, (active, hits) in totals.items():
        metrics[metric] = {"active": active, "hits": hits,
                           "percent": _percent(hits, active)}
    percents = [metrics[metric]["percent"] for metric in _TRL5_METRICS
                if metrics[metric]["percent"] is not None]
    if not percents:
        return None
    # Headline number for the dashboard: the average of the TRL5 code metrics,
    # which is what the scraped 'tc' field of the HTML report used to report.
    metrics["code"] = round(sum(percents) / len(percents), 2)
    return metrics


def parse_questa_functional_rollup(xml_path):
    """Covergroup-bin coverage of a `vcover report -xml` export, whole hierarchy.

    The covergroup rollups hang off one <instanceData> per package, whose path
    is the package itself (/uvme_cv32e20_pkg, …) -- always outside the DUT, so
    this export must not be instance-restricted. Returns

        {"bins_total": n, "bins_covered": n, "percent": p,
         "packages": {name: {"bins_total", "bins_covered", "percent"}}}

    or None when the export carries no covergroups."""
    root = _parse_questa_xml(xml_path)
    if root is None:
        return None

    packages = {}
    for inst in root.iter("instanceData"):
        node = inst.find("cvgbins")
        if node is None:
            continue
        active = _rollup_int(node.get("active"))
        if not active:
            continue
        hits = _rollup_int(node.get("hits")) or 0
        name = inst.get("path", "").strip("/") or "(unknown)"
        packages[name] = {"bins_total": active, "bins_covered": hits,
                          "percent": _percent(hits, active)}
    if not packages:
        return None

    total = sum(pkg["bins_total"] for pkg in packages.values())
    covered = sum(pkg["bins_covered"] for pkg in packages.values())
    return {"bins_total": total, "bins_covered": covered,
            "percent": _percent(covered, total), "packages": packages}


def copy_common_css(dest_dir):
    """Publish templates/common/style.css as <dest_dir>/common.css.

    Returns the destination path, or None when the template is missing (a
    warning is printed either way). Kept as its own function because there are
    two copy sites on purpose: this one for coverage_report/ and one in
    regression_report.publish() for coverage_report/regression/.
    """
    common_css = REPO / "templates" / "common" / "style.css"
    if not common_css.is_file():
        print(f"warning: shared stylesheet not found at {common_css}")
        return None
    dest = Path(dest_dir) / "common.css"
    shutil.copy(common_css, dest)
    return dest


# The analysis files the published page reads, relative to docs/coverage/. Kept
# as a module constant so a test can publish a smaller set. Not
# raw/holes_by_du.csv: that rollup is a count of the rows of holes.csv, the page
# recomputes it itself, and bin/coverage_holes.py writes it straight into the
# published tree rather than leaving it to be committed beside its own input.
COVERAGE_ANALYSIS_FILES = (
    "coverage_review.csv",
    "raw/waiver_audit.csv",
    "raw/holes.csv",
    "raw/holes_parked.csv",
    "raw/phase_c_acceptance.csv",
)

# What to tell whoever sees a dump missing. The sheet is generated from the
# dumps, the dumps are measurements: holes_parked.csv needs the second merged
# database of a --cov-report batch, and phase_c_acceptance.csv is read out of
# `vcover report -showexcluded` by hand (docs/coverage/README.md).
ANALYSIS_REGENERATED_BY = {
    "coverage_review.csv": "bin/coverage_review.py",
    "raw/waiver_audit.csv": "bin/coverage_waiver_audit.py",
    "raw/holes.csv": "bin/coverage_holes.py",
    # --ucdb is quoted with $PWD because coverage_holes.py resolves it inside
    # its own vsim session's directory, and --out because its default target is
    # the *default* dump this one must not overwrite (README step 1b).
    "raw/holes_parked.csv": "bin/coverage_holes.py --ucdb "
                            "\"$PWD/sim/uvmt/vsim_results/<cfg>/merged_parked/"
                            "merged.ucdb\" --apply-cov-tcl "
                            "--out docs/coverage/raw/holes_parked.csv",
    "raw/phase_c_acceptance.csv": "the vcover report recipe in "
                                  "docs/coverage/README.md",
}


def publish_coverage_analysis(dest_dir, source_root=None):
    """Mirror the committed coverage analysis into ``<dest_dir>/analysis/``.

    The originals live under docs/coverage/ because they are input to a review,
    not output of a run; they are mirrored into the published tree because that
    is where anyone looking for anything coverage-related goes, and the page
    this copies in alongside them fetches them by relative path. The mirror is
    regenerated with every report, never edited and never read back by python:
    the tools and the cite checker read docs/coverage/.

    source_root defaults to docs/coverage/ so a test can point it at a tree of
    its own. Each file is fail-soft on its own, because an analysis nobody has
    run yet is a warning naming the command that regenerates it, not a report
    worth losing. Returns the destination directory.
    """
    dest_dir = Path(dest_dir)
    source_root = REPO / "docs" / "coverage" if source_root is None else Path(source_root)
    analysis_dest = dest_dir / "analysis"

    published = 0
    for name in COVERAGE_ANALYSIS_FILES:
        source = source_root / name
        if not source.is_file():
            # Each dump names the tool that measured it -- only the sheet is
            # coverage_review.py's own output, and the Phase C rows come off
            # `vcover report -details` runs no script wraps. An absent dump is
            # a tool nobody has run on this tree, not a broken report; the
            # parked one in particular needs a second merged database.
            tool = ANALYSIS_REGENERATED_BY.get(name, "its tool (see the header)")
            print(f"warning: no coverage analysis at {source}; regenerate it "
                  f"with {tool} (docs/coverage/README.md)")
            continue
        # One mkdir per file, so a set without any raw dump does not leave an
        # empty raw/ directory behind.
        (analysis_dest / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, analysis_dest / name)
        published += 1

    # The page that reads them. Templates missing says so and keeps the CSVs:
    # a downloadable sheet is still worth publishing without the viewer.
    page_templates = REPO / "templates" / "analysis_dashboard"
    if (page_templates / "index.html").is_file():
        analysis_dest.mkdir(parents=True, exist_ok=True)
        for name in ("index.html", "style.css"):
            shutil.copy(page_templates / name, analysis_dest / name)
        copy_common_css(analysis_dest)
        print(f"Coverage analysis page copied to {analysis_dest}/")
    else:
        print(f"warning: analysis page templates not found at {page_templates}/")

    if published:
        print(f"Coverage analysis mirrored to {analysis_dest}/ ({published} "
              f"of {len(COVERAGE_ANALYSIS_FILES)} file(s))")
    return analysis_dest


def read_merged_test_names(merge_dir):
    """The tests one merged database was built from, read back from the
    ucdb.list that vcover merge consumed (written into the merge directory by
    mk/uvmt/vsim.mk). [] without a list -- the dashboard renders an absent set
    rather than an invented one."""
    listing = Path(merge_dir) / "ucdb.list"
    if not listing.is_file():
        return []
    names = [Path(line.strip()).stem
             for line in listing.read_text(errors="replace").splitlines()
             if line.strip()]
    return sorted(set(names))


def _disclose_unchecked_pairing(label, merge_dir, source, reason):
    """Say that a recovered pairing went unchecked, rather than saying nothing.

    The shapes of unknown -- a database with no input list, a summary that
    recorded no test names -- share one consequence: the counts about to be
    published beside this database were never compared against it. Silence
    reads as a clean bill of health, which is the opposite of true."""
    print(f"warning: cannot check the {label} merged database against "
          f"{source}: {Path(merge_dir) / 'merged.ucdb'} -- {reason}")


def _compare_names_with_database(label, recovered_names, merge_dir, source):
    """Warn when one recovered set of test names and one merge input list disagree.

    The input list is the only record of what a merged database holds, so it is
    what any recovered set of counts has to be measured against. A difference
    does not by itself prove two batches -- ``batch_ucdb_lists()`` leaves out a
    PASSing test whose ``.ucdb`` never reached the disk, and ``--merge-existing``
    merges every ``.ucdb`` the results tree holds, parked and leftover included
    -- so both benign causes are named next to the two lists rather than the
    reader being told which batch they came from. A database with no list beside
    it is the other shape of unknown: not agreeing, simply unrecorded."""
    listing = Path(merge_dir) / "ucdb.list"
    merged = set(read_merged_test_names(merge_dir))
    if not merged:
        # An absent list and an empty one both mean nothing to compare, but
        # they do not mean the same thing happened: write_ucdb_list() can
        # produce either, and only one of them says the merge took no input.
        if (Path(merge_dir) / "merged.ucdb").is_file():
            if listing.is_file():
                _disclose_unchecked_pairing(
                    label, merge_dir, source,
                    f"{listing} is empty, so nothing records which batch built "
                    "it (--cov-report writes one line per merged test).")
            else:
                _disclose_unchecked_pairing(
                    label, merge_dir, source,
                    "no input list was written beside it, so nothing records "
                    "which batch built it (--cov-report writes ucdb.list next "
                    "to the database when it merges).")
        return
    if merged == recovered_names:
        return
    print(f"warning: the recovered verdicts and the {label} merged database "
          f"list different tests: {source} counts {len(recovered_names)} as "
          f"PASS, {listing} lists {len(merged)} (recovered-only: "
          f"{', '.join(sorted(recovered_names - merged)) or 'none'}; "
          f"database-only: {', '.join(sorted(merged - recovered_names)) or 'none'}). "
          "A PASSing test that left no .ucdb on disk, or a --merge-existing "
          "merge of every .ucdb in the tree, move the two lists apart the "
          "same way; anything else is two batches, and only a fresh "
          "--cov-report run publishes counts and metrics from one of them.")


def warn_recovered_vs_databases(rows, merged_dir, merged_parked_dir):
    """Warn when recovered verdicts and merged databases are not one batch.

    Every uvmt batch rewrites the regression document, while the merged
    databases survive until the next --cov-report wipes them, so a --report-only
    run after an unrelated batch would publish one batch's pass counts beside
    another batch's coverage metrics. The merge input lists are the only record
    of what each database holds, so the document's PASS rows are compared to
    them, scope by scope. Both sides stay true of their own batch, so this warns
    rather than withholding the report -- but never silently."""
    _compare_names_with_database(
        "default",
        {row.get("name") for row in rows
         if row.get("verdict") == "PASS" and not row.get("parked")},
        merged_dir, "the regression document")
    _compare_names_with_database(
        "including-parked",
        {row.get("name") for row in rows if row.get("verdict") == "PASS"},
        merged_parked_dir, "the regression document")


def warn_summary_vs_databases(prev, merged_dir, merged_parked_dir):
    """The same provenance check for the summary.json fallback.

    A summary recovered from summary.json pairs that publish's counts with the
    databases now on disk, and summary.json records the names those databases
    were built from -- ``test_sets`` is read out of the very ``ucdb.list`` files
    below -- so the comparison costs nothing here either. A summary written
    before ``test_sets`` existed can say nothing, and does."""
    recorded = prev.get("test_sets") or {}
    default_names = set(recorded.get("default") or [])
    parked_names = set(recorded.get("parked") or [])
    if not default_names and not parked_names:
        # Nothing recorded -- an older summary, or a publish whose databases had
        # no input list to read. Comparing an empty set would say "counts 0 as
        # PASS", which is a worse lie than silence, so the pairing is disclosed
        # as unchecked instead -- and never silently agreed.
        for label, merge_dir in (("default", merged_dir),
                                 ("including-parked", merged_parked_dir)):
            if (Path(merge_dir) / "merged.ucdb").is_file():
                _disclose_unchecked_pairing(
                    label, merge_dir, "the published summary",
                    "it recorded no test names (test_sets is empty), so the "
                    "counts recovered from it are tied to no database")
        return
    _compare_names_with_database("default", default_names, merged_dir,
                                 "the published summary")
    # test_sets stores the parked side as just the parked names, while the
    # parked database is the default list plus those: the union is what its own
    # input list has to agree with.
    _compare_names_with_database("including-parked", default_names | parked_names,
                                 merged_parked_dir, "the published summary")


EXTERNAL_REPOS_MK = Path("sim") / "ExternalRepos.mk"


def parse_external_repos(path):
    """Variable -> value for every live (uncommented) 'VAR ?= value' line of a
    sim/ExternalRepos.mk. The commented rollback entries are meant to stay
    invisible here: a report must publish the pin that was actually used."""
    pins = {}
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return pins
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"^(\w+)\s*\?=\s*(\S+)", stripped)
        if m:
            pins[m.group(1)] = m.group(2)
    return pins


def _git_output(cwd, *args):
    """Trimmed git stdout, or None when git -- or the checkout -- is
    unavailable. Every version the report publishes is best-effort: a source
    tarball has no .git, and inventing a hash would defeat the point."""
    try:
        completed = subprocess.run(["git", *args], cwd=str(cwd), timeout=20,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return (completed.stdout or "").strip()


def collect_versions(repo=None):
    """Where a report's sources come from, per component.

    Returns {component: {repo, branch, pinned_hash, actual_hash, clean,
    matches_pin}} for the three checkouts a coverage number depends on: this
    repository, the CVE2 RTL (core-v-cores/cv32e20) and the vendored
    core-v-verif library (vendor_lib/openhwgroup_core-v-verif). pinned_hash is
    what sim/ExternalRepos.mk asks for, actual_hash and clean what is actually
    on disk; the pair is the direct guard against a runner compiling a silently
    stale RTL, which mis-aims every line-number waiver in cov.tcl. This
    repository has no pin of its own (repo/branch come from its git,
    matches_pin stays null); a component that was never cloned reports
    actual_hash "not cloned". Follows the git_meta()/simulator_meta() pattern
    of bin/regression_report.py."""
    repo = Path(repo) if repo is not None else REPO
    pins = parse_external_repos(repo / EXTERNAL_REPOS_MK)
    components = [
        ("cv32e20-dv", repo, None),
        ("cve2", repo / "core-v-cores" / "cv32e20", "CV_CORE"),
        ("core-v-verif", repo / "vendor_lib" / "openhwgroup_core-v-verif",
         "CV_VERIF"),
    ]
    versions = {}
    for name, checkout, prefix in components:
        entry = {"repo": None, "branch": None, "pinned_hash": None,
                 "actual_hash": None, "clean": None, "matches_pin": None}
        if prefix:
            entry["repo"] = pins.get(f"{prefix}_REPO")
            entry["branch"] = pins.get(f"{prefix}_BRANCH")
            entry["pinned_hash"] = pins.get(f"{prefix}_HASH")
        head = (_git_output(checkout, "rev-parse", "HEAD")
                if checkout.is_dir() else None)
        if head is None:
            entry["actual_hash"] = "not cloned"
            versions[name] = entry
            continue
        entry["actual_hash"] = head
        # An empty porcelain listing is the whole answer for "clean": no
        # output means the tree matches the commit.
        status = _git_output(checkout, "status", "--porcelain")
        entry["clean"] = (not status) if status is not None else None
        if prefix is None:
            # This repository is not pinned: report what it *is*.
            entry["repo"] = _git_output(checkout, "remote", "get-url",
                                        "origin")
            entry["branch"] = _git_output(checkout, "rev-parse",
                                          "--abbrev-ref", "HEAD")
        else:
            # Vendored checkouts sit on the pinned commit detached, so the
            # pinned branch is the honest label; the checkout state above is
            # what says whether it really is that commit.
            entry["matches_pin"] = bool(entry["pinned_hash"]) and head.startswith(
                entry["pinned_hash"])
        versions[name] = entry
    return versions


def build_including_parked_summary(code_metrics, functional, passed_count,
                                   total_count):
    """The including_parked block of summary.json: the same metric keys as the
    top level, computed from the including-parked database and its pass/fail
    counts, so the dashboard renders either view through one code path.
    code_metrics and functional may be None (an export that failed), which
    lands as the same N/A zeros the default scope uses for a missing
    database; total_count 0 keeps pass_rate at 0, never None."""
    pass_rate = (passed_count / total_count * 100) if total_count else 0
    block = {
        "code_coverage": code_metrics["code"] if code_metrics else "N/A",
        "functional_coverage": (functional["percent"]
                                if functional else "N/A"),
        "bins_covered": functional["bins_covered"] if functional else 0,
        "bins_total": functional["bins_total"] if functional else 0,
        "functional_packages": functional["packages"] if functional else {},
        "code_metrics": ({metric: value for metric, value in code_metrics.items()
                          if metric != "code"} if code_metrics else {}),
        "pass_rate": round(pass_rate, 2),
        "total_tests": total_count,
        "passed": passed_count,
        "failed": total_count - passed_count,
    }
    if code_metrics:
        block.update(
            {f"{key}_coverage": (code_metrics[metric]["percent"]
                                 if code_metrics[metric]["percent"] is not None
                                 else "N/A")
             for key, metric in (("line", "statement"),
                                 ("condition", "condition"),
                                 ("branch", "branch"),
                                 ("fsm_state", "fsm_state"),
                                 ("fsm_transition", "fsm_transition"))})
    return block


def generate_coverage_reports(tb, cfg, results, timeout, clean=False):
    """Publish the full coverage-report artifact set from merged.ucdb and write
    sim/uvmt/test_results.log; returns (passed_count, total_count) as recorded in
    coverage_report/summary.json.

    results: this batch's (test, outcome, detail, gen_seed, run_seed) tuples, or
    None when nothing was executed (--report-only), in which case the pass/fail
    counts are recovered from sim/uvmt/regression_results.json -- the authority
    on this run's verdicts, whose rows carry the parked flag -- falling back to
    an existing coverage_report/summary.json, rather than reported as 0/0. Every coverage step is guarded on merged.ucdb actually
    existing, so a batch in which everything failed (or that never ran) still
    produces the dashboard plus summary.json, with N/A metrics.

    The top-level summary keys describe the default scope: rows for PARKED
    tests never move them -- they only ever contribute to the including_parked
    block (and the regression document), computed from the batch's second
    merged database, merged_parked/merged.ucdb, when that exists.

    clean: wipe coverage_report/ first, so no artifact of a previous run survives
    into the published set.

    Every step is independent and fail-soft: a missing merged.ucdb, a vcover
    invocation that fails, or a template that is not checked out all print a
    warning and leave the rest of the artifact set in place, because a partial
    report is still worth publishing and the dashboard renders an absent
    artifact as N/A (and hides the button that would have opened it)."""
    tbcfg = TESTBENCHES[tb]
    sim_dir = tbcfg["sim_dir"]
    cov_instance = tbcfg["cov_instance"]
    report_dest_root = REPO / "coverage_report"
    log_file_abs = sim_dir / "test_results.log"
    merged_ucdb = sim_dir / "vsim_results" / cfg / "merged" / "merged.ucdb"
    merged_dir = merged_ucdb.parent
    merged_parked_dir = sim_dir / "vsim_results" / cfg / "merged_parked"
    merged_parked_ucdb = merged_parked_dir / "merged.ucdb"
    summary_json_path = report_dest_root / "summary.json"

    # Pass/fail counts: from this batch, or recovered from the previous one.
    # Top-level counts are the default scope -- parked rows move only the
    # including_parked block; with no parked tests in the batch both views
    # count the same rows anyway.
    parked_names = set(PARKED)
    if results is None:
        # The regression document first: its rows name every test that ran with
        # its verdict and its parked flag, so both views recover. The published
        # summary.json only knows the default-scope counts (an older one may
        # not even carry an including_parked block), so it is the fallback for
        # a tree where the document was never written.
        passed_count = total_count = 0
        parked_view = (0, 0)
        recovered_from = None
        doc_path = sim_dir / regression_report.DOCUMENT_NAME
        doc = None
        if doc_path.is_file():
            try:
                doc = json.loads(doc_path.read_text())
            except (OSError, ValueError) as exc:
                print(f"warning: could not read {doc_path}: {exc}")
        if (doc and doc.get("tests") and doc.get("tb") == tb
                and doc.get("cfg") == cfg):
            rows = doc["tests"]
            main_rows = [r for r in rows if not r.get("parked")]
            passed_count = sum(1 for r in main_rows
                               if r.get("verdict") == "PASS")
            total_count = len(main_rows)
            parked_view = (sum(1 for r in rows
                               if r.get("verdict") == "PASS"), len(rows))
            recovered_from = doc_path.name
            warn_recovered_vs_databases(rows, merged_dir, merged_parked_dir)
        else:
            prev = {}
            if summary_json_path.is_file():
                try:
                    prev = json.loads(summary_json_path.read_text())
                except (OSError, ValueError) as exc:
                    print(f"warning: could not read {summary_json_path}: {exc}")
            passed_count = prev.get("passed", 0)
            total_count = prev.get("total_tests", 0)
            prev_parked = prev.get("including_parked") or {}
            parked_view = (prev_parked.get("passed", 0),
                           prev_parked.get("total_tests", 0))
            if prev:
                # Any summary read is a pairing with the databases on disk. The
                # counts used to gate this, so a summary whose only numbers
                # were the parked block published beside them unchecked.
                recovered_from = summary_json_path.name
                warn_summary_vs_databases(prev, merged_dir, merged_parked_dir)
        log_lines = ["Tests skipped. Using recovered metrics from previous run."]
        parked_note = (f", {parked_view[0]}/{parked_view[1]} including parked"
                       if parked_view[1] else "")
        source_note = f" from {recovered_from}" if recovered_from else ""
        print(f"Recovered previous test results: {passed_count}/{total_count} "
              f"passed{parked_note}{source_note}.")
    else:
        main_rows = [r for r in results if r[0] not in parked_names]
        passed_count = sum(1 for r in main_rows if r[1] == "PASS")
        total_count = len(main_rows)
        parked_view = (sum(1 for r in results if r[1] == "PASS"), len(results))
        status = {"PASS": "PASSED", "FAIL": "FAILED"}
        log_lines = [f"{test}: {status.get(outcome, outcome)}"
                     for test, outcome, _detail, _gen, _run, _dur in results]

    if clean and report_dest_root.exists():
        shutil.rmtree(report_dest_root)
        print(f"Removed previous report directory {report_dest_root}")
    report_dest_root.mkdir(parents=True, exist_ok=True)

    # Questa XML exports: the machine-readable source of every number below and
    # of the Cobertura and UCIS conversions. Three of them, because the two
    # coverage policies have different scopes:
    #
    #   merged.questasim.xml  whole hierarchy -> covergroup bins (functional)
    #   dut_rollup.xml        DUT instance    -> code and TRL5 metrics
    #   dut_detail.xml        DUT instance    -> per-file/per-line Cobertura
    #
    # The functional one must stay unrestricted: the environment's covergroups
    # live in packages outside the DUT, so restricting it reports the RTL's cover
    # directives instead (see parse_questa_functional_rollup). The -details
    # exports are converter input rather than browsable reports -- the covergroup
    # detail runs to tens of megabytes -- so they land next to the .ucdb instead
    # of in the published coverage_report/.
    questa_xml_path = report_dest_root / "merged.questasim.xml"
    dut_rollup_path = report_dest_root / "dut_rollup.xml"
    dut_detail_path = merged_dir / "dut_detail.xml"
    cvg_detail_path = merged_dir / "cvg_detail.xml"
    cobertura_path = report_dest_root / "cobertura.xml"
    ucis_xml_path = report_dest_root / "merged.ucis.xml"

    code_metrics = None
    functional = None
    if merged_ucdb.is_file():
        print("Exporting Questa XML coverage reports ...")
        for destination, options in (
            (questa_xml_path, ["-xml"]),
            (dut_rollup_path, ["-xml", f"-instance={cov_instance}."]),
            (dut_detail_path, ["-xml", "-details", "-code", "scb",
                               f"-instance={cov_instance}."]),
            (cvg_detail_path, ["-xml", "-details", "-cvg"]),
        ):
            returncode, _, stderr = _run(
                ["vcover", "report"] + options + ["-output", str(destination),
                                                  str(merged_ucdb)],
                sim_dir, None, timeout, capture=True)
            if returncode != 0:
                last = (stderr or "").strip().splitlines()
                print(f"  warning: failed to export {destination.name} "
                      f"(exit {returncode}): {last[-1] if last else 'no output'}")

        code_metrics = parse_questa_code_rollup(dut_rollup_path, cov_instance)
        functional = parse_questa_functional_rollup(questa_xml_path)
        if code_metrics:
            print(f"  code coverage (DUT-scoped): {code_metrics['code']}% -- "
                  + ", ".join(
                      f"{metric} {code_metrics[metric]['hits']}"
                      f"/{code_metrics[metric]['active']}"
                      f"={code_metrics[metric]['percent']}%"
                      for metric in _TRL5_METRICS))
        else:
            print("  warning: no code coverage in the DUT scope")
        if functional:
            print(f"  functional coverage (full hierarchy): {functional['percent']}% "
                  f"of {functional['bins_total']} covergroup bins in "
                  f"{len(functional['packages'])} packages")
        else:
            print("  warning: no covergroup coverage found in the export")

        # Vendor-neutral formats, both converted out of the Questa XML above.
        print("Generating vendor-neutral coverage formats ...")
        if generate_cobertura_xml(str(dut_detail_path), str(cobertura_path),
                                  rollup_path=str(dut_rollup_path),
                                  scope=cov_instance):
            print(f"  Cobertura XML generated: {cobertura_path}")
        else:
            print("  warning: failed to generate Cobertura XML")
        if generate_ucis_xml(str(questa_xml_path), str(ucis_xml_path),
                             detail_path=str(dut_detail_path),
                             cvg_detail_path=str(cvg_detail_path),
                             ucdb_name=str(merged_ucdb)):
            print(f"  UCIS XML generated: {ucis_xml_path}")
        else:
            print("  warning: failed to generate UCIS XML")
    else:
        print("warning: merged UCDB not found, coverage metrics and "
              "vendor-neutral formats not generated")

    # Questa HTML report. `make cov` leaves it inside the sim tree; publish a
    # copy at the top level so GitHub Pages can serve it as-is.
    report_dest_questasim = report_dest_root / "questasim"
    if merged_ucdb.is_file():
        print(f"Generating HTML coverage report in {report_dest_questasim} ...")
        # -html takes no positional output directory (that is read as a second
        # ucdb); the scope/flags mirror `make cov`'s own vcover invocation.
        returncode, _, stderr = _run(["vcover", "report", "-html", "-details",
                                      "-precision", "2", "-annotate",
                                      f"-instance={cov_instance}.",
                                      "-output", str(report_dest_questasim),
                                      str(merged_ucdb)],
                                     sim_dir, None, timeout, capture=True)
        if returncode != 0:
            print(f"  warning: failed to generate HTML report: {(stderr or '').strip()}")
        else:
            print("  HTML report generated successfully")
    else:
        print("warning: merged UCDB not found, HTML report not generated")

    # Functional-Coverage-only HTML report, for the dashboard's second button.
    # -cvg and deliberately no -instance: this is the covergroup-bin number of
    # the whole hierarchy, environment included, and scoping it to the DUT would
    # silently turn it into the RTL's cover-directive count (see the invariant
    # in the module docstring). Same fail-soft contract as its sibling above --
    # without it the Functional Coverage button is simply hidden.
    report_dest_questasim_func = report_dest_root / "questasim_func"
    if merged_ucdb.is_file():
        print(f"Generating functional coverage HTML report in "
              f"{report_dest_questasim_func} ...")
        returncode, _, stderr = _run(["vcover", "report", "-html", "-details",
                                      "-precision", "2", "-cvg",
                                      "-output", str(report_dest_questasim_func),
                                      str(merged_ucdb)],
                                     sim_dir, None, timeout, capture=True)
        if returncode != 0:
            print(f"  warning: failed to generate functional coverage HTML "
                  f"report: {(stderr or '').strip()}")
        else:
            print("  functional coverage HTML report generated successfully")
    else:
        print("warning: merged UCDB not found, functional coverage HTML report "
              "not generated")

    # Including-parked view: the same metric set computed from the batch's
    # second merged database (the default scope plus the PARKED tests), and
    # the two detail trees behind that view's buttons -- same scopes as their
    # default-scope twins above, which is what lets the dashboard's toggle
    # swap one set for the other. Fail-soft in the same way: no parked
    # database simply means no including_parked block in summary.json, the
    # dashboard then hides the toggle, and an old published report renders
    # exactly as it always did.
    parked_summary = None
    if merged_parked_ucdb.is_file():
        print("Exporting including-parked coverage metrics "
              f"({merged_parked_ucdb}) ...")
        parked_xml = merged_parked_dir / "merged.questasim.xml"
        parked_rollup = merged_parked_dir / "dut_rollup.xml"
        for destination, options in (
            (parked_xml, ["-xml"]),
            (parked_rollup, ["-xml", f"-instance={cov_instance}."]),
        ):
            returncode, _, stderr = _run(
                ["vcover", "report"] + options + ["-output", str(destination),
                                                  str(merged_parked_ucdb)],
                sim_dir, None, timeout, capture=True)
            if returncode != 0:
                last = (stderr or "").strip().splitlines()
                print(f"  warning: failed to export {destination.name} "
                      f"(exit {returncode}): {last[-1] if last else 'no output'}")
        parked_code = parse_questa_code_rollup(parked_rollup, cov_instance)
        parked_functional = parse_questa_functional_rollup(parked_xml)

        for html_dest, options in (
            (report_dest_root / "questasim_parked",
             ["-html", "-details", "-precision", "2", "-annotate",
              f"-instance={cov_instance}."]),
            (report_dest_root / "questasim_func_parked",
             ["-html", "-details", "-precision", "2", "-cvg"]),
        ):
            returncode, _, stderr = _run(
                ["vcover", "report"] + options
                + ["-output", str(html_dest), str(merged_parked_ucdb)],
                sim_dir, None, timeout, capture=True)
            if returncode != 0:
                print(f"  warning: failed to generate {html_dest.name}: "
                      f"{(stderr or '').strip()}")

        parked_pass, parked_total = parked_view
        parked_summary = build_including_parked_summary(
            parked_code, parked_functional, parked_pass, parked_total)
    else:
        print(f"No including-parked merged database ({merged_parked_ucdb}); "
              "summary.json carries the default scope only")

    # Dashboard shell that reads summary.json; copied unconditionally so even a
    # run without coverage data publishes something browsable.
    dashboard_templates = REPO / "templates" / "coverage_dashboard"
    if (dashboard_templates / "index.html").is_file():
        shutil.copy(dashboard_templates / "index.html", report_dest_root / "index.html")
        shutil.copy(dashboard_templates / "style.css", report_dest_root / "style.css")
        print("Dashboard templates copied to coverage_report/")
    else:
        print(f"warning: dashboard templates not found at {dashboard_templates}/")

    # The stylesheet the two dashboards share. It is published *into each*
    # directory rather than referenced across them, because the regression
    # dashboard lives in coverage_report/regression/ and the Pages artifact
    # preserves those paths: regression_report.py copies the same file one
    # directory down, so both pages use the same href="common.css".
    copy_common_css(report_dest_root)

    # The waiver / open-hole analysis lives under docs/ (it is input to a
    # review, not output of a run); this mirrors the whole of it, sheet and raw
    # dumps, into coverage_report/analysis/ next to the page that reads it.
    publish_coverage_analysis(report_dest_root)

    # TRL5 metrics: the five code metrics of the DUT scope, read out of
    # dut_rollup.xml. 'condition' is Questa's own condition metric
    # (<fec_conditions> rollups); it used to be filled with the scraped
    # functional number, which made the two dashboard cards agree by
    # construction.
    trl5_metrics = None
    if code_metrics:
        trl5_metrics = {metric: (code_metrics[metric]["percent"]
                                 if code_metrics[metric]["percent"] is not None
                                 else "N/A")
                        for metric in _TRL5_METRICS}
        print("TRL5 coverage metrics (DUT-scoped):")
        for metric in _TRL5_METRICS:
            print(f"  {metric}: {trl5_metrics[metric]}%")
    else:
        print("warning: no DUT-scoped code coverage, TRL5 metrics not available")

    if trl5_metrics:
        trl5_json_path = report_dest_root / "trl5_metrics.json"
        trl5_json_path.write_text(json.dumps({
            "line_coverage": trl5_metrics.get("statement", "N/A"),
            "condition_coverage": trl5_metrics.get("condition", "N/A"),
            "branch_coverage": trl5_metrics.get("branch", "N/A"),
            "fsm_state_coverage": trl5_metrics.get("fsm_state", "N/A"),
            "fsm_transition_coverage": trl5_metrics.get("fsm_transition", "N/A"),
        }, indent=4))
        print(f"TRL5 coverage metrics saved to {trl5_json_path}")

    # sim/uvmt/test_results.log: plain-text pass/fail list, kept for continuity
    # with the artifacts previous CI iterations published.
    pass_rate = (passed_count / total_count * 100) if total_count else 0
    with open(log_file_abs, "w") as f:
        f.write("UVM Test Results\n================\n")
        for line in log_lines:
            f.write(line + "\n")
        f.write(f"\nSummary: {passed_count}/{total_count} tests passed "
                f"({pass_rate:.2f}%).\n")
    print(f"Results saved to {log_file_abs}")

    # summary.json drives the dashboard's cards and its TRL badge.
    summary_data = {
        # Code coverage stays DUT-scoped; functional coverage is the real
        # covergroup-bin number over the whole hierarchy, environment included.
        # Each card labels its scope, and the raw counts ride along so the
        # dashboard can say "6 183 / 45 942 bins" instead of a bare percent.
        "code_coverage": code_metrics["code"] if code_metrics else "N/A",
        "code_scope": f"DUT-scoped ({cov_instance})",
        "functional_coverage": functional["percent"] if functional else "N/A",
        "functional_scope": "full hierarchy (env covergroups included)",
        "bins_covered": functional["bins_covered"] if functional else 0,
        "bins_total": functional["bins_total"] if functional else 0,
        "functional_packages": functional["packages"] if functional else {},
        "code_metrics": ({metric: value for metric, value in code_metrics.items()
                          if metric != "code"} if code_metrics else {}),
        "pass_rate": round(pass_rate, 2),
        "total_tests": total_count,
        "passed": passed_count,
        "failed": total_count - passed_count,
    }
    # trl5_metrics is derived from code_metrics above, so the two are consistent;
    # without a merged .ucdb there are no numbers and everything stays N/A.
    if trl5_metrics:
        summary_data.update({
            "line_coverage": trl5_metrics.get("statement", "N/A"),
            "condition_coverage": trl5_metrics.get("condition", "N/A"),
            "branch_coverage": trl5_metrics.get("branch", "N/A"),
            "fsm_state_coverage": trl5_metrics.get("fsm_state", "N/A"),
            "fsm_transition_coverage": trl5_metrics.get("fsm_transition", "N/A"),
        })
    else:
        summary_data.update({
            "line_coverage": "N/A",
            "condition_coverage": "N/A",
            "branch_coverage": "N/A",
            "fsm_state_coverage": "N/A",
            "fsm_transition_coverage": "N/A",
        })
    if parked_summary is not None:
        summary_data["including_parked"] = parked_summary
    # Which tests each database actually holds, read back from the ucdb.list
    # files vcover merge consumed: the published names then cannot disagree
    # with the databases, because both are read from the same file. A tree with
    # no input list publishes two empty sets, which means unrecorded rather
    # than empty -- warn_summary_vs_databases() reads it that way and says the
    # pairing went unchecked. The keys themselves always ship: the Pages
    # validation step in .github/workflows/coverage.yml requires test_sets.
    summary_data["test_sets"] = {
        "default": read_merged_test_names(merged_dir),
        "parked": sorted(set(read_merged_test_names(merged_parked_dir))
                         & parked_names),
    }
    # Where this report's sources come from: the dashboard's Build Versions
    # table and footer timestamp. Metadata only -- nothing gates on it, and a
    # component without git renders as such rather than as a placeholder.
    summary_data["generated"] = regression_report.now()
    simulator = regression_report.simulator_meta("uvmt")
    summary_data["simulator"] = (simulator or {}).get("version")
    summary_data["versions"] = collect_versions()
    summary_json_path.write_text(json.dumps(summary_data, indent=4))
    print(f"Summary metrics saved to {summary_json_path}")

    return passed_count, total_count


_CERTIFY_SUMMARY_RE = re.compile(r"TOTAL=(\d+)\s+PASS=(\d+)\s+FAIL=(\d+)")


CERTIFY_SUMMARY = Path("test_program") / "certification_summary.txt"


def certify_summary_path(seed):
    """Location of certification_summary.txt (certify hardwires
    TEST=certification, so this path isn't parameterized by tb/test/cfg)."""
    return core_results_dir("certification") / str(seed) / CERTIFY_SUMMARY


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


def run_certify(seed, timeout, quiet, spike_tandem=False, filter_=None):
    """Run `make certify` (the ACT4 compliance-ELF sweep) with one seed for
    every ELF ('random' resolved here); return (outcome, detail, seed_used).
    Unlike run_test(), one `make` invocation runs every ELF and self-reports
    to certification_summary.txt (see classify_certify_summary()).

    spike_tandem: SPIKE_TANDEM=1 -- see the certify target's own comment in
    sim/core/Makefile for why +elf_file ordering matters there.
    filter_: passed through as FILTER=... to narrow the ELF scan.
    """
    tbcfg = TESTBENCHES["core"]
    env = make_env(tbcfg)
    seed = resolve_seed(seed)
    cmd = ["make", "certify", f"SEED={seed}"]
    if spike_tandem:
        cmd.append("SPIKE_TANDEM=1")
    if filter_:
        cmd.append(f"FILTER={filter_}")
    cmd += tbcfg["make_args"]

    try:
        returncode, stdout, stderr = _run(cmd, tbcfg["sim_dir"], env, timeout, capture=True)
    except subprocess.TimeoutExpired:
        return "ERROR", f"timed out after {timeout}s", seed
    except OSError as exc:
        return "ERROR", f"could not launch make: {exc}", seed

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

    summary_path = certify_summary_path(seed)
    if not summary_path.is_file() and returncode != 0:
        return "ERROR", f"make certify exited {returncode} (no summary written)", seed
    if returncode != 0 and "No .elf files found" in stdout:
        return "ERROR", (f"make certify exited {returncode}: no compliance "
                          "ELFs found -- run `make gen` or `make gen-certify` "
                          "in sim/core first"), seed
    return (*classify_certify_summary(summary_path), seed)


def main(argv=None):
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
    ap.add_argument("--testlist", metavar="PATH", default=None,
                    help="run the regression testlist in PATH (a regress/*.yaml "
                         "file, see 'Regression testlists' below): it selects "
                         "the tests and may set tb, cfg, timeout, jobs, seed and "
                         "per-test make args. An option given on the command "
                         "line still wins over the file. Cannot be combined "
                         "with test names, --all-custom, --corev-dv-only, "
                         "--certify, --include-parked or --include-corev-dv, "
                         "because the file is the selection.")
    ap.add_argument("--parse-only", action="store_true",
                    help="do not run; just parse existing logs in the results "
                         "directory (core: every <test>/<seed>/ found, one "
                         "row each, or only --seed N's)")
    ap.add_argument("--cfg", default="default",
                    help="uvmt config subdirectory under vsim_results (default: "
                         "default). Only 'default' is exercised end to end: the "
                         "per-test make invocations do not pass CFG=, so another "
                         "value selects a results directory without building "
                         "that configuration.")
    ap.add_argument("--timeout", type=int, default=1800,
                    help="per-test timeout in seconds (default: 1800; the "
                         "interrupt-heavy corev-dv templates routinely take "
                         "10-15 minutes including compile)")
    ap.add_argument("--gen-seed", default="random",
                    help="SEED for the corev-dv generation step (gen_corev-dv; "
                         "the random-instruction-stream generator). 'random' "
                         "(default) or a literal value to replay a specific "
                         "prior run -- see --seed, a fully independent "
                         "knob (gen_corev-dv and test are separate UVM "
                         "environments/vsim invocations, each seeded "
                         "separately). No effect on non-corev-dv tests.")
    ap.add_argument("--seed", type=seed_arg, default=None,
                    help="seed for the test run itself (env-level "
                         "randomization, e.g. OBI stall knobs): an integer "
                         f"1..{MAX_SEED}, or 'random' for a fresh seed per "
                         f"test (default: {DEFAULT_SEED}). Applies to every "
                         "test, on both testbenches. core results go in "
                         "simulation_results/<test>/<seed>/, overwriting a "
                         "previous run with the same seed. With --parse-only, "
                         "selects which seed's results to read (default: all).")
    ap.add_argument("--cov", action="store_true",
                    help="collect code coverage (uvmt only; equivalent to "
                         "`make test ... COV=1` per test). Requires "
                         "sim/tools/vsim/cov.tcl to exist, or Questa silently "
                         "collects nothing. The report targets that consume "
                         "the resulting .ucdb (cov, cov_txt, cov_holes, "
                         "cov_holes_details) live in mk/uvmt/vsim.mk.")
    ap.add_argument("--cov-report", action="store_true",
                    help="implies --cov, and additionally merges this batch's "
                         "PASSing .ucdb files into vsim_results/<cfg>/merged/"
                         "merged.ucdb (plus the PARKED tests into the sibling "
                         "merged_parked/ database) and publishes the full report "
                         "artifact set under coverage_report/ (uvmt only; "
                         "requires --tb uvmt). Tests that did not PASS are not "
                         "merged -- see --merge-existing.")
    ap.add_argument("--all-custom", action="store_true",
                    help="select every directory under TESTS_ROOTS "
                         "(tests/programs/custom, tests/programs/corev-dv) "
                         "instead of the curated lists. PARKED and corev-dv names are "
                         "skipped unless --include-parked / --include-corev-dv also ask "
                         "for them (a --cov-report batch asks for PARKED on its own, "
                         "for the including-parked report), and DISCOVERY_EXCLUDES is "
                         "always skipped. Cannot be combined with test names or "
                         "--corev-dv-only")
    ap.add_argument("--merge-existing", action="store_true",
                    help="run no simulation: merge every selected test that already has "
                         "a .ucdb on disk (verdicts re-parsed from their existing logs, "
                         "as with --parse-only), then regenerate the reports (uvmt only)")
    ap.add_argument("--report-only", action="store_true",
                    help="run nothing and merge nothing: regenerate coverage_report/ "
                         "from the merged .ucdb already on disk, recovering the "
                         "pass/fail counts from the published regression document "
                         "(sim/uvmt/regression_results.json), falling back to the "
                         "previous summary.json (uvmt only). Warns when the "
                         "recovered PASS rows and the merged databases' input "
                         "lists name different tests, and whenever a pairing "
                         "goes unchecked (no input list beside a merged "
                         "database, or a summary recording no test names) -- "
                         "the metrics always come from the databases. Always "
                         "exits 0 -- no test was run to gate on.")
    ap.add_argument("--clean-report", action="store_true",
                    help="delete coverage_report/ before regenerating it (a --cov-report "
                         "run wipes it, and the merged .ucdb, on its own)")
    ap.add_argument("--allow-failures", action="store_true",
                    help="exit 0 even if some selected tests FAIL or ERROR (the "
                         "per-test verdicts are still printed and summarized). Use "
                         "this when a downstream step (e.g. publishing coverage "
                         "reports) must run regardless of the test outcome. Genuine "
                         "setup failures -- 'make comp_corev-dv'/'make comp' errors, "
                         "no tests selected, missing sim directory -- still exit "
                         "non-zero.")
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

    args = ap.parse_args(argv)

    # A testlist is loaded before anything else validates the options, because
    # it can name the testbench itself ('--tb uvmt' would otherwise be required
    # for a regress/*.yaml that says tb: uvmt). Precedence is command line >
    # file > built-in default, which means only the options still sitting at
    # their parser default are taken from the file.
    testlist_meta, testlist_entries = None, None
    if args.testlist:
        testlist_meta, testlist_entries = load_testlist(args.testlist)
        for key in ("tb", "cfg", "timeout", "jobs", "seed"):
            value = testlist_meta.get(key)
            if value is None or getattr(args, key) != ap.get_default(key):
                continue
            if key == "tb" and value not in TESTBENCHES:
                ap.error(f"{testlist_meta['path']}: unknown tb '{value}' "
                         f"(choose from {', '.join(sorted(TESTBENCHES))})")
            if key == "seed":
                try:
                    value = seed_arg(str(value))
                except argparse.ArgumentTypeError as exc:
                    ap.error(f"{testlist_meta['path']}: bad seed: {exc}")
            setattr(args, key, value)
        print(f"Testlist {testlist_meta['path']}: {testlist_meta['name']} -- "
              f"{len(testlist_entries)} test(s)")

    if args.jobs < 1:
        ap.error("--jobs must be >= 1")

    if args.parse_only and args.seed == "random":
        ap.error("--seed random has no meaning with --parse-only (give a "
                  "specific seed, or omit --seed to report every seed)")
    # Runs default to DEFAULT_SEED; --parse-only without --seed reads every
    # seed directory, so keep None there.
    seed = DEFAULT_SEED if args.seed is None else args.seed

    if args.cov and args.tb != "uvmt":
        ap.error("--cov requires --tb uvmt (Questa coverage; the core "
                  "Verilator testbench has no COV support)")

    # The merge/report pipeline is Questa- and therefore uvmt-only throughout.
    cov_pipeline = args.cov_report or args.merge_existing or args.report_only
    if cov_pipeline and args.tb != "uvmt":
        ap.error("--cov-report/--merge-existing/--report-only require --tb uvmt "
                  "(Questa coverage data; the core Verilator testbench writes no "
                  ".ucdb and has no vcover to merge it with)")
    if args.cov_report:
        # Collecting the per-test .ucdb files is a precondition of merging them.
        args.cov = True
    if args.report_only and (args.parse_only or args.merge_existing):
        ap.error("--report-only cannot be combined with --parse-only or "
                  "--merge-existing (--report-only neither runs nor merges)")
    if args.all_custom and (args.tests or args.corev_dv_only):
        ap.error("--all-custom cannot be combined with test names or --corev-dv-only")
    if args.testlist and (args.tests or args.all_custom or args.corev_dv_only
                          or args.certify or args.include_parked
                          or args.include_corev_dv):
        ap.error("--testlist cannot be combined with test names, --all-custom, "
                 "--corev-dv-only, --certify, --include-parked or "
                 "--include-corev-dv (the testlist file is the selection)")
    # Neither of these launches a simulation.
    no_exec = args.merge_existing or args.report_only

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

    if testlist_entries is not None:
        # The file is ordered (a quick smoke test before a long one) and every
        # entry is already known to name a real test-program directory.
        selected = [entry["name"] for entry in testlist_entries]
    elif args.corev_dv_only:
        if args.tests or args.include_parked or args.include_corev_dv:
            ap.error("--corev-dv-only cannot be combined with test names, "
                      "--include-parked, or --include-corev-dv")
        selected = list(COREV_DV_TESTS)
    elif args.all_custom:
        selected = discover_all_custom()
        if args.include_parked:
            selected += PARKED
        if args.include_corev_dv:
            selected += COREV_DV_TESTS
        if args.cov_report and not args.include_parked:
            # A coverage batch owns both dashboard views: the PARKED tests run
            # for the including-parked database even when the caller did not
            # spell out --include-parked. Only PASSes are ever merged, so a
            # parked failure can only ever lower the parked view -- which is
            # why CI can add them unconditionally behind --allow-failures.
            print("note: --cov-report also runs the parked tests "
                  "(including-parked report)")
            selected += PARKED
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

    if not selected:
        # --all-custom on an empty/missing TESTS_ROOTS would otherwise blow up on
        # the summary-table width computation below.
        sys.exit("error: no tests selected")

    sim_dir = TESTBENCHES[args.tb]["sim_dir"]
    if not sim_dir.is_dir():
        sys.exit(f"error: sim directory for --tb {args.tb} not found at {sim_dir}")

    # A --cov-report regression starts from a clean slate: merged.ucdb is keyed
    # on *every* .ucdb mk/uvmt/vsim.mk finds under the cfg, so leftover per-test
    # data from earlier runs would otherwise leak into the published numbers.
    clean_report = args.clean_report
    if args.cov_report and not no_exec:
        cfg_results = sim_dir / "vsim_results" / args.cfg
        # Every merge input of a previous batch goes, not just the merge
        # outputs: the published numbers are only reproducible if the merged
        # databases hold exactly this batch, and a leftover per-test .ucdb (an
        # old parked run, say) is otherwise indistinguishable from a fresh one.
        for stale in sorted(cfg_results.rglob("*.ucdb")):
            stale.unlink()
        for stale_name in ("merged", "merged_parked"):
            stale_dir = cfg_results / stale_name
            if stale_dir.exists():
                shutil.rmtree(stale_dir)
                print(f"Removed stale merged coverage directory {stale_dir}")
        clean_report = True

    if args.report_only:
        passed, total_ran = generate_coverage_reports(
            args.tb, args.cfg, None, args.timeout, clean=clean_report)
        print(f"\n{passed}/{total_ran} test(s) passed in the run these "
              "reports describe")
        # Nothing was executed here, so there is nothing to gate on.
        sys.exit(0)

    if args.spike_tandem and not args.parse_only:
        setup_spike_lib(args.tb, args.timeout)

    if args.certify:
        # Own fixed ELF sweep -- short-circuit the rest of main().
        action = "Parsing" if args.parse_only else "Running"
        print(f"[{action}/core] certify"
              + (" (spike-tandem)" if args.spike_tandem else "")
              + (f" FILTER={args.filter}" if args.filter else "") + " ...")
        if args.parse_only:
            dirs = seed_dirs(core_results_dir("certification"),
                             CERTIFY_SUMMARY, args.seed)
            if dirs:
                runs = [(*classify_certify_summary(d / CERTIFY_SUMMARY), d.name)
                        for d in dirs]
            else:
                runs = [("ERROR", "no certification summary found",
                         args.seed if args.seed is not None else "-")]
        else:
            runs = [run_certify(seed, args.timeout, args.quiet,
                                spike_tandem=args.spike_tandem,
                                filter_=args.filter)]
        print()
        for outcome, detail, seed in runs:
            print(f"certify (seed {seed}): {outcome} {detail}".rstrip())
        sys.exit(0 if all(r[0] == "PASS" for r in runs) else 1)

    needs_corev_dv = any(is_corev_dv(test) for test in selected)
    if needs_corev_dv and not (args.parse_only or no_exec):
        if args.tb != "uvmt":
            sys.exit("error: corev-dv tests require --tb uvmt")
        setup_corev_dv(args.tb, args.timeout)

    extra_make_args = []
    if args.jobs > 1 and not (args.parse_only or no_exec):
        if args.tb == "uvmt":
            # One-time compile so the batch below can pass COMP=NO safely --
            # see the module docstring's "Concurrency" section.
            setup_comp(args.tb, args.timeout, cov=args.cov)
            extra_make_args = ["COMP=NO"]
        else:
            print(f"warning: --jobs {args.jobs} with --tb core has not been "
                  "verified race-free against the shared Verilator build "
                  "directory (sim/core/simulation_results/cobj_dir); "
                  "proceeding anyway, but "
                  "prefer --jobs 1 unless you've confirmed it's safe.")

    # Per-test make args from the testlist (e.g. CVE2_CONFIG=CV32E20X for a
    # core built with an extension interface). Combined with, not replacing,
    # the batch-level args -- COMP=NO from setup_comp() has to survive.
    per_test_make_args = {}
    if testlist_entries is not None:
        for entry in testlist_entries:
            extra = list(testlist_meta.get("make_args") or []) + entry["make_args"]
            if extra:
                per_test_make_args[entry["name"]] = extra

    descriptions = dict((entry["name"], entry["description"])
                        for entry in (testlist_entries or [])
                        if entry["description"])
    # --merge-existing contributes to the merge only; verdicts still come from
    # the logs of whatever ran before. Hoisted out of run_one() because the
    # published document at the end of main() has to know whether this batch
    # timed anything at all.
    just_parse = args.parse_only or args.merge_existing
    started = regression_report.now()

    def run_one(test):
        """Rows (test, outcome, detail, gen_seed, run_seed, duration) for one
        test -- several when --parse-only finds more than one seed directory."""
        action = "Parsing" if just_parse else "Running"
        with _print_lock:
            print(f"[{action}/{args.tb}] {test} ...")
        start = time.monotonic()
        if just_parse:
            rows = parse_only(args.tb, test, args.cfg, args.seed)
        else:
            rows = [run_test(
                args.tb, test, args.cfg,
                args.timeout, args.quiet,
                extra_make_args=(extra_make_args
                                 + per_test_make_args.get(test, [])),
                label=test if args.jobs > 1 else None,
                gen_seed=args.gen_seed, seed=seed,
                cov=args.cov, spike_tandem=args.spike_tandem)]
        # Nothing is measured when a verdict is read back out of an old log, and
        # an unmeasured duration is null rather than 0 -- see regression_report.
        duration = None if just_parse else round(time.monotonic() - start, 1)

        # The .ucdb files are merged once, after the whole batch, from an
        # explicit list of this batch's PASSes -- see the "Coverage reports"
        # section of the module docstring and merge_batch_coverage().

        if args.jobs > 1:
            done = "Parsed" if just_parse else "Done"
            with _print_lock:
                for outcome, detail, _, _ in rows:
                    print(f"[{done}/{args.tb}] {test}: {outcome} {detail}".rstrip())
        return [(test, *row, duration) for row in rows]

    width = max(len(t) for t in selected)
    if args.jobs == 1:
        per_test = [run_one(test) for test in selected]
    else:
        outcomes = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = {pool.submit(run_one, test): test for test in selected}
            for future in concurrent.futures.as_completed(futures):
                outcomes[futures[future]] = future.result()
        # Report in the original --selected order regardless of completion order.
        per_test = [outcomes[test] for test in selected]
    results = [row for rows in per_test for row in rows]

    # GEN_SEED is "-" for non-corev-dv tests (no generate step -- see
    # run_test()); RUN_SEED is populated for every test now. Either column
    # can still show "-" if extract_seed() couldn't find a banner (e.g. a
    # build failure before the run ever printed one).
    def _fmt_seed(s):
        return s if s is not None else "-"

    def _fmt_duration(seconds):
        return "-" if seconds is None else f"{seconds:g}s"

    gen_width = max([len("GEN_SEED")] + [len(_fmt_seed(r[3])) for r in results])
    run_width = max([len("RUN_SEED")] + [len(_fmt_seed(r[4])) for r in results])
    time_width = max([len("TIME")] + [len(_fmt_duration(r[5])) for r in results])
    header = (f"{'TEST'.ljust(width)}   RESULT   "
              f"{'GEN_SEED'.ljust(gen_width)}   {'RUN_SEED'.ljust(run_width)}   "
              f"{'TIME'.ljust(time_width)}   DETAIL")
    sep_width = len(header)

    print()
    print("=" * sep_width)
    print(f"testbench: {args.tb}")
    print("-" * sep_width)
    print(header)
    print("-" * sep_width)
    counts = {"PASS": 0, "FAIL": 0, "ERROR": 0}
    for test, outcome, detail, gen_seed, run_seed, duration in results:
        counts[outcome] = counts.get(outcome, 0) + 1
        print(f"{test.ljust(width)}   {outcome:<6}   "
              f"{_fmt_seed(gen_seed).ljust(gen_width)}   "
              f"{_fmt_seed(run_seed).ljust(run_width)}   "
              f"{_fmt_duration(duration).ljust(time_width)}   {detail}")
    print("=" * sep_width)
    total = len(results)
    print(f"{total} test(s): {counts['PASS']} passed, "
          f"{counts['FAIL']} failed, {counts['ERROR']} error(s)")

    # Deterministic, batch-scoped merges: write each scope's input list from
    # this batch's PASSing .ucdb files, then merge each scope into its own
    # database. --merge-existing has no batch of its own to scope by -- it
    # merges whatever is already on disk -- so it keeps the historical
    # default-scope find merge and produces no including-parked database.
    if args.cov_report and not no_exec:
        default_paths, parked_paths = batch_ucdb_lists(
            results, args.tb, args.cfg)
        cfg_results = sim_dir / "vsim_results" / args.cfg
        if default_paths:
            request = cfg_results / "merged" / "ucdb.request"
            write_ucdb_list(request, default_paths)
            merge_batch_coverage(args.tb, args.cfg, args.timeout,
                                 ucdb_list=request, merge_dir="merged")
        else:
            print("warning: no PASSing test with a .ucdb in this batch; "
                  "no default-scope merge")
        if parked_paths:
            request = cfg_results / "merged_parked" / "ucdb.request"
            write_ucdb_list(request, sorted(default_paths + parked_paths))
            merge_batch_coverage(args.tb, args.cfg, args.timeout,
                                 ucdb_list=request, merge_dir="merged_parked")
        print(f"Merged coverage: {len(default_paths)} test(s) in merged/, "
              f"{len(default_paths) + len(parked_paths)} in merged_parked/")
    elif args.merge_existing:
        merge_batch_coverage(args.tb, args.cfg, args.timeout)

    # Reports last, so a coverage run publishes exactly what this batch scored.
    if cov_pipeline:
        print()
        generate_coverage_reports(args.tb, args.cfg, results, args.timeout,
                                  clean=clean_report)

    # The regression dashboard goes out after the coverage report on purpose:
    # a --cov-report run wipes coverage_report/ before it starts, and publishing
    # into coverage_report/regression/ before that would delete the page again.
    # Publishing is reporting, not gating -- a dashboard that could not be
    # written must not change what this batch's exit code says about the tests.
    # Nothing is timed when the verdicts were read back out of existing logs, so
    # the window between two now() calls in the same second is not this
    # regression's wall time: publishing "0.0s" underneath a 100% pass rate is
    # the invented number this whole report exists to avoid (see the "Never
    # invent a number" note in bin/regression_report.py). The window goes null
    # together with the per-test durations and the dashboard renders N/A.
    measure_window = not just_parse
    try:
        document = regression_document(
            args.tb, args.cfg, results,
            testlist=testlist_meta["path"] if testlist_meta else None,
            started=started if measure_window else None,
            finished=regression_report.now() if measure_window else None,
            descriptions=descriptions)
        regression_report.publish(document, REPO / "coverage_report" / "regression")
        # A second copy next to the logs this document describes, so a machine
        # can pick up the run without the published report tree.
        regression_report.write_document(document, sim_dir / regression_report.DOCUMENT_NAME)
    except (OSError, ValueError) as exc:
        print(f"warning: could not publish the regression results: {exc}")

    # Exit non-zero unless everything ran and passed -- which is also what makes
    # a --cov-report batch usable as the CI gate. --allow-failures downgrades a
    # failing batch to exit 0 so downstream report/publish steps still run.
    if counts["PASS"] != total and args.allow_failures:
        print(f"\nnote: {counts['FAIL']} failed, {counts['ERROR']} error(s); "
              "exit code forced to 0 by --allow-failures")
        sys.exit(0)
    sys.exit(0 if counts["PASS"] == total else 1)


if __name__ == "__main__":
    main()
