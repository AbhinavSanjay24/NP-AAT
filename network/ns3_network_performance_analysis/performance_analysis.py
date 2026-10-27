#!/usr/bin/env python3
"""
Member 4: NS-3 FlowMonitor performance analysis.

Reads NS-3 FlowMonitor XML output and creates:
- results/processed/performance_metrics.csv
- results/graphs/*.png

Example:
  python3 performance_analysis.py --normal results/raw/normal_flowmon.xml
  python3 performance_analysis.py --normal results/raw/normal_flowmon.xml \
      --failure results/raw/failure_flowmon.xml

Note: FlowMonitor does not provide route-change counts. Recovery time must be
measured from real failure/recovery events logged by the simulation.
"""
import argparse
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


def seconds(value):
    """Convert NS-3 time strings to seconds, respecting their units."""
    if not value:
        return 0.0

    match = re.search(
        r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(ns|us|ms|s)?",
        value
    )
    if not match:
        return 0.0

    number = float(match.group(1))
    unit = match.group(2) or "s"
    scale = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1.0}
    return number * scale[unit]


def read_flowmon(xml_path, scenario, measurement_duration):
    """Read and aggregate packet statistics across all flows in an NS-3 XML file."""
    if not os.path.isfile(xml_path):
        raise FileNotFoundError(
            f"Cannot find {xml_path}. Run main.py and save its FlowMonitor XML first."
        )

    root = ET.parse(xml_path).getroot()
    flow_stats = root.find("FlowStats")
    if flow_stats is None:
        raise ValueError(f"{xml_path} does not contain a FlowStats section.")

    tx_packets = rx_packets = tx_bytes = rx_bytes = 0
    delay_sum_s = 0.0

    for flow in flow_stats.findall("Flow"):
        tx_packets += int(flow.get("txPackets", "0"))
        rx_packets += int(flow.get("rxPackets", "0"))
        tx_bytes += int(flow.get("txBytes", "0"))
        rx_bytes += int(flow.get("rxBytes", "0"))
        delay_sum_s += seconds(flow.get("delaySum", "0s"))

    lost_packets = max(tx_packets - rx_packets, 0)
    packet_loss_pct = (lost_packets / tx_packets * 100) if tx_packets else 0.0
    pdr_pct = (rx_packets / tx_packets * 100) if tx_packets else 0.0
    throughput_mbps = (
        rx_bytes * 8 / measurement_duration / 1_000_000
        if measurement_duration > 0 else 0.0
    )
    avg_delay_ms = (
        delay_sum_s / rx_packets * 1000 if rx_packets else 0.0
    )

    return {
        "scenario": scenario,
        "packets_sent": tx_packets,
        "packets_received": rx_packets,
        "packets_lost": lost_packets,
        "packet_loss_percent": round(packet_loss_pct, 4),
        "pdr_percent": round(pdr_pct, 4),
        "received_bytes": rx_bytes,
        "throughput_mbps": round(throughput_mbps, 6),
        "average_end_to_end_delay_ms": round(avg_delay_ms, 6),
        # These are intentionally blank until the simulation records them.
        "route_changes": None,
        "failure_recovery_time_seconds": None,
    }


def make_graphs(df, output_dir):
    """Create charts from the metrics that are available."""
    os.makedirs(output_dir, exist_ok=True)
    charts = [
        ("pdr_percent", "Packet Delivery Ratio", "PDR (%)", "pdr_comparison.png"),
        ("packet_loss_percent", "Packet Loss", "Packet loss (%)", "packet_loss.png"),
        ("throughput_mbps", "Throughput", "Throughput (Mbps)", "throughput.png"),
        ("average_end_to_end_delay_ms", "Average End-to-End Delay",
         "Delay (ms)", "end_to_end_delay.png"),
    ]

    for column, title, ylabel, filename in charts:
        plt.figure(figsize=(7, 4.5))
        plt.bar(df["scenario"], df[column])
        plt.title(title)
        plt.ylabel(ylabel)
        plt.xlabel("Scenario")
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, filename), dpi=160)
        plt.close()



REPEAT_NAME = re.compile(r"^(baseline|failure)-run-(\d+)-seed-(\d+)\.xml$")
REPEAT_METRICS = {
    "throughput_mbps": ("Throughput", "Throughput (Mbps)", "throughput_mean_std.png"),
    "packet_loss_percent": ("Packet Loss", "Packet loss (%)", "packet_loss_mean_std.png"),
    "pdr_percent": ("Packet Delivery Ratio", "PDR (%)", "pdr_mean_std.png"),
    "average_end_to_end_delay_ms": (
        "Average End-to-End Delay", "Delay (ms)", "end_to_end_delay_mean_std.png"
    ),
}
PRIORITY_BY_PORT = {5000: 3, 5001: 2, 5002: 1, 5003: 3}


