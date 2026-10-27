#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/network-module.h"
#include "ns3/wifi-module.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <functional>
#include <iostream>
#include <limits>
#include <memory>
#include <queue>
#include <string>
#include <utility>
#include <vector>

using namespace ns3;

namespace
{

constexpr uint32_t CLIENT_COUNT = 4;
constexpr uint32_t SERVER_COUNT = 4;
constexpr uint32_t RELAY_COUNT = 8;
constexpr uint32_t NODE_COUNT = CLIENT_COUNT + SERVER_COUNT + RELAY_COUNT;
constexpr uint16_t FIRST_PORT = 5000;
constexpr double SIMULATION_END = 18.0;
constexpr double TRAFFIC_START = 1.0;
constexpr double TRAFFIC_STOP = 17.0;
constexpr double FAILURE_TIME = 4.0;
constexpr double FIRST_RELAY_RECOVERY_TIME = 6.0;
constexpr double RELAY_RECOVERY_INTERVAL = 2.0;

enum NodeIndex : uint32_t
{
    CLIENTS_START = 0,
    SERVERS_START = CLIENTS_START + CLIENT_COUNT,
    PRIMARY_RELAYS_START = SERVERS_START + SERVER_COUNT,
    BACKUP_RELAYS_START = PRIMARY_RELAYS_START + CLIENT_COUNT
};

struct Link
{
    uint32_t first;
    uint32_t second;
    double distance;
    double congestion;
    bool available = true;
};

struct Route
{
    std::vector<uint32_t> nodes;
    double cost = std::numeric_limits<double>::infinity();
};

class AStarGraph
{
  public:
    explicit AStarGraph(std::vector<Vector> positions)
        : m_positions(std::move(positions)), m_failedNodes(NODE_COUNT, false)
    {
    }

    void AddLink(uint32_t first, uint32_t second, double congestion)
    {
        const double distance = CalculateDistance(m_positions[first], m_positions[second]);
        m_links.push_back({first, second, distance, congestion, true});
    }

    void SetLinkAvailable(uint32_t first, uint32_t second, bool available)
    {
        for (auto& link : m_links)
        {
            if ((link.first == first && link.second == second) ||
                (link.first == second && link.second == first))
            {
                link.available = available;
                return;
            }
        }
        NS_ABORT_MSG("Cannot update a link that is not in the routing graph.");
    }

    void SetNodeAvailable(uint32_t node, bool available)
    {
        m_failedNodes[node] = !available;
    }

    Route FindPath(uint32_t start, uint32_t goal, uint32_t priority) const
    {
        Route result;
        if (m_failedNodes[start] || m_failedNodes[goal])
        {
            return result;
        }

        const double heuristicScale = GetHeuristicScale(priority);
        std::vector<double> best(NODE_COUNT, std::numeric_limits<double>::infinity());
        std::vector<int32_t> parent(NODE_COUNT, -1);
        std::vector<bool> closed(NODE_COUNT, false);
        using QueueEntry = std::pair<double, uint32_t>;
        std::priority_queue<QueueEntry, std::vector<QueueEntry>, std::greater<QueueEntry>> open;
        best[start] = 0;
        open.emplace(heuristicScale * CalculateDistance(m_positions[start], m_positions[goal]),
                     start);

        while (!open.empty())
        {
            const uint32_t current = open.top().second;
            open.pop();
            if (closed[current])
            {
                continue;
            }
            if (current == goal)
            {
                result.cost = best[goal];
                for (int32_t node = static_cast<int32_t>(goal); node >= 0;
                     node = parent[static_cast<uint32_t>(node)])
                {
                    result.nodes.push_back(static_cast<uint32_t>(node));
                    if (static_cast<uint32_t>(node) == start)
                    {
                        break;
                    }
                }
                std::reverse(result.nodes.begin(), result.nodes.end());
                return result;
            }

            closed[current] = true;
            for (const auto& link : m_links)
            {
                uint32_t neighbor;
                if (link.first == current)
                {
                    neighbor = link.second;
                }
                else if (link.second == current)
                {
                    neighbor = link.first;
                }
                else
                {
                    continue;
                }
                if (!link.available || m_failedNodes[neighbor] || closed[neighbor])
                {
                    continue;
                }

                const double edgeCost = link.distance + link.congestion / priority;
                const double candidate = best[current] + edgeCost;
                if (candidate < best[neighbor])
                {
                    best[neighbor] = candidate;
                    parent[neighbor] = static_cast<int32_t>(current);
                    const double estimate =
                        candidate + heuristicScale *
                                        CalculateDistance(m_positions[neighbor],
                                                          m_positions[goal]);
                    open.emplace(estimate, neighbor);
                }
            }
        }
        return result;
    }

