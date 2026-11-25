/* Orbitals PC Recomp. GNU AGPL v3.0 with the additional terms of NOTICE.txt. */
/* Included by backend_win32.c. The panel and its preferences belong to the window thread. */
#include <windowsx.h>

enum { SETTINGS_MESSAGE=WM_APP+9, SETTINGS_MENU=0x1C10, SETTINGS_WIDTH=640, SETTINGS_HEIGHT=540,
       SETTINGS_ROWS_Y=150, SETTINGS_ROW_STEP=82, SETTINGS_ROW_HEIGHT=72, SETTINGS_FROM_GAME=0x10000 };
enum SettingsRow { SET_DISPLAY, SET_SIZE, SET_VSYNC, SET_FPS, SET_SCENE, SET_VOLUME, SET_KEYBOARD, SET_MOUSE, SET_MOUSE_SENSITIVITY, SET_VIBRATION };

static HWND settings_window;
static int settings_tab, settings_row, settings_saved_size, settings_vsync, settings_fps, settings_audio_muted;
static char settings_path[MAX_PATH];
static const char* const settings_tabs[]={"Display","Graphics","Audio","Controls"};
static const int settings_first[]={SET_DISPLAY,SET_SCENE,SET_VOLUME,SET_KEYBOARD,SET_VIBRATION+1};
static const char* const settings_keys[]={"borderless","window_height","vsync","fps","scene_height","volume","keyboard","mouse","mouse_sensitivity","vibration"};
static const char* const settings_names[]={
  "Window mode","Window resolution","VSync","Frame rate","3D resolution","Master volume","Keyboard player","Right stick","Mouse sensitivity","Vibration"
};
static const char* const settings_details[]={
  "Switch between a resizable window and the full display.",
  "Set the window's client area in pixels.",
  "Vulkan presentation mode. Applies at the next launch.",
  "60 FPS is experimental. Applies at the next launch.",
  "Set the resolution of the 3D scene.",
  "Adjust the sound sent to your audio device.",
  "Assign the keyboard and mouse to a player.",
  "Use the mouse as the right stick alongside I J K L.",
  "Adjust mouse movement when it controls the right stick.",
  "Send vibration to compatible controllers."
};
static const int settings_window_sizes[]={540,720,900,1080};
static const int settings_frame_rates[]={0,30,60};

static void adjust_client_rect(RECT* r, DWORD style);

static void settings_load(void){
  const char* present=getenv("NXRT_VK_PRESENT"), *interval=getenv("SWR_PRESENT_INTERVAL"), *async=getenv("SWR_ASYNC_SUBMIT");
  const char* mute=getenv("SWR_AUDIO_MUTE");
  settings_vsync=!present || strcmp(present,"immediate")!=0;
  settings_fps=interval && atoi(interval)==1?60:async && atoi(async)>0?30:0;
  settings_audio_muted=mute && *mute=='1';
  char path[sizeof g_exedir+32];
  snprintf(path,sizeof path,"%sorbitals-pc-settings.ini",g_exedir);
  DWORD length=GetFullPathNameA(path,sizeof settings_path,settings_path,NULL);
  if(!length || length>=sizeof settings_path){ settings_path[0]=0; return; }
  int value=(int)GetPrivateProfileIntA("Settings","borderless",-1,settings_path);
  if(value==0 || value==1) g_want_fs=value;
  value=(int)GetPrivateProfileIntA("Settings","window_height",-1,settings_path);
  for(unsigned i=0;i<sizeof settings_window_sizes/sizeof *settings_window_sizes;i++)
    if(value==settings_window_sizes[i]) settings_saved_size=value;
  value=(int)GetPrivateProfileIntA("Settings","vsync",-1,settings_path);
  if(value==0 || value==1){
    settings_vsync=value;
    _putenv(value?"NXRT_VK_PRESENT=fifo":"NXRT_VK_PRESENT=immediate");
  }
  value=(int)GetPrivateProfileIntA("Settings","fps",-1,settings_path);
  if(value==0 || value==30 || value==60){
    settings_fps=value;
    _putenv(value==60?"SWR_PRESENT_INTERVAL=1":"SWR_PRESENT_INTERVAL=0");
    _putenv(value?"SWR_ASYNC_SUBMIT=1":"SWR_ASYNC_SUBMIT=0");
  }
  value=(int)GetPrivateProfileIntA("Settings","scene_height",-1,settings_path);
  if(value==0 || value==540 || value==720 || value==900 || value==1080) orbitals_scene_request(value);
  swr_audio_volume_set((int)GetPrivateProfileIntA("Settings","volume",-1,settings_path));
  value=(int)GetPrivateProfileIntA("Settings","keyboard",-1,settings_path);
  if(value==1 || value==2) __atomic_store_n(&g_kb_player,value,__ATOMIC_RELAXED);
  value=(int)GetPrivateProfileIntA("Settings","mouse",-1,settings_path);
  if(value==0 || value==1) g_mouse_mode=value;
  value=(int)GetPrivateProfileIntA("Settings","mouse_sensitivity",-1,settings_path);
  if(value>=10 && value<=500) InterlockedExchange(&g_mouse_sensitivity,value);
  value=(int)GetPrivateProfileIntA("Settings","vibration",-1,settings_path);
  if(value==0 || value==1) __atomic_store_n(&g_vibration,value,__ATOMIC_RELAXED);
}

