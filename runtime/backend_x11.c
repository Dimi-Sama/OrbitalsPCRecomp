/* SwitchRecomp - Copyright 2026 MZ Labs
   Licensed under the GNU Affero General Public License v3.0, see LICENSE.txt and NOTICE.txt.
   Forks and derived works have to keep the credit to SwitchRecomp by MZ Labs and the startup screen. */
/* X11 backend (Wayland desktops run it through XWayland), with Vulkan NVN or GLX 4.3.
   Controllers come from SDL2, loaded at run time. F1 help F3 screenshot F4 fps limit F5
   trace F8 full res screenshot F11/Alt+Enter fullscreen Esc quit. the Xvfb tests run on this too (screenshots,
   scripted input) */
#include "rt.h"
#include "desktop_input.h"
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/Xatom.h>
#include <X11/XKBlib.h>
#include <X11/keysym.h>
#include <GL/glx.h>
#include "window_config.h"
#include <dlfcn.h>
#include <time.h>

static Display* dpy; static Window win; static Atom wm_delete, a_state, a_fs; static Cursor g_blank;
static volatile int g_ww=1280, g_wh=720; static int g_fullscreen=0, g_want_fs=1;
static int g_seconds=0, g_maxframes=-1; static char g_shot[1024]; static u64 g_start; static u64 g_press=0, g_press_at=0, g_press_len=300;
static char g_script[8192], g_script2[8192]; static char g_title[256]; static volatile int g_shot_req;
static int g_kb_player=1;
static u64 keys_held;
static int mouse_mode, mouse_invert, mouse_sensitivity=100;
static int mouse_focused, mouse_captured, mouse_x, mouse_y, mouse_moved;
static u64 mouse_buttons, mouse_time;
extern int g_opt_fps;

void backend_ini(const char* k, const char* v){
  if(!strcmp(k,"fullscreen")) g_want_fs=atoi(v);
  else if(!strcmp(k,"seconds")) g_seconds=atoi(v);
  else if(!strcmp(k,"frames")) g_maxframes=atoi(v);
  else if(!strcmp(k,"shot")) strncpy(g_shot,v,1023);
  else if(!strcmp(k,"press")) g_press=strtoull(v,NULL,16);
  else if(!strcmp(k,"press_at")) g_press_at=strtoull(v,NULL,10);
  else if(!strcmp(k,"press_len")) g_press_len=strtoull(v,NULL,10);
  else if(!strcmp(k,"script")) strncpy(g_script,v,8191);
  else if(!strcmp(k,"script2")) strncpy(g_script2,v,8191);
  else if(!strcmp(k,"keyboard_player")) g_kb_player=atoi(v)==2? 2 : 1;
  else if(!strcmp(k,"mouse_right_stick")) mouse_mode=atoi(v)!=0;
  else if(!strcmp(k,"mouse_sensitivity")) mouse_sensitivity=mouse_sensitivity_percent(v);
  else if(!strcmp(k,"mouse_invert")) mouse_invert=atoi(v)&3;
  else if(!strcmp(k,"renderer")){
    extern int g_edenvk_want;
    int vulkan=!strcmp(v,"vulkan");
#ifdef SWR_HAVE_NVN
    static int set_nvn;
    if(vulkan && !getenv("SWR_GPU")){ setenv("SWR_GPU","nvn",1); set_nvn=1; }
    else if(!vulkan && set_nvn){ unsetenv("SWR_GPU"); set_nvn=0; }
    if(vulkan){ setenv("NXRT_GFX","vulkan",0); }
    g_edenvk_want=!strcmp(v,"eden");
#else
    g_edenvk_want=vulkan || !strcmp(v,"eden");
#endif
  }
}

/* renderer=vulkan: what the Vulkan surface is made from (1 = Xlib) */
int backend_vk_window(void** display, void** surface, int* w, int* h){
  /* its own connection: the Vulkan driver's WSI and GLX on one Display from two threads ended in "XIO: fatal IO error 11" */
  static Display* vdpy; if(!vdpy) vdpy=XOpenDisplay(NULL); if(!vdpy) return 0;
  *display=vdpy; *surface=(void*)(uintptr_t)win; *w=g_ww; *h=g_wh; return 1; }

int video_has_gl(void){ return 1; }

