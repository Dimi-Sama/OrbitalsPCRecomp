/* Orbitals PC Recomp, based on SwitchRecomp by MZ Labs. AGPL-3.0, see LICENSE.txt and NOTICE.txt. */
/* Optional button layouts; Nintendo defaults leave the game unchanged. */
#include "rt.h"
#include "orbitals_buttons.h"


int code_dynamic_call(u64 pc);                /* main.c: the code module calls pc through g_disp */

/* ===================================================================== button layout
   Measured on the PC (2026-11-26, docs/BUTTON_LAYOUT.md):
   - Icons: DA_PlatformInputIcons maps each key to a texture per EPlatformType (Desktop 0, Playstation 1, Xbox 2, Switch 3) and the Switch 2
     build always asks for the Switch one. button_layout=xbox / playstation wraps the game's icon lookup (icon_lookup) and the action
     prompt that inlines its own Switch lookup (icon_prompt) so that a Switch icon becomes that controller's texture for the same key
     (observed in the original implementation). Buttons keep their
     places unless button_accept_bottom is on, and the icons follow the key either way.
   - Accept on the bottom button (button_accept_bottom=1, experimental): the Switch 2 build redirects six Enhanced Input mapping contexts
     to Switch versions (BP_Switch2InputPlatformData, MappingContextRedirects) and its UI lists those Switch versions
     (MoreporkDeveloperSettings PlatformMappingContexts). The redirect data does not come from the config at run time (a user Input.ini,
     the Generated platform layer and a replaced Switch2Input.ini inside the pak were all ignored), so as the redirect maps load the
     runtime points each redirect at its own source context (ei_virtual) and gives the UI the PC contexts (user Game.ini):
     the lobby, the pause menu and the game then accept on the bottom button. CommonUI's own buttons (title screen, main menu,
     "Comenzar") and Slate navigation use the platform's accept / back keys: those two EKeys globals are swapped at start (ekeys_init).
   nintendo (default) changes nothing. */
static int g_layout;   /* 0 nintendo, 1 xbox, 2 playstation */
static int g_accept_bottom;   /* button_accept_bottom=1: Enhanced Input's Switch redirects taken out (experimental) */

static int write_text(const char* path, const char* text){
  FILE* f=fopen(path,"wb"); if(!f) return 0;
  fputs(text,f); fclose(f); return 1;
}

const char* orbitals_layout_overlay(void){
  if(!g_layout || !g_accept_bottom) return NULL;
  static char root[1200];
  const char* name= g_layout==1? "xbox" : "playstation";
  char dir[1400];
  snprintf(root,sizeof root,"%sbutton_layout",g_exedir); plat_mkdir(root);
  snprintf(root,sizeof root,"%sbutton_layout/%s",g_exedir,name); plat_mkdir(root);
  static const char* parts[]={"Orbitals","Saved","Config","Switch2"};
  size_t n=(size_t)snprintf(dir,sizeof dir,"%s",root);
  for(unsigned i=0;i<4 && n<sizeof dir;i++){ n+=(size_t)snprintf(dir+n,sizeof dir-n,"/%s",parts[i]); plat_mkdir(dir); }
  char path[1500];
  snprintf(path,sizeof path,"%s/Game.ini",dir);
  if(!write_text(path,
    "; written by the runtime (button_accept_bottom): the UI's input contexts are the PC version's ones\n"
    "[/Script/MoreporkUI.MoreporkDeveloperSettings]\n"
    "!PlatformMappingContexts=ClearArray\n"
    "+PlatformMappingContexts=/Game/Orbitals/Input/UI/IMC_UI_Default.IMC_UI_Default\n"
    "+PlatformMappingContexts=/Game/Orbitals/Input/IMC_Cutscene.IMC_Cutscene\n"
    "+PlatformMappingContexts=/Game/Orbitals/Input/IMC_SpiritJug.IMC_SpiritJug\n"
    "+PlatformMappingContexts=/Game/Orbitals/Input/IMC_SettlementGames.IMC_SettlementGames\n"
    "+PlatformMappingContexts=/Game/Orbitals/Input/UI/IMC_UI_CRU.IMC_UI_CRU\n"
    "+PlatformMappingContexts=/Game/Orbitals/Input/IMC_Default.IMC_Default\n")){
    LOG("Orbitals: button layout %s: could not write %s\n",name,dir); return NULL; }
  LOG("Orbitals: accept on the bottom button (Unreal user config from %s)\n",root);
  return root;
}

