###############################################################################
#
# Copyright 2020,2022 OpenHW Group
#
# Licensed under the Solderpad Hardware Licence, Version 2.1 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://solderpad.org/licenses/
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
#
###############################################################################
#
# Makefile for the CV32E20 UVM testbench.
#
###############################################################################

# "Constants"
# TODO: unify CORE_V_VERIF and CV32E20_DV into single variable (perhaps CV_DV?).
MAKE                  = make
MAKE_PATH            := $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))
export CORE_V_VERIF   = $(abspath $(MAKE_PATH)/../..)
export CV32E20_DV     = $(abspath $(MAKE_PATH)/../..)
export CV_CORE       ?= cv32e20

export CV_SW_MARCH   = rv32imc_zicsr_zifencei
CV_SW_TOOLCHAIN      ?= /opt/riscv
CV_SW_PREFIX         ?= riscv32-corev-elf-

CORE_DEFINES         = +define+CV32E20_RVFI+RVFI

UVM_VERBOSITY        ?= UVM_LOW

USER_RUN_FLAGS       ?= +scoreboard_enable=1 +UVM_VERBOSITY=$(UVM_VERBOSITY) +report_file=$(TEST).yaml

ISS ?= SPIKE

include ../ExternalRepos.mk
include $(CV32E20_DV)/mk/uvmt/uvmt.mk
