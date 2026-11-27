/* Orbitals PC Recomp, based on SwitchRecomp by MZ Labs. AGPL-3.0, see LICENSE.txt and NOTICE.txt. */
/* Optional Orbitals button layouts. */
#ifndef ORBITALS_BUTTONS_H
#define ORBITALS_BUTTONS_H
#include "rt.h"
void orbitals_buttons_ini(const char* key, const char* value);
void orbitals_buttons_install(const SwrModInfo* mod);
const char* orbitals_layout_overlay(void);
#endif
