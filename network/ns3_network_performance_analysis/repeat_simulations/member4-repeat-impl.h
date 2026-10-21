#ifndef MEMBER4_REPEAT_IMPL_H
#define MEMBER4_REPEAT_IMPL_H

#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/wifi-module.h"
#include "ns3/mobility-module.h"
#include "ns3/applications-module.h"
#include "ns3/flow-monitor-module.h"

#include <fstream>
#include <iostream>
#include <string>

using namespace ns3;

int runSimulation(int argc, char* argv[], bool failureScenario)
{
    uint64_t runNumber = 1;
    uint32_t seed = 1;
    CommandLine commandLine(__FILE__);
    commandLine.AddValue("run", "NS-3 random-variable run number", runNumber);
    commandLine.AddValue("seed", "NS-3 random seed", seed);
    commandLine.Parse(argc, argv);

    if (runNumber == 0 || seed == 0)
    {
        std::cerr << "Both --run and --seed must be positive integers.\n";
        return 2;
    }

    RngSeedManager::SetSeed(seed);
    RngSeedManager::SetRun(runNumber);

    const std::string scenario = failureScenario ? "failure" : "baseline";
    const std::string outputPath =
        "scratch/member4-" + scenario + "-run-" +
        std::to_string(runNumber) + "-seed-" + std::to_string(seed) + ".xml";
    std::ifstream existingOutput(outputPath);
    if (existingOutput.good())
    {
        std::cerr << "Refusing to overwrite existing FlowMonitor XML: "
                  << outputPath << '\n';
        return 3;
    }

    std::cout << "RUN_METADATA scenario=" << scenario
              << " seed=" << seed << " run=" << runNumber << '\n';

    NodeContainer clients;
    clients.Create(2);

    NodeContainer servers;
    servers.Create(2);

    NodeContainer allNodes;
    allNodes.Add(clients);
    allNodes.Add(servers);

    YansWifiChannelHelper channel = YansWifiChannelHelper::Default();
    YansWifiPhyHelper phy;
    phy.SetChannel(channel.Create());

    WifiHelper wifi;
    wifi.SetStandard(WIFI_STANDARD_80211g);

    WifiMacHelper mac;
    mac.SetType("ns3::AdhocWifiMac");

    NetDeviceContainer devices = wifi.Install(phy, mac, allNodes);

    if (failureScenario)
    {
        Ptr<WifiNetDevice> failedDevice =
            DynamicCast<WifiNetDevice>(devices.Get(2));
        Simulator::Schedule(Seconds(5), [failedDevice]() {
            failedDevice->GetPhy()->SetSleepMode();
            std::cout << "Wi-Fi receiver sleeping at 5 seconds" << std::endl;
        });
        Simulator::Schedule(Seconds(7), [failedDevice]() {
            failedDevice->GetPhy()->ResumeFromSleep();
            std::cout << "Wi-Fi receiver resumed at 7 seconds" << std::endl;
        });
    }

    MobilityHelper mobility;
    Ptr<ListPositionAllocator> positions =
        CreateObject<ListPositionAllocator>();
    positions->Add(Vector(0, 0, 0));
    positions->Add(Vector(0, 20, 0));
    positions->Add(Vector(50, 0, 0));
    positions->Add(Vector(50, 20, 0));
    mobility.SetPositionAllocator(positions);
    mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobility.Install(allNodes);

    InternetStackHelper internet;
    internet.Install(allNodes);

    Ipv4AddressHelper address;
    address.SetBase("10.1.1.0", "255.255.255.0");
    Ipv4InterfaceContainer interfaces = address.Assign(devices);

    PacketSinkHelper sink1(
        "ns3::UdpSocketFactory",
        InetSocketAddress(Ipv4Address::GetAny(), 5000));
    ApplicationContainer sinkApp1 = sink1.Install(servers.Get(0));
    sinkApp1.Start(Seconds(0));
    sinkApp1.Stop(Seconds(10));

    PacketSinkHelper sink2(
        "ns3::UdpSocketFactory",
        InetSocketAddress(Ipv4Address::GetAny(), 5001));
    ApplicationContainer sinkApp2 = sink2.Install(servers.Get(1));
    sinkApp2.Start(Seconds(0));
    sinkApp2.Stop(Seconds(10));

    OnOffHelper source1(
        "ns3::UdpSocketFactory",
        Address(InetSocketAddress(interfaces.GetAddress(2), 5000)));
    source1.SetAttribute("DataRate", StringValue("2Mbps"));
    source1.SetAttribute("PacketSize", UintegerValue(512));
    source1.SetAttribute("OnTime",
        StringValue("ns3::ConstantRandomVariable[Constant=1]"));
    source1.SetAttribute("OffTime",
        StringValue("ns3::ConstantRandomVariable[Constant=0]"));
    ApplicationContainer sourceApp1 = source1.Install(clients.Get(0));
    sourceApp1.Start(Seconds(1));
    sourceApp1.Stop(Seconds(9));

    OnOffHelper source2(
        "ns3::UdpSocketFactory",
        Address(InetSocketAddress(interfaces.GetAddress(3), 5001)));
    source2.SetAttribute("DataRate", StringValue("1Mbps"));
    source2.SetAttribute("PacketSize", UintegerValue(512));
    source2.SetAttribute("OnTime",
        StringValue("ns3::ConstantRandomVariable[Constant=1]"));
    source2.SetAttribute("OffTime",
        StringValue("ns3::ConstantRandomVariable[Constant=0]"));
    ApplicationContainer sourceApp2 = source2.Install(clients.Get(1));
    sourceApp2.Start(Seconds(1));
    sourceApp2.Stop(Seconds(9));

    FlowMonitorHelper flowHelper;
    Ptr<FlowMonitor> monitor = flowHelper.InstallAll();

    Simulator::Stop(Seconds(10));
    Simulator::Run();

    monitor->CheckForLostPackets();
    monitor->SerializeToXmlFile(outputPath, true, true);
    std::cout << "FlowMonitor results saved to " << outputPath << '\n';

    Simulator::Destroy();
    return 0;
}

#endif // MEMBER4_REPEAT_IMPL_H