/* The Switch 2 mapping context redirects are not read from the config at run time (neither the user layer nor a replaced
   Switch2Input.ini changes them: measured 2026-11-26), so they are taken out of the loaded data instead. UEnhancedInputPlatformData
   (0x78 bytes, vtable main+0x7fecb38, built by main+0x16847a0) keeps MappingContextRedirects as a TMap at +0x28: TSparseArray data
   pointer +0x28, count +0x30, capacity +0x34, allocation bits (heap pointer +0x48 when set, else inline +0x38; bit count +0x50), first free +0x58,
   free count +0x5c. Each redirect's target is set to its source (IMC_UI_Default -> IMC_UI_Default): no element is added or removed, so
   the map's structure stays valid for its readers, and Enhanced Input keeps the PC version's contexts at its next rebuild. The game's own
   UI list (MoreporkDeveloperSettings PlatformMappingContexts, user Game.ini) is set to the same PC contexts so the prompts match. */
enum { EI_PLATFORM_DATA_VTABLE=0x7fecb38 };
static u64 g_ei_vtable;
int mem_with_range(u64 addr, u64 len, void (*fn)(u64 addr, u64 len, void* ctx), void* ctx);
int mem_span_ok_locked(u64 addr, u64 size, u32 perm);   /* inside mem_with_range only */
#include "orbitals_buttons_internal.h"
/* Button icons: DA_PlatformInputIcons (UMoreporkInputIconDataAsset) keeps InputIcons, a TMap<FKey, entry> (0x70-byte elements at
   +0x30) whose entry holds a TMap<EPlatformType, UTexture2D*> (Desktop 0, Playstation 1, Xbox 2, Switch 3; 0x18-byte elements: key
   byte, texture at +8). The per-key lookup is main+0x40c5ce0 (asset, const FKey*, EPlatformType, UTexture2D** out) -> bool, called
   only by the GetIconBrushForKey exec (Blueprint prompts, main+0x40b2e64) and the native icon widget (main+0x4634a78, which asks for
   Switch 3 when it has an owning player and Xbox 2 when not). It is NOT the only reader: the action prompt main+0x40c5020 inlines the
   same lookup (icon_prompt_install below), and the PC runs showed the prompts never reaching 0x40c5ce0. button_layout=xbox /
   playstation wraps that function: a Switch request (and, for playstation, the Xbox fallback) looks up the layout's entry first and
   falls back to the original request when the key has none or a NULL texture (icon_lookup, orbitals_buttons.h). Only the caller's output slot is written. Both callers reach it with a direct bl, which the generated code turns into a direct C call unless codegen.py lists the
   target in DYNAMIC_CALLS: then the call goes through g_disp, where the wrapper sits. The code module says which targets it built
   that way (swr_dynamic_calls); without it the wrapper would never run, so nothing is installed. */
enum { ICON_LOOKUP=0x40c5ce0, ICON_CALL_BP=0x40b2e64, ICON_CALL_WIDGET=0x4634a78 };
static void icon_install(const SwrModInfo* mod){
  /* entry pacibsp; stp x29, x30, [sp, #-0x40]!; mov w12, #0x70 (outer element); mov w10, #0x18 (inner element); ldrb w12, [x11]
     (platform key); ldr x8, [x11, #8] (texture); and the two callers' bl */
  static const struct { u32 off, w; } sig[]={ {0x40c5ce0,0xd503237f}, {0x40c5ce4,0xa9bc7bfd}, {0x40c5d78,0x52800e0c}, {0x40c5de4,0x5280030a},
                                               {0x40c5dec,0x3940016c}, {0x40c5e10,0xf9400568}, {ICON_CALL_BP,0x94004b9f}, {ICON_CALL_WIDGET,0x97ea449a} };
  for(unsigned i=0;i<sizeof sig/sizeof sig[0];i++){
    u64 a=mod->base+sig[i].off;
    if(a<g_code_lo || a>=g_code_hi || gr32(a)!=sig[i].w){ LOG("Orbitals: button icons: not applied (icon lookup not found, %x)\n",sig[i].off); return; }
  }
  u64 pc=mod->base+ICON_LOOKUP;
  GuestFn* e=&g_disp[(pc-g_code_lo)/4];
  if(!*e){ LOG("Orbitals: button icons: not applied (icon lookup has no entry)\n"); return; }
  if(!code_dynamic_call(pc)){ LOG("Orbitals: button icons: not applied (the game code calls the icon lookup directly: generate it again with this SwitchRecomp)\n"); return; }
  icon_lookup_orig=*e; *e=icon_lookup;
  LOG("Orbitals: button icons: %s icons (icon lookup main+%x wrapped)\n",g_layout==1?"Xbox":"PlayStation",ICON_LOOKUP);
}
/* The action prompt (icon_prompt, orbitals_buttons.h): main+0x40c5020 looks the action's keys up in the same InputIcons map with
   Switch 3 inlined (it never calls the icon lookup above), and it is what the title, menus, lobby, settings and co-op prompts reach
   (callers main+0x40c4ed0 and main+0x40d3990, both a direct bl, the only references in main.bin). Installed on its own, with its own
   checks: the entry, the arguments it keeps (x2 into x20, then [sp+8]), both strides, the outer map fields, the inner map fields and
   hash mask, the platform compare (cmp w8, #3), the texture load and its store to the pad slot, and the two callers' bl words. */
