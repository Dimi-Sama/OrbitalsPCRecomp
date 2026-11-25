/* SwitchRecomp - Copyright 2026 MZ Labs
   Licensed under the GNU Affero General Public License v3.0, see LICENSE.txt and NOTICE.txt.
   Forks and derived works have to keep the credit to SwitchRecomp by MZ Labs and the startup screen. */
/* hid. games read the shared memory directly, so we fill it in the real layout (17 entry LIFOs) */
#include "rt.h"
#include "hid_layout.h"
#include <math.h>

KShmem* kshmem_new(u64 size, const char* name);
u8* kshmem_ptr(KShmem* s);
static KShmem* g_hid_shm;
PadState g_pad, g_pad2;
int g_pad1_connected, g_pad2_connected;
static u64 g_samp;
static u32 g_style_supported=0x7F;
static int g_handheld_id_supported=1;
static KEvent* g_style_ev[10];
static PMutex g_style_lock;
static void no1_setup(void);

static void lifo_push(u8* lifo, u32 esize, const void* state, u32 ssize, u64 samp){
  /* lifo header: unused, buffer_count, tail, count. entries: {u64 sampling_number; state}. the entry's sampling
     number is the state's one shifted left by one. SDK 20+ readers (nn::hid::GetNpadStates in tomodachi life:
     living the dream) retry until it matches, older SDKs only check that it doesn't change while they copy the
     state */
  u64 cnt=17, tail, count, tag=samp<<1; memcpy(&tail,lifo+0x10,8); memcpy(&count,lifo+0x18,8);
  tail=(tail+1)%cnt; u8* e=lifo+0x20+tail*esize;
  memcpy(e,&tag,8); memcpy(e+8,state,ssize);
  __atomic_thread_fence(__ATOMIC_SEQ_CST);
  memcpy(lifo+8,&cnt,8); memcpy(lifo+0x10,&tail,8); if(count<16) count++; memcpy(lifo+0x18,&count,8);
}

/* npad index: 0..7 = No1..No8, 8 = Handheld (0x20), 9 = Other (0x10) */
static void npad_setup(u8* base, int idx, u32 style, u32 devtype){
  u8* e=base+HO_HidSharedMemory_npad+idx*HS_HidNpadSharedMemoryEntry;
  memcpy(e+HO_HidNpadInternalState_style_set,&style,4);
  u32 jam=0; memcpy(e+HO_HidNpadInternalState_joy_assignment_mode,&jam,4);
  u32 col[3]={1,0xFF323232u,0xFF0A0A0A}; memcpy(e+HO_HidNpadInternalState_full_key_color,col,12);
  u32 jc[5]={1,0xFF3C3C3Cu,0xFF0A0A0A,0xFF3C3C3Cu,0xFF0A0A0A}; memcpy(e+HO_HidNpadInternalState_joy_color,jc,20);
  memcpy(e+HO_HidNpadInternalState_device_type,&devtype,4);
  u64 props=(1ull<<0)|(1ull<<1)|(1ull<<2)|(1ull<<3)|(1ull<<11)|(1ull<<12); /* charging, powered, dual joy... + abxy + plus/minus */
  memcpy(e+HO_HidNpadInternalState_system_properties,&props,8);
  u32 bat[3]={4,4,4}; memcpy(e+HO_HidNpadInternalState_battery_level,bat,12);
  u32 fattr=0; memcpy(e+HO_HidNpadInternalState_applet_footer_ui_attribute,&fattr,4);
  u8 ftype= idx==8? 4 : 3; e[HO_HidNpadInternalState_applet_footer_ui_type]=ftype;   /* handheld / pro controller */
}

static u32 player_style(void){
  u32 supported=__atomic_load_n(&g_style_supported,__ATOMIC_RELAXED);
  return (supported&1) || !(supported&(1u<<2)) ? 1u : 1u<<2;
}

static int primary_is_handheld(void){
  return !g_opt_docked && (__atomic_load_n(&g_style_supported,__ATOMIC_RELAXED)&2) &&
    __atomic_load_n(&g_handheld_id_supported,__ATOMIC_RELAXED);
}

u32 hid_primary_npad(void){ return primary_is_handheld()? 0x20u : 0; }

