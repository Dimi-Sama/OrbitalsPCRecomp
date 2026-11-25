/* Orbitals PC Recomp, based on SwitchRecomp by MZ Labs. AGPL-3.0, see LICENSE.txt and NOTICE.txt. */
#include "rt.h"

/* The validated main build reads its secondary screen percentage from a float returned by AsVariableFloat.
   The float is read on the game thread while preparing each viewport. Zero selects Unreal's original policy. */
static const u8 orbitals_main_id[32] = {
  0x0f,0x8e,0xf5,0x2c,0xf4,0xee,0xe3,0x76,0x28,0xf3,0x66,0xa5,0x39,0xd5,0xd6,0xad,
};
static u64 scene_slot;
static int scene_request;
static int scene_applied;
static int scene_initialized;
static u32 scene_original;

#ifdef _WIN32
/* The validated guest build's native base of the Blueprint settings screen. CommonUI calls slot 171
   through the AOT dispatch table when it activates the widget. Filter by the object's primary vtable. */
enum { SETTINGS_VTABLE=0x8890a38, SETTINGS_ACTIVATE_SLOT=171, SETTINGS_ACTIVE=992 };
static u64 settings_guest_vtable;
static GuestFn settings_guest_activate;
void backend_game_settings_show(void);

static void orbitals_widget_activate(CPU* c,u64 pc){
  u64 widget=c->x[0];
  int settings=guest_span_readable(widget,SETTINGS_ACTIVE+1,8) && gr64(widget)==settings_guest_vtable &&
               !(*GP(widget+SETTINGS_ACTIVE)&1);
  settings_guest_activate(c,pc);
  if(settings && guest_span_readable(widget,SETTINGS_ACTIVE+1,8) && gr64(widget)==settings_guest_vtable &&
     (*GP(widget+SETTINGS_ACTIVE)&1)) backend_game_settings_show();
}

static void orbitals_widget_install(const SwrModInfo* mod){
  u64 vtable=mod->base+SETTINGS_VTABLE;
  u64 slot=vtable+SETTINGS_ACTIVATE_SLOT*sizeof(u64);
  if(slot-mod->base+sizeof(u64)>mod->size || !guest_span_readable(slot,sizeof(u64),8)) return;
  u64 relative=gr64(slot);
  if(relative<mod->text_off || relative-mod->text_off>=mod->text_size || (relative&3)) return;
  u64 pc=mod->base+relative;
  if(pc<g_code_lo || pc>=g_code_hi) return;
  GuestFn* entry=&g_disp[(pc-g_code_lo)/4];
  if(!*entry) return;
  settings_guest_vtable=vtable;
  settings_guest_activate=*entry;
  *entry=orbitals_widget_activate;
  LOG("Orbitals: PC Settings bound to the CommonUI widget activation\n");
}
#endif

void orbitals_scene_init(void){
  for(u32 i=0;i<g_mod->nmods;i++){
    const SwrModInfo* mod=&g_mod->mods[i];
    if(strcmp(mod->name,"main") || memcmp(mod->build_id,orbitals_main_id,sizeof orbitals_main_id)) continue;
#ifdef _WIN32
    orbitals_widget_install(mod);
#endif
    if(mod->size<0x9c48a38 || mod->text_size<0x2ddc5c8) return;
    u64 load=mod->base+0x2ddc5bc;
    if(gr32(load)!=0x90037368 || gr32(load+4)!=0xf9451908 || gr32(load+8)!=0xbd400100) return;
    scene_slot=mod->base+0x9c48a30;
    LOG("Orbitals: internal 3D resolution control available\n");
    return;
  }
}

int orbitals_scene_available(void){ return scene_slot!=0; }
int orbitals_scene_requested(void){ return __atomic_load_n(&scene_request,__ATOMIC_RELAXED); }

void orbitals_scene_request(int height){
  if(height==0 || height==540 || height==720 || height==900 || height==1080)
    __atomic_store_n(&scene_request,height,__ATOMIC_RELAXED);
}

void orbitals_scene_poll(void){
  int height=orbitals_scene_requested();
  if(!scene_slot || !g_frames || height==scene_applied) return;
  u64 value=__atomic_load_n((const u64*)GP(scene_slot),__ATOMIC_ACQUIRE);
  if(!guest_span_writable(value,sizeof(u32),sizeof(u32))) return;
  u32* bits=(u32*)GP(value);
  if(!scene_initialized){
    scene_original=__atomic_load_n(bits,__ATOMIC_RELAXED);
    scene_initialized=1;
  }
  u32 next=scene_original;
  if(height){
    float percent=height==540? 50.0f : height==720? 66.6667f : height==900? 83.3333f : 100.0f;
    memcpy(&next,&percent,sizeof next);
  }
  __atomic_store_n(bits,next,__ATOMIC_RELEASE);
  scene_applied=height;
  if(height) LOG("Orbitals: internal 3D resolution set to %dp\n",height);
  else LOG("Orbitals: restored the starting 3D resolution\n");
}
