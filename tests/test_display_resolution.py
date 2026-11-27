"""Compile a generated direct BL and run it through the real resolution hook."""
import struct
import nxloader
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import codegen

ROOT = Path(__file__).resolve().parents[1]
TARGET = 0x35d1740
BUILD = bytes.fromhex('0f8ef52cf4eee37628f366a539d5d6ad')


def generated(kind='bl', build=BUILD):
    mod = SimpleNamespace(name='main', base=0, build_id=build)
    prog = SimpleNamespace(dyn_calls=codegen.dynamic_call_targets([mod]), mod_of=lambda t: mod, decode=lambda x: (0, (kind, TARGET)) if x == 0x100 else (0, ('ret', 'c->x[30]')))
    caller = codegen.Func(0x100, [0x100, 0x104], mod)
    caller.leaders = {0x100}
    target = codegen.Func(TARGET, [], mod)
    return codegen.emit_function(prog, caller, {TARGET: target})


class ResolutionTest(unittest.TestCase):
    def test_loader_build_id_routes_resolution(self):
        header = bytearray(0x100)
        header[:4] = b'NSO0'
        header[0x40:0x50] = BUILD
        struct.pack_into('<III', header, 0x10, 0x100, 0, 8)
        struct.pack_into('<III', header, 0x30, 0x108, 8, 0)
        struct.pack_into('<I', header, 0x60, 8)
        header.extend(bytes(8))
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'main'
            path.write_bytes(header)
            mod = nxloader.load_nso(path)
        self.assertEqual(mod.build_id, BUILD)
        self.assertNotIn('F_35D1740(c,', generated(build=mod.build_id))
        self.assertNotIn('F_35D1740(c,', generated(build=BUILD + bytes(16)))

    def test_ini_resolution_parser(self):
        main = (ROOT / 'runtime/main.c').read_text()
        body = main.split('else if(!strcmp(k,"display_resolution")){', 1)[1].split('\n    }', 1)[0]
        source = '#include <stdlib.h>\n#include <assert.h>\nint g_opt_display_h;\nvoid parse(const char* v){' + body + '}\n'
        source += r'''int main(void){
          const char* invalid[]={"0","1080","2161","2160oops","", "1440.0", "-1440"};
          for(int i=0;i<7;i++){g_opt_display_h=2160;parse(invalid[i]);assert(g_opt_display_h==0);}
          parse("1440");assert(g_opt_display_h==1440);parse("1620");assert(g_opt_display_h==1620);
          parse("1800");assert(g_opt_display_h==1800);parse("2160");assert(g_opt_display_h==2160);
        }'''
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            (path/'ini.c').write_text(source)
            subprocess.run(['gcc', str(path/'ini.c'), '-o', str(path/'ini')], check=True)
            subprocess.run([str(path/'ini')], check=True)

    def test_other_build_keeps_direct_calls(self):
        self.assertIn('F_35D1740(c,', generated(build=bytes(32)))
        self.assertNotIn('F_35D1740(c,', generated())
        self.assertNotIn('F_35D1740(c,', generated('b'))

    def test_generated_bl_reaches_real_runtime_hook(self):
        source = r'''
#include <assert.h>
#include "runtime/orbitals_settings.c"
u8* g_mem; GuestFn* g_disp; u64 g_code_lo, g_code_hi;
int g_opt_docked=1, g_opt_display_h=2160, g_display_h=0;
static int capability=1;
int code_dynamic_call(u64 pc){ return capability; }
GuestFn swr_interp_entry;
int guest_span_readable(u64 a,u64 n,u64 align){ return a%align==0 && a+n<=g_code_hi; }
int guest_span_writable(u64 a,u64 n,u64 align){ return guest_span_readable(a,n,align); }
void logf_(int level,const char* fmt,...){}
static int calls, success=1, abort_parse=0; static u32 input_w=1920, input_h=1080;
static void original(CPU* c,u64 pc){
 calls++; memcpy(GP(c->x[1]),&input_w,4); memcpy(GP(c->x[2]),&input_h,4);
 c->x[0]=success; c->pc=abort_parse? 0xdead : c->x[30];
}
'''
        source += generated()
        source += r'''
int main(void){
 g_code_lo=0; g_code_hi=PARSE_RES+8;
 g_mem=calloc(1,g_code_hi); g_disp=calloc(g_code_hi/4,sizeof *g_disp);
 u32 sig[]={0xd503237f,0xd10243ff}; memcpy(GP(PARSE_RES),sig,8);
 SwrModInfo mod={0}; mod.text_size=g_code_hi;
 g_disp[PARSE_RES/4]=original;
 g_opt_docked=0; orbitals_parse_res_install(&mod); assert(g_disp[PARSE_RES/4]==original);
 g_opt_docked=1; g_opt_display_h=0; orbitals_parse_res_install(&mod); assert(g_disp[PARSE_RES/4]==original);
 g_opt_display_h=2160;
 mod.text_size=PARSE_RES; orbitals_parse_res_install(&mod); assert(g_disp[PARSE_RES/4]==original);
 mod.text_size=g_code_hi; GP(PARSE_RES)[0]=0; orbitals_parse_res_install(&mod); assert(g_disp[PARSE_RES/4]==original);
 memcpy(GP(PARSE_RES),sig,8); capability=0; orbitals_parse_res_install(&mod);
 assert(g_disp[PARSE_RES/4]==original && g_display_h==0);
 capability=1; orbitals_parse_res_install(&mod); assert(g_disp[PARSE_RES/4]==orbitals_parse_res && g_display_h==2160);
 orbitals_parse_res_install(&mod); assert(parse_res_orig==original);
 CPU c={0}; c.mem=g_mem; c.disp=g_disp; c.code_hi=g_code_hi; c.x[1]=16; c.x[2]=20;
 F_100(&c,0x100); assert(calls==1 && gr32(16)==3840 && gr32(20)==2160);
 for(int h=1440;h<=2160;h+= (h==1440?180: (h==1620?180:360))){
  g_display_h=h; F_100(&c,0x100); assert(gr32(16)==(u32)(h*16/9) && gr32(20)==(u32)h);
 }
 success=0; F_100(&c,0x100); assert(gr32(16)==1920);
 success=1; abort_parse=1; F_100(&c,0x100); assert(gr32(16)==1920 && c.pc==0xdead);
 abort_parse=0; input_w=1280; input_h=720; F_100(&c,0x100); assert(gr32(16)==1280 && gr32(20)==720);
 free(g_mem); free(g_disp); puts("generated BL -> dispatch -> real parse hook: PASS");
}
'''
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)
            (path/'test.c').write_text(source)
            result = subprocess.run(['gcc', '-O1', '-ffunction-sections', '-fdata-sections', '-I', str(ROOT), str(path/'test.c'), '-Wl,--gc-sections', '-o', str(path/'test')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(path/'test')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('real parse hook: PASS', result.stdout)

if __name__ == '__main__':
    unittest.main()