static void player_setup(u8* b, int idx, u32 style){
  u32 device=style==1u ? 1u : style==2u ? (1u<<2)|(1u<<3) : (1u<<4)|(1u<<5);
  pm_lock(&g_style_lock);
  if(style) npad_setup(b,idx,style,device);
  else {
    u8* e=b+HO_HidSharedMemory_npad+idx*HS_HidNpadSharedMemoryEntry;
    memcpy(e+HO_HidNpadInternalState_style_set,&style,4);
    memcpy(e+HO_HidNpadInternalState_device_type,&style,4);
  }
  if(g_style_ev[idx]) kevent_signal(g_style_ev[idx]);
  pm_unlock(&g_style_lock);
}

static void pad_state(u8 st[0x28], const PadState* pad, u32 connected){
  memset(st,0,0x28);
  memcpy(st+HO_HidNpadCommonState_sampling_number,&g_samp,8);
  if(!connected) return;
  u64 btn=pad->buttons;
  /* sticks also set the stick-direction button bits, like hw */
  if(pad->lx<-16000) btn|=1ull<<16; if(pad->ly>16000) btn|=1ull<<17; if(pad->lx>16000) btn|=1ull<<18; if(pad->ly<-16000) btn|=1ull<<19;
  if(pad->rx<-16000) btn|=1ull<<20; if(pad->ry>16000) btn|=1ull<<21; if(pad->rx>16000) btn|=1ull<<22; if(pad->ry<-16000) btn|=1ull<<23;
  memcpy(st+HO_HidNpadCommonState_buttons,&btn,8);
  i32 s4[4]={pad->lx,pad->ly,pad->rx,pad->ry}; memcpy(st+HO_HidNpadCommonState_analog_stick_l,s4,16);
  memcpy(st+HO_HidNpadCommonState_attributes,&connected,4);
}

