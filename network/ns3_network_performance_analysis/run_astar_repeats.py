#!/usr/bin/env python3
"""Build and run paired multi-client A* simulations in the ns3-lab container."""

import argparse
import hashlib
import shlex
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


def run_command(command, *, capture=False):
    return subprocess.run(
        command,
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


def remote_exists(container, path):
    result = subprocess.run(
        ["docker", "exec", container, "sh", "-lc", f"test -e {shlex.quote(path)}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Unable to check container path: {path}")
    return result.returncode == 0


def install_source(container):
    if not remote_exists(container, REMOTE_SOURCE):
        run_command(["docker", "cp", str(SOURCE), f"{container}:{REMOTE_SOURCE}"])
        return

    remote = docker_exec(
        container, f"sha256sum {shlex.quote(REMOTE_SOURCE)}", capture=True
    ).stdout.split()[0]
    local = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if remote != local:
        raise FileExistsError(
            f"Refusing to overwrite a different source in the container: {REMOTE_SOURCE}"
        )


def validate_xml(path):
    root = ET.parse(path).getroot()
    flow_stats = root.find("FlowStats")
    if root.tag != "FlowMonitor" or flow_stats is None or not flow_stats.findall("Flow"):
        raise ValueError(f"Invalid or empty FlowMonitor XML: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", type=int, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--failure-type", choices=("link", "node"), default="link")
    parser.add_argument("--container", default="ns3-lab")
    args = parser.parse_args()

    if args.seed < 1 or any(run < 1 for run in args.runs):
        parser.error("Seed and run numbers must be positive integers.")
    if len(set(args.runs)) != len(args.runs):
        parser.error("Run numbers must be distinct.")
    if not SOURCE.is_file():
        raise FileNotFoundError(f"A* simulation source not found: {SOURCE}")

    planned = []
    for run in args.runs:
        for scenario, failure in (("baseline", False), ("failure", True)):
            stem = f"{scenario}-run-{run:04d}-seed-{args.seed}"
            local_xml = RAW_DIR / f"{stem}.xml"
            local_log = LOG_DIR / f"{stem}.txt"
            remote_xml = f"{NS3_DIR}/scratch/{stem}.xml"
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
        if remote_exists(args.container, remote_xml):
            raise FileExistsError(
                f"Refusing to overwrite container output: {remote_xml}"
            )

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    install_source(args.container)
    ns3_dir = shlex.quote(NS3_DIR)
    docker_exec(args.container, f"cd {ns3_dir} && ./ns3 build scratch/astar-multiclient")

    for scenario, failure, run, local_xml, local_log, remote_xml in planned:
        command = (
            f"cd {ns3_dir} && ./ns3 run 'scratch/astar-multiclient "
            f"--run={run} --seed={args.seed} --failure={'true' if failure else 'false'} "
            f"--failureType={args.failure_type} --output={shlex.quote(remote_xml)}'"
        )
        print(f"Running {scenario}: seed={args.seed}, run={run}")
        result = docker_exec(args.container, command, capture=True)
        local_log.write_text(result.stdout, encoding="utf-8")
        expected = (
            f"RUN_METADATA scenario={scenario} seed={args.seed} run={run}"
        )
        if expected not in result.stdout:
            raise RuntimeError(f"Run metadata mismatch; inspect {local_log}")
        if not remote_exists(args.container, remote_xml):
            raise FileNotFoundError(f"Simulation did not produce {remote_xml}")
        run_command(["docker", "cp", f"{args.container}:{remote_xml}", str(local_xml)])
        validate_xml(local_xml)
        print(f"Verified FlowMonitor XML: {local_xml}")

    print("Paired A* runs complete. Analyze with:")
    print(
        "python performance_analysis.py --repeat-xml-dir "
        "results/raw/astar_repeats --repeat-log-dir "
        "results/processed/astar_repeats/run_logs --repeat-output-dir "
        "results/processed/astar_repeats/analysis --repeat-graphs "
        "results/graphs/astar_repeats"
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