/* ---------------------------------------------------------------- SDL2 game controllers, loaded dynamically */
typedef void SDLGC;
static struct {
  int (*Init)(u32); int (*SetHint)(const char*, const char*); int (*NumJoysticks)(void); int (*IsGameController)(int);
  i32 (*InstanceID)(int);
  SDLGC* (*Open)(int); int (*Attached)(SDLGC*); void (*Close)(SDLGC*); void (*Update)(void);
  u8 (*Button)(SDLGC*, int); i16 (*Axis)(SDLGC*, int); const char* (*Name)(SDLGC*);
  const char* (*DeviceName)(int);
  int (*Rumble)(SDLGC*, u16, u16, u32);
} sdl;

static SDLGC* g_pad_gc[2];
static i32 g_pad_id[2]={-1,-1};
static u64 g_pad_scan;

static void sdl_load(void){
  /* SDL_Init installs SIGINT/SIGTERM handlers that turn the signal into an SDL_QUIT event, which this backend never reads (the window
     is X11's): SIGTERM from Steam's Stop, orbitals-deck.sh or the launcher then did nothing and only SIGKILL ended the game. Without
     them the signals keep their default action. The environment variable reaches SDL_audio's init too (audio.c) */
  setenv("SDL_NO_SIGNAL_HANDLERS","1",0);
  void* h=dlopen("libSDL2-2.0.so.0",RTLD_NOW|RTLD_LOCAL); if(!h) h=dlopen("libSDL2.so",RTLD_NOW|RTLD_LOCAL);
  if(!h) return;
  void** f[]={(void**)&sdl.Init,(void**)&sdl.SetHint,(void**)&sdl.NumJoysticks,(void**)&sdl.IsGameController,(void**)&sdl.Open,(void**)&sdl.Attached,
              (void**)&sdl.Close,(void**)&sdl.Update,(void**)&sdl.Button,(void**)&sdl.Axis,(void**)&sdl.Name};
  const char* n[]={"SDL_Init","SDL_SetHint","SDL_NumJoysticks","SDL_IsGameController","SDL_GameControllerOpen","SDL_GameControllerGetAttached",
                   "SDL_GameControllerClose","SDL_GameControllerUpdate","SDL_GameControllerGetButton","SDL_GameControllerGetAxis","SDL_GameControllerName"};
  for(int i=0;i<11;i++){ *f[i]=dlsym(h,n[i]); if(!*f[i]){ memset(&sdl,0,sizeof sdl); return; } }
  sdl.InstanceID=dlsym(h,"SDL_JoystickGetDeviceInstanceID");
  sdl.DeviceName=dlsym(h,"SDL_JoystickNameForIndex");
  sdl.Rumble=dlsym(h,"SDL_GameControllerRumble");
  /* buttons by position like on windows, also for nintendo controllers that SDL would map by label */
  sdl.SetHint("SDL_GAMECONTROLLER_USE_BUTTON_LABELS","0");
  sdl.SetHint("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS","1");
  if(sdl.Init(0x2000 /* SDL_INIT_GAMECONTROLLER */)){ memset(&sdl,0,sizeof sdl); return; }
}

void backend_list_gamepads(void){
  sdl_load();
  printf("backend\t%s\n",sdl.Init?"SDL2":"unavailable");
  if(!sdl.Init) return;
  int count=sdl.NumJoysticks();
  for(int i=0;i<count;i++) gamepad_report(sdl.DeviceName?sdl.DeviceName(i):NULL,sdl.IsGameController(i));
}

static i32 dz(i32 v){ return (v>-7000 && v<7000)? 0 : v; }

static void pad_scan(void){
  if(!sdl.Init) return;
  sdl.Update();
  for(int slot=0;slot<2;slot++){
    if(!g_pad_gc[slot] || sdl.Attached(g_pad_gc[slot])) continue;
    sdl.Close(g_pad_gc[slot]); g_pad_gc[slot]=NULL; g_pad_id[slot]=-1;
    LOG("controllers: player %d disconnected\n",slot+1);
  }
  u64 now=plat_ns();
  if((g_pad_gc[0] && g_pad_gc[1]) || now-g_pad_scan<500000000ull) return;
  g_pad_scan=now;
  int count=sdl.NumJoysticks();
  for(int i=0;i<count && !(g_pad_gc[0] && g_pad_gc[1]);i++){
    if(!sdl.IsGameController(i)) continue;
    int slot=g_pad_gc[0]? 1 : 0;
    if(!sdl.InstanceID && slot==1) break;   // old SDL2 can still supply player one
    i32 id=sdl.InstanceID? sdl.InstanceID(i) : 0;
    if(id<0 || id==g_pad_id[0] || id==g_pad_id[1]) continue;
    SDLGC* pad=sdl.Open(i);
    if(!pad) continue;
    g_pad_gc[slot]=pad; g_pad_id[slot]=id;
    const char* name=sdl.Name(pad);
    LOG("controllers: player %d: %s\n",slot+1,name? name : "connected");
  }
}

