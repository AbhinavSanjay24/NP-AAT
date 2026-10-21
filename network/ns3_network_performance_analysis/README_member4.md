# Member 4 — Performance Analysis and Visualization (NS-3.45)

## What this package does
- Adds a Python analysis script that reads NS-3 FlowMonitor XML output.
- Calculates packet loss, PDR, throughput, and average end-to-end delay.
- Saves a metrics CSV and PNG charts under `results/processed/` and `results/graphs/`.
- Leaves route-change count and failure recovery time blank until the simulation records real events.

## Required environment and setup

- macOS with Docker Desktop installed and running.
- The existing Docker container `ns3-lab`, with NS-3.45 at
  `/opt/ns-3.45` and its `./ns3` build driver for running simulations. The
  original C++ sources are included in this project under
  `original_simulations/`; the repeat runner uses the separate sources in
  `repeat_simulations/`.
- Python 3.9 or later and the packages in `requirements.txt` (pandas 2.3.3,
  matplotlib 3.9.4).

From the project directory, create/use the virtual environment and install the
analysis packages:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
```

Start the existing container if it is stopped and verify NS-3 is available:

```bash
docker start ns3-lab
docker exec ns3-lab sh -lc 'cd /opt/ns-3.45 && ./ns3 --help'
```

The repeat runner copies only its three new sources into the container; it does
not overwrite the original C++ sources. Refer to the repeat-run section below
for the commands that build and execute the repeat variants.

## Included original sources and external topology

The verified original `member4-simulation.cc` and `member4-failure.cc` sources
are included under `original_simulations/`. They were copied byte-for-byte from
`/opt/ns-3.45/scratch/` in the existing container; the copies have matching
SHA-256 hashes to those source files. The separate `repeat_simulations/`
variants are used for seeded repeated experiments and do not replace the
originals.

The original `topology.py` is not bundled in this project. It is present
separately at `~/Downloads/topology.py`; the standalone C++ simulations in this
project do not load that Python file. It was not reconstructed or modified.

## Verified continuation — 21 October 2026

The existing baseline artifacts were preserved. The baseline XML remains
`results/raw/flowmon.xml`; the separate failure run is
`results/raw/failure_flowmon.xml`. The original
`results/processed/performance_metrics.csv` and four original graphs were not
used as comparison outputs or overwritten.

The failure scenario is a separate NS-3.45 C++ program based on the same four
node Wi-Fi setup as `member4-simulation.cc`. At 5 seconds it puts the first
server's Wi-Fi PHY (device index 2) to sleep using `WifiPhy::SetSleepMode()`;
at 7 seconds it resumes it using `WifiPhy::ResumeFromSleep()`. These are valid
NS-3.45 APIs and the failure program built and ran successfully. The original
`topology.py` was not present at the stated `/opt/ns-3.45/scratch/topology.py`
path during inspection; it was not modified. The separate C++ failure program
uses the topology coded in the baseline C++ simulation.

### Commands used

Build and run the failure test inside the existing container:

```bash
docker exec ns3-lab sh -lc 'cd /opt/ns-3.45 && ./ns3 build scratch/member4-failure && ./ns3 run scratch/member4-failure'
```

It writes `scratch/member4-failure-flowmon.xml` in the container. Copy it to
the project only if the destination does not already exist. The validated
`results/raw/failure_flowmon.xml` is already present; do not rerun this copy
command over it unless intentionally preserving that existing result elsewhere:

```bash
docker cp ns3-lab:/opt/ns-3.45/scratch/member4-failure-flowmon.xml results/raw/failure_flowmon.xml
```

Generate the comparison from both actual FlowMonitor XML files:

```bash
./.venv/bin/python performance_analysis.py \
  --normal results/raw/flowmon.xml \
  --failure results/raw/failure_flowmon.xml
