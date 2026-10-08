import cppyy

# ---------------------------------------------------------
# NS-3 library and header paths
# ---------------------------------------------------------
cppyy.add_library_path("./build/lib")
cppyy.add_include_path("./build/include")

# Load required NS-3 libraries
for module in [
    "core",
    "network",
    "internet",
    "wifi",
    "mobility",
    "applications",
]:
    cppyy.load_library(f"./build/lib/libns3.45-{module}-default.so")

# Load required NS-3 headers
for module in [
    "core",
    "network",
    "internet",
    "wifi",
    "mobility",
    "applications",
]:
    cppyy.include(f"ns3/{module}-module.h")


# ---------------------------------------------------------
# NS-3 namespace
# ---------------------------------------------------------
ns3 = cppyy.gbl.ns3


# ---------------------------------------------------------
# Network configuration
# ---------------------------------------------------------
NUM_CLIENTS = 2
NUM_SERVERS = 2

print("Creating Wi-Fi topology...")
# ---------------------------------------------------------
# Traffic Priority Configuration - Member 3
# ---------------------------------------------------------

HIGH_PRIORITY = 3
MEDIUM_PRIORITY = 2
LOW_PRIORITY = 1

# Assign priority to each client's traffic
client_priorities = {
    0: HIGH_PRIORITY,     # Client 1 - High priority
    1: LOW_PRIORITY      # Client 2 - Low priority
}

print("Traffic priorities configured:")
for client_id, priority in client_priorities.items():
    print(f"Client {client_id + 1}: Priority {priority}")
# ---------------------------------------------------------
# Failure and Rerouting Configuration - Member 3
# ---------------------------------------------------------

FAILURE_TIME = 5.0
RECOVERY_TIME = 6.0

# Nodes/links that can be simulated as failed
failed_nodes = set()

# Stores the currently selected route for each client
active_routes = {}



def detect_failure(node_id):
    """
    Check whether a node is currently failed.
    """
    if node_id in failed_nodes:
        print(f"[FAILURE DETECTED] Node {node_id} is unavailable.")
        return True

    return False

def trigger_node_failure(node_id):
    """
    Simulate failure of a network node.
    """
    failed_nodes.add(node_id)

    print(
        f"[FAILURE] Node {node_id} has failed."
    )

    if detect_failure(node_id):
        print(
            f"[FAILURE DETECTED] Rerouting required for Node {node_id}."
        )

def recover_node(node_id):
    """
    Recover a previously failed network node.
    """
    if node_id in failed_nodes:
        failed_nodes.remove(node_id)

        print(
            f"[RECOVERY] Node {node_id} is available again."
        )
    else:
        print(
            f"[RECOVERY] Node {node_id} was not marked as failed."
        )


def calculate_route_score(route_length, congestion, priority):
    """
    Calculate a score for an available route.

    Higher score = better route.
    """

    priority_weight = priority * 10

    score = priority_weight - route_length - congestion

    return score        



def choose_best_route(routes, priority):
    """
    Select the best available route based on traffic priority.
    """

    if not routes:
        print("[REROUTING] No available routes.")
        return None

    best_route = None
    best_score = float("-inf")

    for route in routes:

        score = calculate_route_score(
            route["length"],
            route["congestion"],
            priority
        )

        print(
            f"Route {route['path']} -> "
            f"Score: {score}"
        )

        if score > best_score:
            best_score = score
            best_route = route

    print(
        f"[REROUTING] Selected route: "
        f"{best_route['path']}"
    )

    return best_route

def select_priority_route(routes, priority):
    """
    Select an alternative route based on traffic priority.

    Higher-priority traffic gets the best available route.
    """

    if not routes:
        print("[REROUTING] No alternative routes available.")
        return None

    # Routes are assumed to be ordered from best to worst.
    if priority == HIGH_PRIORITY:
        selected_route = routes[0]

    elif priority == MEDIUM_PRIORITY:
        selected_route = routes[min(1, len(routes) - 1)]

    else:
        selected_route = routes[-1]

    print(
        f"[REROUTING] Priority {priority} selected route: "
        f"{selected_route}"
    )

    return selected_route

# ---------------------------------------------------------
# Create client and server nodes
# ---------------------------------------------------------
clients = ns3.NodeContainer()
clients.Create(NUM_CLIENTS)

servers = ns3.NodeContainer()
servers.Create(NUM_SERVERS)

# Combine all nodes
all_nodes = ns3.NodeContainer()
all_nodes.Add(clients)
all_nodes.Add(servers)

print(f"Clients created: {clients.GetN()}")
print(f"Servers created: {servers.GetN()}")
print(f"Total nodes: {all_nodes.GetN()}")


# ---------------------------------------------------------
# Wi-Fi configuration
# ---------------------------------------------------------

# Create Wi-Fi PHY and channel
wifi_phy = ns3.YansWifiPhyHelper()
wifi_channel = ns3.YansWifiChannelHelper.Default()

wifi_phy.SetChannel(wifi_channel.Create())

# Create Wi-Fi MAC
wifi_mac = ns3.WifiMacHelper()

# Create Wi-Fi helper
wifi = ns3.WifiHelper()

