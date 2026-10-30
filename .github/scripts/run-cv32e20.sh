#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# run-cv32e20.sh - run cv32e20-dv Verilator simulation from an ELF file
#
# Wrapper that makes <base>.hex via objcopy, then runs the sim. Called once per
# ELF by the ACT4 harness, which appends the ELF path as the final argument.
#
# Usage:
#   run-cv32e20.sh [--elf] <elf-file>
#
# Environment:
#   CVE20_DV_ROOT  - path to the cv32e20-dv checkout (default: derived from this
#                    script's location, two levels up from .github/scripts/)
#   CV_SW_PREFIX   - RISC-V toolchain prefix (default: riscv64-unknown-elf-)
#   SIM_TIMEOUT    - wall-clock cap passed to coreutils `timeout` (default: 120s;
#                    hung tests exit 124 instead of blocking the harness)
set -euo pipefail

ELF=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --elf) [[ $# -ge 2 ]] || {
                   echo "--elf requires a path" >&2
                   echo "Usage: run-cv32e20.sh [--elf] <elf-file>" >&2
                   exit 2
               }
               ELF="$2"; shift 2 ;;
        -*)    echo "Unknown argument: $1" >&2
               echo "Usage: run-cv32e20.sh [--elf] <elf-file>" >&2
               exit 2 ;;
        *)     ELF="$1"; shift ;;
    esac
done

: "${ELF:?ELF file is required (pass --elf <file> or as final positional argument)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CVE20_DV_ROOT="${CVE20_DV_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
CV_SW_PREFIX="${CV_SW_PREFIX:-riscv64-unknown-elf-}"
SIM_TIMEOUT="${SIM_TIMEOUT:-120s}"

[[ -f "$CVE20_DV_ROOT/sim/core/Makefile" ]] || {
    echo "CVE20_DV_ROOT does not look like a cv32e20-dv checkout: $CVE20_DV_ROOT" >&2
    echo "Set CVE20_DV_ROOT explicitly." >&2
    exit 2
}

SIM="$CVE20_DV_ROOT/sim/core/simulation_results/verilator_executable"

[[ -x "$SIM" ]] || {
    echo "verilator_executable not found at $SIM" >&2
    echo "Build it with: make certify (or make verilate) in $CVE20_DV_ROOT/sim/core/" >&2
    exit 2
}

# Generate <base>.hex if missing or older than the ELF. Split path before
# stripping the extension so a dot in a directory component does not truncate.
ELF_DIR="${ELF%/*}"
ELF_BASE="${ELF##*/}"
HEX="$ELF_DIR/${ELF_BASE%.*}.hex"
if [[ ! -f "$HEX" || "$ELF" -nt "$HEX" ]]; then
    "${CV_SW_PREFIX}objcopy" -O verilog "$ELF" "$HEX"
fi

exec timeout "$SIM_TIMEOUT" "$SIM" "+test_program=$HEX"