static void settings_save(enum SettingsRow row, int value){
  char text[16];
  snprintf(text,sizeof text,"%d",value);
  if(!settings_path[0] || !WritePrivateProfileStringA("Settings",settings_keys[row],text,settings_path))
    WARN("settings panel: could not save %s\n",settings_keys[row]);
  else LOG("settings panel: saved %s=%d\n",settings_keys[row],value);
}

static int settings_cycle(const int* choices, int count, int current, int direction){
  for(int i=0;i<count;i++)
    if(current==choices[i]) return choices[(i+direction+count)%count];
  return choices[direction<0?count-1:0];
}

static int settings_enabled(enum SettingsRow row){
  if(row==SET_SIZE) return !g_fullscreen && !IsZoomed(g_hwnd);
  if(row==SET_SCENE) return orbitals_scene_available();
  if(row==SET_VOLUME) return !settings_audio_muted;
  if(row==SET_MOUSE_SENSITIVITY) return g_mouse_mode;
  if(row==SET_FPS || row==SET_VSYNC){ extern int g_gpu_nvn; return g_gpu_nvn; }
  return 1;
}

static void settings_value(enum SettingsRow row, char* text, size_t size){
  switch(row){
  case SET_DISPLAY: snprintf(text,size,"%s",g_fullscreen?"Borderless":"Windowed"); break;
  case SET_SIZE: snprintf(text,size,"%d x %d",g_ww,g_wh); break;
  case SET_VSYNC: snprintf(text,size,"%s",settings_enabled(row)?(settings_vsync?"On":"Off"):"Unavailable"); break;
  case SET_FPS:
    snprintf(text,size,"%s",!settings_enabled(row)?"Unavailable":settings_fps==60?"60 experimental":
                            settings_fps==30?"30 async":"30 reference");
    break;
  case SET_SCENE: {
    int height=orbitals_scene_requested();
    if(!orbitals_scene_available()) snprintf(text,size,"Unavailable");
    else if(!height) snprintf(text,size,"Launch setting");
    else snprintf(text,size,"%d x %d",height*16/9,height);
    break;
  }
  case SET_VOLUME:
    if(settings_audio_muted) snprintf(text,size,"Muted at launch");
    else snprintf(text,size,"%d%%",swr_audio_volume());
    break;
  case SET_KEYBOARD: snprintf(text,size,"Player %d",__atomic_load_n(&g_kb_player,__ATOMIC_RELAXED)); break;
  case SET_MOUSE: snprintf(text,size,"%s",g_mouse_mode?"Mouse + keys":"I J K L keys"); break;
  case SET_MOUSE_SENSITIVITY: snprintf(text,size,"%ld%%",g_mouse_sensitivity); break;
  case SET_VIBRATION: snprintf(text,size,"%s",__atomic_load_n(&g_vibration,__ATOMIC_RELAXED)?"On":"Off"); break;
  }
}

