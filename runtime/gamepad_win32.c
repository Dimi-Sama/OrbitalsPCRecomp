/* Win32 gamepads. SDL handles HID and XInput as one inventory. XInput alone
   remains available on installations without the optional SDL3 DLL. */
#include "gamepad_win32.h"
#include <windows.h>
#include <xinput.h>
#include <stdbool.h>

typedef struct SDL_Gamepad SDL_Gamepad;
static struct {
  bool (*Init)(u32);
  u32* (*GetGamepads)(int*);
  u32* (*GetJoysticks)(int*);
  bool (*IsGamepad)(u32);
  const char* (*GetJoystickNameForID)(u32);
  u16 (*GetJoystickVendorForID)(u32);
  u16 (*GetJoystickProductForID)(u32);
  SDL_Gamepad* (*OpenGamepad)(u32);
  void (*CloseGamepad)(SDL_Gamepad*);
  bool (*GamepadConnected)(SDL_Gamepad*);
  bool (*GetGamepadButton)(SDL_Gamepad*,int);
  i16 (*GetGamepadAxis)(SDL_Gamepad*,int);
  bool (*RumbleGamepad)(SDL_Gamepad*,u16,u16,u32);
  void (*SetJoystickEventsEnabled)(bool);
  void (*SetGamepadEventsEnabled)(bool);
  void (*UpdateGamepads)(void);
  void (*free)(void*);
} sdl;
static bool sdl_active;
static struct { u32 id; SDL_Gamepad* handle; } sdl_slots[WIN_GAMEPAD_SLOTS];
static ULONGLONG next_scan;
static DWORD (WINAPI *xinput_get)(DWORD, XINPUT_STATE*);
static DWORD (WINAPI *xinput_set)(DWORD, XINPUT_VIBRATION*);
static u32 xinput_slots[WIN_GAMEPAD_SLOTS];