  private:
    static double CalculateDistance(const Vector& first, const Vector& second)
    {
        return std::hypot(first.x - second.x, first.y - second.y);
    }

    double GetHeuristicScale(uint32_t priority) const
    {
        double scale = std::numeric_limits<double>::infinity();
        for (const auto& link : m_links)
        {
            if (!link.available || m_failedNodes[link.first] || m_failedNodes[link.second])
            {
                continue;
            }
            const double cost = link.distance + link.congestion / priority;
            if (link.distance > 0)
            {
                scale = std::min(scale, cost / link.distance);
            }
        }
        return std::isfinite(scale) ? scale : 0;
    }

    std::vector<Vector> m_positions;
    std::vector<Link> m_links;
    std::vector<bool> m_failedNodes;
};

class PriorityUdpSource : public Application
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId typeId =
            TypeId("ns3::PriorityUdpSource")
                .SetParent<Application>()
                .SetGroupName("Applications")
                .AddConstructor<PriorityUdpSource>();
        return typeId;
    }

    void Configure(Ipv4Address destination,
                   uint16_t port,
                   uint64_t bitRate,
                   uint32_t packetSize)
    {
        m_destination = destination;
        m_port = port;
        m_bitRate = bitRate;
        m_packetSize = packetSize;
    }

  private:
    void StartApplication() override
    {
        m_running = true;
        m_socket = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        m_socket->Connect(InetSocketAddress(m_destination, m_port));
        SendPacket();
    }

    void StopApplication() override
    {
        m_running = false;
        if (m_sendEvent.IsPending())
        {
            Simulator::Cancel(m_sendEvent);
        }
        if (m_socket)
        {
            m_socket->Close();
            m_socket = nullptr;
        }
    }

    void SendPacket()
    {
        if (!m_running)
        {
            return;
        }
        m_socket->Send(Create<Packet>(m_packetSize));
        const uint64_t intervalNs =
            static_cast<uint64_t>(m_packetSize) * 8ULL * 1000000000ULL / m_bitRate;
        m_sendEvent = Simulator::Schedule(NanoSeconds(intervalNs),
                                          &PriorityUdpSource::SendPacket,
                                          this);
    }

    Ptr<Socket> m_socket;
    EventId m_sendEvent;
    Ipv4Address m_destination;
    uint16_t m_port = 0;
    uint64_t m_bitRate = 0;
    uint32_t m_packetSize = 512;
    bool m_running = false;
};

NS_OBJECT_ENSURE_REGISTERED(PriorityUdpSource);

std::string NodeName(uint32_t node)
{
    if (node < SERVERS_START)
    {
        return "Client" + std::to_string(node + 1);
    }
    if (node < PRIMARY_RELAYS_START)
    {
        return "Server" + std::to_string(node - SERVERS_START + 1);
    }
    if (node < BACKUP_RELAYS_START)
    {
        return "Relay" + std::string(1, static_cast<char>('A' + node - PRIMARY_RELAYS_START));
    }
    return "Relay" + std::string(1, static_cast<char>('E' + node - BACKUP_RELAYS_START));
}

std::string FormatPath(const Route& route)
{
    if (route.nodes.empty())
    {
        return "UNREACHABLE";
    }
    std::string output;
    for (uint32_t node : route.nodes)
    {
        if (!output.empty())
        {
            output += "->";
        }
        output += NodeName(node);
    }
    return output;
}

