# SwitchRecomp - Copyright 2026 MZ Labs
"""What the launcher says about the shader preparation: before it, and for each event of it (tools/nxshader/nxs_prepare.py)."""

SHADER_PREP_TEXT = ("Shader preparation reads the shader archives of your game files and prepares the supported shaders for Vulkan "
                    "(about 23,000), reducing translation pauses while you play. It takes about "
                    "15 minutes on 8 cores, more on fewer, and about 4 GB of disk. Nothing is sent anywhere. When Stop is available, "
                    "completed translations can be reused. The graphics driver still builds each Vulkan pipeline the first time a scene needs it.")


def shader_progress(event):
    """0..100 for the progress bar"""
    phase = event.get("phase")
    if phase == "translate" and event.get("discovered"):
        done = event.get("cached", 0) + event.get("translated", 0) + event.get("failed", 0)
        return 8 + 90 * done / event["discovered"]
    return {"deps": 0, "deps_ready": 1, "start": 1, "decoder": 1, "extract": 3, "decode": 6,
            "publish_wait": 99, "publish": 99, "done": 100}.get(phase, 0)


def shader_progress_text(event):
    phase = event.get("phase")
    if phase == "decoder":
        return "Shaders · building the archive decoder"
    if phase == "deps":
        return f"Shaders · {event.get('component', 'tools')}: {event.get('status', '')}"
    if phase in ("start", "extract"):
        return "Shaders · reading the game's shader archives"
    if phase == "decode":
        return "Shaders · decoding the shader archives" + (f" · {event['pairs']:,} found".replace(",", " ") if event.get("pairs") else "")
    if phase == "translate":
        n = event.get("discovered", 0)
        return (f"Shaders · {event.get('translated', 0):,} translated · {event.get('cached', 0):,} already in cache · "
                f"{event.get('failed', 0)} failed · of {n:,} found").replace(",", " ")
    if phase in ("publish_wait", "publish"):
        return "Shaders · writing the shader cache"
    if phase == "done":
        return (f"Shaders · {event.get('validated', 0):,} prepared and validated").replace(",", " ")
    return "Shaders · " + str(phase)
