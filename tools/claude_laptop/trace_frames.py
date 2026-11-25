"""Read a SWR_TRACE file (swr_trace_<present>.json, Chrome trace events) frame by frame: between two presents, each thread's spans in time order,
and per span name the total, count and longest. Shows a frame's critical path: who waits for whom between the game's submit, the replay, the GPU
and the completion that releases the game's sync waits.

  trace_frames.py swr_trace_7000.json [--frames 3] [--from N]
"""
import argparse, collections, json


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('trace'); ap.add_argument('--frames', type=int, default=3); ap.add_argument('--from', dest='first', type=int, default=2)
    a = ap.parse_args()
    ev = [e for e in json.load(open(a.trace))['traceEvents'] if e.get('ph') == 'X']
    ev.sort(key=lambda e: e['ts'])
    names = collections.defaultdict(collections.Counter)
    for e in ev:
        names[e['tid']][e['name']] += 1
    label = {tid: c.most_common(1)[0][0][:28] for tid, c in names.items()}
    presents = [e for e in ev if e['name'] == 'nvnQueuePresentTexture']
    span = (presents[-1]['ts'] - presents[0]['ts']) / max(1, len(presents) - 1) if len(presents) > 1 else 0
    print(f'{len(ev)} spans, {len(presents)} presents, {span / 1000:.2f} ms per present; threads:')
    for tid, c in sorted(names.items(), key=lambda kv: -sum(kv[1].values())):
        print(f'  {tid:6d} {label[tid]:30s} ' + ', '.join(f'{n} x{k}' for n, k in c.most_common(4)))
    tot = collections.defaultdict(lambda: [0.0, 0, 0.0])
    t0, t1 = presents[0]['ts'], presents[-1]['ts']
    for e in ev:
        if t0 <= e['ts'] < t1:
            t = tot[e['name']]; t[0] += e['dur']; t[1] += 1; t[2] = max(t[2], e['dur'])
    n = max(1, len(presents) - 1)
    print('\nper frame (between the first and last present):')
    for name, (d, k, mx) in sorted(tot.items(), key=lambda kv: -kv[1][0]):
        print(f'  {d / n / 1000:7.2f} ms  {k / n:6.1f} x  longest {mx / 1000:6.2f} ms  {name}')
    for f in range(a.first, min(a.first + a.frames, len(presents) - 1)):
        s, e = presents[f]['ts'], presents[f + 1]['ts']
        print(f'\nframe {f}: {(e - s) / 1000:.2f} ms')
        for x in ev:
            if s <= x['ts'] < e and x['dur'] >= 200:
                print(f"  +{(x['ts'] - s) / 1000:6.2f} .. +{(x['ts'] + x['dur'] - s) / 1000:6.2f} ms  {label[x['tid']][:18]:18s} {x['name']}")


if __name__ == '__main__':
    main()
