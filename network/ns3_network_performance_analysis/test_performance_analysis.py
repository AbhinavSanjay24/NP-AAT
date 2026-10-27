import pytest

from network.ns3_network_performance_analysis.performance_analysis import (
    analyze_repeats,
    read_priority_flow_metrics,
    read_recovery_events,
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


def test_failure_log_reports_unique_recovery_for_all_client_server_relays(tmp_path):
    log_path = tmp_path / "failure-all-pairs.txt"
    records = [
        "FAILURE_RECOVERY client=Client1 server=Server1 relay=RelayA seconds=0.01",
        "FAILURE_RECOVERY client=Client2 server=Server2 relay=RelayB seconds=0.02",
        "FAILURE_RECOVERY client=Client3 server=Server3 relay=RelayC seconds=unrecovered",
        "FAILURE_RECOVERY client=Client4 server=Server4 relay=RelayD seconds=0.04",
    ]
    reroutes = [
        "REROUTE client=Client1 server=Server1 failed_relay=RelayA "
        "old=Client1->RelayA->Server1 new=Client1->RelayE->Server1 time=4",
        "REROUTE client=Client2 server=Server2 failed_relay=RelayB "
        "old=Client2->RelayB->Server2 new=Client2->RelayF->Server2 time=4",
        "REROUTE client=Client3 server=Server3 failed_relay=RelayC "
        "old=Client3->RelayC->Server3 new=Client3->RelayG->Server3 time=4",
        "REROUTE client=Client4 server=Server4 failed_relay=RelayD "
        "old=Client4->RelayD->Server4 new=Client4->RelayH->Server4 time=4",
    ]
    restorations = [
        f"RECOVERY type=node client=Client{index} server=Server{index} "
        f"relay=Relay{chr(ord('A') + index - 1)} time={6 + (index - 1) * 2}"
        for index in range(1, 5)
    ]
    log_path.write_text(
        "ROUTE_CHANGE_COUNT total=8\n"
        + "\n".join(reroutes + restorations + records)
        + "\n",
        encoding="utf-8",
    )

    events = read_recovery_events(log_path, require_recovery=True)
    route_changes, average_recovery = read_simulation_events(
        log_path, require_recovery=True
    )

    assert [(event["client"], event["server"], event["failed_relay"])
            for event in events] == [
        ("Client1", "Server1", "RelayA"),
        ("Client2", "Server2", "RelayB"),
        ("Client3", "Server3", "RelayC"),
        ("Client4", "Server4", "RelayD"),
    ]
    assert events[0]["failed_path"] == "Client1 → RelayA → Server1"
    assert events[0]["rerouted_path"] == "Client1 → RelayE → Server1"
    assert events[3]["failed_path"] == "Client4 → RelayD → Server4"
    assert events[3]["rerouted_path"] == "Client4 → RelayH → Server4"
    assert [event["relay_restored_time_seconds"] for event in events] == [
        6.0, 8.0, 10.0, 12.0
    ]
    assert events[2]["recovery_time_seconds"] is None
    assert route_changes == 8
    assert average_recovery is None

    log_path.write_text(
        log_path.read_text(encoding="utf-8").replace(
            "new=Client1->RelayE->Server1 time=4",
            "new=Client1->RelayE->Server1 time=5",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="fail all four primary relays together"):
        read_recovery_events(log_path, require_recovery=True)


def test_failure_log_rejects_missing_pair_recovery_record(tmp_path):
    log_path = tmp_path / "failure-missing-pair.txt"
    log_path.write_text(
        "FAILURE_RECOVERY client=Client1 server=Server1 relay=RelayA seconds=0.01\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="all four client/server pairs"):
        read_recovery_events(log_path, require_recovery=True)


def test_repeat_analysis_writes_per_route_recovery_csv(tmp_path):
    xml_dir = tmp_path / "xml"
    log_dir = tmp_path / "logs"
    output_dir = tmp_path / "analysis"
    graph_dir = tmp_path / "graphs"
    xml_dir.mkdir()
    log_dir.mkdir()
    flow_stats = "".join(
        f'<Flow flowId="{index}" txPackets="10" rxPackets="9" txBytes="5120" '
        f'rxBytes="4608" delaySum="1s" />'
        for index in range(1, 5)
    )
    classifiers = "".join(
        f'<Flow flowId="{index}" sourceAddress="10.1.0.{index}" '
        f'destinationAddress="10.1.0.{index + 4}" protocol="17" '
        f'sourcePort="4915{index}" destinationPort="{4999 + index}" />'
        for index in range(1, 5)
    )
    xml = (
        "<FlowMonitor><FlowStats>" + flow_stats + "</FlowStats>"
        "<Ipv4FlowClassifier>" + classifiers + "</Ipv4FlowClassifier></FlowMonitor>"
    )
    for scenario in ("baseline", "failure"):
        (xml_dir / f"{scenario}-run-0001-seed-1.xml").write_text(xml, encoding="utf-8")
    (log_dir / "baseline-run-0001-seed-1.txt").write_text(
        "ROUTE_CHANGE_COUNT total=0\n", encoding="utf-8"
    )
    failure_events = "\n".join(
        f"FAILURE_RECOVERY client=Client{index} server=Server{index} "
        f"relay=Relay{chr(ord('A') + index - 1)} seconds=0.0{index}"
        for index in range(1, 5)
    )
    reroute_events = "\n".join(
        f"REROUTE client=Client{index} server=Server{index} "
        f"failed_relay=Relay{chr(ord('A') + index - 1)} "
        f"old=Client{index}->Relay{chr(ord('A') + index - 1)}->Server{index} "
        f"new=Client{index}->Relay{chr(ord('E') + index - 1)}->Server{index} "
        "time=4"
        for index in range(1, 5)
    )
    restoration_events = "\n".join(
        f"RECOVERY type=node client=Client{index} server=Server{index} "
        f"relay=Relay{chr(ord('A') + index - 1)} time={4 + index * 2}"
        for index in range(1, 5)
    )
    (log_dir / "failure-run-0001-seed-1.txt").write_text(
        f"ROUTE_CHANGE_COUNT total=8\n{reroute_events}\n"
        f"{restoration_events}\n{failure_events}\n",
        encoding="utf-8",
    )

    analyze_repeats(
        xml_dir,
        measurement_duration=16,
        output_dir=output_dir,
        graph_dir=graph_dir,
        log_dir=log_dir,
    )

    recovery_rows = (output_dir / "per_route_recovery.csv").read_text(encoding="utf-8")
    assert "Client1,Server1,RelayA,Client1 → RelayA → Server1," in recovery_rows
    assert "Client4,Server4,RelayD,Client4 → RelayD → Server4," in recovery_rows
    assert "Client4 → RelayH → Server4" in recovery_rows
    assert ",12.0," in recovery_rows


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
