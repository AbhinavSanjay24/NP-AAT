#!/usr/bin/env python3
"""Build and run repeatable NS-3 baseline/failure scenarios in Docker."""

import argparse
import hashlib
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


PROJECT = Path(__file__).resolve().parent
SOURCE_DIR = PROJECT / "repeat_simulations"
RAW_DIR = PROJECT / "results" / "raw" / "repeats"
LOG_DIR = PROJECT / "results" / "processed" / "repeats" / "run_logs"
NS3_DIR = "/opt/ns-3.45"
SOURCES = {
    "member4-repeat-impl.h": SOURCE_DIR / "member4-repeat-impl.h",
    "member4-repeat-baseline.cc": SOURCE_DIR / "member4-repeat-baseline.cc",
    "member4-repeat-failure.cc": SOURCE_DIR / "member4-repeat-failure.cc",
}


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
        ["docker", "exec", container, "sh", "-lc", command], capture=capture
    )


def remote_file_exists(container, path):
    result = subprocess.run(
        ["docker", "exec", container, "sh", "-lc", f"test -e {shlex.quote(path)}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Could not inspect Docker path: {path}")
    return result.returncode == 0


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install_sources(container):
    for name, local_path in SOURCES.items():
        remote_path = f"{NS3_DIR}/scratch/{name}"
        if remote_file_exists(container, remote_path):
            result = docker_exec(
                container, f"sha256sum {shlex.quote(remote_path)}", capture=True
            )
            remote_hash = result.stdout.split()[0]
            if remote_hash != sha256(local_path):
                raise FileExistsError(
                    f"Refusing to replace different container source: {remote_path}"
                )
            print(f"Verified existing container source: {remote_path}")
        else:
            run_command(["docker", "cp", str(local_path), f"{container}:{remote_path}"])
            print(f"Installed new repeat source: {remote_path}")


def validate_xml(path):
    root = ET.parse(path).getroot()
    flow_stats = root.find("FlowStats")
    if root.tag != "FlowMonitor" or flow_stats is None:
        raise ValueError(f"Not a valid FlowMonitor XML: {path}")
    if not flow_stats.findall("Flow"):
        raise ValueError(f"FlowMonitor XML has no flow records: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", type=int, required=True,
                        help="Distinct positive NS-3 run numbers, e.g. --runs 101 102")
    parser.add_argument("--seed", type=int, default=1,
                        help="NS-3 seed held constant while run numbers vary")
    parser.add_argument("--container", default="ns3-lab")
    args = parser.parse_args()

    if args.seed < 1 or any(run < 1 for run in args.runs):
        parser.error("Seed and run numbers must be positive integers.")
    if len(set(args.runs)) != len(args.runs):
        parser.error("Run numbers must be distinct.")

    scenarios = {
        "baseline": "member4-repeat-baseline",
        "failure": "member4-repeat-failure",
    }
    planned = []
    for run_number in args.runs:
        for scenario, target in scenarios.items():
            filename = f"{scenario}-run-{run_number:04d}-seed-{args.seed}.xml"
            logname = f"{scenario}-run-{run_number:04d}-seed-{args.seed}.txt"
            planned.append((scenario, target, run_number,
                            RAW_DIR / filename, LOG_DIR / logname,
                            f"{NS3_DIR}/scratch/member4-{scenario}-run-"
                            f"{run_number}-seed-{args.seed}.xml"))

    # Preflight the whole batch. No run starts if any destination collides.
    local_targets = [target for *_, xml_path, log_path, remote_path in planned
                     for target in (xml_path, log_path)]
    collisions = [str(path) for path in local_targets if path.exists()]
    if collisions:
        raise FileExistsError("Refusing to overwrite existing output(s): " +
                              ", ".join(collisions))
    for *_, remote_path in planned:
        if remote_file_exists(args.container, remote_path):
            raise FileExistsError(
                f"Refusing to overwrite existing container output: {remote_path}"
            )

    # Existing results are untouched. This only creates the new repeat folders.
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    install_sources(args.container)
    ns3_dir = shlex.quote(NS3_DIR)
    for target in scenarios.values():
        docker_exec(
            args.container,
            f"cd {ns3_dir} && ./ns3 build scratch/{target}",
        )

    for scenario, target, run_number, xml_path, log_path, remote_path in planned:
        command = (
            f"cd {ns3_dir} && ./ns3 run "
            f"'scratch/{target} --run={run_number} --seed={args.seed}'"
        )
        print(f"Running {scenario}: seed={args.seed}, run={run_number}")
        result = docker_exec(args.container, command, capture=True)
        log_path.write_text(result.stdout)
        if f"RUN_METADATA scenario={scenario} seed={args.seed} run={run_number}" \
                not in result.stdout:
            raise RuntimeError(f"Run metadata mismatch; inspect {log_path}")
        if not remote_file_exists(args.container, remote_path):
            raise FileNotFoundError(f"Simulation did not produce {remote_path}")
        run_command(["docker", "cp", f"{args.container}:{remote_path}", str(xml_path)])
        if not xml_path.is_file() or xml_path.stat().st_size == 0:
            raise RuntimeError(f"Copied XML is missing or empty: {xml_path}")
        validate_xml(xml_path)
        print(f"Verified FlowMonitor XML: {xml_path}")

    print("Repeat runs completed. Analyze them with performance_analysis.py --repeat-xml-dir "
          "results/raw/repeats")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, FileExistsError, FileNotFoundError,
            RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stdout:
            print(error.stdout, file=sys.stderr)
        sys.exit(1)