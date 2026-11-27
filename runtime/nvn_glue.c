/* SwitchRecomp - Copyright 2026 MZ Labs
   Licensed under the GNU Affero General Public License v3.0, see LICENSE.txt and NOTICE.txt.
   Forks and derived works have to keep the credit to SwitchRecomp by MZ Labs and the startup screen. */
/* What the NVN layer (runtime/nvn, renderer=vulkan) expects from the runtime around it: frame pacing, timing and a
   few debug hooks. The debug ones (watchpoints, breakpoints, flight recorder) do nothing here; trace spans are recorded (SWR_TRACE below). */
#ifndef _WIN32
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#endif
#include "rt.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#include <sys/syscall.h>
#endif

static u64 g_run0;
unsigned long long swr_run_ns(void){ if(!g_run0) g_run0=plat_ns(); return plat_ns()-g_run0; }
volatile u32 g_swr_present_seq;
volatile unsigned long long g_swr_stall_ns;   /* the renderer's waits for shaders being translated (vk_replay.c shader_wait): the test input clock leaves them out */
volatile u64 g_frame_mode;          /* 0: the game's own present interval */
int g_opt_tile_skip=-1;
volatile int g_swr_trace_on;
volatile int g_flight_req;
#ifdef _WIN32
volatile DWORD g_host_focus_tid;
#else
volatile unsigned long g_host_focus_tid;
#endif
int vdec_playing(void){ return 0; }
void kernel_svc_report(void){}
void plat_bp_min(u64 m){ (void)m; }
void plat_bp(u64 rva, long n){ (void)rva; (void)n; }
void plat_watch_range(u64 guest, u64 len, int huge){ (void)guest; (void)len; (void)huge; }
void plat_watch_page_arm(u64 guest){ (void)guest; }
/* SWR_TRACE=<first present>[:<presents>] (default 10): the spans of the calls that make up a frame's critical path (swr_trace_span: the NVN layer's submits,
   sync waits, acquires and presents, the Vulkan replay of each submission, its queue submit and the completion work), on every thread, for that many presents
   from that present, written as Chrome trace events to swr_trace_<first>.json in the working folder (chrome://tracing, ui.perfetto.dev). A span is
   (name, start, end, thread); names are string literals. Off outside the window: one load and a branch per call site. */
typedef struct { const char* name; u64 t0, t1; u32 tid; } TrSpan;
enum { TR_MAX = 1<<20 };
static TrSpan* g_tr; static volatile long g_ntr; static long g_tr_first=-1, g_tr_n=10, g_tr_frame;
static int g_tr_requested;
static int tr_hotkey(const char* config){
  return config && !strncmp(config,"hotkey",6) && (!config[6] || config[6]==':');
}
int swr_trace_request(void){
  if(!tr_hotkey(getenv("SWR_TRACE"))) return 0;
  __atomic_store_n(&g_tr_requested,1,__ATOMIC_RELEASE);
  return 1;
}
static u32 tr_tid(void){
#ifdef _WIN32
  return (u32)GetCurrentThreadId();
#else
  return (u32)syscall(SYS_gettid);
#endif
}
unsigned long long swr_trace_ts(void){ return plat_ns(); }
void swr_trace_span(const char* name, unsigned long long t0){
  if(!g_swr_trace_on || !t0 || !g_tr) return;
  long i=__atomic_fetch_add(&g_ntr,1,__ATOMIC_RELAXED); if(i>=TR_MAX) return;
  g_tr[i]=(TrSpan){name,t0,plat_ns(),tr_tid()};
}
static void tr_write(void){
  char path[64]; snprintf(path,sizeof path,"swr_trace_%ld.json",g_tr_first);
  FILE* f=fopen(path,"wb"); if(!f) return;
  long n=g_ntr<TR_MAX? g_ntr : TR_MAX; u64 base=n? g_tr[0].t0 : 0;
  for(long i=0;i<n;i++) if(g_tr[i].t0<base) base=g_tr[i].t0;
  fputs("{\"traceEvents\":[\n",f);
  for(long i=0;i<n;i++){ const TrSpan* e=&g_tr[i];
    fprintf(f,"%s{\"name\":\"%s\",\"ph\":\"X\",\"pid\":1,\"tid\":%u,\"ts\":%.3f,\"dur\":%.3f}",i?",\n":"",e->name,e->tid,(e->t0-base)/1000.0,(e->t1-e->t0)/1000.0); }
  fputs("\n]}\n",f); fclose(f);
  fprintf(stderr,"swr trace: %ld spans over %ld presents written to %s\n",n,g_tr_n,path);
}
void input_rec_present(u32 interval){ (void)interval; }

/* vblank pacing: the game moves its clock by its present interval (vblanks at 60 Hz) each frame, so a frame isn't
   shown before that much time has passed since the last one, or the game runs fast. SWR_PACE=0 turns it off */
void swr_present_pace(u32 iv){
  static int on=-1; if(on<0){ const char* e=getenv("SWR_PACE"); on= !e || *e!='0'; }
  static u64 next; if(iv<1) iv=1; if(iv>4) iv=4;
  if(!on) return;
  u64 per=(u64)iv*1000000000ull/60, now=swr_run_ns();
  if(!next || now>next+per) next=now;
  else if(now<next){ if(next-now>1500000) plat_sleep_ns((i64)(next-now-1000000)); while(swr_run_ns()<next) plat_yield(); }
  next+=per; }
void plat_dump_native_stacks(void){}
void swr_trace_poll(void){   /* each present (hle_nvn.c): opens and closes SWR_TRACE's window */
  static int st=-1;
  if(st<0){ st=0; const char* e=getenv("SWR_TRACE"); if(e && *e){ const char* q;
              if(tr_hotkey(e)) q=e+6;
              else { char* end; long first=strtol(e,&end,10); g_tr_first=first>0?first:0; q=end; }
              if(*q==':') g_tr_n=strtol(q+1,NULL,10); if(g_tr_n<1) g_tr_n=1;
              g_tr=(TrSpan*)malloc(sizeof *g_tr*(size_t)TR_MAX); if(g_tr) st=1; } }
  if(st==0) return;
  g_tr_frame++;
  if(st==1 && g_tr_first<0 && __atomic_load_n(&g_tr_requested,__ATOMIC_ACQUIRE)) g_tr_first=g_tr_frame;
  if(st==1 && g_tr_first>=0 && g_tr_frame>=g_tr_first){ g_ntr=0; g_swr_trace_on=1; st=2; }
  else if(st==2 && g_tr_frame>=g_tr_first+g_tr_n){ g_swr_trace_on=0; st=3; tr_write(); }
}
/* makes the folders of a file path (screenshots) */
void plat_mkdir_for(const char* path){
  char p[1200]; snprintf(p,sizeof p,"%s",path);
  for(char* q=p+1;*q;q++) if(*q=='/' || *q=='\\'){ char c=*q; *q=0;
#ifdef _WIN32
    CreateDirectoryA(p,NULL);
#else
    { extern int mkdir(const char*, unsigned); mkdir(p,0755); }
#endif
    *q=c; } }
#ifndef _WIN32
#include <pthread.h>
void plat_thread_name(const char* n){ char b[16]; snprintf(b,sizeof b,"%s",n? n : ""); pthread_setname_np(pthread_self(),b); }
#endif
