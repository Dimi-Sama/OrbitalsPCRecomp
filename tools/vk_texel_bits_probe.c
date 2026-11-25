// Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
// vk_texel_bits_probe: does a texel fetch through a uniform texel buffer view of a float format return the buffer's bits unchanged?
// The translated NVN2 shaders read buffer textures as float (Maxwell's TLD returns the raw 32-bit words) and the runtime views a buffer
// written as R32_UINT through R32_SFLOAT (tbuf_fi): integers below 2^23 are float denormals there, and a NaN keeps its payload only if the
// fetch passes it through. Each word is fetched by a compute shader and written back with floatBitsToUint; the words that changed are listed.
//
//   tools\vk_texel_bits_probe.comp -> spv:  glslangValidator -V --target-env vulkan1.3 tools/vk_texel_bits_probe.comp -o probe.spv
//   Windows: x86_64-w64-mingw32-gcc -O1 -I runtime/edenvk/deps/vulkan-headers/include tools/vk_texel_bits_probe.c -o vk_texel_bits_probe.exe
//   vk_texel_bits_probe.exe probe.spv [R32_SFLOAT|R32_UINT|R16G16_SFLOAT ...]
//   vk_texel_bits_probe.exe probe_oob.spv oob   (tools/vk_texel_bits_probe_oob.comp) a 4-texel view inside a larger buffer, read at 0..14 and -1:
//                                               what an out-of-range fetch returns with robustBufferAccess, as the runtime runs on NVIDIA
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <windows.h>

#define F(name) static PFN_##name name;
#define DEVICE_FNS(X) X(vkGetDeviceQueue) X(vkCreateBuffer) X(vkGetBufferMemoryRequirements) X(vkAllocateMemory) X(vkBindBufferMemory) X(vkMapMemory) \
    X(vkCreateBufferView) X(vkCreateShaderModule) X(vkCreateDescriptorSetLayout) X(vkCreatePipelineLayout) X(vkCreateComputePipelines) \
    X(vkCreateDescriptorPool) X(vkAllocateDescriptorSets) X(vkUpdateDescriptorSets) X(vkCreateCommandPool) X(vkAllocateCommandBuffers) \
    X(vkBeginCommandBuffer) X(vkCmdBindPipeline) X(vkCmdBindDescriptorSets) X(vkCmdDispatch) X(vkEndCommandBuffer) X(vkQueueSubmit) X(vkQueueWaitIdle) \
    X(vkCmdPipelineBarrier)
DEVICE_FNS(F)
static PFN_vkGetPhysicalDeviceMemoryProperties vkGetPhysicalDeviceMemoryProperties;
static VkPhysicalDeviceMemoryProperties mp;
static VkDevice dev;

static uint32_t memtype(uint32_t bits, VkMemoryPropertyFlags want) {
    for (uint32_t i = 0; i < mp.memoryTypeCount; i++) if ((bits >> i & 1) && (mp.memoryTypes[i].propertyFlags & want) == want) return i;
    return UINT32_MAX;
}
static void *host_buffer(VkDeviceSize n, VkBufferUsageFlags use, VkBuffer *b) {
    VkBufferCreateInfo bi = {VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, NULL, 0, n, use, VK_SHARING_MODE_EXCLUSIVE, 0, NULL};
    vkCreateBuffer(dev, &bi, NULL, b); VkMemoryRequirements mr; vkGetBufferMemoryRequirements(dev, *b, &mr);
    VkMemoryAllocateInfo ai = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, NULL, mr.size, memtype(mr.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)};
    VkDeviceMemory m; vkAllocateMemory(dev, &ai, NULL, &m); vkBindBufferMemory(dev, *b, m, 0);
    void *p; vkMapMemory(dev, m, 0, n, 0, &p); return p;
}

static const struct { const char *n; VkFormat f; } FMT[] = {{"R32_SFLOAT", VK_FORMAT_R32_SFLOAT}, {"R32_UINT", VK_FORMAT_R32_UINT}, {"R32G32B32A32_SFLOAT", VK_FORMAT_R32G32B32A32_SFLOAT}};

