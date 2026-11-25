// The contract functions the recording layer calls (gfx_backend.h, nvn_obj.h), each forwarding to the backend chosen at run time (gfx_ops.h).
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include "gfx_ops.h"
#include "dm.h"
#include "../host/nvn_present_history.h"

static const struct { const char *name; const gfx_backend_ops *ops; } g_backends[] = {
    {"null", &null_gfx_ops},
#ifdef NXRT_GFX_VK
    {"vulkan", &vk_gfx_ops},
#endif
};
static const gfx_backend_ops *_Atomic g_be;
static _Atomic int g_used;   // a contract function ran: the choice is final

static const gfx_backend_ops *find(const char *name) {
    for (size_t i = 0; i < sizeof g_backends / sizeof *g_backends; i++) if (!strcmp(g_backends[i].name, name)) return g_backends[i].ops;
    return NULL;
}
int nxrt_gfx_select(const char *name) {
    const char *e = getenv("NXRT_GFX");
    if (!name || !*name) name = e && *e ? e : "null";
    const gfx_backend_ops *o = find(name);
    if (!o) {
        LOG("[RED] graphics backend \"%s\" is not built into this nxrt (built in: null%s)", name,
#ifdef NXRT_GFX_VK
            ", vulkan"
#else
            ""
#endif
        );
        return -1;
    }
    const gfx_backend_ops *cur = atomic_load(&g_be);
    if (atomic_load(&g_used) && cur && cur != o) { LOG("[RED] graphics backend already in use (%s): cannot switch to %s", cur->name, o->name); return -1; }
    atomic_store(&g_be, o);
    if (cur != o) LOG("[gfx] backend: %s", o->name);
    return 0;
}
static const gfx_backend_ops *be(void) {
    const gfx_backend_ops *o = atomic_load(&g_be);
    if (!o) {
        if (nxrt_gfx_select(NULL)) { LOG("[RED] NXRT_GFX names no built-in backend: using null"); atomic_store(&g_be, &null_gfx_ops); }
        o = atomic_load(&g_be);
    }
    if (!atomic_load(&g_used)) atomic_store(&g_used, 1);
    return o;
}
const char *nxrt_gfx_name(void) { return be()->name; }

#define GFX_FN(ret, member, name, params, args) ret name params { return be()->member args; }
#define GFX_FNV(ret, member, name, params, args) ret name params { be()->member args; }
#include "gfx_api.h"

int gfx_frame_history_available(void) {
#ifdef NXRT_GFX_VK
    const gfx_backend_ops *selected = atomic_load(&g_be);
    if (selected) return selected == &vk_gfx_ops;
    const char *name = getenv("NXRT_GFX");
    return name && !strcmp(name, "vulkan");
#else
    return 0;
#endif
}

uint64_t gfx_nvn_begin_frame(const void *native) {
#ifdef NXRT_GFX_VK
    if (gfx_frame_history_available()) return vkp_begin_frame(native);
#endif
    (void)native;
    return 0;
}

int gfx_nvn_latest_frame(const void *native, uint64_t *number) {
#ifdef NXRT_GFX_VK
    if (gfx_frame_history_available()) return vkp_latest_frame(native, number);
#endif
    (void)native; (void)number;
    return 0;
}

int gfx_nvn_frame_history(const void *native, NvnFrameInfo *out, int capacity) {
#ifdef NXRT_GFX_VK
    if (gfx_frame_history_available()) return vkp_frame_history(native, out, capacity);
#endif
    (void)native; (void)out; (void)capacity;
    return -1;
}

uint64_t gfx_nvn_present(const tex_t *t, double period, const int crop[4],
                         const void *native, uint64_t number, uint64_t tick) {
#ifdef NXRT_GFX_VK
    if (number) {
        extern uint64_t vk_gfx_present_native(const tex_t *, double, const int[4], const void *, uint64_t, uint64_t);
        return vk_gfx_present_native(t, period, crop, native, number, tick);
    }
#endif
    (void)native; (void)number; (void)tick;
    return gfx_present(t, period, crop);
}
