#pragma once
#include "rt.h"

enum { WIN_GAMEPAD_SLOTS = 2 };

typedef struct {
  u32 id;
  u16 vendor, product;
  char name[128];
  PadState pad;
  u16 zl, zr;
} WinGamepad;

void win_gamepads_init(void);
const char* win_gamepads_backend(void);
void win_gamepads_poll(WinGamepad pads[WIN_GAMEPAD_SLOTS]);
int win_gamepads_rumble(int player, u16 low, u16 high, u32 duration_ms);
void win_gamepads_inventory(void);