static void pad_read(SDLGC* g, PadState* pad){
  if(!g) return;
  /* SDL names buttons by Xbox position: A bottom, B right, X left, Y top */
  static const struct { int sdl, bit; } m[]={{1,0},{0,1},{3,2},{2,3},{7,4},{8,5},{9,6},{10,7},{6,10},{4,11},{13,12},{11,13},{14,14},{12,15}};
  for(unsigned i=0;i<sizeof m/sizeof m[0];i++) if(sdl.Button(g,m[i].sdl)) pad->buttons|=1ull<<m[i].bit;
  if(sdl.Axis(g,4)>7700) pad->buttons|=1ull<<8; if(sdl.Axis(g,5)>7700) pad->buttons|=1ull<<9;
  /* SDL's Y axes point down, the Switch's up */
  i32 x=sdl.Axis(g,0), y=-(i32)sdl.Axis(g,1), x2=sdl.Axis(g,2), y2=-(i32)sdl.Axis(g,3);
  if(y>32767) y=32767; if(y2>32767) y2=32767;
  if(!pad->lx && !pad->ly){ pad->lx=dz(x); pad->ly=dz(y); }
  if(!pad->rx && !pad->ry){ pad->rx=dz(x2); pad->ry=dz(y2); }
}

/* ---------------------------------------------------------------- window */
static void set_fullscreen(int on){
  if(on==g_fullscreen) return;
  XEvent e; memset(&e,0,sizeof e); e.xclient.type=ClientMessage; e.xclient.window=win; e.xclient.message_type=a_state; e.xclient.format=32;
  e.xclient.data.l[0]=on? 1 : 0; e.xclient.data.l[1]=(long)a_fs; e.xclient.data.l[3]=1;
  XSendEvent(dpy,DefaultRootWindow(dpy),False,SubstructureRedirectMask|SubstructureNotifyMask,&e);
  if(on) XDefineCursor(dpy,win,g_blank); else XUndefineCursor(dpy,win);
  XFlush(dpy); g_fullscreen=on; }

static void set_title(const char* t){ XStoreName(dpy,win,t); XFlush(dpy); }

static const char* HELP=
  "SwitchRecomp - controls\n\n"
  "Controller: same as the Switch controller (buttons by position).\n\n"
  "Keyboard:\n"
  "  Arrows = D-Pad     W A S D = Left stick    I J K L = Right stick\n"
  "  X / Space = A    Z = B    C = X    V = Y\n"
  "  Q = L   E = R   1 = ZL   3 = ZR   Enter = +   Backspace = -\n\n"
  "F2 = toggle mouse camera (left click = ZR, right click = ZL)\n"
  "F1 = this help   F3 = screenshot   F4 = FPS limit 60 / unlimited   F5 = diagnostic dump (trace)\n"
  "F8 = instant full-resolution screenshot (PNG in the captures folder)\n"
  "F11 / Alt+Enter = fullscreen   Esc = quit";

/* the screen stays on while the game runs: a player with only a gamepad (the Steam Deck's controls in desktop mode) gives the desktop no
   keyboard or mouse activity, KDE / GNOME turn the screen off after a few minutes and FIFO presents then wait for it (the game froze at
   2 presents a second). org.freedesktop.ScreenSaver.Inhibit through libdbus, loaded at run time; the inhibition lasts as long as the
   connection, i.e. the process. SWR_ALLOW_SCREENSAVER=1 leaves the desktop's settings alone. gamescope (game mode) has no screen saver */
