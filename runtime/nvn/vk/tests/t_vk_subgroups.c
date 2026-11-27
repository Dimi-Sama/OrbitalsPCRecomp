#include "vk_subgroups.h"
#include <stdio.h>

static int check_mask(const char *name, uint32_t vendor, VkDriverId driver, const char *override, VkShaderStageFlags expected) {
    VkPhysicalDeviceProperties props = {.vendorID = vendor};
    snprintf(props.deviceName, sizeof props.deviceName, "%s", name);
    int particle_sort_only = !override && vk_radv_navi10_or_navi14(&props, driver);
    VkShaderStageFlags actual = vk_subgroup32_stages(0xf0, override, particle_sort_only);
    if (actual == expected) return 0;
    fprintf(stderr, "%s: expected mask %#x, got %#x\n", name, expected, actual);
    return 1;
}

int main(void) {
    const VkShaderStageFlags rdna1 = VK_SHADER_STAGE_FRAGMENT_BIT | VK_SHADER_STAGE_COMPUTE_BIT;
    const VkDriverId radv = VK_DRIVER_ID_MESA_RADV;
    const char *other = "12b55e2d0b73497e";
    int errors = 0;
    errors += check_mask("AMD Radeon RX 5700 XT (RADV NAVI10)", 0x1002, radv, NULL, 0x30);
    errors += check_mask("AMD Radeon RX 5500 XT (RADV NAVI14)", 0x1002, radv, NULL, 0x30);
    errors += check_mask("AMD Radeon (gfx1010)", 0x1002, radv, NULL, 0x30);
    errors += check_mask("AMD Radeon (GFX1012)", 0x1002, radv, NULL, 0x30);
    errors += check_mask("AMD Custom GPU 0405 (RADV VANGOGH)", 0x1002, radv, NULL, 0xf0);
    errors += check_mask("AMD Custom GPU (gfx1033)", 0x1002, radv, NULL, 0xf0);
    errors += check_mask("AMD Radeon (RADV NAVI12)", 0x1002, radv, NULL, 0xf0);
    errors += check_mask("AMD Radeon (RADV NAVI100)", 0x1002, radv, NULL, 0xf0);
    errors += check_mask("AMD Radeon (RADV NAVI10)", 0x1002, VK_DRIVER_ID_AMD_PROPRIETARY, NULL, 0xf0);
    errors += check_mask("Other device (RADV NAVI10)", 0x10de, radv, NULL, 0xf0);
    errors += check_mask("AMD Radeon (RADV NAVI10)", 0x1002, radv, "1", 0xf0);
    errors += check_mask("AMD Radeon (RADV NAVI10)", 0x1002, radv, "0", 0);
    errors += vk_subgroup32_stages(0, NULL, 1) != 0;
    errors += !vk_compute_has_32_lanes(rdna1, 1, "5c7fb5af900ce0bc");
    errors += !vk_compute_has_32_lanes(rdna1, 1, "f27f74bb26d86ae9");
    errors += !vk_compute_has_32_lanes(rdna1, 1, "d032ce5090303e01");
    errors += vk_compute_has_32_lanes(rdna1, 1, other);
    errors += vk_compute_has_32_lanes(VK_SHADER_STAGE_FRAGMENT_BIT, 1, "d032ce5090303e01");
    errors += !vk_compute_has_32_lanes(0xf0, 0, other);
    if (errors) fprintf(stderr, "%d subgroup policy checks failed\n", errors);
    else puts("Vulkan subgroup policy: PASS");
    return errors != 0;
}