static bool load_sdl(void){
  HMODULE lib=LoadLibraryExW(L"SDL3.dll",NULL,LOAD_LIBRARY_SEARCH_APPLICATION_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
  if(!lib) return false;
#define SDL_BIND(name) do { \
    sdl.name=(__typeof__(sdl.name))GetProcAddress(lib,"SDL_" #name); \
    if(!sdl.name){ FreeLibrary(lib); return false; } \
  } while(0)
  SDL_BIND(Init);
  SDL_BIND(GetGamepads);
  SDL_BIND(GetJoysticks);
  SDL_BIND(IsGamepad);
  SDL_BIND(GetJoystickNameForID);
  SDL_BIND(GetJoystickVendorForID);
  SDL_BIND(GetJoystickProductForID);
  SDL_BIND(OpenGamepad);
  SDL_BIND(CloseGamepad);
  SDL_BIND(GamepadConnected);
  SDL_BIND(GetGamepadButton);
  SDL_BIND(GetGamepadAxis);
  SDL_BIND(SetJoystickEventsEnabled);
  SDL_BIND(SetGamepadEventsEnabled);
  SDL_BIND(UpdateGamepads);
  SDL_BIND(free);
#undef SDL_BIND
  sdl.RumbleGamepad=(__typeof__(sdl.RumbleGamepad))GetProcAddress(lib,"SDL_RumbleGamepad");
  if(!sdl.Init(0x2000)){ FreeLibrary(lib); return false; } /* SDL_INIT_GAMEPAD */
  sdl.SetGamepadEventsEnabled(false);
  sdl.SetJoystickEventsEnabled(false);
  return true;
}

void win_gamepads_init(void){
  const wchar_t* libraries[]={L"xinput1_4.dll", L"xinput1_3.dll", L"xinput9_1_0.dll"};
  for(unsigned i=0;i<sizeof libraries/sizeof libraries[0] && !xinput_get;i++){
    HMODULE lib=LoadLibraryExW(libraries[i],NULL,LOAD_LIBRARY_SEARCH_SYSTEM32);
    if(lib){
      xinput_get=(__typeof__(xinput_get))GetProcAddress(lib,"XInputGetState");
      if(xinput_get) xinput_set=(__typeof__(xinput_set))GetProcAddress(lib,"XInputSetState");
    }
  }
  const char* backend=getenv("SWR_GAMEPAD_BACKEND");
  if(!backend || strcmp(backend,"xinput")) sdl_active=load_sdl();
}

const char* win_gamepads_backend(void){
  return sdl_active ? "SDL3" : xinput_get ? "XInput" : "unavailable";
}

static i32 deadzone(i32 value){ return value>-7000 && value<7000 ? 0 : value; }
static i32 sdl_vertical(i16 value){ return deadzone(value==INT16_MIN ? INT16_MAX : -value); }

static void sdl_scan(void){
  for(int i=0;i<WIN_GAMEPAD_SLOTS;i++){
    if(!sdl_slots[i].handle || sdl.GamepadConnected(sdl_slots[i].handle)) continue;
    sdl.CloseGamepad(sdl_slots[i].handle);
    sdl_slots[i].handle=NULL;
    sdl_slots[i].id=0;
  }
  u32* ids=sdl.GetGamepads(NULL);
  if(!ids) return;
  for(int i=0;i<WIN_GAMEPAD_SLOTS;i++){
    if(sdl_slots[i].id) continue;
    for(const u32* id=ids;*id;id++){
      if(*id==sdl_slots[1-i].id) continue;
      SDL_Gamepad* handle=sdl.OpenGamepad(*id);
      if(!handle) continue;
      sdl_slots[i].id=*id;
      sdl_slots[i].handle=handle;
      break;
    }
  }
  sdl.free(ids);
}

static void sdl_pad(int i, WinGamepad* out){
  SDL_Gamepad* pad=sdl_slots[i].handle;
  if(!pad || !sdl.GamepadConnected(pad)) return;
  out->id=sdl_slots[i].id;
  const char* name=sdl.GetJoystickNameForID(out->id);
  snprintf(out->name,sizeof out->name,"%s",name ? name : "SDL gamepad");
  out->vendor=sdl.GetJoystickVendorForID(out->id);
  out->product=sdl.GetJoystickProductForID(out->id);
  /* Switch button bits indexed by SDL's positional button enum. */
  static const int bits[]={1,0,3,2,11,-1,10,4,5,6,7,13,15,12,14};
  for(unsigned b=0;b<sizeof bits/sizeof bits[0];b++)
    if(bits[b]>=0 && sdl.GetGamepadButton(pad,(int)b)) out->pad.buttons|=1ull<<bits[b];
  out->pad.lx=deadzone(sdl.GetGamepadAxis(pad,0));
  out->pad.ly=sdl_vertical(sdl.GetGamepadAxis(pad,1));
  out->pad.rx=deadzone(sdl.GetGamepadAxis(pad,2));
  out->pad.ry=sdl_vertical(sdl.GetGamepadAxis(pad,3));
  out->zl=(u16)sdl.GetGamepadAxis(pad,4);
  out->zr=(u16)sdl.GetGamepadAxis(pad,5);
}

static void xinput_poll(WinGamepad pads[WIN_GAMEPAD_SLOTS]){
  if(!xinput_get) return;
  u32* slots=xinput_slots;
  XINPUT_STATE states[XUSER_MAX_COUNT];
  bool connected[XUSER_MAX_COUNT];
  for(DWORD i=0;i<XUSER_MAX_COUNT;i++) connected[i]=xinput_get(i,&states[i])==ERROR_SUCCESS;
  for(int i=0;i<WIN_GAMEPAD_SLOTS;i++)
    if(slots[i] && !connected[slots[i]-1]) slots[i]=0;
  for(int i=0;i<WIN_GAMEPAD_SLOTS;i++){
    if(!slots[i]){
      for(u32 id=1;id<=XUSER_MAX_COUNT;id++)
        if(connected[id-1] && id!=slots[1-i]){ slots[i]=id; break; }
    }
    if(!slots[i]) continue;
    WinGamepad* out=&pads[i];
    const XINPUT_GAMEPAD* pad=&states[slots[i]-1].Gamepad;
    static const WORD buttons[]={
      XINPUT_GAMEPAD_B, XINPUT_GAMEPAD_A, XINPUT_GAMEPAD_Y, XINPUT_GAMEPAD_X,
      XINPUT_GAMEPAD_LEFT_THUMB, XINPUT_GAMEPAD_RIGHT_THUMB, XINPUT_GAMEPAD_LEFT_SHOULDER,
      XINPUT_GAMEPAD_RIGHT_SHOULDER, 0, 0, XINPUT_GAMEPAD_START, XINPUT_GAMEPAD_BACK,
      XINPUT_GAMEPAD_DPAD_LEFT, XINPUT_GAMEPAD_DPAD_UP, XINPUT_GAMEPAD_DPAD_RIGHT, XINPUT_GAMEPAD_DPAD_DOWN
    };
    for(unsigned b=0;b<sizeof buttons/sizeof buttons[0];b++)
      if(pad->wButtons&buttons[b]) out->pad.buttons|=1ull<<b;
    out->id=slots[i];
    snprintf(out->name,sizeof out->name,"XInput %u",slots[i]-1);
    out->pad.lx=deadzone(pad->sThumbLX); out->pad.ly=deadzone(pad->sThumbLY);
    out->pad.rx=deadzone(pad->sThumbRX); out->pad.ry=deadzone(pad->sThumbRY);
    out->zl=(u16)(pad->bLeftTrigger*32767u/255u); out->zr=(u16)(pad->bRightTrigger*32767u/255u);
  }
}

void win_gamepads_poll(WinGamepad pads[WIN_GAMEPAD_SLOTS]){
  memset(pads,0,sizeof *pads*WIN_GAMEPAD_SLOTS);
  if(sdl_active){
    sdl.UpdateGamepads();
    ULONGLONG now=GetTickCount64();
    if(now>=next_scan){ sdl_scan(); next_scan=now+250; }
    for(int i=0;i<WIN_GAMEPAD_SLOTS;i++) sdl_pad(i,&pads[i]);
  }else xinput_poll(pads);
  for(int i=0;i<WIN_GAMEPAD_SLOTS;i++){
    if(pads[i].zl>7710) pads[i].pad.buttons|=1ull<<8;
    if(pads[i].zr>7710) pads[i].pad.buttons|=1ull<<9;
  }
}

int win_gamepads_rumble(int player, u16 low, u16 high, u32 duration_ms){
  if(sdl_active){
    SDL_Gamepad* pad=sdl_slots[player].handle;
    return pad && sdl.RumbleGamepad && sdl.RumbleGamepad(pad,low,high,duration_ms);
  }
  u32 id=xinput_slots[player];
  XINPUT_VIBRATION motors={low,high};
  return id && xinput_set && xinput_set(id-1,&motors)==ERROR_SUCCESS;
}

void win_gamepads_inventory(void){
  printf("backend\t%s\n",win_gamepads_backend());
  if(sdl_active){
    u32* ids=sdl.GetJoysticks(NULL);
    if(ids){
      for(const u32* id=ids;*id;id++){
        gamepad_report(sdl.GetJoystickNameForID(*id),sdl.IsGamepad(*id));
      }
      sdl.free(ids);
    }
    return;
  }
  if(xinput_get) for(DWORD i=0;i<XUSER_MAX_COUNT;i++){
    XINPUT_STATE state;
    if(xinput_get(i,&state)==ERROR_SUCCESS){
      char name[32];
      snprintf(name,sizeof name,"XInput controller %lu",(unsigned long)i+1);
      gamepad_report(name,1);
    }
  }
}
