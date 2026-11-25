/* Enumerate Windows controllers and monitor the same slot assignment as Orbitals. */
#define COBJMACROS
#define DIRECTINPUT_VERSION 0x0800
#include <windows.h>
#include <dinput.h>
#include "gamepad_win32.h"

static BOOL CALLBACK print_directinput(const DIDEVICEINSTANCEA* device, void* unused){
  (void)unused;
  fprintf(stdout,"DirectInput: %s (VID:PID %04lx:%04lx)\n",device->tszProductName,
          (unsigned long)(device->guidProduct.Data1&0xffff),
          (unsigned long)(device->guidProduct.Data1>>16));
  return DIENUM_CONTINUE;
}

int main(int argc, char** argv){
  char* end;
  unsigned long seconds=argc>1 ? strtoul(argv[1],&end,10) : 30;
  if((argc>1 && (end==argv[1] || *end)) || seconds>3600){
    fprintf(stderr,"Usage: gamepad-probe.exe [seconds 0..3600]\n");
    return 2;
  }
  IDirectInput8A* direct=NULL;
  if(SUCCEEDED(DirectInput8Create(GetModuleHandleA(NULL),DIRECTINPUT_VERSION,&IID_IDirectInput8A,(void**)&direct,NULL))){
    IDirectInput8_EnumDevices(direct,DI8DEVCLASS_GAMECTRL,print_directinput,NULL,DIEDFL_ATTACHEDONLY);
    IDirectInput8_Release(direct);
  }
  win_gamepads_init();
  win_gamepads_inventory(stdout);
  WinGamepad last[WIN_GAMEPAD_SLOTS]={{0}};
  ULONGLONG start=GetTickCount64(), elapsed;
  do {
    elapsed=GetTickCount64()-start;
    WinGamepad pads[WIN_GAMEPAD_SLOTS];
    win_gamepads_poll(pads);
    for(unsigned i=0;i<WIN_GAMEPAD_SLOTS;i++){
      WinGamepad* p=&pads[i],*old=&last[i];
      if(p->id!=old->id || elapsed==0){
        printf("%5llu ms  P%u Npad %u  %s  ID %u VID:PID %04x:%04x\n",
               (unsigned long long)elapsed,i+1,i,p->id?p->name:"disconnected",p->id,p->vendor,p->product);
      }
      if(p->id && (p->id!=old->id || p->pad.buttons!=old->pad.buttons ||
         p->pad.lx!=old->pad.lx || p->pad.ly!=old->pad.ly || p->pad.rx!=old->pad.rx || p->pad.ry!=old->pad.ry ||
         p->zl!=old->zl || p->zr!=old->zr)){
        printf("%5llu ms  P%u buttons=0x%04llx A=%d Plus=%d sticks=%d,%d/%d,%d ZL=%u ZR=%u\n",
               (unsigned long long)elapsed,i+1,(unsigned long long)p->pad.buttons,
               !!(p->pad.buttons&1),!!(p->pad.buttons&(1ull<<10)),
               p->pad.lx,p->pad.ly,p->pad.rx,p->pad.ry,p->zl,p->zr);
      }
      *old=*p;
    }
    fflush(stdout);
    if(elapsed>=seconds*1000) break;
    Sleep(33);
  } while(1);
  return 0;
}
