"""Client of the runtime's control channel (runtime/nvn/vk/vk_ctl.c, \\\\.\\pipe\\swr_ctl): one command per connection, the reply printed.

  gamectl.py status | flight [label] | flashes [frames] [min_blocks] | pause | resume | step [n] | hide KEY... | show KEY... | showall
             set NAME VALUE | get NAME | switches | shot [path] | gputime | passdump [n] | passview [n] | drawstats [n] | quit ...

Usable as a module: ctl('status') returns the reply text.
"""
import sys, time

PIPE = r'\\.\pipe\swr_ctl'


def ctl(command, timeout=130.0):
    t0 = time.monotonic()
    while True:
        try:
            with open(PIPE, 'r+b', buffering=0) as p:
                p.write(command.encode() + b'\n')
                out = b''
                while True:
                    try:
                        chunk = p.read(65536)
                    except OSError:   # the runtime closed its end: the reply is complete
                        break
                    if not chunk:
                        break
                    out += chunk
                return out.decode('utf-8', 'replace')
        except (FileNotFoundError, PermissionError, OSError):   # busy (one connection at a time) or not up yet
            if time.monotonic() - t0 > timeout:
                raise
            time.sleep(0.05)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.stdout.write(ctl(' '.join(sys.argv[1:])))
