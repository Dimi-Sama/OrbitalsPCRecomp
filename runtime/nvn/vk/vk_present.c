// The swapchain and the present thread (vk_present.h; docs/m5-vulkan.md §2.3). Behaviour follows nxnative's present queue (nvn_mtl.m present_enqueue,
// mtl_present_wait: a ticket per present, the game's acquire waits for its texture's last ticket); the Vulkan side is written from the specification.
#include "vk_present.h"
#include "vk_flight.h"
#include "vk_shot.h"
#include "vk_submit.h"
#include "vk_window.h"
#include "../host/nvn_present_history.h"
#include "present_vert.h"
#include "present_frag.h"
#include <math.h>
#include <process.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { PQ = 4, NFR = 3, TRING = 256, STAT_N = 300 };
typedef struct { uint64_t serial, wait_value; double period; int crop[4], has_crop, flip; uint64_t t_enq, frame; const void *native; uint64_t frame_number, submitted_tick; char *capture_path; } pq_item;
typedef struct { VkCommandPool pool; VkCommandBuffer cb; VkSemaphore acq; VkFence fence; VkDescriptorSet ds; int used; } frame_t;
typedef struct { VkImage image; VkImageView view; VkSemaphore ready; } present_image;

static struct {
    VkSurfaceKHR surf; VkSwapchainKHR sc; VkFormat fmt; VkExtent2D ext; VkPresentModeKHR mode; int want_mode;
    uint32_t nimg; present_image *images; uint32_t resize_seen; int stale;
    frame_t fr[NFR]; int fi;
    VkPipeline pipe; VkFormat pipe_fmt; VkPipelineLayout pl; VkDescriptorSetLayout dsl; VkDescriptorPool dp; VkSampler samp;
    VkImage dummy; VkImageView dummy_view; vk_alloc dummy_mem;
    pq_item q[PQ]; uint64_t in, read, done; SRWLOCK lk; CONDITION_VARIABLE cv;
    HANDLE thread; _Atomic int stop; vkp_resolve_fn resolve;
    _Atomic uint64_t count, dropped, stall_ns;
    const void *native;
    uint64_t frame_number, native_start;
    struct { uint64_t n; double t; const void *native; NvnFrameInfo frame; } tring[TRING];
    double st_iv[STAT_N]; int st_n; uint64_t st_t0, last_t, acq_ns, src_frames, pattern_frames;
    // capture
    _Atomic int cap_want; int cap_ok, cap_w, cap_h; VkBuffer cap_buf; vk_alloc cap_mem; size_t cap_size; HANDLE cap_ev; uint32_t *cap_px;
    int upscale; float sharpness;   // presentation shader modes: standard (0), sharp (2), EASU (3)
    int upscale_logged;
    int stretch_wide;
} g_p;

static uint64_t t0_ns;

static VkShaderModule shader(const uint32_t *code, size_t bytes) {
    VkShaderModuleCreateInfo ci = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, NULL, 0, bytes, code};
    VkShaderModule m = VK_NULL_HANDLE; vk_module(&ci, &m, "internal-present", "runtime"); return m;
}