def read_simulation_events(log_path, *, require_recovery=False):
    """Read routing events recorded by the multi-client A* simulation."""
    if not log_path.is_file():
        raise FileNotFoundError(f"Simulation event log does not exist: {log_path}")

    text = log_path.read_text(encoding="utf-8")
    route_counts = re.findall(r"^ROUTE_CHANGE_COUNT total=(\d+)$", text, re.MULTILINE)
    if not route_counts:
        raise ValueError(f"{log_path} does not contain a final route-change count.")

    recovery_events = read_recovery_events(log_path, require_recovery=require_recovery)
    if recovery_events:
        recovery_times = [event["recovery_time_seconds"] for event in recovery_events]
        recovery_time = (
            sum(recovery_times) / len(recovery_times)
            if all(value is not None for value in recovery_times) else None
        )
        return int(route_counts[-1]), recovery_time

    recovery_matches = re.findall(
        r"^FAILURE_RECOVERY_TIME seconds=([^\s]+)$", text, re.MULTILINE
    )
    if require_recovery and not recovery_matches:
        raise ValueError(f"{log_path} does not contain a recovery-time result.")
    recovery_time = None
    if recovery_matches and recovery_matches[-1] != "unrecovered":
        recovery_time = float(recovery_matches[-1])

    return int(route_counts[-1]), recovery_time


def read_recovery_events(log_path, *, require_recovery=False):
    """Read each client/server/failed-relay recovery record from a simulation log."""
    text = log_path.read_text(encoding="utf-8")
    pattern = (
        r"^FAILURE_RECOVERY client=(Client[1-4]) server=(Server[1-4]) "
        r"relay=(Relay[A-H]) seconds=([^\s]+)$"
    )
    matches = re.findall(pattern, text, re.MULTILINE)
    if not matches:
        if require_recovery and not re.search(
            r"^FAILURE_RECOVERY_TIME seconds=[^\s]+$", text, re.MULTILINE
        ):
            raise ValueError(f"{log_path} does not contain a recovery-time result.")
        return []

    reroute_pattern = (
        r"^REROUTE client=(Client[1-4]) server=(Server[1-4]) "
        r"failed_relay=(Relay[A-H]) old=([^\s]+) new=([^\s]+) time=([^\s]+)$"
    )
    reroute_matches = re.findall(reroute_pattern, text, re.MULTILINE)
    reroutes = {}
    for client, server, relay, old_path, new_path, failure_time in reroute_matches:
        if client in reroutes:
            raise ValueError(f"{log_path} contains duplicate reroute records for {client}.")
        if server != f"Server{client[6:]}":
            raise ValueError(f"{log_path} has mismatched client/server reroute pair.")
        if relay != f"Relay{chr(ord('A') + int(client[6:]) - 1)}":
            raise ValueError(f"{log_path} has mismatched failed relay for {client}.")
        if old_path == "UNREACHABLE" or new_path == "UNREACHABLE" or old_path == new_path:
            raise ValueError(f"{log_path} contains an invalid reroute for {client}.")
        reroutes[client] = {
            "failed_path": old_path.replace("->", " → "),
            "rerouted_path": new_path.replace("->", " → "),
            "failure_time_seconds": float(failure_time),
        }

    restoration_pattern = (
        r"^RECOVERY type=(?:node|link) client=(Client[1-4]) "
        r"server=(Server[1-4]) relay=(Relay[A-H]) time=([^\s]+)$"
    )
    restoration_matches = re.findall(restoration_pattern, text, re.MULTILINE)
    restorations = {}
    for client, server, relay, restore_time in restoration_matches:
        if client in restorations:
            raise ValueError(f"{log_path} contains duplicate relay restorations for {client}.")
        if server != f"Server{client[6:]}":
            raise ValueError(f"{log_path} has mismatched client/server restoration pair.")
        if relay != f"Relay{chr(ord('A') + int(client[6:]) - 1)}":
            raise ValueError(f"{log_path} has mismatched restored relay for {client}.")
        restorations[client] = float(restore_time)

    seen_clients = set()
    for client, server, relay, value in matches:
        if client in seen_clients:
            raise ValueError(f"{log_path} contains duplicate recovery records for {client}.")
        if server != f"Server{client[6:]}":
            raise ValueError(f"{log_path} has mismatched client/server recovery pair.")
        if relay != f"Relay{chr(ord('A') + int(client[6:]) - 1)}":
            raise ValueError(f"{log_path} has mismatched failed relay for {client}.")
        seen_clients.add(client)

    if require_recovery and seen_clients != {f"Client{index}" for index in range(1, 5)}:
        raise ValueError(
            f"{log_path} must contain recovery records for all four client/server pairs."
        )
    if require_recovery and set(restorations) != seen_clients:
        raise ValueError(
            f"{log_path} must contain relay-restoration events for all four pairs."
        )

    events = []
    for client, server, relay, value in matches:
        reroute = reroutes.get(client)
        if require_recovery and reroute is None:
            raise ValueError(f"{log_path} is missing the failed and rerouted paths for {client}.")
        events.append({
            "client": client,
            "server": server,
            "failed_relay": relay,
            "failed_path": reroute["failed_path"] if reroute else "",
            "rerouted_path": reroute["rerouted_path"] if reroute else "",
            "failure_time_seconds": (
                reroute["failure_time_seconds"] if reroute else None
            ),
            "relay_restored_time_seconds": restorations.get(client),
            "recovery_time_seconds": None if value == "unrecovered" else float(value),
            "recovered": value != "unrecovered",
        })

    if require_recovery and set(reroutes) != seen_clients:
        raise ValueError(
            f"{log_path} must contain failed and rerouted paths for all four pairs."
        )
    if require_recovery:
        failure_times = {
            event["failure_time_seconds"] for event in events
        }
        restoration_times = {
            event["relay_restored_time_seconds"] for event in events
        }
        if len(failure_times) != 1:
            raise ValueError(f"{log_path} must fail all four primary relays together.")
        failure_time = next(iter(failure_times))
        if len(restoration_times) != len(events) or any(
            restore_time <= failure_time for restore_time in restoration_times
        ):
            raise ValueError(
                f"{log_path} must restore each primary relay separately after failure."
            )
    return events