enum { ICON_PROMPT=0x40c5020, ICON_PROMPT_CALL_A=0x40c4ed0, ICON_PROMPT_CALL_B=0x40d3990 };
static void icon_prompt_install(const SwrModInfo* mod){
  static const struct { u32 off, w; } sig[]={
    {0x40c5020,0xd503237f}, {0x40c5024,0xd10243ff},                          /* pacibsp; sub sp, sp, #0x90 */
    {0x40c5060,0xaa0203f4}, {0x40c5088,0xf90007f4},                          /* mov x20, x2; str x20, [sp, #8] */
    {0x40c5084,0x52800e1a}, {0x40c50e4,0xb9403b08}, {0x40c50e8,0xb9406709},  /* mov w26, #0x70; ldr w8, [x24, #0x38]; ldr w9, [x24, #0x64] */
    {0x40c5120,0xf9401b09}, {0x40c5134,0xb9406908},                          /* ldr x9, [x24, #0x30]; ldr w8, [x8, #0x68] */
    {0x40c51c4,0xb9402109}, {0x40c51c8,0xb9404d0a}, {0x40c51d4,0xf9402d0a},  /* inner count +0x20, free +0x4c, hash heap +0x58 */
    {0x40c51d8,0x91014109}, {0x40c51e4,0xb940610a}, {0x40c51ec,0x1200054a},  /* hash inline +0x50, hash size +0x60, and w10, w10, #3 */
    {0x40c51fc,0xf9400d09}, {0x40c5200,0x52800308}, {0x40c5208,0x39400148},  /* inner data +0x18; mov w8, #0x18; ldrb w8, [x10] */
    {0x40c520c,0x71000d1f}, {0x40c5214,0xb940114a},                          /* cmp w8, #3; ldr w10, [x10, #0x10] */
    {0x40c5290,0xf9400548}, {0x40c5294,0xf94007e9}, {0x40c5298,0xf9000128},  /* ldr x8, [x10, #8]; ldr x9, [sp, #8]; str x8, [x9] */
    {ICON_PROMPT_CALL_A,0x94000054}, {ICON_PROMPT_CALL_B,0x97ffc5a4} };
  for(unsigned i=0;i<sizeof sig/sizeof sig[0];i++){
    u64 a=mod->base+sig[i].off;
    if(a<g_code_lo || a>=g_code_hi || gr32(a)!=sig[i].w){ LOG("Orbitals: button prompts: not applied (action prompt not found, %x)\n",sig[i].off); return; }
  }
  u64 pc=mod->base+ICON_PROMPT;
  GuestFn* e=&g_disp[(pc-g_code_lo)/4];
  if(!*e){ LOG("Orbitals: button prompts: not applied (action prompt has no entry)\n"); return; }
  if(!code_dynamic_call(pc)){ LOG("Orbitals: button prompts: not applied (the game code calls the action prompt directly: generate it again with this SwitchRecomp)\n"); return; }
  icon_prompt_orig=*e; *e=icon_prompt;
  LOG("Orbitals: button prompts: %s icons (action prompt main+%x wrapped)\n",g_layout==1?"Xbox":"PlayStation",ICON_PROMPT);
}
/* The platform's accept / back keys. Unreal builds EKeys::Virtual_Accept = FPlatformInput::GetGamepadAcceptKey() and Virtual_Back =
   GetGamepadBackKey() as copies of two face button FKeys at the end of the EKeys static initializer (main+0x50dc00, called once from
   the init array): on Switch accept = FaceButton_Right, back = FaceButton_Bottom (main+0x51188c-0x5118e0). Every runtime reader goes
   through those two globals (directly or by the GOT at main+0x8fa4680 / 0x8fa4688): FNavigationConfig's KeyActionRules (built later,
   when Slate starts), FAnalogCursor / FCommonAnalogCursor's click, CommonUI's action router accept / back. Enhanced Input mappings and
   the game's own bInvertFaceBottomFaceRight name the physical keys and are not touched, so jump stays on the bottom button.
   button_accept_bottom swaps the two 0x18-byte FKeys (FName, KeyDetails pointer, reference controller) right after the initializer
   returns, on the game's main thread before any other code reads them: each controller stays referenced once, by the other global,
   so the reference counts and the exit-time destructors are unchanged. Every check below must hold or nothing is written. */