static int make_pipeline(VkFormat fmt) {
    if (g_p.pipe && g_p.pipe_fmt == fmt) return 0;
    if (g_p.pipe) { vkDestroyPipeline(g_vk.dev, g_p.pipe, NULL); g_p.pipe = VK_NULL_HANDLE; }
    VkShaderModule vs = shader(present_vert_spv, sizeof present_vert_spv), fs = shader(present_frag_spv, sizeof present_frag_spv);
    VkPipelineShaderStageCreateInfo st[2] = {
        {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, NULL, 0, VK_SHADER_STAGE_VERTEX_BIT, vs, "main", NULL},
        {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, NULL, 0, VK_SHADER_STAGE_FRAGMENT_BIT, fs, "main", NULL}};
    VkPipelineVertexInputStateCreateInfo vi = {VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
    VkPipelineInputAssemblyStateCreateInfo ia = {VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO, NULL, 0, VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST, VK_FALSE};
    VkPipelineViewportStateCreateInfo vp = {VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO, NULL, 0, 1, NULL, 1, NULL};
    VkPipelineRasterizationStateCreateInfo rs = {VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO, NULL, 0, VK_FALSE, VK_FALSE, VK_POLYGON_MODE_FILL,
                                                 VK_CULL_MODE_NONE, VK_FRONT_FACE_COUNTER_CLOCKWISE, VK_FALSE, 0, 0, 0, 1.0f};
    VkPipelineMultisampleStateCreateInfo ms = {VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO, NULL, 0, VK_SAMPLE_COUNT_1_BIT};
    VkPipelineColorBlendAttachmentState ba = {VK_FALSE, 0, 0, 0, 0, 0, 0, 0xf};
    VkPipelineColorBlendStateCreateInfo cb = {VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO, NULL, 0, VK_FALSE, 0, 1, &ba};
    VkDynamicState dyn[2] = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo ds = {VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO, NULL, 0, 2, dyn};
    VkPipelineRenderingCreateInfo ri = {VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO, NULL, 0, 1, &fmt, VK_FORMAT_UNDEFINED, VK_FORMAT_UNDEFINED};
    VkGraphicsPipelineCreateInfo pci = {VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO, &ri, 0, 2, st, &vi, &ia, NULL, &vp, &rs, &ms, NULL, &cb, &ds, g_p.pl,
                                        VK_NULL_HANDLE, 0, VK_NULL_HANDLE, -1};
    VkResult r = vkCreateGraphicsPipelines(g_vk.dev, g_vk.pcache, 1, &pci, NULL, &g_p.pipe);
    void vkpc_note_created(int n); vkpc_note_created(1);
    vkDestroyShaderModule(g_vk.dev, vs, NULL); vkDestroyShaderModule(g_vk.dev, fs, NULL);
    if (r != VK_SUCCESS) { VKRED("cannot create the present pipeline (%d)", r); return -1; }
    g_p.pipe_fmt = fmt;
    return 0;
}

static void destroy_swapchain_views(void) {
    for (uint32_t i = 0; i < g_p.nimg; i++) {
        present_image *img = &g_p.images[i];
        if (img->view) vkDestroyImageView(g_vk.dev, img->view, NULL);
        if (img->ready) vkDestroySemaphore(g_vk.dev, img->ready, NULL);
    }
    free(g_p.images); g_p.images = NULL; g_p.nimg = 0;
}

// (Re)creates the swapchain at the window's current drawable size; 0 = usable, 1 = not now (minimized, zero size), -1 = failed
static int make_swapchain(void) {
    g_p.stale = 1;
    VkSurfaceCapabilitiesKHR caps;
    VkResult r = vkGetPhysicalDeviceSurfaceCapabilitiesKHR(g_vk.pd, g_p.surf, &caps);
    if (r != VK_SUCCESS) { VKRED("cannot query window surface capabilities (%d)", r); return -1; }
    int ww, wh; vkw_pixel_size(&ww, &wh);
    VkExtent2D ext = caps.currentExtent;
    if (ext.width == 0xFFFFFFFFu) { ext.width = (uint32_t)ww; ext.height = (uint32_t)wh; }
    if (!ext.width || !ext.height || !caps.maxImageExtent.width || !caps.maxImageExtent.height) return 1;
    if (ext.width < caps.minImageExtent.width) ext.width = caps.minImageExtent.width;
    if (ext.height < caps.minImageExtent.height) ext.height = caps.minImageExtent.height;
    if (ext.width > caps.maxImageExtent.width) ext.width = caps.maxImageExtent.width;
    if (ext.height > caps.maxImageExtent.height) ext.height = caps.maxImageExtent.height;
    VkSurfaceFormatKHR format = {0};
    {
        uint32_t n = 0;
        r = vkGetPhysicalDeviceSurfaceFormatsKHR(g_vk.pd, g_p.surf, &n, NULL);
        if (r != VK_SUCCESS || !n) { VKRED("window surface reports no formats (%d)", r); return -1; }
        VkSurfaceFormatKHR *f = calloc(n, sizeof *f);
        if (!f) return -1;
        r = vkGetPhysicalDeviceSurfaceFormatsKHR(g_vk.pd, g_p.surf, &n, f);
        if (r != VK_SUCCESS || !n) { free(f); return r == VK_INCOMPLETE ? 1 : -1; }
        const VkFormat pref[] = {VK_FORMAT_B8G8R8A8_UNORM, VK_FORMAT_R8G8B8A8_UNORM, VK_FORMAT_A2B10G10R10_UNORM_PACK32};
        for (unsigned k = 0; k < sizeof pref / sizeof *pref && !format.format; k++)
            for (uint32_t i = 0; i < n; i++) if (f[i].format == pref[k] && f[i].colorSpace == VK_COLOR_SPACE_SRGB_NONLINEAR_KHR) { format = f[i]; break; }
        if (!format.format) format = f[0];
        free(f);
    }
    if (!g_p.sc) {
        uint32_t nm = 0; vkGetPhysicalDeviceSurfacePresentModesKHR(g_vk.pd, g_p.surf, &nm, NULL);
        VkPresentModeKHR *m = calloc(nm + 1, sizeof *m); vkGetPhysicalDeviceSurfacePresentModesKHR(g_vk.pd, g_p.surf, &nm, m);
        VkPresentModeKHR want = g_p.want_mode == VKP_MAILBOX ? VK_PRESENT_MODE_MAILBOX_KHR : g_p.want_mode == VKP_IMMEDIATE ? VK_PRESENT_MODE_IMMEDIATE_KHR : VK_PRESENT_MODE_FIFO_KHR;
        g_p.mode = VK_PRESENT_MODE_FIFO_KHR;
        for (uint32_t i = 0; i < nm; i++) if (m[i] == want) g_p.mode = want;
        if (g_p.mode != want) VKLOG("present mode %d not offered by the surface: FIFO", want);
        free(m);
    }
    uint32_t nimg = caps.minImageCount < 3 ? 3 : caps.minImageCount;
    if (caps.maxImageCount && nimg > caps.maxImageCount) nimg = caps.maxImageCount;
    VkImageUsageFlags usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | (caps.supportedUsageFlags & (VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT));
    VkCompositeAlphaFlagBitsKHR alpha = caps.supportedCompositeAlpha & (0u - caps.supportedCompositeAlpha);
    VkSwapchainCreateInfoKHR ci = {VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR, NULL, 0, g_p.surf, nimg, format.format, format.colorSpace, ext, 1, usage,
                                   VK_SHARING_MODE_EXCLUSIVE, 0, NULL, caps.currentTransform,
                                   alpha, g_p.mode, VK_TRUE, g_p.sc};
    VkSwapchainKHR sc = VK_NULL_HANDLE;
    // a resize: the old images and semaphores may still be in use by the last presentation, which no fence covers: let the queue drain (rare)
    AcquireSRWLockExclusive(&g_vk.qlock); vkQueueWaitIdle(g_vk.q); ReleaseSRWLockExclusive(&g_vk.qlock);
    r = vkCreateSwapchainKHR(g_vk.dev, &ci, NULL, &sc);
    destroy_swapchain_views();
    if (g_p.sc) vkDestroySwapchainKHR(g_vk.dev, g_p.sc, NULL);
    g_p.sc = VK_NULL_HANDLE;
    if (r == VK_ERROR_OUT_OF_DATE_KHR) return 1;
    if (r != VK_SUCCESS) { VKRED("vkCreateSwapchainKHR %ux%u failed (%d)", ext.width, ext.height, r); return -1; }
    g_p.sc = sc; g_p.ext = ext; g_p.fmt = format.format;
    r = vkGetSwapchainImagesKHR(g_vk.dev, sc, &nimg, NULL);
    if (r != VK_SUCCESS || !nimg) goto fail;
    VkImage *handles = calloc(nimg, sizeof *handles);
    if (!handles) goto fail;
    r = vkGetSwapchainImagesKHR(g_vk.dev, sc, &nimg, handles);
    if (r == VK_SUCCESS) g_p.images = calloc(nimg, sizeof *g_p.images);
    if (!g_p.images) { free(handles); goto fail; }
    g_p.nimg = nimg;
    for (uint32_t i = 0; i < nimg; i++) g_p.images[i].image = handles[i];
    free(handles);
    for (uint32_t i = 0; i < g_p.nimg; i++) {
        present_image *img = &g_p.images[i];
        VkImageViewCreateInfo vci = {VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, NULL, 0, img->image, VK_IMAGE_VIEW_TYPE_2D, g_p.fmt, {0},
                                     {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
        r = vkCreateImageView(g_vk.dev, &vci, NULL, &img->view);
        if (r != VK_SUCCESS) goto fail;
        VkSemaphoreCreateInfo sci = {VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};
        r = vkCreateSemaphore(g_vk.dev, &sci, NULL, &img->ready);
        if (r != VK_SUCCESS) goto fail;
    }
    g_p.cap_ok = (usage & VK_IMAGE_USAGE_TRANSFER_SRC_BIT) &&
        (g_p.fmt == VK_FORMAT_R8G8B8A8_UNORM || g_p.fmt == VK_FORMAT_R8G8B8A8_SRGB ||
         g_p.fmt == VK_FORMAT_B8G8R8A8_UNORM || g_p.fmt == VK_FORMAT_B8G8R8A8_SRGB ||
         g_p.fmt == VK_FORMAT_A2B10G10R10_UNORM_PACK32);
    if (make_pipeline(g_p.fmt)) goto fail;
    g_p.stale = 0;
    VKLOG("swapchain %ux%u, %u images, format %d, color space %d, %s", ext.width, ext.height, g_p.nimg, g_p.fmt, format.colorSpace,
          g_p.mode == VK_PRESENT_MODE_MAILBOX_KHR ? "mailbox" : g_p.mode == VK_PRESENT_MODE_IMMEDIATE_KHR ? "immediate" : "FIFO (vsync)");
    return 0;
fail:
    VKRED("could not initialize swapchain images or pipeline (%d)", r);
    destroy_swapchain_views(); vkDestroySwapchainKHR(g_vk.dev, g_p.sc, NULL); g_p.sc = VK_NULL_HANDLE;
    return -1;
}

static int dcmp(const void *a, const void *b) { double x = *(const double *)a, y = *(const double *)b; return x < y ? -1 : x > y; }
static void stats(uint64_t now) {
    if (g_p.last_t) { if (!g_p.st_n) g_p.st_t0 = g_p.last_t; g_p.st_iv[g_p.st_n++] = (now - g_p.last_t) / 1e6; }
    g_p.last_t = now;
    if (g_p.st_n < STAT_N) return;
    double secs = (now - g_p.st_t0) / 1e9, *v = g_p.st_iv;
    qsort(v, STAT_N, sizeof *v, dcmp);
    VKLOG("present: %llu shown (%llu dropped), %.2f per s; interval p50 %.2f / p95 %.2f / p99 %.2f / max %.2f ms; acquire %.2f ms per frame; window %ux%u; "
          "%llu game frames, %llu test pattern", (unsigned long long)atomic_load(&g_p.count), (unsigned long long)atomic_load(&g_p.dropped), STAT_N / secs,
          v[STAT_N / 2], v[STAT_N * 95 / 100], v[STAT_N * 99 / 100], v[STAT_N - 1], g_p.acq_ns / 1e6 / STAT_N, g_p.ext.width, g_p.ext.height,
          (unsigned long long)g_p.src_frames, (unsigned long long)g_p.pattern_frames);
    g_p.st_n = 0; g_p.acq_ns = 0;
}

static uint64_t guest_tick(void) {
    extern uint64_t swr_guest_ticks(void);   // the game's system counter (31.25 MHz on Switch 2)
    return swr_guest_ticks();
}

static void finish_item(uint64_t n, const pq_item *item, int dropped) {
    double t = dropped ? -1.0 : (now_ns() - t0_ns) / 1e9;
    uint64_t tick = item->frame_number && !dropped ? guest_tick() : 0;
    AcquireSRWLockExclusive(&g_p.lk);
    g_p.tring[n % TRING].n = n; g_p.tring[n % TRING].t = t;
    g_p.tring[n % TRING].native = item->native;
    // Vulkan supplies the time the present was accepted. Use it for both SDK display timestamps.
    g_p.tring[n % TRING].frame = (NvnFrameInfo){
        tick ? 2 : 1, item->frame_number, item->submitted_tick, tick, tick
    };
    g_p.done = n; WakeAllConditionVariable(&g_p.cv); ReleaseSRWLockExclusive(&g_p.lk);
}

uint64_t vkp_begin_frame(const void *native) {
    if (!native) return 0;
    AcquireSRWLockExclusive(&g_p.lk);
    if (g_p.native != native) {
        // The Win32 backend presents to one swapchain. A new native window starts its own history.
        g_p.native = native;
        g_p.frame_number = 0;
        g_p.native_start = g_p.in;
    }
    uint64_t number = ++g_p.frame_number;
    ReleaseSRWLockExclusive(&g_p.lk);
    return number;
}

int vkp_latest_frame(const void *native, uint64_t *number) {
    if (!native) return 0;
    AcquireSRWLockShared(&g_p.lk);
    int matches = g_p.native == native;
    if (matches) *number = g_p.frame_number;
    ReleaseSRWLockShared(&g_p.lk);
    return matches;
}

int vkp_frame_history(const void *native, NvnFrameInfo *out, int capacity) {
    if (!native) return -1;
    AcquireSRWLockShared(&g_p.lk);
    int count = -1;
    if (g_p.native == native) {
        count = out && capacity != 0 ? 0 : NVN_FRAME_HISTORY_CAPACITY;
        if (capacity > NVN_FRAME_HISTORY_CAPACITY) capacity = NVN_FRAME_HISTORY_CAPACITY;
        for (uint64_t n = g_p.done; out && n > g_p.native_start && g_p.done - n < TRING && count < capacity; --n) {
            unsigned slot = n % TRING;
            if (g_p.tring[slot].n == n && g_p.tring[slot].native == native && g_p.tring[slot].frame.number)
                out[count++] = g_p.tring[slot].frame;
        }
    }
    ReleaseSRWLockShared(&g_p.lk);
    return count;
}

// Waits on a high-resolution waitable timer (Sleep follows the system timer, 15.6 ms unless something raised it), the last 0.3 ms by yielding
static void sleep_until(uint64_t t) {
    static __thread HANDLE timer;
    if (!timer) timer = CreateWaitableTimerExW(NULL, NULL, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
    for (;;) {
        uint64_t now = now_ns();
        if (now >= t) return;
        uint64_t d = t - now;
        if (d > 600000 && timer) {
            LARGE_INTEGER due; due.QuadPart = -(LONGLONG)((d - 300000) / 100);
            if (SetWaitableTimer(timer, &due, 0, NULL, NULL, FALSE)) { WaitForSingleObject(timer, INFINITE); continue; }
        }
        if (d > 2000000) Sleep((DWORD)((d - 1500000) / 1000000)); else SwitchToThread();
    }
}

static int capture_buffer(size_t bytes) {
    if (g_p.cap_size >= bytes) return 1;
    if (g_p.cap_buf) {
        vkDestroyBuffer(g_vk.dev, g_p.cap_buf, NULL);
        vk_free_mem(&g_p.cap_mem);
        g_p.cap_buf = VK_NULL_HANDLE;
        g_p.cap_size = 0;
    }
    VkBufferCreateInfo bci = {VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, NULL, 0, bytes, VK_BUFFER_USAGE_TRANSFER_DST_BIT, VK_SHARING_MODE_EXCLUSIVE, 0, NULL};
    VkBuffer buffer;
    if (vkCreateBuffer(g_vk.dev, &bci, NULL, &buffer) != VK_SUCCESS) return 0;
    VkMemoryRequirements mr;
    vkGetBufferMemoryRequirements(g_vk.dev, buffer, &mr);
    if (vk_alloc_mem(&mr, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT, 0, &g_p.cap_mem)) {
        vkDestroyBuffer(g_vk.dev, buffer, NULL);
        return 0;
    }
    if (vkBindBufferMemory(g_vk.dev, buffer, g_p.cap_mem.mem, g_p.cap_mem.off) != VK_SUCCESS) {
        vkDestroyBuffer(g_vk.dev, buffer, NULL);
        vk_free_mem(&g_p.cap_mem);
        return 0;
    }
    g_p.cap_buf = buffer;
    g_p.cap_size = bytes;
    return 1;
}

static void capture_file(const char *path, int width, int height) {
    size_t pixels = (size_t)width * height;
    uint8_t *rgba = malloc(pixels * 4);
    int rc = -1;
    if (rgba && !vks_to_rgba8(g_p.fmt, g_p.cap_mem.map, pixels, rgba)) {
        for (size_t i = 0; i < pixels; i++) rgba[4 * i + 3] = 255;
        rc = vks_png_write(path, rgba, width, height);
    }
    free(rgba);
    VKLOG("screenshot: the window (%dx%d) %s %s", width, height, rc ? "could not be written to" : "written to", path);
}

// One present: acquire, draw the source (or the test pattern) letterboxed into the swapchain image, submit after the frame's GPU work, present
// ---------- The SwitchRECOMP startup screen (NOTICE.txt, AGPL v3 section 7(b): every game built with SwitchRecomp shows it at start) ----------
// The OpenGL renderer draws it in gpu_gl.c splash_play; this is the Vulkan renderer's: the same 1280x720 coverage image (splash_img.h), white on
// black, shown for SWR_SPLASH_SECONDS (at least 1) before the game's first picture, through the present pipeline (an R8 image whose view swizzles
// red to RGB).
#include "../../splash_img.h"
static struct { VkImage img; VkImageView view; vk_alloc mem; int on; } g_splash;
static int splash_make(void) {
    VkImageCreateInfo ic = {VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, NULL, 0, VK_IMAGE_TYPE_2D, VK_FORMAT_R8_UNORM, {SPLASH_W, SPLASH_H, 1}, 1, 1, VK_SAMPLE_COUNT_1_BIT,
                            VK_IMAGE_TILING_OPTIMAL, VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, VK_SHARING_MODE_EXCLUSIVE, 0, NULL, VK_IMAGE_LAYOUT_UNDEFINED};
    if (vkCreateImage(g_vk.dev, &ic, NULL, &g_splash.img) != VK_SUCCESS) return -1;
    VkMemoryRequirements mr; vkGetImageMemoryRequirements(g_vk.dev, g_splash.img, &mr);
    if (vk_alloc_mem(&mr, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, 0, &g_splash.mem)) return -1;
    vkBindImageMemory(g_vk.dev, g_splash.img, g_splash.mem.mem, g_splash.mem.off);
    VkImageViewCreateInfo vci = {VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, NULL, 0, g_splash.img, VK_IMAGE_VIEW_TYPE_2D, VK_FORMAT_R8_UNORM,
                                 {VK_COMPONENT_SWIZZLE_R, VK_COMPONENT_SWIZZLE_R, VK_COMPONENT_SWIZZLE_R, VK_COMPONENT_SWIZZLE_ONE}, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    if (vkCreateImageView(g_vk.dev, &vci, NULL, &g_splash.view) != VK_SUCCESS) return -1;
    // the pixels through a host-visible staging buffer
    VkBufferCreateInfo bci = {VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, NULL, 0, (VkDeviceSize)SPLASH_W * SPLASH_H, VK_BUFFER_USAGE_TRANSFER_SRC_BIT, VK_SHARING_MODE_EXCLUSIVE, 0, NULL};
    VkBuffer sb; vk_alloc sm;
    if (vkCreateBuffer(g_vk.dev, &bci, NULL, &sb) != VK_SUCCESS) return -1;
    VkMemoryRequirements br; vkGetBufferMemoryRequirements(g_vk.dev, sb, &br);
    if (vk_alloc_mem(&br, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT, 0, &sm) || !sm.map) { vkDestroyBuffer(g_vk.dev, sb, NULL); return -1; }
    vkBindBufferMemory(g_vk.dev, sb, sm.mem, sm.off);
    splash_unpack((unsigned char *)sm.map);
    VkCommandBuffer cb = vk_once_begin();
    vk_image_barrier(cb, g_splash.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_PIPELINE_STAGE_2_NONE, 0,
                     VK_PIPELINE_STAGE_2_COPY_BIT, VK_ACCESS_2_TRANSFER_WRITE_BIT);
    VkBufferImageCopy c = {0, 0, 0, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, {0, 0, 0}, {SPLASH_W, SPLASH_H, 1}};
    vkCmdCopyBufferToImage(cb, sb, g_splash.img, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &c);
    vk_image_barrier(cb, g_splash.img, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
                     VK_PIPELINE_STAGE_2_COPY_BIT, VK_ACCESS_2_TRANSFER_WRITE_BIT, VK_PIPELINE_STAGE_2_FRAGMENT_SHADER_BIT, VK_ACCESS_2_SHADER_SAMPLED_READ_BIT);
    int r = vk_once_end(cb);   // waits for completion: the staging buffer can go
    vkDestroyBuffer(g_vk.dev, sb, NULL);
    return r;
}

static int present_one(const pq_item *it) {
    if (g_p.stale || vkw_resize_serial() != g_p.resize_seen) { g_p.resize_seen = vkw_resize_serial(); int r = make_swapchain(); if (r) return r; }
    if (!g_p.sc) return 1;
    vkf_poll();
    frame_t *f = &g_p.fr[g_p.fi]; g_p.fi = (g_p.fi + 1) % NFR;
    if (f->used) { vkWaitForFences(g_vk.dev, 1, &f->fence, VK_TRUE, UINT64_MAX); vkResetFences(g_vk.dev, 1, &f->fence); }
    uint64_t a0 = now_ns(); uint32_t idx = 0;
    VkResult r = vkAcquireNextImageKHR(g_vk.dev, g_p.sc, 250000000ull, f->acq, VK_NULL_HANDLE, &idx);
    g_p.acq_ns += now_ns() - a0;
    if (r != VK_SUCCESS && r != VK_SUBOPTIMAL_KHR) {
        f->used = 0;
        if (r == VK_ERROR_OUT_OF_DATE_KHR) { g_p.stale = 1; return 1; }
        if (r == VK_TIMEOUT || r == VK_NOT_READY) return 1;
        VKRED("cannot acquire a swapchain image (%d)", r); vk_lost("swapchain acquire", r); return -1;
    }
    if (r == VK_SUBOPTIMAL_KHR) g_p.stale = 1;
    present_image *img = &g_p.images[idx];

    vkp_source src = {0}; int have = it->serial && g_p.resolve && g_p.resolve(it->serial, &src) && src.view;
    if (!it->serial && g_splash.on) { src = (vkp_source){g_splash.view, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL, SPLASH_W, SPLASH_H}; have = 1; }
    float pw = have ? (float)src.w : 1920.0f, ph = have ? (float)src.h : 1080.0f, u0 = 0, v0 = 0, u1 = 1, v1 = 1;
    if (have && it->has_crop && it->crop[2] > 0 && it->crop[3] > 0) {
        u0 = it->crop[0] / pw; v0 = it->crop[1] / ph; u1 = (it->crop[0] + it->crop[2]) / pw; v1 = (it->crop[1] + it->crop[3]) / ph;
        pw = (float)it->crop[2]; ph = (float)it->crop[3];
    }
    if (it->flip && have) { float t = v0; v0 = v1; v1 = t; }   // GL's lower-left origin: the picture is stored bottom up
    float W = (float)g_p.ext.width, H = (float)g_p.ext.height, s = fminf(W / pw, H / ph), vw = floorf(pw * s + 0.5f), vh = floorf(ph * s + 0.5f);
    int stretch = have && it->serial && g_p.stretch_wide && W * ph > H * pw;
    if (stretch) { vw = W; vh = H; }
    VkViewport vp = {floorf((W - vw) / 2), floorf((H - vh) / 2), vw, vh, 0, 1};
    VkRect2D sc = {{(int32_t)vp.x, (int32_t)vp.y}, {(uint32_t)vw, (uint32_t)vh}};
    VkDescriptorImageInfo dii = {g_p.samp, have ? src.view : g_p.dummy_view, have ? src.layout : VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL};
    VkWriteDescriptorSet w = {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, f->ds, 0, 0, 1, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, &dii, NULL, NULL};
    vkUpdateDescriptorSets(g_vk.dev, 1, &w, 0, NULL);
    if (have) g_p.src_frames++; else g_p.pattern_frames++;

    vkResetCommandPool(g_vk.dev, f->pool, 0);
    VkCommandBufferBeginInfo bi = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, NULL, VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT, NULL};
    vkBeginCommandBuffer(f->cb, &bi);
    vk_image_barrier(f->cb, img->image, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
                     VK_PIPELINE_STAGE_2_COLOR_ATTACHMENT_OUTPUT_BIT, 0, VK_PIPELINE_STAGE_2_COLOR_ATTACHMENT_OUTPUT_BIT, VK_ACCESS_2_COLOR_ATTACHMENT_WRITE_BIT);
    VkRenderingAttachmentInfo ca = {VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO, NULL, img->view, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, 0, VK_NULL_HANDLE,
                                    VK_IMAGE_LAYOUT_UNDEFINED, VK_ATTACHMENT_LOAD_OP_CLEAR, VK_ATTACHMENT_STORE_OP_STORE, {{{0, 0, 0, 1}}}};
    VkRenderingInfo ri = {VK_STRUCTURE_TYPE_RENDERING_INFO, NULL, 0, {{0, 0}, g_p.ext}, 1, 0, 1, &ca, NULL, NULL};
    vkCmdBeginRendering(f->cb, &ri);
    vkCmdBindPipeline(f->cb, VK_PIPELINE_BIND_POINT_GRAPHICS, g_p.pipe);
    vkCmdSetViewport(f->cb, 0, 1, &vp); vkCmdSetScissor(f->cb, 0, 1, &sc);
    vkCmdBindDescriptorSets(f->cb, VK_PIPELINE_BIND_POINT_GRAPHICS, g_p.pl, 0, 1, &f->ds, 0, NULL);
    float mode = !have ? 1.0f : s > 1.01f && !stretch ? (float)g_p.upscale : 0.0f;
    if (mode == 3.0f && !g_p.upscale_logged) {
        g_p.upscale_logged = 1;
        VKLOG("present: FSR 1 EASU active, %.0fx%.0f -> %.0fx%.0f", pw, ph, vw, vh);
    }
    float pc[12] = {u0, v0, u1, v1, mode, (float)(atomic_load(&g_p.count) + 1), pw, ph, g_p.sharpness, vw, vh, 0};
    vkCmdPushConstants(f->cb, g_p.pl, VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof pc, pc);
    vkCmdDraw(f->cb, 3, 1, 0, 0);
    vkCmdEndRendering(f->cb);
    int sync_capture = atomic_load(&g_p.cap_want);
    int cap = (it->capture_path || sync_capture) && g_p.cap_ok && capture_buffer((size_t)g_p.ext.width * g_p.ext.height * 4);
    int fl = have && g_p.cap_ok && vkf_wants();
    if (cap || fl) {
        vk_image_barrier(f->cb, img->image, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                         VK_PIPELINE_STAGE_2_COLOR_ATTACHMENT_OUTPUT_BIT, VK_ACCESS_2_COLOR_ATTACHMENT_WRITE_BIT, VK_PIPELINE_STAGE_2_ALL_TRANSFER_BIT, VK_ACCESS_2_TRANSFER_READ_BIT);
        VkBufferImageCopy c = {0, 0, 0, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, {0, 0, 0}, {g_p.ext.width, g_p.ext.height, 1}};
        if (cap) vkCmdCopyImageToBuffer(f->cb, img->image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, g_p.cap_buf, 1, &c);
        if (fl) vkf_present(f->cb, img->image, g_p.ext, g_p.pipe_fmt, it->frame);
        vk_image_barrier(f->cb, img->image, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR,
                         VK_PIPELINE_STAGE_2_ALL_TRANSFER_BIT, 0, VK_PIPELINE_STAGE_2_BOTTOM_OF_PIPE_BIT, 0);
    } else
        vk_image_barrier(f->cb, img->image, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR,
                         VK_PIPELINE_STAGE_2_COLOR_ATTACHMENT_OUTPUT_BIT, VK_ACCESS_2_COLOR_ATTACHMENT_WRITE_BIT, VK_PIPELINE_STAGE_2_BOTTOM_OF_PIPE_BIT, 0);
    vkEndCommandBuffer(f->cb);

    VkSemaphoreSubmitInfo wait[2] = {{VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO, NULL, f->acq, 0, VK_PIPELINE_STAGE_2_COLOR_ATTACHMENT_OUTPUT_BIT, 0},
                                     {VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO, NULL, g_vk.tl, it->wait_value, VK_PIPELINE_STAGE_2_FRAGMENT_SHADER_BIT, 0}};
    VkSemaphoreSubmitInfo sig = {VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO, NULL, img->ready, 0, VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, 0};
    VkCommandBufferSubmitInfo cbi = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_SUBMIT_INFO, NULL, f->cb, 0};
    VkSubmitInfo2 si = {VK_STRUCTURE_TYPE_SUBMIT_INFO_2, NULL, 0, it->wait_value ? 2u : 1u, wait, 1, &cbi, 1, &sig};
    VkPresentInfoKHR pi = {VK_STRUCTURE_TYPE_PRESENT_INFO_KHR, NULL, 1, &img->ready, 1, &g_p.sc, &idx, NULL};
    // On one queue a wait for work behind it never ends, so the frame's value must be on the queue first: the flush in present_main can come while the frame is still being recorded or
    // committed. (Not the long-race stall in CHANGES_SWITCH2RECOMP.md: that one outlived this)
    while (it->wait_value && atomic_load(&g_vk.tl_submitted) < it->wait_value && !atomic_load(&g_vk.lost)) { vks_flush(); if (atomic_load(&g_vk.tl_submitted) < it->wait_value) Sleep(1); }
    AcquireSRWLockExclusive(&g_vk.qlock);
    r = vkQueueSubmit2(g_vk.q, 1, &si, f->fence);
    VkResult pr = r == VK_SUCCESS ? vkQueuePresentKHR(g_vk.q, &pi) : r;
    ReleaseSRWLockExclusive(&g_vk.qlock);
    f->used = r == VK_SUCCESS;
    if (r != VK_SUCCESS) { VKRED("present submit failed (%d)", r); vk_lost("a present", r); return -1; }
    if (pr == VK_ERROR_OUT_OF_DATE_KHR || pr == VK_SUBOPTIMAL_KHR) g_p.stale = 1;
    if (cap) r = vkWaitForFences(g_vk.dev, 1, &f->fence, VK_TRUE, UINT64_MAX);
    if (pr == VK_ERROR_OUT_OF_DATE_KHR) return 1;
    if (pr != VK_SUCCESS && pr != VK_SUBOPTIMAL_KHR) {
        VKRED("queue present failed (%d)", pr);
        vk_lost("a present", pr);
        return -1;
    }
    if (!g_splash.on && !atomic_load(&g_p.count)) VKLOG("first game present accepted %.2f s after presentation init (source %s)", (now_ns() - t0_ns) / 1e9,
                                                     have ? "available" : "missing");
    if (sync_capture && atomic_load(&g_p.cap_want)) {
        if (cap && r == VK_SUCCESS) {
            size_t n = (size_t)g_p.ext.width * g_p.ext.height;
            g_p.cap_px = malloc(n * 4);
            if (g_p.cap_px) memcpy(g_p.cap_px, g_p.cap_mem.map, n * 4);
            g_p.cap_w = (int)g_p.ext.width; g_p.cap_h = (int)g_p.ext.height;
        }
        atomic_store(&g_p.cap_want, 0);
        SetEvent(g_p.cap_ev);
    }
    if (it->capture_path) {
        if (cap && r == VK_SUCCESS) capture_file(it->capture_path, (int)g_p.ext.width, (int)g_p.ext.height);
        else VKLOG("screenshot: window readback unavailable for %s", it->capture_path);
    }
    return 0;
}

static unsigned __stdcall present_main(void *arg) {
    (void)arg;
    SetThreadDescription(GetCurrentThread(), L"vk present");
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_HIGHEST);
    {   // the startup screen before anything else (the game's first presents wait in the queue meanwhile)
        const char *e = getenv("SWR_SPLASH_SECONDS"); double secs = e && *e ? atof(e) : 1.0; if (secs < 1.0) secs = 1.0;
        if (!splash_make()) {
            // timed from its first picture on screen (an X11 window can take a moment to map), at most 3 s more waiting for that
            g_splash.on = 1; uint64_t t0 = now_ns(), first = 0, next = t0; int n = 0;
            while (!atomic_load(&g_p.stop)) {
                uint64_t now = now_ns();
                if (first ? (double)(now - first) / 1e9 >= secs : (double)(now - t0) / 1e9 >= secs + 3.0) break;
                pq_item sp = {0}; int r = 1;
                if (vkw_is_open() && !vkw_minimized()) { r = present_one(&sp); if (r == 1) r = present_one(&sp); }
                if (!r) { n++; if (!first) first = now_ns(); }
                next += 16666667ull; sleep_until(next);
            }
            g_splash.on = 0;
            VKLOG("startup screen shown for %.1f s (%d presents, first after %.2f s)", first ? (double)(now_ns() - first) / 1e9 : 0.0, n, first ? (double)(first - t0) / 1e9 : -1.0);
        } else VKRED("the startup screen could not be made");
    }
    uint64_t last_present = 0;   // the next present slot (period pacing)
    for (;;) {
        AcquireSRWLockExclusive(&g_p.lk);
        while (g_p.read == g_p.in && !atomic_load(&g_p.stop)) SleepConditionVariableSRW(&g_p.cv, &g_p.lk, 100, 0);
        if (atomic_load(&g_p.stop) && g_p.read == g_p.in) { ReleaseSRWLockExclusive(&g_p.lk); break; }
        pq_item it = g_p.q[g_p.read % PQ]; uint64_t n = ++g_p.read;
        WakeAllConditionVariable(&g_p.cv);   // room in the queue
        ReleaseSRWLockExclusive(&g_p.lk);
        vks_flush();   // the frame's GPU work goes to the queue before its present
        static int dropping;
        int drop = !vkw_is_open() || vkw_minimized();
        if (drop != dropping) { dropping = drop; VKLOG("present: %s at present %llu", drop ? "window minimized, presents dropped from here" : "presenting again", (unsigned long long)n); }
        if (drop) { free(it.capture_path); atomic_fetch_add(&g_p.dropped, 1); finish_item(n, &it, 1); continue; }
        uint64_t st = atomic_load(&g_p.stall_ns); if (st) sleep_until(now_ns() + st);
        // The game's present period on a fixed cadence: a present is not handed over before its slot (k periods after the first), so a producer that runs
        // ahead is held to the period on any display rate (FIFO then shows it at the next vsync); late frames go at once and the cadence restarts from them
        if (it.period > 0) {
            uint64_t per = (uint64_t)(it.period * 1e9), now = now_ns();
            if (!last_present || now > last_present + 2 * per) last_present = now;
            else { sleep_until(last_present - 500000); }
            last_present += per;
        }
        int r = present_one(&it);
        if (r == 1) r = present_one(&it);   // the swapchain was out of date: once more at the new size
        free(it.capture_path);
        if (r) { if (!atomic_fetch_add(&g_p.dropped, 1)) VKLOG("present %llu dropped (no usable swapchain: %d)", (unsigned long long)n, r); finish_item(n, &it, 1); continue; }
        uint64_t now = now_ns();
        atomic_fetch_add(&g_p.count, 1); atomic_fetch_add(&g_vk.presents, 1);
        stats(now);
        finish_item(n, &it, 0);
    }
    return 0;
}

int vkp_init(int mode) {
    t0_ns = now_ns();
    InitializeSRWLock(&g_p.lk); InitializeConditionVariable(&g_p.cv);
    g_p.want_mode = mode;
    if (vkw_create_surface(g_vk.inst, &g_p.surf)) return -1;
    VkBool32 ok = VK_FALSE; vkGetPhysicalDeviceSurfaceSupportKHR(g_vk.pd, g_vk.qfam, g_p.surf, &ok);
    if (!ok) { VKRED("queue family %u cannot present to the window", g_vk.qfam); return -1; }
    // Layout, sampler, descriptors, the dummy image the test pattern binds
    VkDescriptorSetLayoutBinding b = {0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_FRAGMENT_BIT, NULL};
    VkDescriptorSetLayoutCreateInfo dl = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, NULL, 0, 1, &b};
    vkCreateDescriptorSetLayout(g_vk.dev, &dl, NULL, &g_p.dsl);
    VkPushConstantRange pcr = {VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, 48};
    const char *e = getenv("NXRT_VK_UPSCALE");
    g_p.upscale = e && !strcmp(e, "fsr1") ? 3 : e && !strcmp(e, "standard") ? 0 : 2;
    e = getenv("NXRT_VK_STRETCH_WIDE"); g_p.stretch_wide = e && !strcmp(e, "1");
    e = getenv("NXRT_VK_SHARPNESS"); g_p.sharpness = e && *e ? (float)atof(e) : 0.5f;
    if (g_p.sharpness < 0) g_p.sharpness = 0; else if (g_p.sharpness > 1) g_p.sharpness = 1;
    VKLOG("present: upscaling to a window larger than the picture %s",
          g_p.upscale == 3 ? "FSR 1 EASU" : g_p.upscale == 2 ? "sharp (contrast-adaptive)" : "standard (bilinear)");
    if (g_p.upscale == 2) VKLOG("present: sharpness %.2f (NXRT_VK_SHARPNESS 0..1)", g_p.sharpness);
    VkPipelineLayoutCreateInfo pl = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, NULL, 0, 1, &g_p.dsl, 1, &pcr};
    vkCreatePipelineLayout(g_vk.dev, &pl, NULL, &g_p.pl);
    VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, NFR};
    VkDescriptorPoolCreateInfo dp = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, NULL, 0, NFR, 1, &ps};
    vkCreateDescriptorPool(g_vk.dev, &dp, NULL, &g_p.dp);
    VkSamplerCreateInfo sci = {VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO, NULL, 0, VK_FILTER_LINEAR, VK_FILTER_LINEAR, VK_SAMPLER_MIPMAP_MODE_NEAREST,
                               VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, 0, VK_FALSE, 1, VK_FALSE,
                               VK_COMPARE_OP_NEVER, 0, 0, VK_BORDER_COLOR_FLOAT_TRANSPARENT_BLACK, VK_FALSE};
    vkCreateSampler(g_vk.dev, &sci, NULL, &g_p.samp);
    VkImageCreateInfo ic = {VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, NULL, 0, VK_IMAGE_TYPE_2D, VK_FORMAT_R8G8B8A8_UNORM, {1, 1, 1}, 1, 1, VK_SAMPLE_COUNT_1_BIT,
                            VK_IMAGE_TILING_OPTIMAL, VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, VK_SHARING_MODE_EXCLUSIVE, 0, NULL, VK_IMAGE_LAYOUT_UNDEFINED};
    vkCreateImage(g_vk.dev, &ic, NULL, &g_p.dummy);
    VkMemoryRequirements mr; vkGetImageMemoryRequirements(g_vk.dev, g_p.dummy, &mr);
    if (vk_alloc_mem(&mr, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, 0, &g_p.dummy_mem)) return -1;
    vkBindImageMemory(g_vk.dev, g_p.dummy, g_p.dummy_mem.mem, g_p.dummy_mem.off);
    VkImageViewCreateInfo vci = {VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, NULL, 0, g_p.dummy, VK_IMAGE_VIEW_TYPE_2D, VK_FORMAT_R8G8B8A8_UNORM, {0}, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    vkCreateImageView(g_vk.dev, &vci, NULL, &g_p.dummy_view);
    VkCommandBuffer cb = vk_once_begin();
    vk_image_barrier(cb, g_p.dummy, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_PIPELINE_STAGE_2_NONE, 0,
                     VK_PIPELINE_STAGE_2_CLEAR_BIT, VK_ACCESS_2_TRANSFER_WRITE_BIT);
    VkClearColorValue black = {{0, 0, 0, 1}}; VkImageSubresourceRange rr = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    vkCmdClearColorImage(cb, g_p.dummy, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &black, 1, &rr);
    vk_image_barrier(cb, g_p.dummy, VK_IMAGE_ASPECT_COLOR_BIT, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
                     VK_PIPELINE_STAGE_2_CLEAR_BIT, VK_ACCESS_2_TRANSFER_WRITE_BIT, VK_PIPELINE_STAGE_2_FRAGMENT_SHADER_BIT, VK_ACCESS_2_SHADER_SAMPLED_READ_BIT);
    if (vk_once_end(cb)) return -1;
    for (int i = 0; i < NFR; i++) {
        frame_t *f = &g_p.fr[i];
        VkCommandPoolCreateInfo pci = {VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, NULL, VK_COMMAND_POOL_CREATE_TRANSIENT_BIT, g_vk.qfam};
        vkCreateCommandPool(g_vk.dev, &pci, NULL, &f->pool);
        VkCommandBufferAllocateInfo ai = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, NULL, f->pool, VK_COMMAND_BUFFER_LEVEL_PRIMARY, 1};
        vkAllocateCommandBuffers(g_vk.dev, &ai, &f->cb);
        VkSemaphoreCreateInfo sc = {VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO}; vkCreateSemaphore(g_vk.dev, &sc, NULL, &f->acq);
        VkFenceCreateInfo fc = {VK_STRUCTURE_TYPE_FENCE_CREATE_INFO}; vkCreateFence(g_vk.dev, &fc, NULL, &f->fence);
        VkDescriptorSetAllocateInfo da = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, NULL, g_p.dp, 1, &g_p.dsl};
        vkAllocateDescriptorSets(g_vk.dev, &da, &f->ds);
    }
    g_p.resize_seen = vkw_resize_serial();
    if (make_swapchain() < 0) return -1;
    g_p.cap_ev = CreateEventW(NULL, FALSE, FALSE, NULL);
    atomic_store(&g_p.stop, 0);
    g_p.thread = (HANDLE)_beginthreadex(NULL, 0, present_main, NULL, 0, NULL);
    atomic_store(&g_vk.presenting, g_p.thread != NULL);
    return g_p.thread ? 0 : -1;
}

