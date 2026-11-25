// Adapter for AMD FidelityFX Super Resolution 1 EASU (see LICENSE.txt).
#define A_GPU 1
#define A_GLSL 1
#include "ffx_a.h"
#define FSR_EASU_F 1
#include "ffx_fsr1.h"

ivec2 easuMin, easuMax, easuSize;

// Gather order matches GLSL textureGather. Clamp each tap when the NVN crop
// occupies part of the image so filtering cannot read outside its viewport.
vec4 cropGather(vec2 position, int channel) {
    ivec2 q = ivec2(floor(position * vec2(easuSize) - 0.5));
    return vec4(
        texelFetch(src, clamp(q + ivec2(0, 1), easuMin, easuMax), 0)[channel],
        texelFetch(src, clamp(q + ivec2(1, 1), easuMin, easuMax), 0)[channel],
        texelFetch(src, clamp(q + ivec2(1, 0), easuMin, easuMax), 0)[channel],
        texelFetch(src, clamp(q, easuMin, easuMax), 0)[channel]);
}

bool fullImage() {
    return all(equal(easuMin, ivec2(0))) && all(equal(easuMax + 1, easuSize));
}
AF4 FsrEasuRF(AF2 p) { return fullImage() ? textureGather(src, p, 0) : cropGather(p, 0); }
AF4 FsrEasuGF(AF2 p) { return fullImage() ? textureGather(src, p, 1) : cropGather(p, 1); }
AF4 FsrEasuBF(AF2 p) { return fullImage() ? textureGather(src, p, 2) : cropGather(p, 2); }

vec3 presentEasu() {
    easuSize = textureSize(src, 0);
    easuMin = clamp(ivec2(round(min(pc.rect.xy, pc.rect.zw) * vec2(easuSize))), ivec2(0), easuSize - 1);
    easuMax = clamp(ivec2(round(max(pc.rect.xy, pc.rect.zw) * vec2(easuSize))) - 1, easuMin, easuSize - 1);
    vec2 inputSize = vec2(easuMax - easuMin + 1);
    vec2 outputSize = pc.sharp.yz;
    vec2 position = (uv - min(pc.rect.xy, pc.rect.zw)) / abs(pc.rect.zw - pc.rect.xy);
    uvec2 pixel = uvec2(clamp(floor(position * outputSize), vec2(0), outputSize - 1.0));
    AU4 con0, con1, con2, con3;
    FsrEasuConOffset(con0, con1, con2, con3, inputSize.x, inputSize.y,
                     float(easuSize.x), float(easuSize.y), outputSize.x, outputSize.y,
                     float(easuMin.x), float(easuMin.y));
    vec3 color;
    FsrEasuF(color, pixel, con0, con1, con2, con3);
    return color;
}