static void settings_change(enum SettingsRow row, int direction){
  if(!settings_enabled(row)) return;
  int value;
  switch(row){
  case SET_DISPLAY:
    if(g_fullscreen) ShowCursor(FALSE);
    set_fullscreen(!g_fullscreen);
    if(g_fullscreen) ShowCursor(TRUE);
    value=g_fullscreen;
    break;
  case SET_SIZE: {
    value=settings_cycle(settings_window_sizes,sizeof settings_window_sizes/sizeof *settings_window_sizes,g_wh,direction);
    RECT rect={0,0,value*16/9,value};
    adjust_client_rect(&rect,(DWORD)GetWindowLongA(g_hwnd,GWL_STYLE));
    g_requested_outer_w=rect.right-rect.left;
    g_requested_outer_h=rect.bottom-rect.top;
    if(!SetWindowPos(g_hwnd,NULL,0,0,g_requested_outer_w,g_requested_outer_h,SWP_NOMOVE|SWP_NOZORDER|SWP_NOACTIVATE)) return;
    break;
  }
  case SET_VSYNC: value=settings_vsync=!settings_vsync; break;
  case SET_FPS:
    value=settings_fps=settings_cycle(settings_frame_rates,3,settings_fps,direction);
    break;
  case SET_SCENE:
    value=settings_cycle(cw_scene_heights,sizeof cw_scene_heights/sizeof *cw_scene_heights,orbitals_scene_requested(),direction);
    orbitals_scene_request(value);
    break;
  case SET_VOLUME:
    value=swr_audio_volume()+direction*5;
    if(value<0) value=0;
    if(value>100) value=100;
    swr_audio_volume_set(value);
    break;
  case SET_KEYBOARD: value=3-__atomic_load_n(&g_kb_player,__ATOMIC_RELAXED); __atomic_store_n(&g_kb_player,value,__ATOMIC_RELAXED); break;
  case SET_MOUSE: value=!g_mouse_mode; g_mouse_mode=value; break;
  case SET_MOUSE_SENSITIVITY:
    value=g_mouse_sensitivity+direction*10;
    if(value<10) value=10;
    if(value>500) value=500;
    InterlockedExchange(&g_mouse_sensitivity,value);
    break;
  case SET_VIBRATION:
    value=!__atomic_load_n(&g_vibration,__ATOMIC_RELAXED);
    __atomic_store_n(&g_vibration,value,__ATOMIC_RELAXED);
    break;
  default: return;
  }
  settings_save(row,value);
  InvalidateRect(settings_window,NULL,FALSE);
}

static void settings_select_tab(int tab){
  settings_tab=(tab+4)%4;
  settings_row=settings_first[settings_tab];
  InvalidateRect(settings_window,NULL,FALSE);
}

static void settings_position(void){
  if(!settings_window) return;
  RECT rect;
  GetClientRect(g_hwnd,&rect);
  int width=rect.right>32?rect.right-32:rect.right, height=rect.bottom>32?rect.bottom-32:rect.bottom;
  if(width>SETTINGS_WIDTH) width=SETTINGS_WIDTH;
  if(height>SETTINGS_HEIGHT) height=SETTINGS_HEIGHT;
  SetWindowPos(settings_window,HWND_TOP,(rect.right-width)/2,(rect.bottom-height)/2,width,height,SWP_NOACTIVATE);
  InvalidateRect(settings_window,NULL,FALSE);
}