void vkp_shutdown(void) {
    if (!g_p.thread) return;
    vkp_flush();
    atomic_store(&g_p.stop, 1);
    AcquireSRWLockExclusive(&g_p.lk); WakeAllConditionVariable(&g_p.cv); ReleaseSRWLockExclusive(&g_p.lk);
    WaitForSingleObject(g_p.thread, 5000); CloseHandle(g_p.thread); g_p.thread = NULL; atomic_store(&g_vk.presenting, 0);
    AcquireSRWLockExclusive(&g_vk.qlock); vkQueueWaitIdle(g_vk.q); ReleaseSRWLockExclusive(&g_vk.qlock);
    for (int i = 0; i < NFR; i++) { frame_t *f = &g_p.fr[i]; vkDestroyCommandPool(g_vk.dev, f->pool, NULL); vkDestroySemaphore(g_vk.dev, f->acq, NULL); vkDestroyFence(g_vk.dev, f->fence, NULL); }
    destroy_swapchain_views();
    if (g_p.sc) vkDestroySwapchainKHR(g_vk.dev, g_p.sc, NULL);
    if (g_p.pipe) vkDestroyPipeline(g_vk.dev, g_p.pipe, NULL);
    vkDestroyPipelineLayout(g_vk.dev, g_p.pl, NULL); vkDestroyDescriptorPool(g_vk.dev, g_p.dp, NULL); vkDestroyDescriptorSetLayout(g_vk.dev, g_p.dsl, NULL);
    vkDestroySampler(g_vk.dev, g_p.samp, NULL); vkDestroyImageView(g_vk.dev, g_p.dummy_view, NULL); vkDestroyImage(g_vk.dev, g_p.dummy, NULL); vk_free_mem(&g_p.dummy_mem);
    if (g_p.cap_buf) { vkDestroyBuffer(g_vk.dev, g_p.cap_buf, NULL); vk_free_mem(&g_p.cap_mem); }
    if (g_p.surf) vkDestroySurfaceKHR(g_vk.inst, g_p.surf, NULL);
    CloseHandle(g_p.cap_ev);
    memset(&g_p, 0, sizeof g_p);
}