static void screensaver_inhibit(void){
  if(getenv("SWR_ALLOW_SCREENSAVER")) return;
  void* h=dlopen("libdbus-1.so.3",RTLD_NOW|RTLD_LOCAL); if(!h){ LOG("screen saver: libdbus not found, not inhibited\n"); return; }
  void* (*bus_get)(int,void*)=(void*(*)(int,void*))dlsym(h,"dbus_bus_get");
  void* (*new_call)(const char*,const char*,const char*,const char*)=(void*(*)(const char*,const char*,const char*,const char*))dlsym(h,"dbus_message_new_method_call");
  int (*append)(void*,int,...)=(int(*)(void*,int,...))dlsym(h,"dbus_message_append_args");
  void* (*call)(void*,void*,int,void*)=(void*(*)(void*,void*,int,void*))dlsym(h,"dbus_connection_send_with_reply_and_block");
  int (*get_args)(void*,void*,int,...)=(int(*)(void*,void*,int,...))dlsym(h,"dbus_message_get_args");
  void (*unref)(void*)=(void(*)(void*))dlsym(h,"dbus_message_unref");
  void (*no_exit)(void*,unsigned)=(void(*)(void*,unsigned))dlsym(h,"dbus_connection_set_exit_on_disconnect");
  if(!bus_get || !new_call || !append || !call || !unref) return;
  void* conn=bus_get(0 /* DBUS_BUS_SESSION */,NULL); if(!conn){ LOG("screen saver: no session bus, not inhibited\n"); return; }
  if(no_exit) no_exit(conn,0);
  const char* app="Orbitals"; const char* why="Playing";
  static const char* svc[][2]={{"org.freedesktop.ScreenSaver","/org/freedesktop/ScreenSaver"},{"org.freedesktop.ScreenSaver","/ScreenSaver"}};
  for(int i=0;i<2;i++){
    void* m=new_call(svc[i][0],svc[i][1],"org.freedesktop.ScreenSaver","Inhibit"); if(!m) continue;
    append(m,'s',&app,'s',&why,0 /* DBUS_TYPE_INVALID */);
    void* r=call(conn,m,1000,NULL); unref(m);
    if(r){ unsigned cookie=0; if(get_args) get_args(r,NULL,'u',&cookie,0); unref(r); LOG("screen saver: inhibited while the game runs (%s, cookie %u)\n",svc[i][1],cookie); return; }
  }
  LOG("screen saver: no org.freedesktop.ScreenSaver service, not inhibited\n");
}

void video_init(const char* title){
  snprintf(g_title,sizeof g_title,"%s  (F1 help)",title);   /* the SwitchRecomp credit stays on the startup screen and in README.md (NOTICE.txt) */
  XInitThreads();
  /* let mesa run its own glthread so the driver work isn't on our GPU thread (deck, AMD/intel on linux) */
  if(!getenv("SWR_NO_GLTHREAD")) setenv("mesa_glthread","true",0);
  dpy=XOpenDisplay(NULL); if(!dpy) fatal("No X11 display (DISPLAY is not set). Start the game from a desktop session.");
  int scr=DefaultScreen(dpy);
  int width=1280,height=720;
  startup_window_size(&width,&height); g_ww=width; g_wh=height;
  extern int g_gpu_nvn;
  long events=KeyPressMask|KeyReleaseMask|StructureNotifyMask|FocusChangeMask;
  if(g_gpu_nvn){
    win=XCreateSimpleWindow(dpy,RootWindow(dpy,scr),0,0,width,height,0,0,BlackPixel(dpy,scr));
    XSelectInput(dpy,win,events);
  }else{
    static int att[]={GLX_X_RENDERABLE,True,GLX_DRAWABLE_TYPE,GLX_WINDOW_BIT,GLX_RENDER_TYPE,GLX_RGBA_BIT,GLX_RED_SIZE,8,GLX_GREEN_SIZE,8,GLX_BLUE_SIZE,8,GLX_ALPHA_SIZE,8,GLX_DEPTH_SIZE,24,GLX_DOUBLEBUFFER,True,None};
    int n=0; GLXFBConfig* fc=glXChooseFBConfig(dpy,scr,att,&n); if(!fc||!n) fatal("Your graphics driver has no OpenGL support for this display (GLX).");
    XVisualInfo* vi=glXGetVisualFromFBConfig(dpy,fc[0]);
    XSetWindowAttributes swa; memset(&swa,0,sizeof swa); swa.colormap=XCreateColormap(dpy,RootWindow(dpy,vi->screen),vi->visual,AllocNone);
    swa.background_pixel=BlackPixel(dpy,scr);
    swa.event_mask=events;
    win=XCreateWindow(dpy,RootWindow(dpy,vi->screen),0,0,width,height,0,vi->depth,InputOutput,vi->visual,CWColormap|CWEventMask|CWBackPixel,&swa);
    XFree(vi); XFree(fc);
  }
  XStoreName(dpy,win,g_title);
  { XClassHint ch={(char*)"switchrecomp",(char*)"SwitchRecomp"}; XSetClassHint(dpy,win,&ch); }
  wm_delete=XInternAtom(dpy,"WM_DELETE_WINDOW",False); XSetWMProtocols(dpy,win,&wm_delete,1);
  a_state=XInternAtom(dpy,"_NET_WM_STATE",False); a_fs=XInternAtom(dpy,"_NET_WM_STATE_FULLSCREEN",False);
  { static char none[8]; XColor black; memset(&black,0,sizeof black);
    Pixmap p=XCreateBitmapFromData(dpy,win,none,8,8); g_blank=XCreatePixmapCursor(dpy,p,p,&black,&black,0,0); XFreePixmap(dpy,p); }
  /* without this X11 sends a release before every auto-repeated press */
  XkbSetDetectableAutoRepeat(dpy,True,NULL);
  /* start fullscreen: the window manager reads the state when the window is mapped */
  if(g_want_fs){ XChangeProperty(dpy,win,a_state,XA_ATOM,32,PropModeReplace,(unsigned char*)&a_fs,1); XDefineCursor(dpy,win,g_blank); g_fullscreen=1; }
  XMapWindow(dpy,win); XFlush(dpy);
  sdl_load();
  if(!sdl.Init) LOG("controllers: SDL2 unavailable (install libsdl2), keyboard and mouse still work\n");
  screensaver_inhibit();
  g_start=plat_ns();
  if(!g_gpu_nvn){ extern void gpu_gl_start(void); gpu_gl_start(); }
}

