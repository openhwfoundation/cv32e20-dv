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

#CV_CORE_REPO   ?= https://github.com/openhwgroup/cve2
#CV_CORE_BRANCH ?= main
#CV_CORE_HASH   ?= d079e8c
CV_CORE_REPO   ?= https://github.com/MikeOpenHWGroup/cve2
CV_CORE_BRANCH ?= cs_registers
CV_CORE_HASH   ?= 094e974


#CV_VERIF_REPO   ?= https://github.com/openhwgroup/core-v-verif
#CV_VERIF_BRANCH ?= cv32e20-dv/dev
#CV_VERIF_HASH   ?= 6b5a46353bf69baf4f917b9d59c5f0c68a2f529b
CV_VERIF_REPO   ?= https://github.com/MikeOpenHWGroup/core-v-verif
CV_VERIF_BRANCH ?= cv32e20-dv/dev
CV_VERIF_HASH   ?= b6c814799d14b8d235e80ca9d7088e3f82f0c550

RISCVDV_REPO    ?= https://github.com/google/riscv-dv
RISCVDV_BRANCH  ?= master
RISCVDV_HASH    ?= 0b625258549e733082c12e5dc749f05aefb07d5a

EMBENCH_REPO    ?= https://github.com/embench/embench-iot.git
EMBENCH_BRANCH  ?= master
EMBENCH_HASH    ?= 6934ddd1ff445245ee032d4258fdeb9828b72af4

COMPLIANCE_REPO   ?= https://github.com/riscv/riscv-compliance
COMPLIANCE_BRANCH ?= master
# 2020-08-19
COMPLIANCE_HASH   ?= c21a2e86afa3f7d4292a2dd26b759f3f29cde497

# SVLIB
SVLIB_REPO       ?= https://bitbucket.org/verilab/svlib/src/master/svlib
SVLIB_BRANCH     ?= master
SVLIB_HASH       ?= c25509a7e54a880fe8f58f3daa2f891d6ecf6428

# ACT4 (RISC-V Architectural Certification Tests)
ACT4_REPO   ?= https://github.com/riscv/riscv-arch-test
ACT4_BRANCH ?= act4
ACT4_HASH   ?= head