void hid_update(void){
  if(!g_hid_shm) return;
  u8* b=kshmem_ptr(g_hid_shm);
  g_samp++;
  int handheld=primary_is_handheld();
  u8 st[0x28]; pad_state(st,&g_pad,!handheld);
  /* The host primary pad drives one guest device, either No1 or Handheld. */
  u8* e0=b+HO_HidSharedMemory_npad;
  lifo_push(e0+HO_HidNpadInternalState_full_key_lifo,HS_HidNpadCommonStateAtomicStorage,st,0x28,g_samp);
  lifo_push(e0+HO_HidNpadInternalState_joy_dual_lifo,HS_HidNpadCommonStateAtomicStorage,st,0x28,g_samp);
  lifo_push(e0+HO_HidNpadInternalState_handheld_lifo,HS_HidNpadCommonStateAtomicStorage,st,0x28,g_samp);
  u8* eh=b+HO_HidSharedMemory_npad+8*HS_HidNpadSharedMemoryEntry;
  pad_state(st,&g_pad,handheld);
  lifo_push(eh+HO_HidNpadInternalState_handheld_lifo,HS_HidNpadCommonStateAtomicStorage,st,0x28,g_samp);
  lifo_push(eh+HO_HidNpadInternalState_full_key_lifo,HS_HidNpadCommonStateAtomicStorage,st,0x28,g_samp);
  static u32 second_style;
  u32 style=__atomic_load_n(&g_pad2_connected,__ATOMIC_ACQUIRE) ? player_style() : 0;
  u8* e1=b+HO_HidSharedMemory_npad+HS_HidNpadSharedMemoryEntry;
  u8 second[0x28]; pad_state(second,&g_pad2,style!=0);
  lifo_push(e1+HO_HidNpadInternalState_full_key_lifo,HS_HidNpadCommonStateAtomicStorage,second,sizeof second,g_samp);
  lifo_push(e1+HO_HidNpadInternalState_joy_dual_lifo,HS_HidNpadCommonStateAtomicStorage,second,sizeof second,g_samp);
  if(style!=second_style){ player_setup(b,1,style); second_style=style; }
  /* unused npads still need a sampling number, the SDK looks at it */
  u8 z[0x28]; memset(z,0,sizeof z); memcpy(z,&g_samp,8);
  for(int i=2;i<10;i++){ if(i==8) continue; u8* e=b+HO_HidSharedMemory_npad+i*HS_HidNpadSharedMemoryEntry;
    lifo_push(e+HO_HidNpadInternalState_full_key_lifo,HS_HidNpadCommonStateAtomicStorage,z,0x28,g_samp); }
  /* six-axis: at rest, gravity down */
  u8 six[HS_HidSixAxisSensorState]; memset(six,0,sizeof six);
  memcpy(six,&g_samp,8); memcpy(six+8,&g_samp,8);
  float acc[3]={0,0,-1}; memcpy(six+HO_HidSixAxisSensorState_acceleration,acc,12);
  float dir[9]={1,0,0, 0,1,0, 0,0,1}; memcpy(six+HO_HidSixAxisSensorState_direction,dir,36);
  u32 sattr=1; memcpy(six+HO_HidSixAxisSensorState_attributes,&sattr,4);
  lifo_push(e0+HO_HidNpadInternalState_full_key_six_axis_sensor_lifo,HS_HidSixAxisSensorStateAtomicStorage,six,sizeof six,g_samp);
  lifo_push(e0+HO_HidNpadInternalState_joy_dual_left_six_axis_sensor_lifo,HS_HidSixAxisSensorStateAtomicStorage,six,sizeof six,g_samp);
  lifo_push(e0+HO_HidNpadInternalState_joy_dual_right_six_axis_sensor_lifo,HS_HidSixAxisSensorStateAtomicStorage,six,sizeof six,g_samp);
  sattr=(u32)handheld; memcpy(six+HO_HidSixAxisSensorState_attributes,&sattr,4);
  lifo_push(eh+HO_HidNpadInternalState_handheld_six_axis_sensor_lifo,HS_HidSixAxisSensorStateAtomicStorage,six,sizeof six,g_samp);
  /* touch */
  u8 ts[HS_HidTouchScreenState]; memset(ts,0,sizeof ts); memcpy(ts,&g_samp,8);
  if(g_pad.touch){ u32 cnt=1; memcpy(ts+HO_HidTouchScreenState_count,&cnt,4);
    u8* t=ts+HO_HidTouchScreenState_touches; u64 dt=0; memcpy(t,&dt,8); u32 attr2=0, fid=0; memcpy(t+8,&attr2,4); memcpy(t+12,&fid,4);
    u32 xy[4]={(u32)g_pad.tx,(u32)g_pad.ty,20,20}; memcpy(t+16,xy,16); }
  lifo_push(b+HO_HidSharedMemory_touchscreen+HO_HidTouchScreenSharedMemoryFormat_lifo,HS_HidTouchScreenStateAtomicStorage,ts,sizeof ts,g_samp);
  /* keyboard/mouse/debug pad: only bump the counters */
  u8 kb[HS_HidKeyboardState]; memset(kb,0,sizeof kb); memcpy(kb,&g_samp,8);
  lifo_push(b+HO_HidSharedMemory_keyboard,8+HS_HidKeyboardState,kb,sizeof kb,g_samp);
  u8 ms[HS_HidMouseState]; memset(ms,0,sizeof ms); memcpy(ms,&g_samp,8);
  lifo_push(b+HO_HidSharedMemory_mouse,8+HS_HidMouseState,ms,sizeof ms,g_samp);
  u8 dp[HS_HidDebugPadState]; memset(dp,0,sizeof dp); memcpy(dp,&g_samp,8);
  lifo_push(b+HO_HidSharedMemory_debug_pad,8+HS_HidDebugPadState,dp,sizeof dp,g_samp);
}

static int hid_applet_res(SvcObj* o, IpcCtx* c){
  if(c->cmd==0){ out_copy_h(c,h_new(&g_hid_shm->o)); return 0; }
  return stub_ok(o,c); }

static int hid_vibration_list(SvcObj* o, IpcCtx* c){ (void)o; (void)c; return 0; }   /* IActiveVibrationDeviceList: 0 ActivateVibrationDevice */

/* The guest supplies both frequency bands for each half of a controller.
   The PC APIs expose one low and one high motor per gamepad. */
