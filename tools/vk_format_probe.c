// Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
// vk_format_probe: which formats each Vulkan GPU can read from a storage image or a storage texel buffer declared without a format
// (VK_FORMAT_FEATURE_2_STORAGE_READ_WITHOUT_FORMAT_BIT, Vulkan 1.3 / VK_KHR_format_feature_flags2), next to the device-wide
// shaderStorageImageReadWithoutFormat feature. A device without the feature can still read such an image when the view's format has the bit;
// for the other formats the shader has to declare the format (KNOWN_ISSUES.md, Intel white triangle edges).
//
//   Windows: x86_64-w64-mingw32-gcc -O1 -I runtime/edenvk/deps/vulkan-headers/include tools/vk_format_probe.c -o vk_format_probe.exe
//   Linux:   gcc -O1 -I runtime/edenvk/deps/vulkan-headers/include tools/vk_format_probe.c -o vk_format_probe -ldl
#include <stdio.h>
#include <string.h>
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#ifdef _WIN32
#include <windows.h>
static void *open_loader(void) { return (void *)LoadLibraryA("vulkan-1.dll"); }
static void *sym(void *l, const char *n) { return (void *)GetProcAddress((HMODULE)l, n); }
#else
#include <dlfcn.h>
static void *open_loader(void) { void *l = dlopen("libvulkan.so.1", RTLD_NOW); return l ? l : dlopen("libvulkan.so", RTLD_NOW); }
static void *sym(void *l, const char *n) { return dlsym(l, n); }
#endif

static const struct { VkFormat f; const char *n; } FMT[] = {
    {VK_FORMAT_R8_UNORM, "R8_UNORM"}, {VK_FORMAT_R8_UINT, "R8_UINT"}, {VK_FORMAT_R8G8_UNORM, "R8G8_UNORM"}, {VK_FORMAT_R8G8B8A8_UNORM, "R8G8B8A8_UNORM"},
    {VK_FORMAT_R8G8B8A8_SNORM, "R8G8B8A8_SNORM"}, {VK_FORMAT_R8G8B8A8_UINT, "R8G8B8A8_UINT"}, {VK_FORMAT_B8G8R8A8_UNORM, "B8G8R8A8_UNORM"},
    {VK_FORMAT_A2B10G10R10_UNORM_PACK32, "A2B10G10R10_UNORM"}, {VK_FORMAT_B10G11R11_UFLOAT_PACK32, "B10G11R11_UFLOAT"},
    {VK_FORMAT_R16_SFLOAT, "R16_SFLOAT"}, {VK_FORMAT_R16_UINT, "R16_UINT"}, {VK_FORMAT_R16_UNORM, "R16_UNORM"}, {VK_FORMAT_R16G16_SFLOAT, "R16G16_SFLOAT"},
    {VK_FORMAT_R16G16_UINT, "R16G16_UINT"}, {VK_FORMAT_R16G16B16A16_SFLOAT, "R16G16B16A16_SFLOAT"}, {VK_FORMAT_R16G16B16A16_UNORM, "R16G16B16A16_UNORM"},
    {VK_FORMAT_R16G16B16A16_UINT, "R16G16B16A16_UINT"}, {VK_FORMAT_R32_SFLOAT, "R32_SFLOAT"}, {VK_FORMAT_R32_UINT, "R32_UINT"}, {VK_FORMAT_R32_SINT, "R32_SINT"},
    {VK_FORMAT_R32G32_SFLOAT, "R32G32_SFLOAT"}, {VK_FORMAT_R32G32_UINT, "R32G32_UINT"}, {VK_FORMAT_R32G32B32A32_SFLOAT, "R32G32B32A32_SFLOAT"},
    {VK_FORMAT_R32G32B32A32_UINT, "R32G32B32A32_UINT"},
};

int main(void) {
    void *l = open_loader(); if (!l) { puts("no Vulkan loader"); return 1; }
    PFN_vkGetInstanceProcAddr gipa = (PFN_vkGetInstanceProcAddr)sym(l, "vkGetInstanceProcAddr");
    PFN_vkCreateInstance ci = (PFN_vkCreateInstance)gipa(NULL, "vkCreateInstance");
    VkApplicationInfo app = {VK_STRUCTURE_TYPE_APPLICATION_INFO, NULL, "vk_format_probe", 1, NULL, 0, VK_API_VERSION_1_3};
    VkInstanceCreateInfo ici = {VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, NULL, 0, &app};
    VkInstance inst; if (ci(&ici, NULL, &inst) != VK_SUCCESS) { puts("vkCreateInstance failed"); return 1; }
    PFN_vkEnumeratePhysicalDevices epd = (PFN_vkEnumeratePhysicalDevices)gipa(inst, "vkEnumeratePhysicalDevices");
    PFN_vkGetPhysicalDeviceProperties gp = (PFN_vkGetPhysicalDeviceProperties)gipa(inst, "vkGetPhysicalDeviceProperties");
    PFN_vkGetPhysicalDeviceFeatures gf = (PFN_vkGetPhysicalDeviceFeatures)gipa(inst, "vkGetPhysicalDeviceFeatures");
    PFN_vkGetPhysicalDeviceFormatProperties2 gfp = (PFN_vkGetPhysicalDeviceFormatProperties2)gipa(inst, "vkGetPhysicalDeviceFormatProperties2");
    uint32_t n = 0; epd(inst, &n, NULL); VkPhysicalDevice pd[16]; if (n > 16) n = 16; epd(inst, &n, pd);
    for (uint32_t i = 0; i < n; i++) {
        VkPhysicalDeviceProperties p; gp(pd[i], &p); VkPhysicalDeviceFeatures f; gf(pd[i], &f);
        printf("GPU %u: %s (vendor %#x, Vulkan %u.%u.%u)\n  shaderStorageImageReadWithoutFormat %u, WriteWithoutFormat %u\n", i, p.deviceName, p.vendorID,
               VK_API_VERSION_MAJOR(p.apiVersion), VK_API_VERSION_MINOR(p.apiVersion), VK_API_VERSION_PATCH(p.apiVersion),
               f.shaderStorageImageReadWithoutFormat, f.shaderStorageImageWriteWithoutFormat);
        if (p.apiVersion < VK_API_VERSION_1_3) { puts("  (no Vulkan 1.3: no per-format answer)"); continue; }
        printf("  %-22s %-14s %-14s\n", "format", "image: st/rd", "buffer: st/rd");
        for (unsigned k = 0; k < sizeof FMT / sizeof *FMT; k++) {
            VkFormatProperties3 p3 = {VK_STRUCTURE_TYPE_FORMAT_PROPERTIES_3};
            VkFormatProperties2 p2 = {VK_STRUCTURE_TYPE_FORMAT_PROPERTIES_2, &p3};
            gfp(pd[i], FMT[k].f, &p2);
            VkFormatFeatureFlags2 im = p3.optimalTilingFeatures, bu = p3.bufferFeatures;
            printf("  %-22s %s/%s          %s/%s\n", FMT[k].n,
                   im & VK_FORMAT_FEATURE_2_STORAGE_IMAGE_BIT ? "yes" : " - ", im & VK_FORMAT_FEATURE_2_STORAGE_READ_WITHOUT_FORMAT_BIT ? "yes" : " - ",
                   bu & VK_FORMAT_FEATURE_2_STORAGE_TEXEL_BUFFER_BIT ? "yes" : " - ", bu & VK_FORMAT_FEATURE_2_STORAGE_READ_WITHOUT_FORMAT_BIT ? "yes" : " - ");
        }
    }
    return 0;
}