/* GPU thread */
static GLXContext ctx, wctxs[3]; static GLXFBConfig wfc; static volatile int g_wnext;

static int xerr_ignore(Display* d, XErrorEvent* e){ (void)d;(void)e; return 0; }

int backend_gl_create(void){
  int scr=DefaultScreen(dpy);
  static int att[]={GLX_X_RENDERABLE,True,GLX_DRAWABLE_TYPE,GLX_WINDOW_BIT,GLX_RENDER_TYPE,GLX_RGBA_BIT,GLX_RED_SIZE,8,GLX_GREEN_SIZE,8,GLX_BLUE_SIZE,8,GLX_ALPHA_SIZE,8,GLX_DOUBLEBUFFER,True,None};
  int n=0; GLXFBConfig* fc=glXChooseFBConfig(dpy,scr,att,&n); if(!fc||!n) return 0;
  typedef GLXContext (*CCA)(Display*,GLXFBConfig,GLXContext,Bool,const int*);
  CCA cca=(CCA)glXGetProcAddressARB((const GLubyte*)"glXCreateContextAttribsARB");
  static const int vers[4][2]={{4,6},{4,5},{4,4},{4,3}};
  int (*old)(Display*,XErrorEvent*)=XSetErrorHandler(xerr_ignore);
  for(int i=0;i<4 && !ctx && cca;i++){ int ca[]={0x2091,vers[i][0],0x2092,vers[i][1],0x9126,0x00000001,None}; ctx=cca(dpy,fc[0],NULL,True,ca); XSync(dpy,False);
    if(ctx){ for(int k=0;k<3;k++) wctxs[k]=cca(dpy,fc[0],ctx,True,ca); XSync(dpy,False); } }
  wfc=fc[0];
  XSetErrorHandler(old);
  if(!ctx){ fatal("Your graphics driver does not support OpenGL 4.3.\nPlease update Mesa or your GPU driver."); return 0; }
  glXMakeCurrent(dpy,win,ctx);
  extern int g_opt_vsync;
  typedef void (*SIE)(Display*,GLXDrawable,int); typedef int (*SIM)(unsigned);
  SIE sie=(SIE)glXGetProcAddressARB((const GLubyte*)"glXSwapIntervalEXT"); SIM sim=(SIM)glXGetProcAddressARB((const GLubyte*)"glXSwapIntervalMESA");
  if(sie) sie(dpy,win,g_opt_vsync? 1 : 0); else if(sim) sim(g_opt_vsync? 1 : 0);
  return 1; }

void* backend_gl_proc(const char* n){ return (void*)glXGetProcAddressARB((const GLubyte*)n); }

void backend_gl_swap(void){ glXSwapBuffers(dpy,win); }

