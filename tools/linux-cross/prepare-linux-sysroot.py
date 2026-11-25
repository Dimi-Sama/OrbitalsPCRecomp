import hashlib, io, lzma, tarfile, urllib.request
from pathlib import Path, PurePosixPath

root=Path(__file__).resolve().parent
base="https://archive.ubuntu.com/ubuntu/"
req={"libx11-dev", "libx11-6", "x11proto-dev", "libgl-dev", "libgl1", "libglx-dev", "libglx0", "libglvnd0", "libxcb1", "libxau6", "libxdmcp6", "libx11-xcb1"}
index=lzma.decompress(urllib.request.urlopen(base+"dists/noble/main/binary-amd64/Packages.xz",timeout=30).read()).decode()
links=[]
for stanza in index.split("\n\n"):
    fields=dict(line.split(": ",1) for line in stanza.splitlines() if line and not line.startswith((" ","\t")) and ": " in line)
    name=fields.get("Package")
    if name not in req: continue
    req.remove(name)
    for mirror in (base,"https://mirrors.edge.kernel.org/ubuntu/","https://mirrors.mit.edu/ubuntu/","https://ftp.ubuntu.com/ubuntu/"):
        try:
            package=urllib.request.urlopen(mirror+fields["Filename"],timeout=15).read()
            break
        except (OSError,ValueError) as error:
            print(name,mirror,str(error),flush=True)
    else: raise RuntimeError(f"All official Ubuntu mirrors failed for {name}: {fields['Filename']}")
    if hashlib.sha256(package).hexdigest()!=fields["SHA256"]: raise ValueError(f"{name}: package digest mismatch")
    if not package.startswith(b"!<arch>\n"): raise ValueError(f"{name}: wrong archive type")
    at=8
    while at+60<len(package):
        member,n=package[at:at+16].strip(),int(package[at+48:at+58]); at+=60
        if member.startswith(b"data.tar"):
            with tarfile.open(fileobj=io.BytesIO(package[at:at+n]),mode="r:*") as data:
                for entry in data:
                    path=PurePosixPath(entry.name)
                    if path.is_absolute() or ".." in path.parts: raise ValueError(path)
                    if path.parts[:2]==("usr","include") or (path.parts[:3]==("usr","lib","x86_64-linux-gnu") and ".so" in path.name):
                        dest=root.joinpath("sysroot",*path.parts)
                        if entry.isfile():
                            dest.parent.mkdir(parents=True,exist_ok=True)
                            dest.write_bytes(data.extractfile(entry).read())
                        elif entry.issym() and "/" not in entry.linkname:
                            links.append((dest,entry.linkname))
            break
        at+=n+(n%2)
    print(name,fields["Version"],flush=True)
if req: raise ValueError(f"Missing packages: {req}")
while links:
    pending=[]
    for path,target in links:
        target=path.with_name(target)
        if target.is_file(): path.write_bytes(target.read_bytes())
        else: pending.append((path,target.name))
    if len(pending)==len(links): break
    links=pending
for need in ("include/X11/Xlib.h","include/GL/glx.h","lib/x86_64-linux-gnu/libGL.so","lib/x86_64-linux-gnu/libX11.so"):
    if not (root/"sysroot/usr"/need).exists(): raise ValueError(f"Missing ELF build input: {need}")
