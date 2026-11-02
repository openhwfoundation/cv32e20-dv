// SPDX-License-Identifier: Apache-2.0 WITH SHL-2.1
//
// Copyright (c) 2026 Eclipse Foundation
//
// Licensed under the Solderpad Hardware Licence, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://solderpad.org/licenses/
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

`ifndef __UVME_RV32ISA_COVG_DRV_SV__
`define __UVME_RV32ISA_COVG_DRV_SV__


/**
 * Drives uvmt_cv32e20_isa_covg_if from the RVFI instruction stream.
 *
 * That interface used to be filled by the reference-ISS wrapper which has since
 * been removed from this testbench, so uvme_rv32isa_covg never saw another
 * instruction and every covergroup in it stayed empty. The RVFI retire stream
 * (which the environment already taps for uvma_isacov) carries the same
 * information; this component rebuilds the `ins_t` record the coverage model
 * expects from it, decoding with the same Spike disassembler library
 * uvma_isacov_mon_c uses (lib/dpi_dasm). Its DPI imports are reached through
 * the uvma_isacov_pkg scope: uvmc_rvfi_scoreboard_pkg declares the very same
 * names, so an unqualified call would be ambiguous in this package.
 *
 * Note that the vendored Spike build keeps underscores in the few multi word
 * mnemonics it knows ("fence_i"), which the coverage model spells with a dot;
 * write() converts.
 *
 * The record follows what uvme_rv32isa_covg was written against:
 *
 *   ins_str    mnemonic. The vendored Spike build has its pseudo-instruction
 *              decompositions commented out, so 32-bit instructions arrive with
 *              their canonical name and only the names of sample()'s non
 *              compressed branch are used. Compressed instructions are handed
 *              over under their *decompressed* name, because
 *              check_compressed() is the one picking the c.* covergroup, out of
 *              the mnemonic and the operand shapes.
 *   ops[]      operands as text, in the order each covergroup indexes them:
 *              registers as ABI names, immediates as decimal, branch and jump
 *              targets as the absolute target address in hex (that is what
 *              get_pc_imm() subtracts the PC from), CSRs by name.
 *   pc         the instruction's own PC.
 *
 * Instructions the coverage model cannot bin - undecodable encodings, extensions
 * it has no covergroups for, CSRs its get_csr_name() does not know - are dropped
 * instead of triggered: sample() and get_csr_name() only warn about them, once
 * per retirement, and an operand-less record would land in an unrelated bin.
 */