```

Both applications send from 1 to 9 seconds, so throughput uses the configured
8-second traffic window. Packet loss is `txPackets - rxPackets`; PDR is
`rxPackets / txPackets`; average delay is the summed FlowMonitor `delaySum`
divided by received packets.

### Verified aggregate results

| Metric | Baseline | Wi-Fi PHY sleep (5–7 s) |
| --- | ---: | ---: |
| Packets sent | 5,859 | 5,859 |
| Packets received | 5,617 | 4,876 |
| Packets lost | 242 | 983 |
| Packet loss | 4.1304% | 16.7776% |
| PDR | 95.8696% | 83.2224% |
| Received bytes | 3,033,180 | 2,633,040 |
| Throughput (Mbps, 8 s) | 3.033180 | 2.633040 |
| Average end-to-end delay (ms) | 1.317192 | 18.361520 |

In this single run, the temporary receiver interruption coincides with fewer
packets received, lower PDR and throughput, and higher packet loss and average
delay. This is only an aggregate two-flow result; it does not establish which
flow recovered when or indicate route changes.

### Preserved single-run comparison outputs

These files were generated by the earlier single-run analysis and remain
unchanged:

- `results/processed/failure_comparison.csv` — both scenarios in one table.
- `results/processed/baseline_metrics.csv` and
  `results/processed/failure_metrics.csv` — individual scenario summaries.
- `results/graphs/comparison/` — four separate metric charts and the historical
  mixed-unit `normal_vs_failure.png` (see the graph note below).
- The pre-existing `performance_metrics.csv` and images directly under
  `results/graphs/` remain the original baseline outputs.

The updated analyzer does not overwrite these historical outputs. A new
single-run comparison should use:

```bash
./.venv/bin/python performance_analysis.py \
  --normal results/raw/flowmon.xml \
  --failure results/raw/failure_flowmon.xml
```

By default this writes `results/processed/comparison_metrics.csv`, two
`comparison_*_metrics.csv` files, and four unit-specific charts under
`results/graphs/comparison_units/`.

### Remaining limitations

- The documented repeat dataset contains ten baseline runs and ten failure
  runs (run numbers 31–40, seed 1). This is a ten-run sample, not a guarantee of
  statistical power or a confidence interval.
- The comparison aggregates both UDP flows. It does not attribute metric
  changes to a specific flow in the CSV.
- This is a Wi-Fi PHY sleep/resume interruption, not a node crash, link removal,
  or routing-protocol failure. The simulation has no multi-hop alternate-route
  recovery implementation.
- No route-change events or defined recovery event are logged. Therefore route
  changes and recovery time are intentionally blank/not reported.
- Throughput depends on the configured 8-second application traffic duration;
  use `--measurement-duration SECONDS` if the traffic window is changed.

## Existing baseline analysis

To analyze the preserved baseline XML without overwriting the original baseline
CSV or graphs, run:

```bash
./.venv/bin/python performance_analysis.py --normal results/raw/flowmon.xml
```

This writes to `results/processed/normal_analysis.csv` and
`results/graphs/normal_analysis/`. The analyzer refuses to overwrite existing
output files; choose `--output` and `--graphs` to select another unused path.

## Metric notes

- FlowMonitor counters are aggregated across the UDP flows in each XML.
- Throughput is received FlowMonitor bytes × 8 divided by the configured
  measurement window in seconds, reported in Mbps.
- Average delay is total FlowMonitor `delaySum` divided by received packets.
- FlowMonitor alone does not report reliable route-change counts or a recovery
  time. Those values require explicit event logging and a defined recovery rule.

## Repeatable paired experiments

The new repeat variants are isolated under `repeat_simulations/`; they do not
modify `member4-simulation.cc` or `member4-failure.cc`. Both accept an NS-3
random seed and run number. Each run applies `RngSeedManager::SetSeed(seed)` and
`RngSeedManager::SetRun(run)`, then writes a distinct scenario/run/seed XML.
The runner checks all local and container destinations before starting and
refuses to overwrite any existing run XML, log, or analysis output.

### First verified test: two paired runs

The initial test used a fixed seed and two different run numbers:

```bash
./.venv/bin/python run_repeats.py --runs 31 32 --seed 1
./.venv/bin/python performance_analysis.py \
  --repeat-xml-dir results/raw/repeats
```

Both new C++ variants built, all four simulations completed, and each generated
XML parsed with two flows. The logs recorded the requested seed/run values.
Runs 31 and 32 had different reception counts and distinct XML hashes even
with the same seed, confirming that different NS-3 run numbers select distinct
random streams. The small two-run sample is a workflow check, not a strong
statistical estimate.

The initial two-run test outputs are:

- `results/raw/repeats/baseline-run-0031-seed-1.xml`
- `results/raw/repeats/failure-run-0031-seed-1.xml`
- `results/raw/repeats/baseline-run-0032-seed-1.xml`
- `results/raw/repeats/failure-run-0032-seed-1.xml`
- `results/processed/repeats/per_run_metrics.csv`
- `results/processed/repeats/repeat_summary.csv`
- Four charts under `results/graphs/repeats/`, one per metric, with means and
  sample-standard-deviation error bars.

For these two workflow-check runs (seed 1), results were:

| Metric | Baseline mean ± sample SD | Failure mean ± sample SD |
| --- | ---: | ---: |
| Throughput (Mbps) | 3.162240 ± 0.000764 | 2.765610 ± 0.000382 |
| Packet loss (%) | 0.051200 ± 0.024183 | 12.587450 ± 0.012092 |
| PDR (%) | 99.948800 ± 0.024183 | 87.412550 ± 0.012092 |
| Average end-to-end delay (ms) | 0.845692 ± 0.006236 | 17.099731 ± 0.020514 |

### Expanding the run count without replacing the test outputs

The first test consumed run numbers 31 and 32. Add new unique run numbers (for
example, 33–40); the runner refuses reused outputs. The analyzer reads all
paired XMLs in the repeat directory. Choose new summary and chart directories
to preserve the two-run test summary:

```bash
./.venv/bin/python run_repeats.py \
  --runs 33 34 35 36 37 38 39 40 --seed 1
