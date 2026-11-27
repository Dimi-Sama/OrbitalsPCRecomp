#ifndef NXRT_VK_SUBGROUPS_H
#define NXRT_VK_SUBGROUPS_H

#include <string.h>
#include <vulkan/vulkan_core.h>

// Match the RADV chip name or graphics target. GFX10.3 devices keep their existing subgroup policy.
static inline int vk_radv_navi10_or_navi14(const VkPhysicalDeviceProperties *props, VkDriverId driver) {
    if (props->vendorID != 0x1002 || driver != VK_DRIVER_ID_MESA_RADV) return 0;
    const char *separators = " \t()[],/:";
    for (const char *name = props->deviceName; *name;) {
        name += strspn(name, separators);
        size_t length = strcspn(name, separators);
        if ((length == 6 && (!strncmp(name, "NAVI10", length) || !strncmp(name, "NAVI14", length))) ||
            (length == 7 && (!strncmp(name, "gfx1010", length) || !strncmp(name, "gfx1012", length) ||
                             !strncmp(name, "GFX1010", length) || !strncmp(name, "GFX1012", length))))
            return 1;
        name += length;
    }
    return 0;
}

static inline VkShaderStageFlags vk_subgroup32_stages(VkShaderStageFlags supported, const char *override, int particle_sort_only) {
    if (override && *override == '0') return 0;
    return particle_sort_only ? supported & (VK_SHADER_STAGE_FRAGMENT_BIT | VK_SHADER_STAGE_COMPUTE_BIT) : supported;
}

static inline int vk_is_particle_sort_shader(const char *key) {
    // Unreal's GPU radix sort: upsweep, spine and downsweep.
    return !strcmp(key, "5c7fb5af900ce0bc") || !strcmp(key, "f27f74bb26d86ae9") || !strcmp(key, "d032ce5090303e01");
}

static inline int vk_compute_has_32_lanes(VkShaderStageFlags stages32, int particle_sort_only, const char *key) {
    return (stages32 & VK_SHADER_STAGE_COMPUTE_BIT) && (!particle_sort_only || vk_is_particle_sort_shader(key));
}

#endif