void CheckRecovery(Ptr<PacketSink> sink,
                   uint64_t receivedBeforeFailure,
                   double failureTime,
                   const std::string& client,
                   const std::string& server,
                   const std::string& relay,
                   std::shared_ptr<bool> recovered)
{
    if (*recovered)
    {
        return;
    }
    if (sink->GetTotalRx() > receivedBeforeFailure)
    {
        *recovered = true;
        std::cout << "FAILURE_RECOVERY client=" << client
                  << " server=" << server
                  << " relay=" << relay
                  << " seconds=" << Simulator::Now().GetSeconds() - failureTime
                  << '\n';
        return;
    }
    if (Simulator::Now().GetSeconds() + 0.01 < SIMULATION_END)
    {
        Simulator::Schedule(MilliSeconds(10),
                            &CheckRecovery,
                            sink,
                            receivedBeforeFailure,
                            failureTime,
                            client,
                            server,
                            relay,
                            recovered);
    }
    else
    {
        std::cout << "FAILURE_RECOVERY client=" << client
                  << " server=" << server
                  << " relay=" << relay
                  << " seconds=unrecovered\n";
    }
}

} // namespace

int main(int argc, char* argv[])
{
    uint64_t runNumber = 1;
    uint32_t seed = 1;
    bool failureScenario = false;
    std::string failureType = "node";
    std::string outputPath = "scratch/astar-multiclient.xml";
    CommandLine commandLine(__FILE__);
    commandLine.AddValue("run", "NS-3 random-variable run number", runNumber);
    commandLine.AddValue("seed", "NS-3 random seed", seed);
    commandLine.AddValue("failure", "Enable the failure and recovery scenario", failureScenario);
    commandLine.AddValue("failureType", "Failure type: link or node", failureType);
    commandLine.AddValue("output", "FlowMonitor XML output path", outputPath);
    commandLine.Parse(argc, argv);
    if (runNumber == 0 || seed == 0 ||
        (failureType != "link" && failureType != "node"))
    {
        std::cerr << "Use positive --run/--seed values and --failureType=link|node.\n";
        return 2;
    }
    std::ifstream existingOutput(outputPath);
    if (existingOutput.good())
    {
        std::cerr << "Refusing to overwrite existing FlowMonitor XML: " << outputPath << '\n';
        return 3;
    }
    RngSeedManager::SetSeed(seed);
    RngSeedManager::SetRun(runNumber);

    std::vector<Vector> positions;
    positions.reserve(NODE_COUNT);
    for (uint32_t i = 0; i < CLIENT_COUNT; ++i)
    {
        const double row = i * 20.0;
        positions.emplace_back(0, row, 0);
    }
    for (uint32_t i = 0; i < SERVER_COUNT; ++i)
    {
        const double row = i * 20.0;
        positions.emplace_back(48, row, 0);
    }
    for (uint32_t i = 0; i < CLIENT_COUNT; ++i)
    {
        positions.emplace_back(20, i * 20.0, 0);
    }
    for (uint32_t i = 0; i < CLIENT_COUNT; ++i)
    {
        positions.emplace_back(28, i * 20.0, 0);
    }

    NodeContainer allNodes;
    allNodes.Create(NODE_COUNT);
    NodeContainer clients;
    NodeContainer servers;
    for (uint32_t i = 0; i < CLIENT_COUNT; ++i)
    {
        clients.Add(allNodes.Get(CLIENTS_START + i));
        servers.Add(allNodes.Get(SERVERS_START + i));
    }

    MobilityHelper mobility;
    Ptr<ListPositionAllocator> allocator = CreateObject<ListPositionAllocator>();
    for (const auto& position : positions)
    {
        allocator->Add(position);
    }
    mobility.SetPositionAllocator(allocator);
    mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobility.Install(allNodes);

    YansWifiChannelHelper channel;
    channel.AddPropagationLoss("ns3::RangePropagationLossModel",
                               "MaxRange",
                               DoubleValue(30.0));
    channel.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel");
    YansWifiPhyHelper phy;
    phy.SetChannel(channel.Create());
    WifiHelper wifi;
    wifi.SetStandard(WIFI_STANDARD_80211g);
    WifiMacHelper mac;
    mac.SetType("ns3::AdhocWifiMac");
    NetDeviceContainer devices = wifi.Install(phy, mac, allNodes);

    Ipv4StaticRoutingHelper staticRoutingHelper;
    InternetStackHelper internet;
    internet.SetRoutingHelper(staticRoutingHelper);
    internet.Install(allNodes);

    Ipv4AddressHelper address;
    address.SetBase("10.1.0.0", "255.255.255.0");
    Ipv4InterfaceContainer interfaces = address.Assign(devices);
    for (uint32_t node = 0; node < NODE_COUNT; ++node)
    {
        Ptr<Ipv4> ipv4 = allNodes.Get(node)->GetObject<Ipv4>();
        const int32_t interface = ipv4->GetInterfaceForDevice(devices.Get(node));
        if (node >= PRIMARY_RELAYS_START)
        {
            NS_ABORT_MSG_IF(interface < 0, "Wi-Fi interface missing from relay node.");
            ipv4->SetForwarding(static_cast<uint32_t>(interface), true);
        }
    }

    AStarGraph graph(positions);
    for (uint32_t i = 0; i < CLIENT_COUNT; ++i)
    {
        const uint32_t client = CLIENTS_START + i;
        const uint32_t server = SERVERS_START + i;
        const uint32_t primary = PRIMARY_RELAYS_START + i;
        const uint32_t backup = BACKUP_RELAYS_START + i;
        graph.AddLink(client, primary, 0.0);
        graph.AddLink(primary, server, 0.0);
        graph.AddLink(client, backup, 6.0);
        graph.AddLink(backup, server, 6.0);
        graph.AddLink(primary, backup, 2.0);
        if (i + 1 < CLIENT_COUNT)
        {
            graph.AddLink(primary, primary + 1, 3.0);
            graph.AddLink(backup, backup + 1, 3.0);
        }
    }

    const std::vector<uint32_t> priorities = {3, 2, 1, 3};
    std::vector<Route> activeRoutes(CLIENT_COUNT);
    uint32_t routeChangeCount = 0;
    auto installRoutes = [&]() {
        for (uint32_t node = 0; node < NODE_COUNT; ++node)
        {
            Ptr<Ipv4StaticRouting> routing =
                staticRoutingHelper.GetStaticRouting(allNodes.Get(node)->GetObject<Ipv4>());
            for (int32_t route = static_cast<int32_t>(routing->GetNRoutes()) - 1;
                 route >= 0;
                 --route)
            {
                const auto entry = routing->GetRoute(static_cast<uint32_t>(route));
                for (uint32_t server = 0; server < SERVER_COUNT; ++server)
                {
                    if (entry.GetDest() == interfaces.GetAddress(SERVERS_START + server) &&
                        entry.GetDestNetworkMask() == Ipv4Mask("255.255.255.255"))
                    {
                        routing->RemoveRoute(static_cast<uint32_t>(route));
                        break;
                    }
                }
            }
        }

        for (uint32_t clientIndex = 0; clientIndex < CLIENT_COUNT; ++clientIndex)
        {
            const uint32_t client = CLIENTS_START + clientIndex;
            const uint32_t server = SERVERS_START + clientIndex;
            const Route oldRoute = activeRoutes[clientIndex];
            const Route newRoute = graph.FindPath(client, server, priorities[clientIndex]);
            activeRoutes[clientIndex] = newRoute;
            if (oldRoute.nodes != newRoute.nodes)
            {
                if (!oldRoute.nodes.empty())
                {
                    ++routeChangeCount;
                }
                std::cout << "ROUTE_CHANGE time=" << Simulator::Now().GetSeconds()
                          << " client=" << NodeName(client)
                          << " priority=" << priorities[clientIndex]
                          << " old=" << FormatPath(oldRoute)
                          << " new=" << FormatPath(newRoute)
                          << " cost=" << newRoute.cost << '\n';
            }

            if (newRoute.nodes.empty())
            {
                continue;
            }
            for (size_t hop = 0; hop + 1 < newRoute.nodes.size(); ++hop)
            {
                const uint32_t current = newRoute.nodes[hop];
                const uint32_t next = newRoute.nodes[hop + 1];
                Ptr<Ipv4> ipv4 = allNodes.Get(current)->GetObject<Ipv4>();
                const int32_t interface = ipv4->GetInterfaceForDevice(devices.Get(current));
                NS_ABORT_MSG_IF(interface < 0, "Wi-Fi interface missing from route node.");
                Ptr<Ipv4StaticRouting> routing =
                    staticRoutingHelper.GetStaticRouting(ipv4);
                routing->AddHostRouteTo(interfaces.GetAddress(server),
                                        interfaces.GetAddress(next),
                                        static_cast<uint32_t>(interface));
            }
        }
    };
    installRoutes();
    std::cout << "TOPOLOGY clients=4 servers=4 relays=8 links=26 relay_mesh=ladder "
              << "failure_schedule=staggered failure_type=" << failureType << '\n';
    std::cout << "ROUTE_CHANGE_COUNT total=0\n";

    std::vector<Ptr<PacketSink>> sinks;
    for (uint32_t i = 0; i < SERVER_COUNT; ++i)
    {
        PacketSinkHelper sinkHelper(
            "ns3::UdpSocketFactory",
            InetSocketAddress(Ipv4Address::GetAny(), FIRST_PORT + i));
        ApplicationContainer sinkApp = sinkHelper.Install(servers.Get(i));
        sinkApp.Start(Seconds(0));
        sinkApp.Stop(Seconds(SIMULATION_END));
        sinks.push_back(DynamicCast<PacketSink>(sinkApp.Get(0)));

        const uint32_t priority = priorities[i];
        const uint64_t bitRate = priority == 3 ? 2000000 : priority == 2 ? 1000000 : 512000;
        Ptr<PriorityUdpSource> source = CreateObject<PriorityUdpSource>();
        source->Configure(interfaces.GetAddress(SERVERS_START + i),
                          FIRST_PORT + i,
                          bitRate,
                          512);
        clients.Get(i)->AddApplication(source);
        source->SetStartTime(Seconds(TRAFFIC_START));
        source->SetStopTime(Seconds(TRAFFIC_STOP));
        std::cout << "TRAFFIC client=" << NodeName(CLIENTS_START + i)
                  << " server=" << NodeName(SERVERS_START + i)
                  << " priority=" << priority << " rate_bps=" << bitRate << '\n';
    }

    if (failureScenario)
    {
        Simulator::Schedule(Seconds(FAILURE_TIME), [&, failureType]() {
            std::vector<uint64_t> receivedBeforeFailure(CLIENT_COUNT);
            std::vector<std::string> oldPaths(CLIENT_COUNT);
            std::vector<std::string> clientsNames(CLIENT_COUNT);
            std::vector<std::string> serversNames(CLIENT_COUNT);
            std::vector<std::string> relayNames(CLIENT_COUNT);

            for (uint32_t pair = 0; pair < CLIENT_COUNT; ++pair)
            {
                const uint32_t client = CLIENTS_START + pair;
                const uint32_t server = SERVERS_START + pair;
                const uint32_t primary = PRIMARY_RELAYS_START + pair;
                Ptr<Ipv4> primaryIpv4 = allNodes.Get(primary)->GetObject<Ipv4>();
                const int32_t primaryInterface =
                    primaryIpv4->GetInterfaceForDevice(devices.Get(primary));
                NS_ABORT_MSG_IF(primaryInterface < 0,
                                "Wi-Fi interface missing from primary relay.");

                oldPaths[pair] = FormatPath(activeRoutes[pair]);
                receivedBeforeFailure[pair] = sinks[pair]->GetTotalRx();
                clientsNames[pair] = NodeName(client);
                serversNames[pair] = NodeName(server);
                relayNames[pair] = NodeName(primary);
                if (failureType == "link")
                {
                    graph.SetLinkAvailable(client, primary, false);
                    std::cout << "FAILURE type=link client=" << clientsNames[pair]
                              << " server=" << serversNames[pair]
                              << " relay=" << relayNames[pair]
                              << " link=" << clientsNames[pair] << "-"
                              << relayNames[pair]
                              << " time=" << Simulator::Now().GetSeconds() << '\n';
                }
                else
                {
                    graph.SetNodeAvailable(primary, false);
                    primaryIpv4->SetDown(static_cast<uint32_t>(primaryInterface));
                    std::cout << "FAILURE type=node client=" << clientsNames[pair]
                              << " server=" << serversNames[pair]
                              << " relay=" << relayNames[pair]
                              << " time=" << Simulator::Now().GetSeconds() << '\n';
                }
            }

            installRoutes();
            for (uint32_t pair = 0; pair < CLIENT_COUNT; ++pair)
            {
                std::cout << "REROUTE client=" << clientsNames[pair]
                          << " server=" << serversNames[pair]
                          << " failed_relay=" << relayNames[pair]
                          << " old=" << oldPaths[pair]
                          << " new=" << FormatPath(activeRoutes[pair])
                          << " time=" << Simulator::Now().GetSeconds() << '\n';
                auto recovered = std::make_shared<bool>(false);
                Simulator::Schedule(MilliSeconds(10),
                                    &CheckRecovery,
                                    sinks[pair],
                                    receivedBeforeFailure[pair],
                                    FAILURE_TIME,
                                    clientsNames[pair],
                                    serversNames[pair],
                                    relayNames[pair],
                                    recovered);
            }
        });

        for (uint32_t pair = 0; pair < CLIENT_COUNT; ++pair)
        {
            const uint32_t client = CLIENTS_START + pair;
            const uint32_t server = SERVERS_START + pair;
            const uint32_t primary = PRIMARY_RELAYS_START + pair;
            Ptr<Ipv4> primaryIpv4 = allNodes.Get(primary)->GetObject<Ipv4>();
            const int32_t primaryInterface =
                primaryIpv4->GetInterfaceForDevice(devices.Get(primary));
            NS_ABORT_MSG_IF(primaryInterface < 0,
                            "Wi-Fi interface missing from primary relay.");
            const std::string clientName = NodeName(client);
            const std::string serverName = NodeName(server);
            const std::string relayName = NodeName(primary);
            const double recoveryTime =
                FIRST_RELAY_RECOVERY_TIME + pair * RELAY_RECOVERY_INTERVAL;

            Simulator::Schedule(Seconds(recoveryTime),
                                [&, client, primary, primaryIpv4,
                                 primaryInterface, clientName, serverName, relayName,
                                 failureType]() {
                if (failureType == "link")
                {
                    graph.SetLinkAvailable(client, primary, true);
                }
                else
                {
                    graph.SetNodeAvailable(primary, true);
                    primaryIpv4->SetUp(static_cast<uint32_t>(primaryInterface));
                }
                std::cout << "RECOVERY type=" << failureType
                          << " client=" << clientName
                          << " server=" << serverName
                          << " relay=" << relayName
                          << " time=" << Simulator::Now().GetSeconds() << '\n';
                installRoutes();
            });
        }
    }

    FlowMonitorHelper flowHelper;
    Ptr<FlowMonitor> monitor = flowHelper.InstallAll();
    std::cout << "RUN_METADATA scenario=" << (failureScenario ? "failure" : "baseline")
              << " seed=" << seed << " run=" << runNumber << '\n';
    Simulator::Stop(Seconds(SIMULATION_END));
    Simulator::Run();

    monitor->CheckForLostPackets();
    monitor->SerializeToXmlFile(outputPath, true, true);
    std::cout << "ROUTE_CHANGE_COUNT total=" << routeChangeCount << '\n';
    for (uint32_t pair = 0; pair < CLIENT_COUNT; ++pair)
    {
        std::cout << "CLIENT_RX client=" << NodeName(CLIENTS_START + pair)
                  << " server=" << NodeName(SERVERS_START + pair)
                  << " bytes=" << sinks[pair]->GetTotalRx() << '\n';
    }
    std::cout << "FlowMonitor results saved to " << outputPath << '\n';
    Simulator::Destroy();
    return 0;
}
