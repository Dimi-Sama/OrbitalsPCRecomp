#include "vk_spv_issue2.h"
#include <stdlib.h>
#include <string.h>

enum {
    OP_MEMORY_MODEL = 14, OP_ENTRY_POINT = 15, OP_CAPABILITY = 17,
    OP_TYPE_VOID = 19, OP_TYPE_INT = 21, OP_TYPE_POINTER = 32, OP_TYPE_FORWARD_POINTER = 39,
    OP_CONSTANT = 43, OP_FUNCTION = 54, OP_FUNCTION_PARAMETER = 55, OP_FUNCTION_END = 56, OP_FUNCTION_CALL = 57,
    OP_VARIABLE = 59, OP_LOAD = 61, OP_STORE = 62, OP_COPY_MEMORY = 63, OP_COPY_MEMORY_SIZED = 64,
    OP_ACCESS_CHAIN = 65, OP_IN_BOUNDS_ACCESS_CHAIN = 66,
    OP_DECORATE = 71, OP_GROUP_DECORATE = 74, OP_COPY_OBJECT = 83,
    OP_FNEGATE = 127, OP_FADD = 129, OP_FSUB = 131, OP_FMUL = 133, OP_FDIV = 136,
    OP_CONTROL_BARRIER = 224, OP_MEMORY_BARRIER = 225,
    OP_ATOMIC_LOAD = 227, OP_ATOMIC_STORE = 228, OP_ATOMIC_XOR = 242,
    OP_LABEL = 248, OP_BRANCH = 249, OP_BRANCH_CONDITIONAL = 250, OP_SWITCH = 251,
    OP_RETURN = 253, OP_UNREACHABLE = 255,
    DEC_NO_CONTRACTION = 42, MODEL_COMPUTE = 5, STORAGE_WORKGROUP = 4,
    SCOPE_WORKGROUP = 2, SCOPE_SUBGROUP = 3, ACQUIRE_RELEASE = 0x8,
    SEQUENTIALLY_CONSISTENT = 0x10, WORKGROUP_MEMORY = 0x100
};

static int module_ok(const uint32_t *w, size_t n) {
    if (n < 5 || w[0] != 0x07230203u || !w[3] || w[3] >= (1u << 22)) return 0;
    for (size_t i = 5; i < n;) {
        unsigned len = w[i] >> 16;
        if (!len || len > n - i) return 0;
        i += len;
    }
    return 1;
}

uint32_t *vkspv_no_contraction(const uint32_t *w, size_t n, size_t *out_n, unsigned *count) {
    *count = 0;
    if (!module_ok(w, n)) return NULL;
    uint32_t bound = w[3];
    unsigned char *decorated = calloc(bound, 1);
    if (!decorated) return NULL;
    size_t types = 0;
    for (size_t i = 5; i < n && !types; i += w[i] >> 16) {
        unsigned op = w[i] & 0xffff, len = w[i] >> 16;
        if (op == OP_DECORATE && len == 3 && w[i + 1] < bound && w[i + 2] == DEC_NO_CONTRACTION)
            decorated[w[i + 1]] = 1;
        if (op >= OP_TYPE_VOID && op <= OP_TYPE_FORWARD_POINTER) types = i;
    }
    if (!types) { free(decorated); return NULL; }
    for (size_t i = 5; i < types; i += w[i] >> 16) {
        unsigned len = w[i] >> 16;
        if ((w[i] & 0xffff) != OP_GROUP_DECORATE || len < 3 || w[i + 1] >= bound || !decorated[w[i + 1]]) continue;
        for (unsigned j = 2; j < len; ++j)
            if (w[i + j] < bound) decorated[w[i + j]] = 1;
    }
    unsigned added = 0;
    for (size_t i = types; i < n; i += w[i] >> 16) {
        switch (w[i] & 0xffff) {
        case OP_FNEGATE: case OP_FADD: case OP_FSUB: case OP_FMUL: case OP_FDIV:
            if ((w[i] >> 16) >= 4 && w[i + 2] < bound && !decorated[w[i + 2]]) {
                decorated[w[i + 2]] = 2;
                ++added;
            }
        }
    }
    uint32_t *result = added ? malloc((n + 3u * added) * sizeof(*result)) : NULL;
    if (result) {
        memcpy(result, w, types * sizeof(*w));
        size_t pos = types;
        for (uint32_t id = 1; id < bound; ++id) {
            if (decorated[id] != 2) continue;
            result[pos++] = (3u << 16) | OP_DECORATE;
            result[pos++] = id;
            result[pos++] = DEC_NO_CONTRACTION;
        }
        memcpy(result + pos, w + types, (n - types) * sizeof(*w));
        *out_n = pos + n - types;
        *count = added;
    }
    free(decorated);
    return result;
}

enum { READ = 1, WRITE = 2, CONTROL_ORDER = 3, MEMORY_ORDER = 4 };
enum { WORKGROUP_POINTER = 1, UINT32_TYPE = 2, INT32_TYPE = 3 };