def read_priority_flow_metrics(xml_path, scenario, run_number, seed,
                                measurement_duration):
    """Calculate per-flow measurements and associate the configured priority."""
    root = ET.parse(xml_path).getroot()
    flow_stats = root.find("FlowStats")
    classifier = root.find("Ipv4FlowClassifier")
    if flow_stats is None or classifier is None:
        raise ValueError(f"{xml_path} is missing FlowStats or Ipv4FlowClassifier.")

    flow_details = {
        flow.get("flowId"): flow
        for flow in classifier.findall("Flow")
    }
    rows = []
    for flow in flow_stats.findall("Flow"):
        detail = flow_details.get(flow.get("flowId"))
        if detail is None:
            raise ValueError(
                f"{xml_path} has no IPv4 classifier record for flow "
                f"{flow.get('flowId')}."
            )
        destination_port = int(detail.get("destinationPort", "0"))
        if destination_port not in PRIORITY_BY_PORT:
            raise ValueError(
                f"Unexpected destination port {destination_port} in {xml_path}."
            )

        tx_packets = int(flow.get("txPackets", "0"))
        rx_packets = int(flow.get("rxPackets", "0"))
        tx_bytes = int(flow.get("txBytes", "0"))
        rx_bytes = int(flow.get("rxBytes", "0"))
        loss = max(tx_packets - rx_packets, 0)
        delay_seconds = seconds(flow.get("delaySum", "0s"))
        rows.append({
            "scenario": scenario,
            "run_number": run_number,
            "seed": seed,
            "flow_id": int(flow.get("flowId", "0")),
            "source_address": detail.get("sourceAddress"),
            "destination_address": detail.get("destinationAddress"),
            "destination_port": destination_port,
            "priority": PRIORITY_BY_PORT[destination_port],
            "packets_sent": tx_packets,
            "packets_received": rx_packets,
            "packets_lost": loss,
            "packet_loss_percent": loss / tx_packets * 100 if tx_packets else 0.0,
            "pdr_percent": rx_packets / tx_packets * 100 if tx_packets else 0.0,
            "throughput_mbps": (
                rx_bytes * 8 / measurement_duration / 1_000_000
                if measurement_duration > 0 else 0.0
            ),
            "average_end_to_end_delay_ms": (
                delay_seconds / rx_packets * 1000 if rx_packets else 0.0
            ),
        })
    return rows