/* each compile thread takes the next shared context */
int backend_gl_worker_current(void){
  int k=__atomic_fetch_add(&g_wnext,1,__ATOMIC_ACQ_REL); GLXContext wctx= k<3? wctxs[k] : NULL;
  if(!wctx) return 0; int pa[]={GLX_PBUFFER_WIDTH,4,GLX_PBUFFER_HEIGHT,4,None};
  int (*old)(Display*,XErrorEvent*)=XSetErrorHandler(xerr_ignore); GLXPbuffer pb=glXCreatePbuffer(dpy,wfc,pa); XSync(dpy,False); XSetErrorHandler(old);
  if(pb && glXMakeContextCurrent(dpy,pb,pb,wctx)) return 1;
  return glXMakeContextCurrent(dpy,None,None,wctx)? 1 : 0; }

void backend_window_size(int* w, int* h){ *w=g_ww; *h=g_wh; }

void video_present_rgba(const u32* px, int w, int h, int stride){ extern void gpu_gl_present_cpu(const u32*,int,int,int); gpu_gl_present_cpu(px,w,h,stride); }

/* keys -> HidNpadButton bits, the same layout as on Windows */
static u64 keymap(KeySym k){
  switch(k){ case XK_x: case XK_space: return 1ull<<0; /* A */ case XK_z: return 1ull<<1; /* B */ case XK_c: return 1ull<<2; /* X */ case XK_v: return 1ull<<3; /* Y */
    case XK_q: return 1ull<<6; /* L */ case XK_e: return 1ull<<7; /* R */ case XK_1: return 1ull<<8; /* ZL */ case XK_3: return 1ull<<9; /* ZR */
    case XK_Return: case XK_KP_Enter: return 1ull<<10; /* + */ case XK_BackSpace: return 1ull<<11; /* - */
    case XK_Left: return 1ull<<12; case XK_Up: return 1ull<<13; case XK_Right: return 1ull<<14; case XK_Down: return 1ull<<15;
    /* stick keys, turned into axes later */
    case XK_a: return 1ull<<40; case XK_w: return 1ull<<41; case XK_d: return 1ull<<42; case XK_s: return 1ull<<43;
    case XK_j: return 1ull<<44; case XK_i: return 1ull<<45; case XK_l: return 1ull<<46; case XK_k: return 1ull<<47; }
  return 0; }

/* one-shot keys act on the first press only, not on auto-repeat */
static int key_once(KeySym k, int down){
  static KeySym held[8]; int i;
  for(i=0;i<8;i++) if(held[i]==k) break;
  if(!down){ if(i<8) held[i]=0; return 0; }
  if(i<8) return 0;
  for(i=0;i<8;i++) if(!held[i]){ held[i]=k; break; }
  return 1; }

static void key_down(XKeyEvent* e){
  KeySym k=XLookupKeysym(e,0);
  int once=key_once(k,1);
  if(k==XK_Return && (e->state&Mod1Mask)){ if(once) set_fullscreen(!g_fullscreen); return; }
  switch(k){
    case XK_Escape: g_quit=1; return;
    case XK_F11: if(once) set_fullscreen(!g_fullscreen); return;
    case XK_F1: if(once){ LOG("%s\n",HELP); plat_message(HELP,0,0); } return;
    case XK_F2: if(once) mouse_mode=!mouse_mode; return;
    case XK_F3: if(once) g_shot_req=1; return;
    case XK_F7: if(once) LOG("F7 video recording is only available on Windows\n"); return;
    case XK_F8: if(once){ extern volatile int g_shot8_req; g_shot8_req=1; } return;
    case XK_F5: if(once){ extern void gpu_gl_dump_rts(void); extern void kernel_dump_threads(void); extern __thread FILE* g_log_redirect;
        plat_mkdir("captures"); FILE* f=fopen("captures/threads.txt","w");   /* written next to the trace */
        if(f){ g_log_redirect=f; kernel_dump_threads(); g_log_redirect=NULL; fclose(f); }
        kernel_dump_threads(); gpu_gl_dump_rts(); } return;
    case XK_F4: if(once){ g_opt_fps= g_opt_fps==0? 1 : 0; char t[300]; snprintf(t,sizeof t,"%s  |  FPS limit: %s",g_title,g_opt_fps==0? "unlimited" : "60"); set_title(t);
        extern void ini_set(const char*, const char*); char v[8]; snprintf(v,sizeof v,"%d",g_opt_fps); ini_set("fps_limit",v); } return;
  }
  keys_held|=keymap(k); }