enum { EKEYS_INIT=0x50dc00, EKEY_BOTTOM=0x94ec028, EKEY_RIGHT=0x94ec040, EKEY_ACCEPT=0x94ed438, EKEY_BACK=0x94ed450,
       GOT_ACCEPT=0x8fa4680, GOT_BACK=0x8fa4688 };
static GuestFn ekeys_init_orig; static u64 g_main_base;
static void ekeys_init(CPU* c, u64 entry){
  ekeys_init_orig(c,entry);
  u64 b=g_main_base, acc=b+EKEY_ACCEPT, back=b+EKEY_BACK, bot=b+EKEY_BOTTOM, right=b+EKEY_RIGHT;
  const char* why=NULL;
  if(!guest_span_readable(acc,0x30,8) || !guest_span_readable(bot,0x30,8) || !guest_span_readable(b+GOT_ACCEPT,16,8)) why="keys not readable";
  else if(gr64(b+GOT_ACCEPT)!=acc || gr64(b+GOT_BACK)!=back) why="GOT entries differ";
  else if(memcmp(GP(acc),GP(right),0x18) || memcmp(GP(back),GP(bot),0x18)) why="accept is not the right button";
  else if(!gr64(acc) || gr64(acc)==gr64(back)) why="key names";
  if(why){ LOG("Orbitals: accept on the bottom button: not applied (%s)\n",why); return; }
  u8 t[0x18]; memcpy(t,GP(acc),0x18); memcpy(GP(acc),GP(back),0x18); memcpy(GP(back),t,0x18);
  LOG("Orbitals: accept on the bottom button: platform accept key = bottom face button, back = right face button\n");
}
static void ekeys_install(const SwrModInfo* mod){
  u64 pc=mod->base+EKEYS_INIT;
  /* pacibsp at the entry; the two copies: ldp x8, x10, [x20]; adrp x9; add x9, x9, #0x438 / ldp x8, x10, [x19]; adrp x9; add x9, x9, #0x450 */
  static const struct { u32 off, w; } sig[]={ {0x50dc00,0xd503237f}, {0x51188c,0xa9402a88}, {0x511894,0x9110e129},
                                               {0x5118bc,0xa9402a68}, {0x5118c4,0x91114129} };
  for(unsigned i=0;i<sizeof sig/sizeof sig[0];i++){
    u64 a=mod->base+sig[i].off;
    if(a<g_code_lo || a>=g_code_hi || gr32(a)!=sig[i].w){ LOG("Orbitals: accept on the bottom button: EKeys initializer not found (%x)\n",sig[i].off); return; }
  }
  GuestFn* e=&g_disp[(pc-g_code_lo)/4];
  if(!*e){ LOG("Orbitals: accept on the bottom button: EKeys initializer has no entry\n"); return; }
  g_main_base=mod->base; ekeys_init_orig=*e; *e=ekeys_init;
}
static void ei_install(const SwrModInfo* mod){
  if(!g_layout) return;
  g_icon_want= g_layout==1? 2 : 1; g_icon_base=mod->base;
  icon_install(mod);
  icon_prompt_install(mod);
  if(!g_accept_bottom) return;
  ekeys_install(mod);
  g_ei_vtable=mod->base+EI_PLATFORM_DATA_VTABLE;
  ei_wrap_vtable(g_ei_vtable,mod->base,mod->size,g_code_lo,g_code_hi,g_disp);
  LOG("Orbitals: button layout: %d virtual functions of the input platform data watched (vtable %llx: %llx %llx, code %llx-%llx)\n",g_neiw,
      (unsigned long long)g_ei_vtable,(unsigned long long)gr64(g_ei_vtable),(unsigned long long)gr64(g_ei_vtable+8),(unsigned long long)g_code_lo,(unsigned long long)g_code_hi);
}

static const u8 orbitals_build[16] = {0x0f,0x8e,0xf5,0x2c,0xf4,0xee,0xe3,0x76,0x28,0xf3,0x66,0xa5,0x39,0xd5,0xd6,0xad};

void orbitals_buttons_ini(const char* k, const char* v){
  if(!strcmp(k,"button_layout")) g_layout= !strcmp(v,"xbox")? 1 : !strcmp(v,"playstation")? 2 : 0;
  else if(!strcmp(k,"button_accept_bottom")) g_accept_bottom=atoi(v)==1;
}
void orbitals_buttons_install(const SwrModInfo* mod){
  if(memcmp(mod->build_id,orbitals_build,sizeof orbitals_build)) return;
  ei_install(mod);
}
