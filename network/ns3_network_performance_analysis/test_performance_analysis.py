import pytest

from network.ns3_network_performance_analysis.performance_analysis import (
    read_priority_flow_metrics,
    read_simulation_events,
)


def test_simulation_events_use_final_route_count_and_recovery_time(tmp_path):
    log_path = tmp_path / "failure-run-0001-seed-1.txt"
    log_path.write_text(
        "ROUTE_CHANGE_COUNT total=0\n"
        "ROUTE_CHANGE time=5 client=Client1\n"
        "FAILURE_RECOVERY_TIME seconds=0.02\n"
        "ROUTE_CHANGE_COUNT total=2\n",
        encoding="utf-8",
    )

    assert read_simulation_events(log_path) == (2, 0.02)


def test_failure_log_requires_and_reports_recovery_status(tmp_path):
    log_path = tmp_path / "failure.txt"
    log_path.write_text(
        "ROUTE_CHANGE_COUNT total=1\n"
        "FAILURE_RECOVERY_TIME seconds=unrecovered\n",
        encoding="utf-8",
    )

    assert read_simulation_events(log_path, require_recovery=True) == (1, None)

    log_path.write_text("ROUTE_CHANGE_COUNT total=1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="recovery-time result"):
        read_simulation_events(log_path, require_recovery=True)


def test_flow_metrics_include_configured_traffic_priority(tmp_path):
    xml_path = tmp_path / "failure.xml"
    xml_path.write_text(
        """<?xml version="1.0"?>
<FlowMonitor>
  <FlowStats>
    <Flow flowId="1" txPackets="10" rxPackets="8" txBytes="5120"
          rxBytes="4096" delaySum="1s" />
  </FlowStats>
  <Ipv4FlowClassifier>
    <Flow flowId="1" sourceAddress="10.1.0.1" destinationAddress="10.1.0.5"
          protocol="17" sourcePort="49153" destinationPort="5002" />
  </Ipv4FlowClassifier>
</FlowMonitor>
""",
        encoding="utf-8",
    )

    [metrics] = read_priority_flow_metrics(
        xml_path,
        scenario="Failure",
        run_number=1,
        seed=1,
        measurement_duration=8,
    )

    assert metrics["priority"] == 1
    assert metrics["packets_lost"] == 2
    assert metrics["packet_loss_percent"] == 20
    assert metrics["average_end_to_end_delay_ms"] == 125