typedef struct { float low_amp, low_hz, high_amp, high_hz; } VibrationValue;
static const VibrationValue vibration_off={0,160,0,320};
static PMutex g_rumble_lock;
static int g_rumble_permitted=1, g_rumble_session;
static struct {
  u32 device_id;
  VibrationValue side[2];
  u32 motors;
} g_rumble[2];
static struct {
  u32 device_id, sent;
  u64 refresh_at;
} g_host_rumble[2]; /* frontend thread only */

static int vibration_player(u32 handle){
  u8 style=(u8)handle, id=(u8)(handle>>8);
  if((handle>>16)>1 || !((style>=3 && style<=8) || style==0x20 || style==0x21)) return -1;
  if(id==1) return 1;
  return id==hid_primary_npad()? 0 : -1;
}

static float vibration_amplitude(float value){
  if(!isfinite(value) || value<=0) return 0;
  return value<1 ? value : 1;
}

/* Called with the rumble lock held. Publish once per player after a whole batch. */
static u32 vibration_set(int player, u32 side, VibrationValue value){
  if(player<0 || !g_rumble[player].device_id || !(g_rumble_permitted || g_rumble_session)) return 0;
  value.low_amp=vibration_amplitude(value.low_amp);
  value.high_amp=vibration_amplitude(value.high_amp);
  if(!isfinite(value.low_hz)) value.low_hz=vibration_off.low_hz;
  if(!isfinite(value.high_hz)) value.high_hz=vibration_off.high_hz;
  g_rumble[player].side[side]=value;
  return 1u<<player;
}

static void vibration_publish(int player){
  const VibrationValue* side=g_rumble[player].side;
  u32 low=(u32)(fmaxf(side[0].low_amp,side[1].low_amp)*65535.f+0.5f);
  u32 high=(u32)(fmaxf(side[0].high_amp,side[1].high_amp)*65535.f+0.5f);
  __atomic_store_n(&g_rumble[player].motors,low|(high<<16),__ATOMIC_RELEASE);
}

static void vibration_clear(int player){
  g_rumble[player].side[0]=g_rumble[player].side[1]=vibration_off;
  __atomic_store_n(&g_rumble[player].motors,0,__ATOMIC_RELEASE);
}

void hid_rumble_update(int player, u32 device_id, int enabled){
  __typeof__(g_host_rumble[0])* host=&g_host_rumble[player];
  if(host->device_id!=device_id){
    pm_lock(&g_rumble_lock);
    g_rumble[player].device_id=device_id;
    vibration_clear(player);
    pm_unlock(&g_rumble_lock);
    host->device_id=device_id;
    host->sent=0;
    host->refresh_at=0;
  }
  if(!device_id) return;
  u32 motors=enabled ? __atomic_load_n(&g_rumble[player].motors,__ATOMIC_ACQUIRE) : 0;
  if(!motors && !host->sent) return;
  u64 now=plat_ns();
  if(motors==host->sent && now<host->refresh_at) return;
  int applied=backend_rumble(player,(u16)motors,(u16)(motors>>16),motors?1000:0);
  if(motors && !host->sent) LOGV("hid: player %d rumble %s\n",player+1,applied?"started":"unavailable");
  host->sent=motors;
  host->refresh_at=now+500000000ull;
}

void hid_rumble_stop(void){
  for(int player=0;player<2;player++) hid_rumble_update(player,g_host_rumble[player].device_id,0);
}

static void vibration_send_many(IpcCtx* c){
  u64 handles, handle_bytes, values, value_bytes;
  if(!buf_in(c,0,&handles,&handle_bytes) || !buf_in(c,1,&values,&value_bytes) ||
     !handle_bytes || handle_bytes%sizeof(u32) || handle_bytes>20*sizeof(u32)) return;
  u32 count=(u32)(handle_bytes/sizeof(u32));
  if(value_bytes!=count*sizeof(VibrationValue) ||
     !guest_span_readable(handles,handle_bytes,1) || !guest_span_readable(values,value_bytes,1)) return;
  pm_lock(&g_rumble_lock);
  u32 changed=0;
  for(u32 i=0;i<count;i++){
    u32 handle=gr32(handles+i*sizeof(u32));
    VibrationValue value;
    memcpy(&value,GP(values+i*sizeof(value)),sizeof(value));
    changed|=vibration_set(vibration_player(handle),handle>>16,value);
  }
  for(int player=0;player<2;player++) if(changed&(1u<<player)) vibration_publish(player);
  pm_unlock(&g_rumble_lock);
}

