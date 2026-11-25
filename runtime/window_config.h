#ifndef SWR_WINDOW_CONFIG_H
#define SWR_WINDOW_CONFIG_H

#include <stdio.h>
#include <stdlib.h>

static inline int startup_window_size(int *width, int *height) {
    const char *size = getenv("SWR_WINDOW_SIZE");
    unsigned w, h;
    char trailing;
    if (!size || sscanf(size, "%ux%u%c", &w, &h, &trailing) != 2 ||
        w < 320 || w > 8192 || h < 240 || h > 8192) return 0;
    *width = (int)w;
    *height = (int)h;
    return 1;
}

#endif