class uvme_rv32isa_covg_drv_c extends uvm_subscriber #(uvma_rvfi_instr_seq_item_c#(ILEN,XLEN));

   uvme_cv32e20_cntxt_c  cntxt;

   `uvm_component_utils(uvme_rv32isa_covg_drv_c)

   extern function new(string name="uvme_rv32isa_covg_drv", uvm_component parent=null);
   extern function void build_phase(uvm_phase phase);
   extern virtual function void write(uvma_rvfi_instr_seq_item_c#(ILEN,XLEN) t);

   extern function bit decode(inout ins_t ins, input bit [63:0] insn, input bit [31:0] pc);
   extern function bit decode_rvc(inout ins_t ins, input bit [31:0] insn, input bit [31:0] pc);
   extern function string gpr_name(bit [4:0] rnum);
   extern function string csr_name(bit [11:0] cnum);
   extern function string dec_imm(longint value);
   extern function string imm20_str(bit [31:0] imm);
   extern function string target_str(bit [31:0] pc, longint offset);

endclass : uvme_rv32isa_covg_drv_c


function uvme_rv32isa_covg_drv_c::new(string name="uvme_rv32isa_covg_drv", uvm_component parent=null);
   super.new(name, parent);
endfunction : new


function void uvme_rv32isa_covg_drv_c::build_phase(uvm_phase phase);
   super.build_phase(phase);

   void'(uvm_config_db#(uvme_cv32e20_cntxt_c)::get(this, "", "cntxt", cntxt));
   if (cntxt == null) begin
      `uvm_fatal("RV32ISACOVGDRV", "No cntxt object passed to model")
   end
   if (cntxt.isa_covg_vif == null) begin
      `uvm_fatal("RV32ISACOVGDRV", "No uvmt_cv32e20_isa_covg_if in the context")
   end

   // Same configuration uvma_isacov_mon_c applies. The Spike disassembler is a
   // process wide singleton, so this is idempotent and keeps this driver working
   // even with the isacov agent turned off.
   uvma_isacov_pkg::dasm_set_config(32, "rv32imc", 0);
endfunction : build_phase


function void uvme_rv32isa_covg_drv_c::write(uvma_rvfi_instr_seq_item_c#(ILEN,XLEN) t);
   ins_t      ins;
   bit [63:0] insn;
   string     name;

   insn           = {32'b0, t.insn};
   name           = uvma_isacov_pkg::dasm_name(insn);
   ins.compressed = (t.insn[1:0] != 2'b11);
   ins.pc         = t.pc_rdata;

   // Spike separates words of a mnemonic with an underscore ("fence_i"),
   // the coverage model spells them with a dot ("fence.i").
   foreach (name[i]) begin
      if (name[i] == "_") name[i] = ".";
   end
   ins.ins_str = name;

   if (!decode(ins, insn, t.pc_rdata)) begin
      `uvm_info("RV32ISACOVGDRV", $sformatf("0x%08x: %s not covered", t.pc_rdata, name), UVM_FULL)
      return;
   end

   `uvm_info("RV32ISACOVGDRV", $sformatf("0x%08x: %s", t.pc_rdata, ins.ins_str), UVM_FULL)

   cntxt.isa_covg_vif.ins = ins;
   -> cntxt.isa_covg_vif.ins_valid;
endfunction : write


/**
 * Operand placement follows how uvme_rv32isa_covg indexes ops[]: R type
 * rd,rs1,rs2 -- I type ALU rd,rs1,imm -- loads rd,imm,rs1 -- stores rs2,imm,rs1
 * -- branches rs1,rs2,target -- jal rd,target -- jalr rd,imm,rs1 -- CSR
 * rd,csr,rs1|zimm. Returns 0 for anything the model has no covergroup for.
 */
function bit uvme_rv32isa_covg_drv_c::decode(inout ins_t ins, input bit [63:0] insn, input bit [31:0] pc);
   bit [4:0] rd, rs1, rs2;
   string    csr;

   if (ins.compressed) begin
      return decode_rvc(ins, insn[31:0], pc);
   end

   rd  = uvma_isacov_pkg::dasm_rd(insn);
   rs1 = uvma_isacov_pkg::dasm_rs1(insn);
   rs2 = uvma_isacov_pkg::dasm_rs2(insn);

   case (ins.ins_str)
      // loads and stores: the "imm(rs)" memory operand splits in two
      "lb", "lbu", "lh", "lhu", "lw" : begin
         ins.ops[0] = '{key:"R", val: gpr_name(rd)};
         ins.ops[1] = '{key:"C", val: dec_imm(uvma_isacov_pkg::dasm_i_imm(insn))};
         ins.ops[2] = '{key:"R", val: gpr_name(rs1)};
      end
      "sb", "sh", "sw" : begin
         ins.ops[0] = '{key:"R", val: gpr_name(rs2)};
         ins.ops[1] = '{key:"C", val: dec_imm(uvma_isacov_pkg::dasm_s_imm(insn))};
         ins.ops[2] = '{key:"R", val: gpr_name(rs1)};
      end

      // ALU operations
      "add", "sub", "and", "or", "xor", "sll", "srl", "sra", "slt", "sltu",
      "mul", "mulh", "mulhu", "mulhsu", "div", "divu", "rem", "remu" : begin
         ins.ops[0] = '{key:"R", val: gpr_name(rd)};
         ins.ops[1] = '{key:"R", val: gpr_name(rs1)};
         ins.ops[2] = '{key:"R", val: gpr_name(rs2)};
      end
      "addi", "andi", "ori", "xori", "slti", "sltiu" : begin
         ins.ops[0] = '{key:"R", val: gpr_name(rd)};
         ins.ops[1] = '{key:"R", val: gpr_name(rs1)};
         ins.ops[2] = '{key:"C", val: dec_imm(uvma_isacov_pkg::dasm_i_imm(insn))};
      end
      "slli", "srli", "srai" : begin
         ins.ops[0] = '{key:"R", val: gpr_name(rd)};
         ins.ops[1] = '{key:"R", val: gpr_name(rs1)};
         ins.ops[2] = '{key:"C", val: dec_imm(uvma_isacov_pkg::dasm_shamt(insn))};
      end
      // The model bins the 20 bit U immediate, not the sign extended address
      // offset the disassembler returns.
      "lui", "auipc" : begin
         ins.ops[0] = '{key:"R", val: gpr_name(rd)};
         ins.ops[1] = '{key:"C", val: imm20_str(uvma_isacov_pkg::dasm_u_imm(insn))};
      end

      // Control transfer: the model derives the PC relative offset itself, so
      // it gets the absolute target address.
      "beq", "bne", "blt", "bge", "bltu", "bgeu" : begin
         ins.ops[0] = '{key:"R", val: gpr_name(rs1)};
         ins.ops[1] = '{key:"R", val: gpr_name(rs2)};
         ins.ops[2] = '{key:"C", val: target_str(pc, uvma_isacov_pkg::dasm_sb_imm(insn))};
      end
      "jal" : begin
         ins.ops[0] = '{key:"R", val: gpr_name(rd)};
         ins.ops[1] = '{key:"C", val: target_str(pc, uvma_isacov_pkg::dasm_uj_imm(insn))};
      end
      "jalr" : begin
         ins.ops[0] = '{key:"R", val: gpr_name(rd)};
         ins.ops[1] = '{key:"C", val: dec_imm(uvma_isacov_pkg::dasm_i_imm(insn))};
         ins.ops[2] = '{key:"R", val: gpr_name(rs1)};
      end

      // CSR accesses: get_csr_name() has no numeric fallback.
      "csrrw", "csrrs", "csrrc" : begin
         csr = csr_name(uvma_isacov_pkg::dasm_csr(insn));
         if (csr == "") return 0;
         ins.ops[0] = '{key:"R", val: gpr_name(rd)};
         ins.ops[1] = '{key:"C", val: csr};
         ins.ops[2] = '{key:"R", val: gpr_name(rs1)};
      end
      "csrrwi", "csrrsi", "csrrci" : begin
         csr = csr_name(uvma_isacov_pkg::dasm_csr(insn));
         if (csr == "") return 0;
         ins.ops[0] = '{key:"R", val: gpr_name(rd)};
         ins.ops[1] = '{key:"C", val: csr};
         ins.ops[2] = '{key:"C", val: dec_imm(uvma_isacov_pkg::dasm_iorw(insn))};
      end

      // No operands of interest
      "fence", "fence.i", "ecall", "ebreak", "mret", "dret", "wfi" : ;

      default : return 0;
   endcase

   return 1;
endfunction : decode


/**
 * RV32C. The disassembler keeps the compressed names ("c.addi", ...) and does
 * not decompress, but check_compressed() selects the c.* covergroup from the
 * decompressed mnemonic and the operand shapes, so that is what goes in the
 * record. The operand order is the one of the 32-bit instruction it maps to
 * (loads rd,imm,rs1 and stores rs2,imm,rs1, base register last, which is how
 * check_compressed() tells c.lw from c.lwsp).
 *
 * rs1'/rd'/rs2' come straight out of the instruction word: bits [9:7] and
 * [4:2] plus 8, the same fields the disassembler prints (rvc_rs1s, rvc_rs2s).
 */
function bit uvme_rv32isa_covg_drv_c::decode_rvc(inout ins_t ins, input bit [31:0] insn, input bit [31:0] pc);
   bit [4:0] rs1_p, rs2_p;
   bit [4:0] rs1, rd;

   rs1_p = 5'd8 + insn[9:7];
   rs2_p = 5'd8 + insn[4:2];
   rd    = insn[11:7];
   rs1   = insn[11:7];

   case (ins.ins_str)
      "c.lw" : begin
         ins.ins_str = "lw";
         ins.ops[0] = '{key:"R", val: gpr_name(rs2_p)};
         ins.ops[1] = '{key:"C", val: dec_imm(uvma_isacov_pkg::dasm_rvc_lw_imm(insn))};
         ins.ops[2] = '{key:"R", val: gpr_name(rs1_p)};
      end
      "c.lwsp" : begin
         ins.ins_str = "lw";
         ins.ops[0] = '{key:"R", val: gpr_name(rd)};
         ins.ops[1] = '{key:"C", val: dec_imm(uvma_isacov_pkg::dasm_rvc_lwsp_imm(insn))};
         ins.ops[2] = '{key:"R", val: "sp"};
      end
      "c.sw" : begin
         ins.ins_str = "sw";
         ins.ops[0] = '{key:"R", val: gpr_name(rs2_p)};
         ins.ops[1] = '{key:"C", val: dec_imm(uvma_isacov_pkg::dasm_rvc_lw_imm(insn))};
         ins.ops[2] = '{key:"R", val: gpr_name(rs1_p)};
      end
      "c.swsp" : begin
         ins.ins_str = "sw";
         ins.ops[0] = '{key:"R", val: gpr_name(insn[6:2])};
         ins.ops[1] = '{key:"C", val: dec_imm(uvma_isacov_pkg::dasm_rvc_swsp_imm(insn))};
         ins.ops[2] = '{key:"R", val: "sp"};
      end

      // addi, three of which check_compressed() tells apart by operands:
      // c.addi16sp (sp,sp), c.addi4spn (rd',sp) and plain c.addi (rd,rd).
      "c.addi" : begin
         ins.ins_str = "addi";
         if (rd == 5'd0) begin
            // c.nop, an addi of zero on x0: binned as c_addi with a zero rd
            ins.ops[0] = '{key:"R", val: "zero"};
            ins.ops[1] = '{key:"R", val: "zero"};
            ins.ops[2] = '{key:"C", val: "0"};
         end
         else begin
            ins.ops[0] = '{key:"R", val: gpr_name(rd)};
            ins.ops[1] = '{key:"R", val: gpr_name(rd)};
            ins.ops[2] = '{key:"C", val: dec_imm(uvma_isacov_pkg::dasm_rvc_imm(insn))};
         end
      end
      "c.addi16sp" : begin
         ins.ins_str = "addi";
         ins.ops[0] = '{key:"R", val: "sp"};
         ins.ops[1] = '{key:"R", val: "sp"};
         ins.ops[2] = '{key:"C", val: dec_imm(uvma_isacov_pkg::dasm_rvc_addi16sp_imm(insn))};
      end
      "c.addi4spn" : begin
         ins.ins_str = "addi";
         ins.ops[0] = '{key:"R", val: gpr_name(rs2_p)};
         ins.ops[1] = '{key:"R", val: "sp"};
         ins.ops[2] = '{key:"C", val: dec_imm(uvma_isacov_pkg::dasm_rvc_addi4spn_imm(insn))};
      end
      "c.li" : begin
         ins.ins_str = "li";
         ins.ops[0] = '{key:"R", val: gpr_name(rd)};
         ins.ops[1] = '{key:"C", val: dec_imm(uvma_isacov_pkg::dasm_rvc_imm(insn))};
      end
      "c.lui" : begin
         // The model bins the 20 bit nzimm, sign extended
         bit [31:0] imm20;
         ins.ins_str = "lui";
         imm20       = uvma_isacov_pkg::dasm_rvc_imm(insn);
         ins.ops[0]  = '{key:"R", val: gpr_name(rd)};
         ins.ops[1]  = '{key:"C", val: imm20_str(imm20 << 12)};
      end
      "c.slli" : begin
         ins.ins_str = "slli";
         ins.ops[0] = '{key:"R", val: gpr_name(rs1)};
         ins.ops[1] = '{key:"R", val: gpr_name(rs1)};
         ins.ops[2] = '{key:"C", val: dec_imm(insn[6:2])};
      end
      "c.srli", "c.srai" : begin
         ins.ins_str = (ins.ins_str == "c.srli") ? "srli" : "srai";
         ins.ops[0] = '{key:"R", val: gpr_name(rs1_p)};
         ins.ops[1] = '{key:"R", val: gpr_name(rs1_p)};
         // shamt is six bits here, the sixth one selects srli over srai
         ins.ops[2] = '{key:"C", val: dec_imm({insn[12], insn[6:2]})};
      end
      "c.andi" : begin
         ins.ins_str = "andi";
         ins.ops[0] = '{key:"R", val: gpr_name(rs1_p)};
         ins.ops[1] = '{key:"R", val: gpr_name(rs1_p)};
         ins.ops[2] = '{key:"C", val: dec_imm(uvma_isacov_pkg::dasm_rvc_imm(insn))};
      end
      "c.add" : begin
         ins.ins_str = "add";
         ins.ops[0] = '{key:"R", val: gpr_name(rd)};
         ins.ops[1] = '{key:"R", val: gpr_name(rd)};
         ins.ops[2] = '{key:"R", val: gpr_name(insn[6:2])};
      end
      "c.mv" : begin
         ins.ins_str = "mv";
         ins.ops[0] = '{key:"R", val: gpr_name(rd)};
         ins.ops[1] = '{key:"R", val: gpr_name(insn[6:2])};
      end
      "c.sub", "c.and", "c.or", "c.xor" : begin
         case (ins.ins_str)
            "c.sub" : ins.ins_str = "sub";
            "c.and" : ins.ins_str = "and";
            "c.or"  : ins.ins_str = "or";
            default : ins.ins_str = "xor";
         endcase
         ins.ops[0] = '{key:"R", val: gpr_name(rs1_p)};
         ins.ops[1] = '{key:"R", val: gpr_name(rs1_p)};
         ins.ops[2] = '{key:"R", val: gpr_name(rs2_p)};
      end

      // Control transfer: c.j takes the target as its only operand, c.jal
      // carries the implied link register first, c.jr and c.jalr the jump
      // register, and the two zero test branches put the rs' register first.
      "c.j" : begin
         ins.ins_str = "j";
         ins.ops[0] = '{key:"C", val: target_str(pc, uvma_isacov_pkg::dasm_rvc_j_imm(insn))};
      end
      "c.jal" : begin
         ins.ins_str = "jal";
         ins.ops[0] = '{key:"R", val: "ra"};
         ins.ops[1] = '{key:"C", val: target_str(pc, uvma_isacov_pkg::dasm_rvc_j_imm(insn))};
      end
      "c.jr", "c.jalr" : begin
         ins.ins_str = (ins.ins_str == "c.jr") ? "jr" : "jalr";
         ins.ops[0] = '{key:"R", val: gpr_name(rs1)};
      end
      "c.beqz", "c.bnez" : begin
         ins.ins_str = (ins.ins_str == "c.beqz") ? "beqz" : "bnez";
         ins.ops[0] = '{key:"R", val: gpr_name(rs1_p)};
         ins.ops[1] = '{key:"C", val: target_str(pc, uvma_isacov_pkg::dasm_rvc_b_imm(insn))};
      end

      "c.ebreak" : ins.ins_str = "ebreak";

      default : return 0;
   endcase

   return 1;
endfunction : decode_rvc


/**
 * ABI names, exactly the spelling uvme_rv32isa_covg::get_gpr_name() switches
 * on -- an index it does not recognise is silently left out of the bins.
 */
function string uvme_rv32isa_covg_drv_c::gpr_name(bit [4:0] rnum);
   const string names[32] = '{"zero", "ra", "sp", "gp", "tp", "t0", "t1", "t2",
                             "s0", "s1", "a0", "a1", "a2", "a3", "a4", "a5",
                             "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7",
                             "s8", "s9", "s10", "s11", "t3", "t4", "t5", "t6"};
   return names[rnum];
endfunction : gpr_name


/**
 * CSR number to the name uvme_rv32isa_covg::get_csr_name() recognises, which is
 * only what CVE2 decodes: its commented out cases show the model gives up on
 * the hpmevent and hpmcounter counters beyond the first one, and on dcsr and
 * dpc. Those return an empty string here so the instruction is dropped rather
 * than binned under the CSR the model falls back to.
 */
function string uvme_rv32isa_covg_drv_c::csr_name(bit [11:0] cnum);
   case (cnum)
      12'h300 : return "mstatus";
      12'h301 : return "misa";
      12'h304 : return "mie";
      12'h305 : return "mtvec";
      12'h320 : return "mcountinhibit";
      12'h323 : return "mhpmevent3";
      12'h340 : return "mscratch";
      12'h341 : return "mepc";
      12'h342 : return "mcause";
      12'h343 : return "mtval";
      12'h344 : return "mip";
      12'h7A0 : return "tselect";
      12'h7A1 : return "tdata1";
      12'h7A2 : return "tdata2";
      12'h7A3 : return "tdata3";
      12'h7A4 : return "tinfo";
      12'h7B2 : return "dscratch0";
      12'h7B3 : return "dscratch1";
      12'hB00 : return "mcycle";
      12'hB02 : return "minstret";
      12'hB03 : return "mhpmcounter3";
      12'hB80 : return "mcycleh";
      12'hB82 : return "minstreth";
      12'hB83 : return "mhpmcounterh3";
      12'hF11 : return "mvendorid";
      12'hF12 : return "marchid";
      12'hF13 : return "mimpid";
      12'hF14 : return "mhartid";
      default : return "";
   endcase
endfunction : csr_name


function string uvme_rv32isa_covg_drv_c::dec_imm(longint value);
   return $sformatf("%0d", value);
endfunction : dec_imm


/**
 * The 20 bit U immediate, in the "0xNNNNN" form get_imm() reads as hex.
 */
function string uvme_rv32isa_covg_drv_c::imm20_str(bit [31:0] imm);
   return $sformatf("0x%05x", imm[31:12]);
endfunction : imm20_str


/**
 * get_pc_imm() reads a bare hex address and subtracts the instruction's PC, so
 * that the sign of the result is the direction of the jump.
 */
function string uvme_rv32isa_covg_drv_c::target_str(bit [31:0] pc, longint offset);
   bit [31:0] target;
   target = pc + offset[31:0];
   return $sformatf("%08x", target);
endfunction : target_str


`endif // __UVME_RV32ISA_COVG_DRV_SV__