./.venv/bin/python performance_analysis.py \
  --repeat-xml-dir results/raw/repeats \
  --repeat-output-dir results/processed/repeats_10 \
  --repeat-graphs results/graphs/repeats_10
```

The output filenames include the scenario, zero-padded run number, and seed.
To use another seed, select a different seed and ensure the corresponding
scenario/run/seed output names do not already exist. Keep seed/run values and
source versions in any report to make runs reproducible.

The requested expansion was then run with eight additional run numbers:

```bash
./.venv/bin/python run_repeats.py \
  --runs 33 34 35 36 37 38 39 40 --seed 1
./.venv/bin/python performance_analysis.py \
  --repeat-xml-dir results/raw/repeats \
  --repeat-output-dir results/processed/repeats_10 \
  --repeat-graphs results/graphs/repeats_10
```

This produced ten paired runs (31–40) with seed 1. The verified aggregate
mean ± sample-standard-deviation results are:

| Metric | Baseline | Failure |
| --- | ---: | ---: |
| Throughput (Mbps) | 3.135618 ± 0.054714 | 2.738124 ± 0.054717 |
| Packet loss (%) | 0.892630 ± 1.729326 | 13.456230 ± 1.729427 |
| PDR (%) | 99.107370 ± 1.729326 | 86.543770 ± 1.729427 |
| Average end-to-end delay (ms) | 0.947693 ± 0.201789 | 17.323317 ± 0.551585 |

Ten-run output files are `results/processed/repeats_10/per_run_metrics.csv`,
`results/processed/repeats_10/repeat_summary.csv`, and the four charts under
`results/graphs/repeats_10/`. The original two-run test summaries remain under
`results/processed/repeats/` and `results/graphs/repeats/`.

The ten-run files are the submission-ready repeated-run outputs. Run logs for
each scenario/run are stored in `results/processed/repeats/run_logs/`.

### Metric formulas and units

For each XML, the analyzer sums FlowMonitor counters across the measured flows.
With `txPackets`, `rxPackets`, `rxBytes`, total delay sum `D`, and configured
measurement duration `T` seconds:

- Lost packets = `txPackets - rxPackets`; packet loss (%) =
  `100 × (txPackets - rxPackets) / txPackets`.
- PDR (%) = `100 × rxPackets / txPackets`.
- Throughput (Mbps) = `8 × rxBytes / T / 1,000,000` (decimal Mbps).
- Average end-to-end delay (ms) = `D / rxPackets`, after converting FlowMonitor
  time units to seconds, then multiplying by 1,000.

The average and sample standard deviation are calculated across run-level
metric values per scenario; sample SD uses `n - 1` in the denominator. With one
run, the sample SD is undefined (blank in the CSV and no visible error bar).

### Routing and recovery metrics are not implemented

The current scenarios do not implement alternate-route recovery or a routing
protocol whose route changes are recorded. A meaningful route-change count
would require installing/configuring the relevant routing protocol and
instrumenting its route-table/route-change events with timestamps and
source/destination context. Recovery time additionally requires a defined
failure timestamp and an observable recovery criterion, such as the first
successful end-to-end probe after failure (or a sustained-success threshold),
plus logging that event. FlowMonitor aggregate counters cannot infer either
metric; they remain omitted/unreported rather than estimated.

### Graph note

The repeat workflow creates only four separate mean ± sample-SD charts, each
with a single metric and its own unit. The packet-loss chart clips the lower
visual error bar at zero because loss cannot be negative; the reported mean and
full sample standard deviation remain unchanged in the summary CSV. The previously existing
`results/graphs/comparison/normal_vs_failure.png` is preserved as a historical
artifact, but it plots percentages and Mbps on one shared axis and should not
be used to compare those different units. The analyzer no longer creates that
mixed-unit graph.