void vkp_set_resolver(vkp_resolve_fn fn) { g_p.resolve = fn; }

uint64_t vkp_enqueue(uint64_t serial, double period, uint64_t wait_value, const int crop[4], int flip,
                     const void *native, uint64_t frame_number, uint64_t submitted_tick, char *capture_path) {
    if (!g_p.thread) { free(capture_path); return 0; }
    AcquireSRWLockExclusive(&g_p.lk);
    while (g_p.in - g_p.read >= PQ) SleepConditionVariableSRW(&g_p.cv, &g_p.lk, 100, 0);   // only when the present thread is a whole queue behind
    pq_item *it = &g_p.q[g_p.in % PQ];
    { extern uint64_t vk_game_frame(void); memset(it, 0, sizeof *it); it->frame = vk_game_frame(); } it->serial = serial; it->period = period; it->wait_value = wait_value; it->flip = flip; it->t_enq = now_ns();
    it->native = native; it->frame_number = frame_number; it->submitted_tick = submitted_tick;
    it->capture_path = capture_path;
    if (crop) { memcpy(it->crop, crop, sizeof it->crop); it->has_crop = 1; }
    uint64_t tk = ++g_p.in;
    WakeAllConditionVariable(&g_p.cv);
    ReleaseSRWLockExclusive(&g_p.lk);
    return tk;
}
void vkp_wait(uint64_t tk) {
    if (!g_p.thread || !tk) return;
    AcquireSRWLockExclusive(&g_p.lk);
    while (g_p.done < tk && g_p.thread) SleepConditionVariableSRW(&g_p.cv, &g_p.lk, 100, 0);
    ReleaseSRWLockExclusive(&g_p.lk);
}
void vkp_flush(void) { AcquireSRWLockShared(&g_p.lk); uint64_t h = g_p.in; ReleaseSRWLockShared(&g_p.lk); vkp_wait(h); }
uint64_t vkp_count(void) { return atomic_load(&g_p.count); }
uint64_t vkp_dropped(void) { return atomic_load(&g_p.dropped); }
double vkp_presented_time(uint64_t n) {
    AcquireSRWLockShared(&g_p.lk);
    double t = g_p.tring[n % TRING].n == n ? g_p.tring[n % TRING].t : 0;
    ReleaseSRWLockShared(&g_p.lk);
    return t;
}
void vkp_set_stall(uint64_t ns) { atomic_store(&g_p.stall_ns, ns); }
void vkp_info(int *w, int *h, int *mode, VkFormat *fmt) {
    if (w) *w = (int)g_p.ext.width; if (h) *h = (int)g_p.ext.height;
    if (mode) *mode = g_p.mode == VK_PRESENT_MODE_MAILBOX_KHR ? VKP_MAILBOX : g_p.mode == VK_PRESENT_MODE_IMMEDIATE_KHR ? VKP_IMMEDIATE : VKP_FIFO;
    if (fmt) *fmt = g_p.fmt;
}
void vkp_stats_line(char *out, size_t n) {
    snprintf(out, n, "%llu presents shown, %llu dropped, window %ux%u", (unsigned long long)atomic_load(&g_p.count), (unsigned long long)atomic_load(&g_p.dropped),
             g_p.ext.width, g_p.ext.height);
}

int vkp_capture_next(uint32_t **pixels, int *w, int *h, int *bgr, uint32_t timeout_ms) {
    *pixels = NULL;
    if (!g_p.cap_ok) return -1;
    free(g_p.cap_px); g_p.cap_px = NULL;
    ResetEvent(g_p.cap_ev); atomic_store(&g_p.cap_want, 1);
    if (WaitForSingleObject(g_p.cap_ev, timeout_ms) != WAIT_OBJECT_0 || !g_p.cap_px) { atomic_store(&g_p.cap_want, 0); return -1; }
    *pixels = g_p.cap_px; g_p.cap_px = NULL; *w = g_p.cap_w; *h = g_p.cap_h; *bgr = g_p.fmt == VK_FORMAT_B8G8R8A8_UNORM;
    return 0;
}
