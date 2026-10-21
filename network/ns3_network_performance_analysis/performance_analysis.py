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


def analyze_repeats(xml_dir, measurement_duration, output_dir, graph_dir):
    """Summarize paired repeat-run XMLs without replacing existing artifacts."""
    xml_dir = Path(xml_dir)
    if not xml_dir.is_dir():
        raise FileNotFoundError(f"Repeat XML directory does not exist: {xml_dir}")

    rows = []
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
        summary_rows.append(summary)
    summary_df = pd.DataFrame(summary_rows)

    per_run_path = Path(output_dir) / "per_run_metrics.csv"
    summary_path = Path(output_dir) / "repeat_summary.csv"
    graph_dir = Path(graph_dir)
    graph_paths = [graph_dir / spec[2] for spec in REPEAT_METRICS.values()]
    collisions = [path for path in [per_run_path, summary_path, *graph_paths]
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
    print(f"Saved four unit-specific mean ± SD graphs in: {graph_dir}")


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