int main(int argc, char **argv) {
    if (argc < 2) { puts("usage: vk_texel_bits_probe probe.spv [format...]"); return 2; }
    FILE *f = fopen(argv[1], "rb"); if (!f) { puts("no shader"); return 2; }
    static uint32_t code[65536]; size_t ncode = fread(code, 1, sizeof code, f); fclose(f);
    HMODULE l = LoadLibraryA("vulkan-1.dll"); if (!l) { puts("no Vulkan loader"); return 1; }
    PFN_vkGetInstanceProcAddr gipa = (PFN_vkGetInstanceProcAddr)GetProcAddress(l, "vkGetInstanceProcAddr");
    VkApplicationInfo app = {VK_STRUCTURE_TYPE_APPLICATION_INFO, NULL, "vk_texel_bits_probe", 1, NULL, 0, VK_API_VERSION_1_3};
    VkInstanceCreateInfo ici = {VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, NULL, 0, &app};
    VkInstance inst; if (((PFN_vkCreateInstance)gipa(NULL, "vkCreateInstance"))(&ici, NULL, &inst)) { puts("vkCreateInstance failed"); return 1; }
    PFN_vkEnumeratePhysicalDevices epd = (PFN_vkEnumeratePhysicalDevices)gipa(inst, "vkEnumeratePhysicalDevices");
    PFN_vkGetPhysicalDeviceProperties gpp = (PFN_vkGetPhysicalDeviceProperties)gipa(inst, "vkGetPhysicalDeviceProperties");
    vkGetPhysicalDeviceMemoryProperties = (PFN_vkGetPhysicalDeviceMemoryProperties)gipa(inst, "vkGetPhysicalDeviceMemoryProperties");
    PFN_vkCreateDevice cd = (PFN_vkCreateDevice)gipa(inst, "vkCreateDevice");
    PFN_vkGetDeviceProcAddr gdpa = (PFN_vkGetDeviceProcAddr)gipa(inst, "vkGetDeviceProcAddr");
    uint32_t npd = 8; VkPhysicalDevice pds[8]; epd(inst, &npd, pds);
    for (uint32_t d = 0; d < npd; d++) {
        VkPhysicalDeviceProperties pp; gpp(pds[d], &pp); vkGetPhysicalDeviceMemoryProperties(pds[d], &mp);
        int oob = argc > 2 && !strcmp(argv[2], "oob");
        VkPhysicalDeviceFeatures feats = {0}; feats.robustBufferAccess = VK_TRUE;   // as the runtime sets it on NVIDIA (vk_dev.c)
        float prio = 1; VkDeviceQueueCreateInfo qi = {VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, NULL, 0, 0, 1, &prio};   // family 0: graphics and compute on the GPUs tested
        VkDeviceCreateInfo di = {VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, NULL, 0, 1, &qi, 0, NULL, 0, NULL, &feats};
        if (cd(pds[d], &di, NULL, &dev)) { printf("%s: no device\n", pp.deviceName); continue; }
#define L(name) name = (PFN_##name)gdpa(dev, #name);
        DEVICE_FNS(L)
        VkQueue q; vkGetDeviceQueue(dev, 0, 0, &q);
        enum { N = 16 };
        const uint32_t words[N] = {0, 1, 2, 3, 500, 4653, 16383, 0x007fffff, 0x00800000, 0x3f800000, 0x7f800000, 0x7f800001, 0x7fc00000, 0xffc00001, 0x80000001, 0x80000000};
        VkBuffer src, dst; uint32_t *s = host_buffer(4 * N * 4, VK_BUFFER_USAGE_UNIFORM_TEXEL_BUFFER_BIT, &src), *o = host_buffer(4 * N, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, &dst);
        for (int i = 0; i < 4 * N; i++) s[i] = oob ? 0x40000000u + (uint32_t)i : words[i % N];   // oob: word i holds 2.0f's bits + i
        VkShaderModuleCreateInfo si = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, NULL, 0, ncode, code}; VkShaderModule sm; vkCreateShaderModule(dev, &si, NULL, &sm);
        VkDescriptorSetLayoutBinding lb[2] = {{0, VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}, {1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}};
        VkDescriptorSetLayoutCreateInfo dli = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, NULL, 0, 2, lb}; VkDescriptorSetLayout dsl; vkCreateDescriptorSetLayout(dev, &dli, NULL, &dsl);
        VkPipelineLayoutCreateInfo pli = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, NULL, 0, 1, &dsl}; VkPipelineLayout pl; vkCreatePipelineLayout(dev, &pli, NULL, &pl);
        VkComputePipelineCreateInfo cpi = {VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, NULL, 0, {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, NULL, 0, VK_SHADER_STAGE_COMPUTE_BIT, sm, "main"}, pl};
        VkPipeline pipe; if (vkCreateComputePipelines(dev, VK_NULL_HANDLE, 1, &cpi, NULL, &pipe)) { printf("%s: no pipeline\n", pp.deviceName); continue; }
        VkDescriptorPoolSize ps[2] = {{VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER, 8}, {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 8}};
        VkDescriptorPoolCreateInfo dpi = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, NULL, 0, 8, 2, ps}; VkDescriptorPool dp; vkCreateDescriptorPool(dev, &dpi, NULL, &dp);
        VkCommandPoolCreateInfo cpci = {VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, NULL, 0, 0}; VkCommandPool cp; vkCreateCommandPool(dev, &cpci, NULL, &cp);
        for (int a = argc > 2 ? 2 : 1; a < (argc > 2 ? argc : 2); a++) {
            const char *want = argc > 2 && !oob ? argv[a] : "R32_SFLOAT"; VkFormat fmt = VK_FORMAT_UNDEFINED;
            for (size_t k = 0; k < sizeof FMT / sizeof *FMT; k++) if (!strcmp(FMT[k].n, want)) fmt = FMT[k].f;
            if (!fmt) { printf("unknown format %s\n", want); continue; }
            VkBufferViewCreateInfo vi = {VK_STRUCTURE_TYPE_BUFFER_VIEW_CREATE_INFO, NULL, 0, src, fmt, oob ? 64 : 0, oob ? 16 : VK_WHOLE_SIZE}; VkBufferView v;
            if (vkCreateBufferView(dev, &vi, NULL, &v)) { printf("%s %s: no view\n", pp.deviceName, want); continue; }
            VkDescriptorSetAllocateInfo dai = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, NULL, dp, 1, &dsl}; VkDescriptorSet ds; vkAllocateDescriptorSets(dev, &dai, &ds);
            VkDescriptorBufferInfo bi = {dst, 0, VK_WHOLE_SIZE};
            VkWriteDescriptorSet w[2] = {{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, ds, 0, 0, 1, VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER, NULL, NULL, &v},
                                         {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, ds, 1, 0, 1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, NULL, &bi, NULL}};
            vkUpdateDescriptorSets(dev, 2, w, 0, NULL);
            VkCommandBufferAllocateInfo cai = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, NULL, cp, VK_COMMAND_BUFFER_LEVEL_PRIMARY, 1}; VkCommandBuffer cb; vkAllocateCommandBuffers(dev, &cai, &cb);
            VkCommandBufferBeginInfo cbi = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, NULL, VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT, NULL}; vkBeginCommandBuffer(cb, &cbi);
            vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, pipe); vkCmdBindDescriptorSets(cb, VK_PIPELINE_BIND_POINT_COMPUTE, pl, 0, 1, &ds, 0, NULL);
            vkCmdDispatch(cb, 1, 1, 1);
            VkMemoryBarrier mb = {VK_STRUCTURE_TYPE_MEMORY_BARRIER, NULL, VK_ACCESS_SHADER_WRITE_BIT, VK_ACCESS_HOST_READ_BIT};
            vkCmdPipelineBarrier(cb, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &mb, 0, NULL, 0, NULL);
            vkEndCommandBuffer(cb);
            VkSubmitInfo sub = {VK_STRUCTURE_TYPE_SUBMIT_INFO, NULL, 0, NULL, NULL, 1, &cb}; vkQueueSubmit(q, 1, &sub, VK_NULL_HANDLE); vkQueueWaitIdle(q);
            if (oob) { printf("%s, 4-texel view at word 16 (words hold 0x40000000 + index):\n", pp.deviceName);
                for (int i = 0; i < N; i++) printf("  texel %2d -> %08x%s\n", i == N - 1 ? -1 : i, o[i], i >= 4 && o[i] ? "  NOT ZERO" : ""); continue; }
            int bad = 0; int texel = fmt == VK_FORMAT_R32G32B32A32_SFLOAT ? 4 : 1;   // the shader reads component x of texel i: word i * texel
            printf("%s, view %s:\n", pp.deviceName, want);
            for (int i = 0; i < N; i++) { uint32_t in = s[i * texel], out = o[i]; if (in != out) bad++; printf("  %08x -> %08x%s\n", in, out, in != out ? "  CHANGED" : ""); }
            printf("  %d of %d words changed\n", bad, N);
        }
    }
    return 0;
}
