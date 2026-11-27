#include "vk_spv_issue2.h"
#include <stdio.h>
#include <stdlib.h>

#define WORDS(a) (sizeof(a) / sizeof((a)[0]))
#define INST(n, op) (((n) << 16) | (op))
#define CHECK(test) do { if (!(test)) { fprintf(stderr, "line %d: %s\n", __LINE__, #test); return 1; } } while (0)

enum {
    TYPE_VOID = 19, TYPE_INT = 21, TYPE_FLOAT = 22, TYPE_POINTER = 32, TYPE_FUNCTION = 33,
    CONSTANT = 43, FUNCTION = 54, FUNCTION_END = 56, VARIABLE = 59, LOAD = 61, STORE = 62,
    DECORATE = 71, DECORATION_GROUP = 73, GROUP_DECORATE = 74, FNEGATE = 127, FADD = 129, FMUL = 133,
    CONTROL_BARRIER = 224, MEMORY_BARRIER = 225, LABEL = 248, BRANCH = 249, RETURN = 253
};

static int count_op(const uint32_t *module, size_t n, unsigned op) {
    int count = 0;
    for (size_t i = 5; i < n; i += module[i] >> 16)
        if ((module[i] & 0xffff) == op) ++count;
    return count;
}

static int test_no_contraction(void) {
    // The FAdd is already decorated directly, the FMul through a group.
    const uint32_t fragment[] = {
        0x07230203, 0x00010300, 0, 14, 0,
        INST(3, DECORATE), 7, 42,
        INST(2, DECORATION_GROUP), 11,
        INST(3, DECORATE), 11, 42,
        INST(3, GROUP_DECORATE), 11, 8,
        INST(3, TYPE_FLOAT), 1, 32,
        INST(5, FADD), 1, 7, 5, 6,
        INST(5, FMUL), 1, 8, 5, 6,
        INST(4, FNEGATE), 1, 9, 8
    };
    size_t n;
    unsigned added;
    uint32_t *out = vkspv_no_contraction(fragment, WORDS(fragment), &n, &added);
    CHECK(out && added == 1 && n == WORDS(fragment) + 3);
    CHECK(out[16] == INST(3, DECORATE) && out[17] == 9 && out[18] == 42 && out[19] == INST(3, TYPE_FLOAT));
    CHECK(!vkspv_no_contraction(out, n, &n, &added) && !added);
    free(out);
    CHECK(!vkspv_no_contraction(fragment, WORDS(fragment) - 1, &n, &added) && !added);
    return 0;
}

static int test_warp_sync(void) {
    // One cross-block write, two local read/write transitions and an existing
    // workgroup barrier. The last read needs no extra barrier.
    static const uint32_t compute[] = {
        0x07230203, 0x00010300, 0, 18, 0,
        INST(2, 17), 1,                        // Shader capability
        INST(3, 14), 0, 1,                     // Logical GLSL450
        INST(5, 15), 5, 9, 0x6e69616d, 0,      // GLCompute main
        INST(6, 16), 9, 17, 32, 1, 1,          // LocalSize
        INST(2, TYPE_VOID), 1,
        INST(4, TYPE_INT), 2, 32, 0,
        INST(4, TYPE_POINTER), 3, 4, 2,
        INST(3, TYPE_FUNCTION), 4, 1,
        INST(4, CONSTANT), 2, 5, 2,
        INST(4, CONSTANT), 2, 6, 0x108,
        INST(4, CONSTANT), 2, 7, 0,
        INST(4, VARIABLE), 3, 8, 4,
        INST(5, FUNCTION), 1, 9, 0, 4,
        INST(2, LABEL), 10,
        INST(3, STORE), 8, 7,
        INST(2, BRANCH), 11,
        INST(2, LABEL), 11,
        INST(4, LOAD), 2, 12, 8,
        INST(3, STORE), 8, 12,
        INST(4, LOAD), 2, 13, 8,
        INST(4, CONTROL_BARRIER), 5, 5, 6,
        INST(3, STORE), 8, 13,
        INST(4, CONTROL_BARRIER), 5, 5, 6,
        INST(4, LOAD), 2, 14, 8,
        INST(1, RETURN),
        INST(1, FUNCTION_END)
    };
    size_t n;
    unsigned added_control, added_memory;
    uint32_t *out = vkspv_warp_sync(compute, WORDS(compute), &n, &added_control, &added_memory);
    CHECK(out && added_control == 2 && added_memory == 1);
    CHECK(out[3] == 19 && n == WORDS(compute) + 4 + 8 + 3);
    CHECK(count_op(out, n, CONTROL_BARRIER) == 4 && count_op(out, n, MEMORY_BARRIER) == 1);
    for (size_t i = 5; i < n; i += out[i] >> 16) {
        unsigned op = out[i] & 0xffff;
        if (op == MEMORY_BARRIER)
            CHECK(out[i + 1] == 18 && out[i + 2] == 6 && out[i + 3] == INST(4, LOAD));
        if (op == CONTROL_BARRIER && out[i + 1] != 5)
            CHECK(out[i + 1] == 18 && out[i + 2] == 18 && out[i + 3] == 6);
    }
    CHECK(!vkspv_warp_sync(out, n, &n, &added_control, &added_memory) && !added_control && !added_memory);
    free(out);
    return 0;
}

int main(void) {
    return test_no_contraction() || test_warp_sync();
}