static void settings_paint(HWND window){
  PAINTSTRUCT paint;
  HDC output=BeginPaint(window,&paint);
  RECT client;
  GetClientRect(window,&client);
  HDC buffer=CreateCompatibleDC(output);
  HBITMAP image=CreateCompatibleBitmap(output,SETTINGS_WIDTH,SETTINGS_HEIGHT);
  if(!buffer || !image){
    if(buffer) DeleteDC(buffer);
    if(image) DeleteObject(image);
    EndPaint(window,&paint);
    return;
  }
  HGDIOBJ old_image=SelectObject(buffer,image), old_font=GetCurrentObject(buffer,OBJ_FONT);
  HFONT title=cw_font(35,FW_SEMIBOLD), body=cw_font(19,FW_SEMIBOLD), small=cw_font(15,FW_NORMAL);
  COLORREF base=RGB(18,26,38), surface=RGB(29,40,52), selected=RGB(41,59,68);
  COLORREF text=RGB(239,244,246), muted=RGB(168,185,194), accent=RGB(139,228,193);
  SetBkMode(buffer,TRANSPARENT);
  cw_rect(buffer,0,0,SETTINGS_WIDTH,SETTINGS_HEIGHT,base);
  cw_rect(buffer,0,0,SETTINGS_WIDTH,4,accent);
  cw_text(buffer,title,"PC settings",28,16,450,56,DT_LEFT,text);
  cw_rect(buffer,544,28,68,34,surface);
  cw_text(buffer,small,"Close",544,28,68,34,DT_CENTER,text);
  for(int i=0;i<4;i++){
    int x=28+i*148;
    cw_rect(buffer,x,94,140,44,i==settings_tab?selected:surface);
    cw_text(buffer,body,settings_tabs[i],x,94,140,44,DT_CENTER,i==settings_tab?accent:text);
  }
  int first=settings_first[settings_tab], end=settings_first[settings_tab+1];
  for(int i=first;i<end;i++){
    int y=SETTINGS_ROWS_Y+(i-first)*SETTINGS_ROW_STEP;
    char value[64];
    settings_value(i,value,sizeof value);
    cw_rect(buffer,28,y,584,SETTINGS_ROW_HEIGHT,i==settings_row?selected:surface);
    if(i==settings_row) cw_rect(buffer,28,y,3,SETTINGS_ROW_HEIGHT,accent);
    cw_text(buffer,body,settings_names[i],46,y+9,284,32,DT_LEFT,text);
    cw_text(buffer,small,settings_details[i],46,y+42,540,26,DT_LEFT,muted);
    COLORREF control=settings_enabled(i)?accent:muted;
    if(settings_enabled(i)){
      cw_text(buffer,body,"<",380,y+9,32,32,DT_CENTER,control);
      cw_text(buffer,body,">",552,y+9,32,32,DT_CENTER,control);
    }
    cw_text(buffer,body,value,412,y+9,140,32,DT_CENTER,control);
  }
  cw_rect(buffer,28,494,584,1,selected);
  cw_text(buffer,small,"Arrows / D-pad   Adjust     Tab / L / R   Category     Esc / East button   Close",28,503,584,28,DT_LEFT,muted);
  StretchBlt(output,0,0,client.right,client.bottom,buffer,0,0,SETTINGS_WIDTH,SETTINGS_HEIGHT,SRCCOPY);
  SelectObject(buffer,old_font);
  DeleteObject(title); DeleteObject(body); DeleteObject(small);
  SelectObject(buffer,old_image);
  DeleteObject(image); DeleteDC(buffer);
  EndPaint(window,&paint);
}

static void settings_close(void){
  DestroyWindow(settings_window);
  settings_window=NULL;
  InterlockedExchange(&g_settings_open,0);
  if(g_fullscreen) ShowCursor(FALSE);
  SetFocus(g_hwnd);
  mouse_capture();
  InvalidateRect(g_hwnd,NULL,FALSE);
}

static void settings_key(WPARAM key){
  int first=settings_first[settings_tab], count=settings_first[settings_tab+1]-first;
  switch(key){
  case VK_ESCAPE: case VK_F10: settings_close(); return;
  case VK_TAB: case VK_NEXT: settings_select_tab(settings_tab+1); return;
  case VK_PRIOR: settings_select_tab(settings_tab-1); return;
  case VK_UP: settings_row=first+(settings_row-first+count-1)%count; break;
  case VK_DOWN: settings_row=first+(settings_row-first+1)%count; break;
  case VK_LEFT: settings_change(settings_row,-1); return;
  case VK_RIGHT: case VK_RETURN: settings_change(settings_row,1); return;
  }
  InvalidateRect(settings_window,NULL,FALSE);
}

