# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""The connected controllers, for the launcher's own window: their names and the buttons held.

SDL3 when the kit or the installation has it (the game's own choice on Windows), SDL3 or SDL2 of the system on Linux, else XInput on
Windows. Everything is called from the Tk thread. Closed while a game runs: the controllers are the game's then."""

import ctypes
import os
from pathlib import Path

WINDOWS = os.name == "nt"
STICK = 16000       # of 32767: how far a stick is pushed to count as a direction
# the buttons of SDL's gamepads, in the order of their numbers (SDL2 and SDL3); the two the launcher does not use are None
SDL_BUTTONS = ("south", "east", "west", "north", "back", None, "start", None, None, "left shoulder", "right shoulder",
               "up", "down", "left", "right")
XINPUT_BUTTONS = {0x0001: "up", 0x0002: "down", 0x0004: "left", 0x0008: "right", 0x0010: "start", 0x0020: "back",
                  0x0100: "left shoulder", 0x0200: "right shoulder", 0x1000: "south", 0x2000: "east", 0x4000: "west", 0x8000: "north"}
HINTS = ((b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1"),   # SDL has no window of its own here
         (b"SDL_JOYSTICK_HIDAPI_STEAMDECK", b"0"))          # the Deck's built-in controls stay Steam's


def stick_directions(x, y):
    """The directions of a stick: x to the right, y downwards."""
    held = set()
    if abs(x) > STICK and abs(x) >= abs(y):
        held.add("right" if x > 0 else "left")
    elif abs(y) > STICK:
        held.add("down" if y > 0 else "up")
    return held


class SDL3:
    def __init__(self, library):
        self.sdl = sdl = library
        for name, result, arguments in (
                ("SDL_SetHint", ctypes.c_bool, (ctypes.c_char_p, ctypes.c_char_p)), ("SDL_Init", ctypes.c_bool, (ctypes.c_uint32,)),
                ("SDL_QuitSubSystem", None, (ctypes.c_uint32,)), ("SDL_UpdateGamepads", None, ()),
                ("SDL_SetGamepadEventsEnabled", None, (ctypes.c_bool,)), ("SDL_SetJoystickEventsEnabled", None, (ctypes.c_bool,)),
                ("SDL_GetGamepads", ctypes.POINTER(ctypes.c_uint32), (ctypes.POINTER(ctypes.c_int),)), ("SDL_free", None, (ctypes.c_void_p,)),
                ("SDL_OpenGamepad", ctypes.c_void_p, (ctypes.c_uint32,)), ("SDL_CloseGamepad", None, (ctypes.c_void_p,)),
                ("SDL_GetGamepadName", ctypes.c_char_p, (ctypes.c_void_p,)),
                ("SDL_GetGamepadButton", ctypes.c_bool, (ctypes.c_void_p, ctypes.c_int)),
                ("SDL_GetGamepadButtonLabel", ctypes.c_int, (ctypes.c_void_p, ctypes.c_int)),
                ("SDL_GetGamepadAxis", ctypes.c_int16, (ctypes.c_void_p, ctypes.c_int))):
            function = getattr(sdl, name)
            function.restype, function.argtypes = result, arguments
        for hint in HINTS:
            sdl.SDL_SetHint(*hint)
        if not sdl.SDL_Init(0x2000):   # SDL_INIT_GAMEPAD
            raise OSError("SDL3 could not start")
        sdl.SDL_SetGamepadEventsEnabled(False)
        sdl.SDL_SetJoystickEventsEnabled(False)
        self.pads = {}   # id -> handle

    def scan(self):
        self.sdl.SDL_UpdateGamepads()
        ids, count = set(), ctypes.c_int()
        found = self.sdl.SDL_GetGamepads(ctypes.byref(count))
        if found:
            ids = {found[i] for i in range(count.value)}
            self.sdl.SDL_free(found)
        for gone in set(self.pads) - ids:
            self.sdl.SDL_CloseGamepad(self.pads.pop(gone))
        for new in sorted(ids - set(self.pads)):
            handle = self.sdl.SDL_OpenGamepad(new)
            if handle:
                self.pads[new] = handle

    def names(self):
        return [(self.sdl.SDL_GetGamepadName(pad) or b"Controller").decode("utf-8", "replace") for pad in self.pads.values()]

    def held(self):
        self.sdl.SDL_UpdateGamepads()
        held = set()
        for pad in self.pads.values():
            buttons = {name for number, name in enumerate(SDL_BUTTONS) if name and self.sdl.SDL_GetGamepadButton(pad, number)}
            if self.sdl.SDL_GetGamepadButtonLabel(pad, 1) == 1 and len(buttons & {"south", "east"}) == 1:   # A on the right: Nintendo's layout
                buttons ^= {"south", "east"}
            held |= buttons | stick_directions(self.sdl.SDL_GetGamepadAxis(pad, 0), self.sdl.SDL_GetGamepadAxis(pad, 1))
        return held

    def close(self):
        for pad in self.pads.values():
            self.sdl.SDL_CloseGamepad(pad)
        self.pads = {}
        self.sdl.SDL_QuitSubSystem(0x2000)


class SDL2:
    def __init__(self, library):
        self.sdl = sdl = library
        for name, result, arguments in (
                ("SDL_SetHint", ctypes.c_int, (ctypes.c_char_p, ctypes.c_char_p)), ("SDL_Init", ctypes.c_int, (ctypes.c_uint32,)),
                ("SDL_QuitSubSystem", None, (ctypes.c_uint32,)), ("SDL_GameControllerUpdate", None, ()),
                ("SDL_GameControllerEventState", ctypes.c_int, (ctypes.c_int,)), ("SDL_JoystickEventState", ctypes.c_int, (ctypes.c_int,)),
                ("SDL_NumJoysticks", ctypes.c_int, ()), ("SDL_IsGameController", ctypes.c_int, (ctypes.c_int,)),
                ("SDL_JoystickGetDeviceInstanceID", ctypes.c_int32, (ctypes.c_int,)),
                ("SDL_GameControllerOpen", ctypes.c_void_p, (ctypes.c_int,)), ("SDL_GameControllerClose", None, (ctypes.c_void_p,)),
                ("SDL_GameControllerGetAttached", ctypes.c_int, (ctypes.c_void_p,)), ("SDL_GameControllerName", ctypes.c_char_p, (ctypes.c_void_p,)),
                ("SDL_GameControllerGetButton", ctypes.c_uint8, (ctypes.c_void_p, ctypes.c_int)),
                ("SDL_GameControllerGetAxis", ctypes.c_int16, (ctypes.c_void_p, ctypes.c_int))):
            function = getattr(sdl, name)
            function.restype, function.argtypes = result, arguments
        for hint in HINTS:
            sdl.SDL_SetHint(*hint)
        if sdl.SDL_Init(0x2000):   # SDL_INIT_GAMECONTROLLER
            raise OSError("SDL2 could not start")
        sdl.SDL_GameControllerEventState(0)
        sdl.SDL_JoystickEventState(0)
        self.pads = {}

    def scan(self):
        self.sdl.SDL_GameControllerUpdate()
        for instance, pad in list(self.pads.items()):
            if not self.sdl.SDL_GameControllerGetAttached(pad):
                self.sdl.SDL_GameControllerClose(self.pads.pop(instance))
        for index in range(self.sdl.SDL_NumJoysticks()):
            instance = self.sdl.SDL_JoystickGetDeviceInstanceID(index)
            if instance >= 0 and instance not in self.pads and self.sdl.SDL_IsGameController(index):
                handle = self.sdl.SDL_GameControllerOpen(index)
                if handle:
                    self.pads[instance] = handle

    def names(self):
        return [(self.sdl.SDL_GameControllerName(pad) or b"Controller").decode("utf-8", "replace") for pad in self.pads.values()]

    def held(self):
        self.sdl.SDL_GameControllerUpdate()
        held = set()
        for pad in self.pads.values():   # (SDL2 already follows the labels of Nintendo's controllers)
            held |= {name for number, name in enumerate(SDL_BUTTONS) if name and self.sdl.SDL_GameControllerGetButton(pad, number)}
            held |= stick_directions(self.sdl.SDL_GameControllerGetAxis(pad, 0), self.sdl.SDL_GameControllerGetAxis(pad, 1))
        return held

    def close(self):
        for pad in self.pads.values():
            self.sdl.SDL_GameControllerClose(pad)
        self.pads = {}
        self.sdl.SDL_QuitSubSystem(0x2000)


class XInput:
    class State(ctypes.Structure):
        _fields_ = [("packet", ctypes.c_uint32), ("buttons", ctypes.c_uint16), ("left_trigger", ctypes.c_uint8), ("right_trigger", ctypes.c_uint8),
                    ("lx", ctypes.c_int16), ("ly", ctypes.c_int16), ("rx", ctypes.c_int16), ("ry", ctypes.c_int16)]

    def __init__(self, library):
        self.read = library.XInputGetState
        self.read.argtypes, self.read.restype = (ctypes.c_uint32, ctypes.POINTER(self.State)), ctypes.c_uint32
        self.slots = []

    def scan(self):   # (asking an empty slot is slow: not at every poll)
        self.slots = [slot for slot in range(4) if self.read(slot, ctypes.byref(self.State())) == 0]

    def names(self):
        return [f"Controller {slot + 1}" for slot in self.slots]

    def held(self):
        held, state = set(), self.State()
        for slot in self.slots:
            if self.read(slot, ctypes.byref(state)) == 0:
                held |= {name for bit, name in XINPUT_BUTTONS.items() if state.buttons & bit}
                held |= stick_directions(state.lx, -state.ly)
        return held

    def close(self):
        self.slots = []


def backends(folders):
    """What can be tried here, best first: (class, library to load). On Windows only files in System32 or the given folders."""
    if WINDOWS:
        for folder in folders:
            if (Path(folder) / "SDL3.dll").is_file():
                yield SDL3, str((Path(folder) / "SDL3.dll").resolve())
        system = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32"
        for name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
            if (system / name).is_file():
                yield XInput, str(system / name)
    else:
        yield SDL3, "libSDL3.so.0"
        yield SDL2, "libSDL2-2.0.so.0"


class Pads:
    """The controllers. open() starts the first backend that works; scan() looks for new and gone ones, held() for buttons."""

    def __init__(self, folders=()):
        self.folders, self.backend, self.failed = tuple(folders), None, False

    @property
    def available(self):
        return self.backend is not None

    def open(self):
        if self.backend or self.failed:
            return
        for kind, library in backends(self.folders):
            try:
                self.backend = kind(ctypes.CDLL(library))
                return
            except (OSError, AttributeError):   # not there, or without a function it needs
                continue
        self.failed = True

    def close(self):
        if self.backend:
            self.backend.close()
            self.backend = None

    def names(self):
        """The connected controllers, or None when it cannot be told."""
        if not self.backend:
            return None
        self.backend.scan()
        return self.backend.names()

    def held(self):
        return self.backend.held() if self.backend else set()