static i32 axis(u64 b, int neg, int pos){ return ((b>>pos)&1? 32767:0) - ((b>>neg)&1? 32767:0); }

static void stick_buttons(PadState* pad){
  if(pad->lx<-16000) pad->buttons|=1ull<<16; if(pad->ly>16000) pad->buttons|=1ull<<17;
  if(pad->lx>16000) pad->buttons|=1ull<<18; if(pad->ly<-16000) pad->buttons|=1ull<<19;
  if(pad->rx<-16000) pad->buttons|=1ull<<20; if(pad->ry>16000) pad->buttons|=1ull<<21;
  if(pad->rx>16000) pad->buttons|=1ull<<22; if(pad->ry<-16000) pad->buttons|=1ull<<23;
}

static void pad_script(PadState* pad, const char* script, u64 elapsed){
  u64 buttons=0;
  while(*script){
    char* next;
    u64 at=strtoull(script,&next,10);
    if(*next!=':') break;
    u64 mask=strtoull(next+1,&next,16);
    u64 duration=(mask>>40) ? 1400 : (u64)g_press_len;
    if(*next=='/') duration=strtoull(next+1,&next,10);
    if(elapsed>=at && elapsed-at<duration) buttons|=mask;
    if(*next!=',') break;
    script=next+1;
  }
  pad->buttons|=buttons&((1ull<<40)-1);
  if(buttons&(5ull<<40)) pad->lx=axis(buttons,40,42);
  if(buttons&(10ull<<40)) pad->ly=axis(buttons,43,41);
  if(buttons&(5ull<<44)) pad->rx=axis(buttons,44,46);
  if(buttons&(10ull<<44)) pad->ry=axis(buttons,47,45);
}

static void mouse_capture_update(void){
  if(mouse_mode && mouse_focused && !g_quit){
    if(mouse_captured) return;
    unsigned mask=PointerMotionMask|ButtonPressMask|ButtonReleaseMask;
    mouse_captured=XGrabPointer(dpy,win,False,mask,GrabModeAsync,GrabModeAsync,win,g_blank,CurrentTime)==GrabSuccess;
    if(mouse_captured){
      XWarpPointer(dpy,None,win,0,0,0,0,g_ww/2,g_wh/2);
      mouse_time=plat_ns();
    }
  }else if(mouse_captured){
    XUngrabPointer(dpy,CurrentTime);
    mouse_captured=0;
    mouse_buttons=0;
    mouse_moved=0;
  }
}