static LRESULT CALLBACK settings_proc(HWND window,UINT message,WPARAM key,LPARAM data){
  switch(message){
  case WM_PAINT: settings_paint(window); return 0;
  case WM_ERASEBKGND: return 1;
  case WM_CLOSE: settings_close(); return 0;
  case WM_SETCURSOR: SetCursor(LoadCursor(NULL,IDC_ARROW)); return TRUE;
  case WM_KEYDOWN: case WM_SYSKEYDOWN:
    if(key==VK_F4 && message==WM_SYSKEYDOWN) break;
    if((key!=VK_F10 && key!=VK_ESCAPE) || !(data&(1L<<30))) settings_key(key);
    return 0;
  case WM_LBUTTONUP: {
    RECT rect;
    GetClientRect(window,&rect);
    if(!rect.right || !rect.bottom) return 0;
    int x=GET_X_LPARAM(data)*SETTINGS_WIDTH/rect.right, y=GET_Y_LPARAM(data)*SETTINGS_HEIGHT/rect.bottom;
    if(y>=28 && y<62 && x>=544 && x<612) settings_close();
    else if(y>=94 && y<138 && x>=28 && x<612 && (x-28)%148<140) settings_select_tab((x-28)/148);
    else if(y>=SETTINGS_ROWS_Y && x>=28 && x<612){
      int row_offset=y-SETTINGS_ROWS_Y;
      int row=settings_first[settings_tab]+row_offset/SETTINGS_ROW_STEP;
      if(row<settings_first[settings_tab+1] && row_offset%SETTINGS_ROW_STEP<SETTINGS_ROW_HEIGHT){
        settings_row=row;
        if(row_offset%SETTINGS_ROW_STEP<42 && x>=380 && x<584) settings_change(row,x<412?-1:1);
        InvalidateRect(window,NULL,FALSE);
      }
    }
    return 0;
  }
  }
  return DefWindowProcA(window,message,key,data);
}

static void settings_toggle(void){
  if(settings_window){ settings_close(); return; }
  if(!g_hwnd || g_controls_open || IsIconic(g_hwnd)) return;
  settings_window=CreateWindowExA(0,"OrbitalsPCSettings","PC settings",WS_CHILD|WS_CLIPSIBLINGS,
                                  0,0,1,1,g_hwnd,NULL,GetModuleHandleA(NULL),NULL);
  if(!settings_window){ WARN("settings panel: window creation failed (%lu)\n",(unsigned long)GetLastError()); return; }
  InterlockedExchange(&g_settings_open,1);
  keys_held=0;
  if(g_fullscreen) ShowCursor(TRUE);
  mouse_capture();
  settings_position();
  ShowWindow(settings_window,SW_SHOW);
  SetFocus(settings_window);
  LOG("settings panel: opened\n");
}

void backend_game_settings_show(void){
  if(g_hwnd) PostMessageA(g_hwnd,SETTINGS_MESSAGE,SETTINGS_FROM_GAME,0);
}

static int settings_controller(const WinGamepad* devices, const u64* scripted, int focused){
  enum { EAST=1<<0, SOUTH=1<<1, L=1<<6, R=1<<7, PLUS=1<<10, LEFT=1<<12, UP=1<<13, RIGHT=1<<14, DOWN=1<<15 };
  static const struct { unsigned button; WPARAM key; } commands[]={
    {EAST,VK_ESCAPE},{L,VK_PRIOR},{R,VK_NEXT},{LEFT,VK_LEFT},{UP,VK_UP},{RIGHT,VK_RIGHT},{DOWN,VK_DOWN},{SOUTH,VK_RETURN}
  };
  static unsigned held[WIN_GAMEPAD_SLOTS];
  static int drain;
  int open=settings_open(), consume=open;
  for(int i=0;i<WIN_GAMEPAD_SLOTS;i++){
    const PadState* pad=&devices[i].pad;
    unsigned buttons=(pad->buttons|scripted[i])&0xffff, chord=L|R|PLUS;
    if(pad->lx<-16000) buttons|=LEFT;
    if(pad->lx>16000) buttons|=RIGHT;
    if(pad->ly<-16000) buttons|=DOWN;
    if(pad->ly>16000) buttons|=UP;
    unsigned rising=buttons&~held[i], old=held[i];
    held[i]=buttons;
    if(!focused && !scripted[i]) continue;   /* a test script's buttons (--script_file) reach the panel without focus; real pads only with it */
    if(!open && !consume && (buttons&chord)==chord && (old&chord)!=chord){
      PostMessageA(g_hwnd,SETTINGS_MESSAGE,0,0);
      consume=1;
    }else if(open){
      for(unsigned j=0;j<sizeof commands/sizeof *commands;j++){
        if(rising&commands[j].button){ PostMessageA(g_hwnd,SETTINGS_MESSAGE,commands[j].key,0); break; }
      }
    }
  }
  if(consume) drain=1;
  else if(drain && !(held[0]|held[1])) drain=0;
  return consume || drain;
}
