from targets.common import *
from targets.atlys_hdmi2usb import *

from misoclib.com.uart.phy import UARTPHY
from misoclib.com import uart
from misoclib.tools.wishbone import WishboneStreamingBridge

from litescope.common import *
from litescope.core.port import LiteScopeTerm
from litescope.frontend.logic_analyzer import LiteScopeLogicAnalyzer


class UARTVirtualPhy:
    def __init__(self):
        self.sink = Sink([("data", 8)])
        self.source = Source([("data", 8)])

# This SoC was used to debug EDID transactions between video sources and the board.
# To use it:
#  - build this SoC & load it
#  - wait for HDMI2USB prompt
#  - change state of SW0
#  - go to test/edid_debug
#  - do make.py --port <your_uart_port> test_regs and verify you are able to get sysid/revision/frequency
#  - do make.py --port <your_uart_port> test_la
#  - connect your video source, this will trigger litescope capture and upload data.
#  - you now have a .vcd you can analyze in GTKwave or others vcd viewers!

class EDIDDebugSoC(VideomixerSoC):
    csr_peripherals = (
        "logic_analyzer",
    )
    csr_map_update(VideomixerSoC.csr_map, csr_peripherals)

    def __init__(self, platform, with_uart=False, **kwargs):
        VideomixerSoC.__init__(self, platform, with_uart=with_uart, **kwargs)

        uart_sel = platform.request("user_dip", 0)
        self.comb += platform.request("user_led", 0).eq(uart_sel)

        self.submodules.uart_phy = UARTPHY(platform.request("serial"), self.clk_freq, 115200)
        uart_phys = {
            "cpu": UARTVirtualPhy(),
            "bridge": UARTVirtualPhy()
        }
        self.comb += [
            If(uart_sel,
                Record.connect(self.uart_phy.source, uart_phys["bridge"].source),
                Record.connect(uart_phys["bridge"].sink, self.uart_phy.sink),
                uart_phys["cpu"].source.ack.eq(1) # avoid stalling cpu
            ).Else(
                Record.connect(self.uart_phy.source, uart_phys["cpu"].source),
                Record.connect(uart_phys["cpu"].sink, self.uart_phy.sink),
                uart_phys["bridge"].source.ack.eq(1) # avoid stalling bridge
            )
        ]

        # UART cpu
        self.submodules.uart = uart.UART(uart_phys["cpu"])

        # UART bridge
        self.submodules.bridge = WishboneStreamingBridge(uart_phys["bridge"], self.clk_freq)
        self.add_wb_master(self.bridge.wishbone)

        # LiteScope on EDID lines and fsm
        self.hdmi_in0_edid_fsm_state = Signal(4)
        self.debug = (
            self.hdmi_in0.edid.scl,
            self.hdmi_in0.edid.sda_i,
            self.hdmi_in0.edid.sda_o,
            self.hdmi_in0.edid.sda_oe,
            self.hdmi_in0.edid.counter,
            self.hdmi_in0.edid.din,
            self.hdmi_in0_edid_fsm_state
        )
        self.submodules.logic_analyzer = LiteScopeLogicAnalyzer(self.debug, 32*1024, with_subsampler=True)
        self.logic_analyzer.trigger.add_port(LiteScopeTerm(self.logic_analyzer.dw))

    def do_finalize(self):
        VideomixerSoC.do_finalize(self)
        self.comb += [
            self.hdmi_in0_edid_fsm_state.eq(self.hdmi_in0.edid.fsm.state)
        ]

    def do_exit(self, vns):
        self.logic_analyzer.export(vns, "../../test/edid_debug/logic_analyzer.csv") # XXX

default_subtarget = EDIDDebugSoC