void video_poll(void){
  while(XPending(dpy)){ XEvent e; XNextEvent(dpy,&e);
    if(e.type==KeyPress) key_down(&e.xkey);
    else if(e.type==KeyRelease){ KeySym k=XLookupKeysym(&e.xkey,0); key_once(k,0); keys_held&=~keymap(k); }
    else if(e.type==FocusIn && e.xfocus.mode!=NotifyGrab && e.xfocus.mode!=NotifyUngrab) mouse_focused=1;
    else if(e.type==FocusOut && e.xfocus.mode!=NotifyGrab && e.xfocus.mode!=NotifyUngrab){
      keys_held=0;
      mouse_focused=0;
      mouse_capture_update();
    }
    else if(mouse_captured && e.type==MotionNotify){
      mouse_x=e.xmotion.x; mouse_y=e.xmotion.y; mouse_moved=1;
    }
    else if(mouse_captured && (e.type==ButtonPress || e.type==ButtonRelease)){
      u64 bit=e.xbutton.button==Button1?1u<<9:e.xbutton.button==Button3?1u<<8:0;
      if(e.type==ButtonPress) mouse_buttons|=bit;
      else mouse_buttons&=~bit;
    }
    else if(e.type==ConfigureNotify){
      int width=e.xconfigure.width>0? e.xconfigure.width : 1, height=e.xconfigure.height>0? e.xconfigure.height : 1;
      if(width!=g_ww || height!=g_wh){
        g_ww=width; g_wh=height;
        if(mouse_captured) XWarpPointer(dpy,None,win,0,0,0,0,g_ww/2,g_wh/2);
        mouse_moved=0;
        extern void nvn_window_resized(int,int); nvn_window_resized(width,height);
      }
    }
    else if(e.type==ClientMessage && (Atom)e.xclient.data.l[0]==wm_delete){ LOG("window: closed by the user\n"); g_quit=1; } }
  u64 k=keys_held;
  PadState pads[2]={{0}};
  pad_scan();
  int keyboard_player=g_kb_player==2 && (g_pad_gc[0] || g_script[0] || g_press);
  PadState* keyboard=&pads[keyboard_player];
  *keyboard=(PadState){k&0xFFFFull,axis(k,40,42),axis(k,43,41),axis(k,44,46),axis(k,47,45)};
  mouse_capture_update();
  if(mouse_captured){
    keyboard->buttons|=mouse_buttons;
    u64 now=plat_ns();
    int dx=mouse_x-g_ww/2, dy=mouse_y-g_wh/2;
    if(mouse_moved && (dx || dy)){
      u64 elapsed=now-mouse_time;
      mouse_stick(dx,dy,elapsed>=8000000ull?elapsed:8000000ull,mouse_sensitivity,mouse_invert,&keyboard->rx,&keyboard->ry);
      XWarpPointer(dpy,None,win,0,0,0,0,g_ww/2,g_wh/2);
    }
    mouse_time=now;
    mouse_moved=0;
  }
  for(int slot=0;slot<2;slot++){
    pad_read(g_pad_gc[slot],&pads[slot]);
    hid_rumble_update(slot,(u32)g_pad_id[slot]+1,!g_quit);
  }
  /* test input: --press=hex --press_at=ms, or --script=ms:hex,ms:hex,... */
  u64 el=(plat_ns()-g_start)/1000000ull;
  { static u64 at=~0ull; if(at==~0ull){ const char* e=getenv("SWR_TDUMP_AT"); at= e? strtoull(e,NULL,10)*1000ull : 0; }   /* tests: game thread dump at N s */
    if(at && el>=at){ static int n; const char* ev=getenv("SWR_TDUMP_EVERY"); at= ev && ++n<6? el+strtoull(ev,NULL,10)*1000ull : 0; extern void kernel_dump_threads(void); kernel_dump_threads(); } }
  if(g_press && el>=g_press_at && el<g_press_at+g_press_len) pads[0].buttons|=g_press;
  if(g_script[0]) pad_script(&pads[0],g_script,el);
  if(g_script2[0]) pad_script(&pads[1],g_script2,el);
  for(int slot=0;slot<2;slot++) stick_buttons(&pads[slot]);
  g_pad=pads[0]; g_pad2=pads[1];
  __atomic_store_n(&g_pad1_connected,g_pad_gc[0]!=NULL || g_script[0]!=0,__ATOMIC_RELEASE);
  __atomic_store_n(&g_pad2_connected,g_pad_gc[1]!=NULL || keyboard_player==1 || g_script2[0]!=0,__ATOMIC_RELEASE);
}

int backend_rumble(int player, u16 low, u16 high, u32 duration_ms){
  SDLGC* pad=g_pad_gc[player];
  return pad && sdl.Rumble && sdl.Rumble(pad,low,high,duration_ms)==0;
}

void frontend_frame(void){
  extern int g_gpu_nvn;
  extern void nvn_shot(const char* path);
  extern u64 gpu_gl_screenshot(const char* path);
  if(g_shot_req){ g_shot_req=0; char p[300]; time_t now=time(NULL); struct tm t; localtime_r(&now,&t); plat_mkdir("captures");
    snprintf(p,sizeof p,"captures/screenshot_%04d%02d%02d_%02d%02d%02d",t.tm_year+1900,t.tm_mon+1,t.tm_mday,t.tm_hour,t.tm_min,t.tm_sec);
    if(g_gpu_nvn) nvn_shot(p); else gpu_gl_screenshot(p); }
  u64 el=plat_ns()-g_start;
  if((g_maxframes>=0 && g_frames>=g_maxframes) || (g_seconds && el>=(u64)g_seconds*1000000000ull)){
    u64 h=0;
    if(g_gpu_nvn){ if(g_shot[0]) nvn_shot(g_shot); }
    else h=gpu_gl_screenshot(g_shot[0]? g_shot : NULL);
    fprintf(stderr,"\nframes=%d hash=%016llx\n",g_frames,(unsigned long long)h);
    hid_rumble_stop();
    extern void save_hints(void); save_hints(); fflush(NULL); _exit(0); }
}

int backend_glq_ok(void){ return 1; }   /* GL calls go through glq */
