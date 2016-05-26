from migen.fhdl.specials import Keep
from migen.flow.actor import *
from migen.actorlib.fifo import AsyncFIFO, SyncFIFO

from misoclib.soc import mem_decoder

from liteeth.common import *
from liteeth.phy import LiteEthPHY
from liteeth.phy.gmii import LiteEthGPHYMII
from liteeth.core import LiteEthUDPIPCore
from liteeth.frontend.etherbone import LiteEthEtherbone

from gateware.hdmi_in import HDMIIn
from gateware.hdmi_out import HDMIOut from gateware.encoder import Encoder
from gateware.encoder.dma import EncoderDMAReader
from gateware.encoder.buffer import EncoderBuffer
from gateware.streamer import UDPStreamer

from targets.common import *
from targets.atlys_base import BaseSoC
from targets.atlys_video import CreateVideoMixerSoC


class GetherboneSoC(BaseSoC):
    csr_peripherals = (
        "ethphy",
        "ethcore"
    )
    csr_map_update(BaseSoC.csr_map, csr_peripherals)

    def __init__(
            self,
            platform,
            mac_address=0x10e2d5000000,
            ip_address="192.168.1.42",
            **kwargs):
        BaseSoC.__init__(self, platform, **kwargs)

        # Ethernet PHY and UDP/IP stack
        self.submodules.ethphy = LiteEthPHYGMII(platform.request("eth_clocks"), platform.request("eth"))
        self.submodules.ethcore = LiteEthUDPIPCore(self.ethphy, mac_address, convert_ip(ip_address), self.clk_freq, with_icmp=False)

        # Etherbone bridge
        self.submodules.etherbone = LiteEthEtherbone(self.ethcore.udp, 20000)
        self.add_wb_master(self.etherbone.master.bus)

        self.specials += [
            Keep(self.ethphy.crg.cd_eth_rx.clk),
            Keep(self.ethphy.crg.cd_eth_tx.clk)
        ]
        platform.add_platform_command("""
NET "{eth_clocks_rx}" CLOCK_DEDICATED_ROUTE = FALSE;
NET "{eth_clocks_rx}" TNM_NET = "GRPeth_clocks_rx";
NET "{eth_rx_clk}" TNM_NET = "GRPeth_rx_clk";
NET "{eth_tx_clk}" TNM_NET = "GRPeth_tx_clk";
TIMESPEC "TSise_sucks1" = FROM "GRPeth_clocks_rx" TO "GRPsys_clk" TIG;
TIMESPEC "TSise_sucks2" = FROM "GRPsys_clk" TO "GRPeth_clocks_rx" TIG;
TIMESPEC "TSise_sucks3" = FROM "GRPeth_tx_clk" TO "GRPsys_clk" TIG;
TIMESPEC "TSise_sucks4" = FROM "GRPsys_clk" TO "GRPeth_tx_clk" TIG;
TIMESPEC "TSise_sucks5" = FROM "GRPeth_rx_clk" TO "GRPsys_clk" TIG;
TIMESPEC "TSise_sucks6" = FROM "GRPsys_clk" TO "GRPeth_rx_clk" TIG;
""", eth_clocks_rx=platform.lookup_request("eth_clocks").rx,
     eth_rx_clk=self.ethphy.crg.cd_eth_rx.clk,
     eth_tx_clk=self.ethphy.crg.cd_eth_tx.clk)


EtherVideoMixerSoC = CreateVideoMixerSoC(EtherboneSoC)


class HDMI2EthSoC(EtherVideoMixerSoC):
    csr_peripherals = (
        "raw_reader",
        "streamer",
    )
    csr_map_update(EtherVideoMixerSoC.csr_map, csr_peripherals)
    mem_map = {
        "encoder": 0x50000000,  # (shadow @0xd0000000)
    }
    mem_map.update(EtherVideoMixerSoC.mem_map)

    def __init__(self, platform, **kwargs):
        EtherVideoMixerSoC.__init__(self, platform, **kwargs)

        lasmim = self.sdram.crossbar.get_master()
        self.submodules.raw_reader = EncoderDMAReader(lasmim)
        self.submodules.encoder_cdc = RenameClockDomains(AsyncFIFO([("data", 128)], 4),
                                          {"write": "sys", "read": "encoder"})
        #self.submodules.encoder_buffer = RenameClockDomains(EncoderBuffer(), "encoder")
        #self.submodules.encoder_fifo = RenameClockDomains(SyncFIFO(EndpointDescription([("data", 16)], packetized=True), 16), "encoder")
        self.submodules.streamer = #Encoder(platform)
        encoder_port = self.ethcore.udp.crossbar.get_port(11112, 8)
        self.submodules.streamer = UDPStreamer(convert_ip("192.168.1.15"), 11112)

        self.comb += [
            platform.request("user_led", 0).eq(self.encoder_reader.source.stb),
            platform.request("user_led", 1).eq(self.encoder_reader.source.ack),
            Record.connect(self.encoder_reader.source, self.encoder_cdc.sink),
            Record.connect(self.encoder_cdc.source, self.encoder_buffer.sink),
            Record.connect(self.encoder_buffer.source, self.encoder_fifo.sink),
            Record.connect(self.encoder_fifo.source, self.encoder.sink),
            Record.connect(self.encoder.source, self.encoder_streamer.sink),
            Record.connect(self.encoder_streamer.source, encoder_port.sink)
        ]
        self.add_wb_slave(mem_decoder(self.mem_map["encoder"]), self.encoder.bus)
        self.add_memory_region("encoder", self.mem_map["encoder"]+self.shadow_base, 0x2000)


default_subtarget = HDMI2EthSoC