# Configure Wi-Fi standard
wifi.SetStandard(ns3.WIFI_STANDARD_80211g)

# Install Wi-Fi devices on all nodes
wifi_devices = wifi.Install(wifi_phy, wifi_mac, all_nodes)

print(f"Wi-Fi devices installed: {wifi_devices.GetN()}")

# ---------------------------------------------------------
# Node positions
# ---------------------------------------------------------

mobility = ns3.MobilityHelper()

position_alloc = ns3.ListPositionAllocator()

# Client 1
position_alloc.Add(ns3.Vector(0.0, 0.0, 0.0))

# Client 2
position_alloc.Add(ns3.Vector(0.0, 20.0, 0.0))

# Server 1
position_alloc.Add(ns3.Vector(50.0, 0.0, 0.0))

# Server 2
position_alloc.Add(ns3.Vector(50.0, 20.0, 0.0))

mobility.SetPositionAllocator(position_alloc)

mobility.SetMobilityModel(
    "ns3::ConstantPositionMobilityModel"
)

mobility.Install(all_nodes)

print("Node positions configured successfully!")

# ---------------------------------------------------------
# Internet stack and IP addressing
# ---------------------------------------------------------

internet = ns3.InternetStackHelper()
internet.Install(all_nodes)

# Assign IPv4 addresses
ipv4 = ns3.Ipv4AddressHelper()
ipv4.SetBase(
    ns3.Ipv4Address("10.1.1.0"),
    ns3.Ipv4Mask("255.255.255.0")
)

interfaces = ipv4.Assign(wifi_devices)

print("IP addresses assigned successfully!")

# Display IP addresses
for i in range(all_nodes.GetN()):
    address = interfaces.GetAddress(i)
    print(f"Node {i} IP address: {address}")

# ---------------------------------------------------------
# UDP client-server applications
# ---------------------------------------------------------

# UDP port numbers
SERVER1_PORT = 5000
SERVER2_PORT = 5001

# Create UDP packet sinks on the servers
server1_sink = ns3.PacketSinkHelper(
    "ns3::UdpSocketFactory",
    ns3.InetSocketAddress(
        interfaces.GetAddress(2),
        SERVER1_PORT
    ).ConvertTo()
)

server2_sink = ns3.PacketSinkHelper(
    "ns3::UdpSocketFactory",
    ns3.InetSocketAddress(
        interfaces.GetAddress(3),
        SERVER2_PORT
    ).ConvertTo()
)

# Install sinks
server1_apps = server1_sink.Install(servers.Get(0))
server2_apps = server2_sink.Install(servers.Get(1))

server1_apps.Start(ns3.Seconds(0.0))
server1_apps.Stop(ns3.Seconds(10.0))

server2_apps.Start(ns3.Seconds(0.0))
server2_apps.Stop(ns3.Seconds(10.0))


# ---------------------------------------------------------
# UDP traffic from clients to servers
# ---------------------------------------------------------
# Get priority assigned to each client
client1_priority = client_priorities[0]
client2_priority = client_priorities[1]

print(
    f"Client 1 traffic priority: {client1_priority} (HIGH)"
)

print(
    f"Client 2 traffic priority: {client2_priority} (LOW)"
)

# Client 1 -> Server 1
client1 = ns3.OnOffHelper(
    "ns3::UdpSocketFactory",
    ns3.InetSocketAddress(
        interfaces.GetAddress(2),
        SERVER1_PORT
    ).ConvertTo()
)

client1.SetAttribute(
    "DataRate",
    ns3.StringValue("2Mbps" if client1_priority == HIGH_PRIORITY else "1Mbps")
)

client1.SetAttribute(
    "PacketSize",
    ns3.UintegerValue(512)
)

client1_apps = client1.Install(clients.Get(0))

client1_apps.Start(ns3.Seconds(1.0))
client1_apps.Stop(ns3.Seconds(9.0))


# Client 2 -> Server 2
client2 = ns3.OnOffHelper(
    "ns3::UdpSocketFactory",
    ns3.InetSocketAddress(
        interfaces.GetAddress(3),
        SERVER2_PORT
    ).ConvertTo()
)

client2.SetAttribute(
    "DataRate",
    ns3.StringValue("1Mbps" if client2_priority == LOW_PRIORITY else "2Mbps")
)

client2.SetAttribute(
    "PacketSize",
    ns3.UintegerValue(512)
)

client2_apps = client2.Install(clients.Get(1))

client2_apps.Start(ns3.Seconds(1.0))
client2_apps.Stop(ns3.Seconds(9.0))


print("UDP applications configured successfully!")

print("Wi-Fi configuration successful!")

# ---------------------------------------------------------
# Run simulation
# ---------------------------------------------------------

print("Starting simulation...")

ns3.Simulator.Stop(ns3.Seconds(10.0))
ns3.Simulator.Run()

# ---------------------------------------------------------
# Packet reception statistics
# ---------------------------------------------------------

server1_received = server1_apps.Get(0).GetTotalRx()
server2_received = server2_apps.Get(0).GetTotalRx()

print("Simulation completed successfully!")
print(f"Server 1 received: {server1_received} bytes")
print(f"Server 2 received: {server2_received} bytes")

ns3.Simulator.Destroy()