static u64 g_hold_type=0, g_comm_mode=0, g_handheld_mode=0;

static int hid_disp(SvcObj* o, IpcCtx* c){
  switch(c->cmd){
    case 0: out_obj(c,svcobj_new("IAppletResource",hid_applet_res,0)); return 0;
    case 40: out_copy_h(c,h_new(&kevent_new("xpad id",0)->o)); return 0;         /* AcquireXpadIdEventHandle */
    case 55: case 59: out64(c,0); return 0;                                        /* GetXpadIds: none */
    case 58: case 62: out_copy_h(c,h_new(&kshmem_new(0x1000,"hid lifo")->o)); return 0;
    case 68: case 82: out8(c,1); return 0;                                         /* IsSixAxisSensorFusionEnabled / AtRest */
    case 69: case 70: case 71: case 72: case 73: case 74: case 75: case 76: case 77: case 78: case 79: case 80: case 81: case 83: case 84: case 85: case 86: case 87: case 88: case 89:
      if(c->cmd==71||c->cmd==73||c->cmd==79||c->cmd==84||c->cmd==86||c->cmd==88){ out32(c,0); out32(c,0); } return 0;
    case 100: __atomic_store_n(&g_style_supported,in32(c,0),__ATOMIC_RELAXED); no1_setup(); return 0; /* SetSupportedNpadStyleSet */
    case 101: out32(c,__atomic_load_n(&g_style_supported,__ATOMIC_RELAXED)); return 0;
    case 102: { /* SetSupportedNpadIdType: only choose Handheld when the title requests that ID. */
      u64 address, size;
      if(buf_in(c,0,&address,&size) && address>=AS_BASE && address<AS_SIZE && size<=10*4 && !(size&3)){
        MemBlock block;
        mem_query(address,&block);
        if((block.perm&PERM_R) && address+size<=block.addr+block.size){
          int handheld=0;
          for(u64 offset=0;offset<size;offset+=4) if(gr32(address+offset)==0x20) handheld=1;
          __atomic_store_n(&g_handheld_id_supported,handheld,__ATOMIC_RELAXED);
          no1_setup();
        }
      }
      return 0; }
    case 106: { u32 id=in32(c,0); int i= id==0x20? 8 : id==0x10? 9 : (int)(id&7);
      pm_lock(&g_style_lock);
      if(!g_style_ev[i]){ g_style_ev[i]=kevent_new("npad style",0); kobj_ref(&g_style_ev[i]->o); kevent_signal(g_style_ev[i]); }
      KEvent* ev=g_style_ev[i];
      pm_unlock(&g_style_lock);
      out_copy_h(c,h_new(&ev->o)); return 0; }
    case 108: { u32 id=in32(c,0); u64 led= id<8? (1ull<<id) : 0; out64(c,led); return 0; }   /* GetPlayerLedPattern */
    case 120: g_hold_type=in64(c,8); return 0;
    case 121: out64(c,g_hold_type); return 0;                                      /* GetNpadJoyHoldType */
    case 127: g_handheld_mode=in64(c,8); return 0;
    case 128: out64(c,g_handheld_mode); return 0;                                  /* GetNpadHandheldActivationMode */
    case 129: out32(c,0); return 0;                                                /* GetNpadFullKeyGripColor... */
    case 133: case 134: case 135: case 136: case 137: case 138: out8(c,0); return 0;
    case 200: { u32 h=in32(c,0); u32 dev=(h>>16)&0xFF; out32(c,1); out32(c,dev==0? 1 : 2); return 0; }  /* GetVibrationDeviceInfo: LRA, left/right */
    case 201: case 213: { /* SendVibrationValue / InMode */
      u32 offset=c->cmd==213?8:4;
      if(c->raw_size<offset+sizeof(VibrationValue)) return 0;
      u32 handle=in32(c,0);
      if(c->cmd==213 && vibration_player(in32(c,4))>=0) handle=in32(c,4);
      int player=vibration_player(handle);
      if(player<0) return 0;
      VibrationValue value;
      memcpy(&value,c->raw+offset,sizeof(value));
      pm_lock(&g_rumble_lock);
      if(vibration_set(player,handle>>16,value)) vibration_publish(player);
      pm_unlock(&g_rumble_lock);
      return 0; }
    case 202: { /* GetActualVibrationValue */
      u32 handle=in32(c,0);
      int player=vibration_player(handle);
      VibrationValue value=vibration_off;
      pm_lock(&g_rumble_lock);
      if(player>=0 && g_rumble[player].device_id) value=g_rumble[player].side[handle>>16];
      pm_unlock(&g_rumble_lock);
      outbytes(c,&value,sizeof(value)); return 0; }
    case 203: out_obj(c,svcobj_new("IActiveVibrationDeviceList",hid_vibration_list,0)); return 0;
    case 204: case 209: case 210: /* PermitVibration / BeginPermitVibrationSession / EndPermitVibrationSession */
      pm_lock(&g_rumble_lock);
      if(c->cmd==204) g_rumble_permitted=in8(c,0)!=0;
      else g_rumble_session=c->cmd==209;
      if(!g_rumble_permitted && !g_rumble_session){ vibration_clear(0); vibration_clear(1); }
      pm_unlock(&g_rumble_lock);
      return 0;
    case 205: /* IsVibrationPermitted */
      pm_lock(&g_rumble_lock);
      out8(c,g_rumble_permitted);
      pm_unlock(&g_rumble_lock);
      return 0;
    case 206: case 214: vibration_send_many(c); return 0; /* SendVibrationValues / InMode */
    case 211: case 220: { /* IsVibrationDeviceMounted / IsOunceVibrationDeviceMounted */
      int player=vibration_player(in32(c,0));
      pm_lock(&g_rumble_lock);
      out8(c,player>=0 && g_rumble[player].device_id!=0);
      pm_unlock(&g_rumble_lock);
      return 0; }
    case 208: out32(c,0); return 0;
    case 400: out8(c,0); return 0;                                                 /* IsUsbFullKeyControllerEnabled */
    case 1000: g_comm_mode=in64(c,8); return 0;
    case 1001: out64(c,g_comm_mode); return 0;
    case 1003: out8(c,0); return 0;
    case 103: case 104: case 107: case 109: case 122: case 123: case 124: case 125: case 126: case 130: case 131: case 132:
    case 207: case 212:
    case 1002: case 1004:
    case 300: case 301: case 302: case 303: case 304: case 305: case 306: case 307: case 308: case 309: case 310: case 311: case 312: case 313: case 314: case 315: case 316: case 317:
    case 60: case 61: case 63: case 64: case 65: case 66: case 67: case 91:
    case 1: case 11: case 21: case 31: case 32: case 51: case 56: return 0;
  }
  return stub_ok(o,c); }

static SvcObj* new_hid(void){ return svcobj_new("hid",hid_disp,0); }

static int hidsys_disp(SvcObj* o, IpcCtx* c){ (void)o; (void)c; return 0; }

static SvcObj* new_hidsys(void){ return svcobj_new("hid:sys",hidsys_disp,0); }

/* No1 is one controller so it gets exactly one style bit: a pro controller if the game takes it, if not dual
   joycons. two bits at once (FullKey|JoyDual) never happens on hw and nn::hid::GetVibrationDeviceHandles aborts on
   it (kirby and the forgotten land at boot) */
static void no1_setup(void){
  if(!g_hid_shm) return;
  u8* b=kshmem_ptr(g_hid_shm);
  int handheld=primary_is_handheld();
  player_setup(b,0,handheld?0:player_style());
  player_setup(b,8,handheld?2:0);
}

void svc_hid_init(void){
  pm_init(&g_style_lock);
  pm_init(&g_rumble_lock);
  g_hid_shm=kshmem_new(0x40000,"hid"); kobj_ref(&g_hid_shm->o);
  no1_setup();
  hid_update(); hid_update();
  svc_register("hid",new_hid); svc_register("hid:sys",new_hidsys);
}
