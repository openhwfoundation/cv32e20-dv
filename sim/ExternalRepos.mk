###############################################################################
# Variables to generate the command to clone external repositories.
# For each repo there are a set of variables:
#      *_REPO:   URL to the repository (note, not all are in GitHub).
#      *_BRANCH: Name of the branch you wish to clone;
#                Set to 'master' to pull the master branch.
#      *_HASH:   Value of the specific hash you wish to clone;
#                Set to 'head' to pull the head of the branch you want.
#

export SHELL = /bin/bash

CV_CORE_REPO   ?= https://github.com/openhwfoundation/cve2
CV_CORE_BRANCH ?= main
CV_CORE_HASH   ?= d7f2156

CV_VERIF_REPO   ?= https://github.com/openhwfoundation/core-v-verif
CV_VERIF_BRANCH ?= cv32e20-dv/dev
CV_VERIF_HASH   ?= c525ca3

RISCVDV_REPO    ?= https://github.com/google/riscv-dv
RISCVDV_BRANCH  ?= master
RISCVDV_HASH    ?= 0b625258549e733082c12e5dc749f05aefb07d5a

# This Spike repo is only cloned when the DPI disassembler needs to be rebuilt
# Typically users can simply use the checked-in shared library
DPI_DASM_SPIKE_REPO   ?= https://github.com/riscv/riscv-isa-sim.git
DPI_DASM_SPIKE_BRANCH ?= master
DPI_DASM_SPIKE_HASH   ?= 8faa928819fb551325e76b463fc0c978e22f5be3

# SVLIB
SVLIB_REPO       ?= https://bitbucket.org/verilab/svlib/src/master/svlib
SVLIB_BRANCH     ?= master
SVLIB_HASH       ?= c25509a7e54a880fe8f58f3daa2f891d6ecf6428

# ACT4 (RISC-V Architectural Certification Tests)
ACT4_REPO   ?= https://github.com/riscv/riscv-arch-test
ACT4_BRANCH ?= act4
ACT4_HASH   ?= head

###############################################################################
# The following repos are no longer actively used
EMBENCH_REPO    ?= https://github.com/embench/embench-iot.git
EMBENCH_BRANCH  ?= master
EMBENCH_HASH    ?= 6934ddd1ff445245ee032d4258fdeb9828b72af4

COMPLIANCE_REPO   ?= https://github.com/riscv/riscv-compliance
COMPLIANCE_BRANCH ?= master
# 2020-08-19
COMPLIANCE_HASH   ?= c21a2e86afa3f7d4292a2dd26b759f3f29cde497
