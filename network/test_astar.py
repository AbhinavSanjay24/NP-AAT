
import math

if __package__:
    from network.astar_routing import AStarRouter
else:
    from astar_routing import AStarRouter


def build_test_network():
    positions = {
        "Client1": (0, 0),
        "RelayA": (1, 1),
        "RelayB": (2, 1),
        "RelayC": (1, -1),
        "RelayD": (2, -1),
        "Server1": (3, 0),
    }

    router = AStarRouter(positions)

    # Primary route
    router.add_link("Client1", "RelayA")
    router.add_link("RelayA", "RelayB")
    router.add_link("RelayB", "Server1")

    # Backup route
    router.add_link("Client1", "RelayC")
    router.add_link("RelayC", "RelayD")
    router.add_link("RelayD", "Server1")

    return router


def build_multi_client_network():
    positions = {}
    for index in range(4):
        y = index * 3
        positions[f"Client{index + 1}"] = (0, y)
        positions[f"Relay{chr(ord('A') + index)}"] = (2, y)
        positions[f"Relay{chr(ord('E') + index)}"] = (4, y)
        positions[f"Server{index + 1}"] = (6, y)

    router = AStarRouter(positions)
    for index in range(4):
        client = f"Client{index + 1}"
        server = f"Server{index + 1}"
        primary = f"Relay{chr(ord('A') + index)}"
        backup = f"Relay{chr(ord('E') + index)}"
        router.add_link(client, primary, cost=1)
        router.add_link(primary, server, cost=1)
        router.add_link(client, backup, cost=2)
        router.add_link(backup, server, cost=2)

    return router


def test_four_client_server_pairs_reroute_independently():
    router = build_multi_client_network()
    initial_routes = {
        f"Client{index}": router.request_route(
            f"Client{index}", f"Server{index}"
        )
        for index in range(1, 5)
    }

    for index in range(1, 5):
        client = f"Client{index}"
        assert initial_routes[client][0] == [
            client,
            f"Relay{chr(ord('A') + index - 1)}",
            f"Server{index}",
        ]

    for index in range(2, 5):
        key = (f"Client{index}", f"Server{index}")
        assert router.active_routes[key] == initial_routes[key[0]]

    for index in range(1, 5):
        client = f"Client{index}"
        server = f"Server{index}"
        primary = f"Relay{chr(ord('A') + index - 1)}"
        backup = f"Relay{chr(ord('E') + index - 1)}"
        assert router.fail_link(client, primary)
        assert router.active_routes[(client, server)][0] == [client, backup, server]
        assert router.recover_link(client, primary)
        assert router.active_routes[(client, server)] == initial_routes[client]


def test_reroutes_after_link_failure():
    router = build_test_network()
    initial_path, initial_cost = router.request_route("Client1", "Server1")

    assert initial_path == ["Client1", "RelayA", "RelayB", "Server1"]
    expected_cost = (
        router.distance("Client1", "RelayA")
        + router.distance("RelayA", "RelayB")
        + router.distance("RelayB", "Server1")
    )
    assert math.isclose(initial_cost, expected_cost)

    assert router.fail_link("RelayA", "RelayB")
    new_path, new_cost = router.active_routes[("Client1", "Server1")]

    assert new_path == ["Client1", "RelayC", "RelayD", "Server1"]
    assert math.isclose(new_cost, initial_cost)
    assert router.recover_link("RelayA", "RelayB")
    assert router.active_routes[("Client1", "Server1")][0] == initial_path


def test_failed_node_reroutes_active_route_and_recovers():
    router = build_test_network()
    router.request_route("Client1", "Server1")

    assert router.fail_node("RelayA")
    assert router.active_routes[("Client1", "Server1")][0] == [
        "Client1", "RelayC", "RelayD", "Server1"
    ]

    assert router.fail_node("RelayC")
    path, cost = router.active_routes[("Client1", "Server1")]
    assert path == []
    assert math.isinf(cost)

    assert router.recover_node("RelayC")
    assert router.active_routes[("Client1", "Server1")][0] == [
        "Client1", "RelayC", "RelayD", "Server1"
    ]


def test_custom_costs_still_return_the_lowest_cost_path():
    router = AStarRouter({"start": (0, 0), "near": (0, 1), "goal": (10, 0)})
    router.add_link("start", "goal", cost=9.5)
    router.add_link("start", "near", cost=0.1)
    router.add_link("near", "goal", cost=0.1)

    path, cost = router.find_path("start", "goal")

    assert path == ["start", "near", "goal"]
    assert math.isclose(cost, 0.2)


def test_unreachable_destination_returns_empty_path_and_infinite_cost():
    router = AStarRouter({"start": (0, 0), "goal": (1, 0)})

    path, cost = router.find_path("start", "goal")

    assert path == []
    assert math.isinf(cost)


def test_equal_priority_entries_do_not_require_comparable_node_names():
    router = AStarRouter(
        {"start": (0, 0), 1: (1, 1), "relay": (1, -1), "goal": (2, 0)}
    )
    router.add_link("start", 1)
    router.add_link(1, "goal")
    router.add_link("start", "relay")
    router.add_link("relay", "goal")
    router.add_link("start", "goal", cost=4)

    path, _ = router.find_path("start", "goal")

    assert path in (["start", 1, "goal"], ["start", "relay", "goal"])
