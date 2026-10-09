"""``livecaptions-bench``: compare local ASR engines on a LibriSpeech subset.

Examples::

    livecaptions-bench --download        # fetch the default subset, then run all engines
    livecaptions-bench                   # re-run on the already downloaded subset
    livecaptions-bench --engines moonshine:moonshine/tiny,whisper:base.en --limit 20
"""

import argparse
import datetime as dt
import json
import multiprocessing as mp
import os
import platform
import sys
import time

DEFAULT_ENGINES = ("moonshine:moonshine/tiny,moonshine:moonshine/base,"
                   "whisper:base.en,whisper:small.en")


def machine_info():
    info = {"os": platform.platform(), "python": platform.python_version(),
            "machine": platform.machine(), "cpu": platform.processor()}
    try:
        import psutil
        info["logical_cpus"] = psutil.cpu_count()
        info["physical_cores"] = psutil.cpu_count(logical=False)
        info["ram_gb"] = round(psutil.virtual_memory().total / 2**30, 1)
    except ImportError:
        info["logical_cpus"] = os.cpu_count()
    if sys.platform == "win32":
        try:
            import subprocess
            name = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"],
                capture_output=True, text=True, timeout=20).stdout.strip()
            if name:
                info["cpu"] = name
        except Exception:
            pass
    return info


def parse_engines(spec):
    out = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        kind, sep, name = item.partition(":")
        if not sep or not name:
            raise argparse.ArgumentTypeError(f"Engine must look like kind:name, got {item!r}")
        out.append((kind, name))
    return out


def _fmt(v, spec):
    return "TBD" if v is None else format(v, spec)


def markdown_table(results):
    lines = [
        "| Engine | WER % | RTF | Latency p50 (s) | Latency p95 (s) | CPU-s per audio-s "
        "| Avg cores busy | Model size (MB) | Peak RAM (MB) | Load (s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        if "error" in r:
            lines.append(f"| {r['engine']} | error: {r['error']} |" + " |" * 9)
            continue
        lines.append(
            f"| {r['engine']} | {r['wer'] * 100:.2f} | {r['rtf']:.3f} | {r['latency_p50_s']:.2f} "
            f"| {r['latency_p95_s']:.2f} | {r['cpu_s_per_audio_s']:.3f} "
            f"| {r['avg_cores_busy']:.2f} | {_fmt(r['model_size_mb'], '.0f')} "
            f"| {_fmt(r['peak_rss_mb'], '.0f')} | {r['load_s']:.1f} |")
    return "\n".join(lines)


def _worker(kind, name, utterances, queue):
    import truststore
    truststore.inject_into_ssl()
    from .runner import run_engine
    try:
        def progress(i, n):
            if i % 10 == 0 or i == n:
                print(f"    {time.strftime('%H:%M:%S')} {kind}:{name} {i}/{n}", flush=True)
        queue.put(run_engine(kind, name, utterances, progress=progress))
    except Exception as e:
        queue.put({"engine": f"{kind}:{name}", "error": f"{type(e).__name__}: {e}"})


def run_isolated(kind, name, utterances):
    """Run one engine in a fresh process so peak-RAM numbers are not polluted by others."""
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=_worker, args=(kind, name, utterances, q))
    p.start()
    result = q.get()
    p.join()
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(prog="livecaptions-bench", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--download", action="store_true",
                    help="download the LibriSpeech test-clean subset first (skipped if present)")
    ap.add_argument("--per-speaker", type=int, default=2, metavar="K",
                    help="subset = first K utterances of each of the 40 speakers (default 2)")
    ap.add_argument("--first", type=int, metavar="N",
                    help="subset = first N utterances in archive order (few speakers; quick checks)")
    ap.add_argument("--data", help="dataset directory or manifest.jsonl "
                                   "(default: data/librispeech-test-clean-2per-speaker)")
    ap.add_argument("--engines", default=DEFAULT_ENGINES, type=parse_engines,
                    help=f"comma-separated kind:name list (default: {DEFAULT_ENGINES})")
    ap.add_argument("--limit", type=int, help="use only the first N utterances")
    ap.add_argument("--out", help="write full JSON results here (default: bench_results/<ts>.json)")
    ap.add_argument("--download-only", action="store_true", help="fetch the dataset and exit")
    args = ap.parse_args(argv)

    from . import dataset

    if args.download or args.download_only:
        manifest = dataset.download(args.per_speaker, args.first, args.data)
        if args.download_only:
            return 0
    else:
        manifest = args.data or dataset.default_dir(args.per_speaker, args.first)
        if not os.path.exists(manifest):
            ap.error(f"{manifest} not found; run `livecaptions-bench --download` first")

    utterances = dataset.load_manifest(manifest)
    if args.limit:
        utterances = utterances[:args.limit]
    audio_min = sum(u["duration"] for u in utterances) / 60
    print(f"{len(utterances)} utterances, {audio_min:.1f} min of audio")

    stamp = dt.datetime.now()
    out = args.out or os.path.join("bench_results", stamp.strftime("%Y%m%d-%H%M%S") + ".json")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    report = {"date": stamp.isoformat(timespec="seconds"), "machine": machine_info(),
              "dataset": os.path.abspath(manifest), "utterances": len(utterances),
              "audio_minutes": round(audio_min, 2), "results": []}
    for kind, name in args.engines:
        print(f"==> {kind}:{name}", flush=True)
        t0 = time.perf_counter()
        result = run_isolated(kind, name, utterances)
        result["bench_wall_s"] = round(time.perf_counter() - t0, 1)
        report["results"].append(result)
        with open(out, "w", encoding="utf-8") as f:   # save after every engine
            json.dump(report, f, indent=2)
        print(f"    done in {result['bench_wall_s']:.0f} s", flush=True)
    results = report["results"]

    m = report["machine"]
    print()
    print(f"Machine: {m.get('cpu')}, {m.get('physical_cores')} cores / "
          f"{m.get('logical_cpus')} threads, {m.get('ram_gb')} GB RAM, {m['os']}, "
          f"Python {m['python']}")
    print(f"Date: {stamp:%Y-%m-%d}   Dataset: {len(utterances)} utterances "
          f"({audio_min:.1f} min) LibriSpeech test-clean")
    print()
    print(markdown_table(results))
    print(f"\nFull results: {out}")
    return 0 if all("error" not in r for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