typedef struct {
    size_t start, end;
    uint32_t next[2];
    unsigned char gen, kill, pending;
} shared_block;

static int shared_pointer(const unsigned char *ptr, uint32_t bound, uint32_t id) {
    return id < bound && ptr[id];
}

// A synchronization between blocks is memory-only. Within a block the execution
// barrier orders lanes in the same dynamic subgroup tangle. It does not reunite
// lanes that took other paths. See SPIR-V 3.3.20 and Issue #2 (KingsmanZer0).
uint32_t *vkspv_warp_sync(const uint32_t *w, size_t n, size_t *out_n, unsigned *control, unsigned *memory) {
    enum { SEMANTICS = ACQUIRE_RELEASE | WORKGROUP_MEMORY };
    *control = *memory = 0;
    if (!module_ok(w, n)) return NULL;
    uint32_t bound = w[3], entry = 0, uint_type = 0, scope_id = 0, semantics_id = 0;
    unsigned char *types = calloc(bound, 1), *pointers = calloc(bound, 1), *events = calloc(n, 1);
    unsigned char *ordered = calloc(bound, 1);
    uint32_t *block_index = calloc(bound, sizeof(*block_index));
    shared_block *blocks = calloc(n / 2 + 1, sizeof(*blocks)), *block = NULL;
    size_t first_function = 0, block_count = 0;
    int in_entry = 0, model_ok = 0;
    uint32_t *result = NULL;
    if (!types || !pointers || !events || !ordered || !block_index || !blocks) goto done;
    for (size_t i = 5; i < n; i += w[i] >> 16) {
        unsigned op = w[i] & 0xffff, len = w[i] >> 16;
        const uint32_t *a = w + i;
        if (op == OP_MEMORY_MODEL) model_ok = len == 3 && a[1] == 0 && a[2] == 1; // Logical GLSL450
        if (op == OP_ENTRY_POINT) {
            if (entry || len < 4 || a[1] != MODEL_COMPUTE || a[2] >= bound) goto done;
            entry = a[2];
        }
        if (op == OP_CAPABILITY && len == 2 && a[1] == 4442) goto done; // VariablePointers permits additional Workgroup pointer producers
        if (op == OP_TYPE_INT && len == 4 && a[1] < bound && a[2] == 32) {
            types[a[1]] = a[3] ? INT32_TYPE : UINT32_TYPE;
            if (!a[3]) uint_type = a[1];
        }
        if (op == OP_TYPE_POINTER && len == 4 && a[1] < bound && a[2] == STORAGE_WORKGROUP) types[a[1]] = WORKGROUP_POINTER;
        if (op == OP_CONSTANT && len == 4 && a[1] < bound && types[a[1]] >= UINT32_TYPE && a[2] < bound) {
            if (types[a[1]] == UINT32_TYPE) {
                if (a[3] == SCOPE_SUBGROUP) scope_id = a[2];
                if (a[3] == SEMANTICS) semantics_id = a[2];
            }
            ordered[a[2]] = (a[3] == SCOPE_SUBGROUP || a[3] == SCOPE_WORKGROUP ? 1 : 0)
                         | ((a[3] & WORKGROUP_MEMORY) && (a[3] & (ACQUIRE_RELEASE | SEQUENTIALLY_CONSISTENT)) ? 2 : 0);
        }
        if (len >= 3 && a[1] < bound && types[a[1]] == WORKGROUP_POINTER && a[2] < bound) {
            if (op == OP_VARIABLE || op == OP_ACCESS_CHAIN || op == OP_IN_BOUNDS_ACCESS_CHAIN || op == OP_COPY_OBJECT) pointers[a[2]] = 1;
            if (op == OP_FUNCTION_PARAMETER || op == OP_FUNCTION_CALL) goto done;
        }
        if (op == OP_FUNCTION) {
            if (len != 5 || !entry || !model_ok) goto done;
            if (!first_function) first_function = i;
            in_entry = a[2] == entry;
        }
        if (op == OP_LABEL && in_entry) {
            if (block || len != 2 || !a[1] || a[1] >= bound || block_index[a[1]]) goto done;
            block_index[a[1]] = (uint32_t)++block_count;
            block = &blocks[block_count - 1];
            block->start = i;
        }
        if (in_entry && op == OP_SWITCH) goto done; // this sort's translated CFG uses only one- and two-way branches
        if (in_entry && (op == OP_BRANCH || op == OP_BRANCH_CONDITIONAL || op == OP_RETURN || op == OP_UNREACHABLE)) {
            if (!block) goto done;
            if (op == OP_BRANCH && len == 2) block->next[0] = a[1];
            if (op == OP_BRANCH_CONDITIONAL && len >= 4) {
                block->next[0] = a[2];
                block->next[1] = a[3];
            }
            block->end = i + len;
            block = NULL;
        }
        if (op == OP_FUNCTION_END) {
            if (block) goto done;
            in_entry = 0;
        }
        uint32_t ptr = op == OP_LOAD && len >= 4 ? a[3] : op == OP_STORE && len >= 3 ? a[1] : 0;
        if (len >= 3 && (op == OP_COPY_MEMORY || op == OP_COPY_MEMORY_SIZED) &&
            (shared_pointer(pointers, bound, a[1]) || shared_pointer(pointers, bound, a[2]))) goto done;
        if (len >= 4 && op >= OP_ATOMIC_LOAD && op <= OP_ATOMIC_XOR &&
            shared_pointer(pointers, bound, a[op == OP_ATOMIC_STORE ? 1 : 3])) goto done;
        if (shared_pointer(pointers, bound, ptr)) {
            if (!block) goto done; // helpers must not access shared memory
            events[i] = op == OP_LOAD ? READ : WRITE;
            if (events[i] == WRITE) block->gen = 1;
        }
        if (op == OP_CONTROL_BARRIER || op == OP_MEMORY_BARRIER) {
            int exec = op == OP_CONTROL_BARRIER;
            if (!in_entry) goto done;
            if (!block || len != (unsigned)(3 + exec) || a[1] >= bound || a[1 + exec] >= bound || a[2 + exec] >= bound) goto done;
            if ((!exec || (ordered[a[1]] & 1)) && (ordered[a[1 + exec]] & 1) && (ordered[a[2 + exec]] & 2)) {
                events[i] = exec ? CONTROL_ORDER : MEMORY_ORDER;
                if (exec) {
                    block->kill = 1;
                    block->gen = 0;
                }
            }
        }
    }
    if (!first_function || !block_count || !uint_type) goto done;
    for (size_t b = 0; b < block_count; ++b) {
        if (!blocks[b].end) goto done;
        for (unsigned edge = 0; edge < 2; ++edge) {
            uint32_t label = blocks[b].next[edge];
            if (label >= bound || (label && !block_index[label])) goto done;
            blocks[b].next[edge] = block_index[label];
        }
    }
    // Propagate writes that can reach a successor without an existing control
    // barrier. Each incoming bit can only rise once, including at loop back edges.
    int changed;
    do {
        changed = 0;
        for (size_t b = 0; b < block_count; ++b) {
            block = &blocks[b];
            if (!block->gen && (block->kill || !block->pending)) continue;
            for (unsigned edge = 0; edge < 2; ++edge) {
                uint32_t next = block->next[edge];
                if (next && !blocks[next - 1].pending) {
                    blocks[next - 1].pending = 1;
                    changed = 1;
                }
            }
        }
    } while (changed);
    unsigned nc = 0, nm = 0;
    for (size_t b = 0; b < block_count; ++b) {
        block = &blocks[b];
        int pending = block->pending, previous = 0;
        for (size_t i = block->start; i < block->end; i += w[i] >> 16) {
            unsigned event = events[i];
            if (event == CONTROL_ORDER) previous = pending = 0;
            if (event == MEMORY_ORDER) pending = 0;
            if (event != READ && event != WRITE) { events[i] = 0; continue; }
            events[i] = 0;
            if (previous && previous != (int)event) { events[i] = CONTROL_ORDER; ++nc; }
            else if (pending) { events[i] = MEMORY_ORDER; ++nm; }
            previous = (int)event;
            pending = 0;
        }
    }
    if (!nc && !nm) goto done;
    result = malloc((n + 8 + 4u * nc + 3u * nm) * sizeof(*result));
    if (!result) goto done;
    memcpy(result, w, first_function * sizeof(*w));
    size_t pos = first_function;
    uint32_t next_id = bound;
    if (!scope_id) {
        scope_id = next_id++;
        const uint32_t literal[] = {(4u << 16) | OP_CONSTANT, uint_type, scope_id, SCOPE_SUBGROUP};
        memcpy(result + pos, literal, sizeof(literal));
        pos += 4;
    }
    if (!semantics_id) {
        semantics_id = next_id++;
        const uint32_t literal[] = {(4u << 16) | OP_CONSTANT, uint_type, semantics_id, SEMANTICS};
        memcpy(result + pos, literal, sizeof(literal));
        pos += 4;
    }
    result[3] = next_id;
    for (size_t i = first_function; i < n; i += w[i] >> 16) {
        if (events[i] == CONTROL_ORDER) {
            result[pos++] = (4u << 16) | OP_CONTROL_BARRIER;
            result[pos++] = scope_id;
            result[pos++] = scope_id;
            result[pos++] = semantics_id;
        }
        if (events[i] == MEMORY_ORDER) {
            result[pos++] = (3u << 16) | OP_MEMORY_BARRIER;
            result[pos++] = scope_id;
            result[pos++] = semantics_id;
        }
        unsigned len = w[i] >> 16;
        memcpy(result + pos, w + i, len * sizeof(*w));
        pos += len;
    }
    *out_n = pos;
    *control = nc;
    *memory = nm;
done:
    free(blocks);
    free(block_index);
    free(ordered);
    free(events);
    free(pointers);
    free(types);
    return result;
}