def analyze_repeats(xml_dir, measurement_duration, output_dir, graph_dir,
                    log_dir=None):
    """Summarize paired repeat-run XMLs without replacing existing artifacts."""
    xml_dir = Path(xml_dir)
    if not xml_dir.is_dir():
        raise FileNotFoundError(f"Repeat XML directory does not exist: {xml_dir}")

    rows = []
    flow_rows = []
    recovery_rows = []
    run_keys = {"baseline": set(), "failure": set()}
    for xml_path in sorted(xml_dir.glob("*.xml")):
        match = REPEAT_NAME.fullmatch(xml_path.name)
        if not match:
            continue
        scenario_key, run_text, seed_text = match.groups()
        run_number, seed = int(run_text), int(seed_text)
        run_keys[scenario_key].add((seed, run_number))
        scenario = "Normal" if scenario_key == "baseline" else "Failure"
        row = read_flowmon(str(xml_path), scenario, measurement_duration)
        if log_dir is not None:
            log_path = Path(log_dir) / f"{scenario_key}-run-{run_number:04d}-seed-{seed}.txt"
            if scenario_key == "failure":
                recovery_rows.extend(
                    {
                        "scenario": scenario,
                        "run_number": run_number,
                        "seed": seed,
                        **event,
                    }
                    for event in read_recovery_events(log_path, require_recovery=True)
                )
            row["route_changes"], row["failure_recovery_time_seconds"] = (
                read_simulation_events(
                    log_path, require_recovery=scenario_key == "failure"
                )
            )
            flow_rows.extend(read_priority_flow_metrics(
                xml_path, scenario, run_number, seed, measurement_duration
            ))
        else:
            row.pop("route_changes", None)
            row.pop("failure_recovery_time_seconds", None)
        row.update({"run_number": run_number, "seed": seed,
                    "xml_file": xml_path.name})
        rows.append(row)

    if not rows:
        raise ValueError(f"No repeat-run XML files found in {xml_dir}")
    if not run_keys["baseline"] or run_keys["baseline"] != run_keys["failure"]:
        raise ValueError(
            "Repeat runs must contain matching baseline and failure files for "
            "each (seed, run number)."
        )

    per_run = pd.DataFrame(rows).sort_values(["seed", "run_number", "scenario"])
    metric_names = list(REPEAT_METRICS)
    summary_rows = []
    for scenario in ("Normal", "Failure"):
        scenario_rows = per_run[per_run["scenario"] == scenario]
        summary = {"scenario": scenario, "run_count": len(scenario_rows)}
        for metric in metric_names:
            summary[f"{metric}_mean"] = scenario_rows[metric].mean()
            # pandas std() uses sample standard deviation (ddof=1).
            summary[f"{metric}_sample_std"] = scenario_rows[metric].std(ddof=1)
        if "route_changes" in scenario_rows:
            summary["route_changes_mean"] = scenario_rows["route_changes"].mean()
            summary["route_changes_sample_std"] = scenario_rows["route_changes"].std(ddof=1)
            summary["failure_recovery_time_seconds_mean"] = (
                scenario_rows["failure_recovery_time_seconds"].mean()
            )
            summary["failure_recovery_time_seconds_sample_std"] = (
                scenario_rows["failure_recovery_time_seconds"].std(ddof=1)
            )
        summary_rows.append(summary)
    summary_df = pd.DataFrame(summary_rows)

    per_run_path = Path(output_dir) / "per_run_metrics.csv"
    summary_path = Path(output_dir) / "repeat_summary.csv"
    flow_path = Path(output_dir) / "per_flow_metrics.csv"
    priority_path = Path(output_dir) / "priority_summary.csv"
    recovery_path = Path(output_dir) / "per_route_recovery.csv"
    graph_dir = Path(graph_dir)
    graph_paths = [graph_dir / spec[2] for spec in REPEAT_METRICS.values()]
    output_paths = [per_run_path, summary_path, *graph_paths]
    if log_dir is not None:
        output_paths.extend([flow_path, priority_path, recovery_path])
        output_paths.extend(
            graph_dir / f"priority_{spec[2]}" for spec in REPEAT_METRICS.values()
        )
    collisions = [path for path in output_paths
                  if path.exists()]
    if collisions:
        raise FileExistsError(
            "Refusing to overwrite existing repeat analysis output(s): "
            + ", ".join(map(str, collisions))
        )

    per_run_path.parent.mkdir(parents=True, exist_ok=True)
    graph_dir.mkdir(parents=True, exist_ok=True)
    per_run.to_csv(per_run_path, index=False)
    summary_df.to_csv(summary_path, index=False)
    if log_dir is not None:
        flow_df = pd.DataFrame(flow_rows)
        flow_df.to_csv(flow_path, index=False)
        pd.DataFrame(recovery_rows).to_csv(recovery_path, index=False)
        priority_metrics = list(REPEAT_METRICS)
        priority_summary = (
            flow_df.groupby(["scenario", "priority"])[priority_metrics]
            .agg(["mean", "std"])
            .reset_index()
        )
        priority_summary.columns = [
            "_".join(str(part) for part in column if part)
            if isinstance(column, tuple) else column
            for column in priority_summary.columns
        ]
        priority_summary.to_csv(priority_path, index=False)
        priority_order = sorted(flow_df["priority"].unique())
        x_positions = list(range(len(priority_order)))
        bar_width = 0.36
        for metric, (title, ylabel, filename) in REPEAT_METRICS.items():
            plt.figure(figsize=(7, 4.5))
            for index, scenario in enumerate(("Normal", "Failure")):
                scenario_data = flow_df[flow_df["scenario"] == scenario]
                grouped = scenario_data.groupby("priority")[metric].agg(["mean", "std"])
                means = [
                    grouped.loc[priority, "mean"] if priority in grouped.index else 0
                    for priority in priority_order
                ]
                deviations = [
                    grouped.loc[priority, "std"]
                    if priority in grouped.index and pd.notna(grouped.loc[priority, "std"])
                    else 0
                    for priority in priority_order
                ]
                offsets = [
                    position + (index - 0.5) * bar_width
                    for position in x_positions
                ]
                plt.bar(offsets, means, width=bar_width, yerr=deviations,
                        capsize=4, label=scenario)
            plt.title(f"{title} by traffic priority")
            plt.ylabel(ylabel)
            plt.xlabel("Traffic priority (1 = low, 3 = high)")
            plt.xticks(x_positions, [f"P{value}" for value in priority_order])
            plt.legend()
            plt.tight_layout()
            plt.savefig(graph_dir / f"priority_{filename}", dpi=160)
            plt.close()

    scenario_order = ["Normal", "Failure"]
    for metric, (title, ylabel, filename) in REPEAT_METRICS.items():
        means = [summary_df.loc[summary_df["scenario"] == scenario,
                                f"{metric}_mean"].iloc[0]
                 for scenario in scenario_order]
        deviations = [summary_df.loc[summary_df["scenario"] == scenario,
                                     f"{metric}_sample_std"].iloc[0]
                      for scenario in scenario_order]
        # A single observation has undefined sample SD; show no error bar,
        # while preserving the undefined value in the CSV.
        deviations = [0.0 if pd.isna(value) else value for value in deviations]
        yerr = deviations
        if metric == "packet_loss_percent":
            # The lower side of a symmetric SD interval cannot imply negative loss.
            yerr = [
                [min(deviation, mean) for mean, deviation in zip(means, deviations)],
                deviations,
            ]
        plt.figure(figsize=(7, 4.5))
        plt.bar(scenario_order, means, yerr=yerr, capsize=6)
        plt.title(f"{title} (mean ± sample SD)")
        plt.ylabel(ylabel)
        plt.xlabel("Scenario")
        if metric == "packet_loss_percent":
            # Packet loss is nonnegative; keep the error-bar axis physically valid.
            plt.ylim(bottom=0)
        plt.tight_layout()
        plt.savefig(graph_dir / filename, dpi=160)
        plt.close()

    print("Per-run metrics:")
    print(per_run.to_string(index=False))
    print("\nMean and sample standard deviation:")
    print(summary_df.to_string(index=False))
    print(f"\nSaved per-run CSV: {per_run_path}")
    print(f"Saved summary CSV: {summary_path}")
    if log_dir is not None:
        print(f"Saved per-flow priority CSV: {flow_path}")
        print(f"Saved priority summary CSV: {priority_path}")
        print(f"Saved per-route recovery CSV: {recovery_path}")
    graph_count = 8 if log_dir is not None else 4
    print(f"Saved {graph_count} unit-specific mean ± SD graphs in: {graph_dir}")


