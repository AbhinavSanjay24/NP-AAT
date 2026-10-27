#!/usr/bin/env python3
"""Build and run paired multi-client A* simulations with Docker or native NS-3."""

import argparse
import hashlib
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


PROJECT = Path(__file__).resolve().parent
SOURCE = PROJECT / "repeat_simulations" / "astar-multiclient.cc"
RAW_DIR = PROJECT / "results" / "raw" / "astar_repeats"
OUTPUT_DIR = PROJECT / "results" / "processed" / "astar_repeats"
LOG_DIR = OUTPUT_DIR / "run_logs"
NS3_DIR = "/opt/ns-3.45"
REMOTE_SOURCE = f"{NS3_DIR}/scratch/astar-multiclient.cc"


def run_command(command, *, capture=False, cwd=None):
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def docker_exec(container, command, *, capture=False):
    return run_command(
        ["docker", "exec", container, "sh", "-lc", command],
        capture=capture,
    )


def remote_exists(container, path, *, backend):
    if backend == "native":
        return Path(path).exists()

    result = subprocess.run(
        ["docker", "exec", container, "sh", "-lc", f"test -e {shlex.quote(path)}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Unable to check container path: {path}")
    return result.returncode == 0


def install_source(container, remote_source, *, backend):
    if not remote_exists(container, remote_source, backend=backend):
        if backend == "native":
            shutil.copy2(SOURCE, remote_source)
            return
        run_command(["docker", "cp", str(SOURCE), f"{container}:{remote_source}"])
        return

    if backend == "native":
        remote = hashlib.sha256(Path(remote_source).read_bytes()).hexdigest()
    else:
        remote = docker_exec(
            container, f"sha256sum {shlex.quote(remote_source)}", capture=True
        ).stdout.split()[0]
    local = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if remote != local:
        raise FileExistsError(
            f"Refusing to overwrite a different NS-3 scratch source: {remote_source}"
        )


def ns3_command(container, ns3_dir, command, *, backend, capture=False):
    if backend == "docker":
        return docker_exec(
            container,
            f"cd {shlex.quote(ns3_dir)} && ./ns3 {shlex.join(command)}",
            capture=capture,
        )
    return run_command(["./ns3", *command], capture=capture, cwd=ns3_dir)


def validate_xml(path):
    root = ET.parse(path).getroot()
    flow_stats = root.find("FlowStats")
    if root.tag != "FlowMonitor" or flow_stats is None or not flow_stats.findall("Flow"):
        raise ValueError(f"Invalid or empty FlowMonitor XML: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", type=int, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--failure-type", choices=("link", "node"), default="node")
    parser.add_argument("--backend", choices=("docker", "native"), default="docker")
    parser.add_argument("--container", default="ns3-lab")
    parser.add_argument(
        "--ns3-dir",
        help="NS-3 source directory (required for --backend native)",
    )
    args = parser.parse_args()

    if args.seed < 1 or any(run < 1 for run in args.runs):
        parser.error("Seed and run numbers must be positive integers.")
    if len(set(args.runs)) != len(args.runs):
        parser.error("Run numbers must be distinct.")
    if args.backend == "docker":
        if shutil.which("docker") is None:
            raise FileNotFoundError(
                "Docker CLI not found. Install Docker Desktop, start it, and ensure "
                "'docker' is available on PATH before running the NS-3 simulations."
            )
        ns3_dir = NS3_DIR
        remote_source = REMOTE_SOURCE
    else:
        if not args.ns3_dir:
            parser.error("--ns3-dir is required when using --backend native.")
        ns3_root = Path(args.ns3_dir).expanduser().resolve()
        if not (ns3_root / "ns3").is_file():
            raise FileNotFoundError(f"NS-3 build driver not found: {ns3_root / 'ns3'}")
        if not (ns3_root / "scratch").is_dir():
            raise FileNotFoundError(f"NS-3 scratch directory not found: {ns3_root / 'scratch'}")
        ns3_dir = str(ns3_root)
        remote_source = str(ns3_root / "scratch" / SOURCE.name)
    if not SOURCE.is_file():
        raise FileNotFoundError(f"A* simulation source not found: {SOURCE}")

    planned = []
    for run in args.runs:
        for scenario, failure in (("baseline", False), ("failure", True)):
            stem = f"{scenario}-run-{run:04d}-seed-{args.seed}"
            local_xml = RAW_DIR / f"{stem}.xml"
            local_log = LOG_DIR / f"{stem}.txt"
            remote_xml = (
                f"{NS3_DIR}/scratch/{stem}.xml"
                if args.backend == "docker"
                else str(Path(ns3_dir) / "scratch" / f"{stem}.xml")
            )
            planned.append((scenario, failure, run, local_xml, local_log, remote_xml))

    local_collisions = [
        str(path)
        for row in planned
        for path in (row[3], row[4])
        if path.exists()
    ]
    if local_collisions:
        raise FileExistsError(
            "Refusing to overwrite existing output(s): " + ", ".join(local_collisions)
        )
    for *_, remote_xml in planned:
        if remote_exists(args.container, remote_xml, backend=args.backend):
            raise FileExistsError(
                f"Refusing to overwrite NS-3 output: {remote_xml}"
            )

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    install_source(args.container, remote_source, backend=args.backend)
    ns3_command(
        args.container,
        ns3_dir,
        ["build", "scratch/astar-multiclient"],
        backend=args.backend,
    )

    for scenario, failure, run, local_xml, local_log, remote_xml in planned:
        command = [
            "run",
            f"scratch/astar-multiclient --run={run} --seed={args.seed} "
            f"--failure={'true' if failure else 'false'} "
            f"--failureType={args.failure_type} --output={shlex.quote(remote_xml)}",
        ]
        print(f"Running {scenario}: seed={args.seed}, run={run}")
        result = ns3_command(
            args.container,
            ns3_dir,
            command,
            backend=args.backend,
            capture=True,
        )
        local_log.write_text(result.stdout, encoding="utf-8")
        expected = (
            f"RUN_METADATA scenario={scenario} seed={args.seed} run={run}"
        )
        if expected not in result.stdout:
            raise RuntimeError(f"Run metadata mismatch; inspect {local_log}")
        if not remote_exists(args.container, remote_xml, backend=args.backend):
            raise FileNotFoundError(f"Simulation did not produce {remote_xml}")
        if args.backend == "native":
            shutil.copy2(remote_xml, local_xml)
        else:
            run_command(["docker", "cp", f"{args.container}:{remote_xml}", str(local_xml)])
        validate_xml(local_xml)
        print(f"Verified FlowMonitor XML: {local_xml}")

    print("Paired A* runs complete. Analyze with:")
    print(
        "python performance_analysis.py --repeat-xml-dir "
        "results/raw/astar_repeats --repeat-log-dir "
        "results/processed/astar_repeats/run_logs --repeat-output-dir "
        "results/processed/astar_repeats/analysis --repeat-graphs "
        "results/graphs/astar_repeats --measurement-duration 16"
    )


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, FileExistsError, FileNotFoundError,
            RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stdout:
            print(error.stdout, file=sys.stderr)
        sys.exit(1)
