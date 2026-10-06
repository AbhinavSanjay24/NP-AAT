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
    ns3.StringValue("1Mbps")
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
    ns3.StringValue("1Mbps")
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