def main():
    parser = argparse.ArgumentParser(description="Analyze NS-3 FlowMonitor XML files.")
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--normal", help="FlowMonitor XML from normal run")
    input_group.add_argument("--repeat-xml-dir",
                             help="Directory of paired repeated-run XML files")
    parser.add_argument("--failure", help="FlowMonitor XML from failure run")
    parser.add_argument(
        "--repeat-output-dir", default="results/processed/repeats",
        help="Output directory for repeat per-run and summary CSV files",
    )
    parser.add_argument(
        "--repeat-graphs", default="results/graphs/repeats",
        help="Output directory for the four repeat mean ± sample-SD graphs",
    )
    parser.add_argument(
        "--repeat-log-dir",
        help="Simulation log directory for route changes and recovery-time analysis",
    )
    parser.add_argument(
        "--measurement-duration", type=float, default=8.0,
        help="Measurement window in seconds (default 8, matching traffic from 1s to 9s)"
    )
    parser.add_argument(
        "--output",
        help="Output summary CSV path"
    )
    parser.add_argument(
        "--graphs",
        help="Directory for generated PNG charts"
    )
    args = parser.parse_args()

    if args.repeat_xml_dir:
        if args.failure:
            parser.error("Use --repeat-xml-dir without --failure.")
        analyze_repeats(
            args.repeat_xml_dir,
            args.measurement_duration,
            args.repeat_output_dir,
            args.repeat_graphs,
            args.repeat_log_dir,
        )
        return

    if not args.normal and not args.failure:
        parser.error("Provide at least one input: --normal and/or --failure.")

    rows = []
    if args.normal:
        rows.append(read_flowmon(args.normal, "Normal", args.measurement_duration))
    if args.failure:
        rows.append(read_flowmon(args.failure, "Failure", args.measurement_duration))

    df = pd.DataFrame(rows)
    is_comparison = bool(args.normal and args.failure)
    default_output = (
        "results/processed/comparison_metrics.csv" if is_comparison
        else "results/processed/normal_analysis.csv" if args.normal
        else "results/processed/failure_analysis.csv"
    )
    output_path = args.output or default_output
    graph_dir = args.graphs or (
        "results/graphs/comparison_units" if is_comparison
        else "results/graphs/normal_analysis"
    )

    output_csv_paths = [output_path]
    if is_comparison:
        output_csv_paths.extend([
            os.path.join(os.path.dirname(output_path), "comparison_baseline_metrics.csv"),
            os.path.join(os.path.dirname(output_path), "comparison_failure_metrics.csv"),
        ])
    existing_csvs = [path for path in output_csv_paths if os.path.exists(path)]
    if existing_csvs:
        raise FileExistsError(
            "Refusing to overwrite existing CSV(s): " + ", ".join(existing_csvs)
        )
    if os.path.isdir(graph_dir):
        expected_graphs = [
            os.path.join(graph_dir, filename)
            for _, _, filename in [
                ("pdr_percent", "PDR", "pdr_comparison.png"),
                ("packet_loss_percent", "Packet loss", "packet_loss.png"),
                ("throughput_mbps", "Throughput", "throughput.png"),
                ("average_end_to_end_delay_ms", "Delay", "end_to_end_delay.png"),
            ]
        ]
        collisions = [path for path in expected_graphs if os.path.exists(path)]
        if collisions:
            raise FileExistsError(
                "Refusing to overwrite existing graph(s): " + ", ".join(collisions)
            )

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    df.to_csv(output_path, index=False)
    make_graphs(df, graph_dir)

    # Preserve the individual scenarios in separate, collision-safe CSVs.
    if is_comparison:
        for scenario, filename in (
            ("Normal", "comparison_baseline_metrics.csv"),
            ("Failure", "comparison_failure_metrics.csv"),
        ):
            scenario_path = os.path.join(os.path.dirname(output_path), filename)
            scenario_df = df[df["scenario"] == scenario]
            scenario_df.to_csv(scenario_path, index=False)

    print("\nPerformance metrics:")
    print(df.to_string(index=False))
    print(f"\nSaved CSV: {output_path}")
    if is_comparison:
        print("Saved scenario CSVs: "
              f"{os.path.dirname(output_path)}/comparison_baseline_metrics.csv and "
              f"{os.path.dirname(output_path)}/comparison_failure_metrics.csv")
    print(f"Saved graphs in: {graph_dir}")
    print("\nRoute changes and recovery time are not measured by these FlowMonitor summaries.")


if __name__ == "__main__":
    main()
