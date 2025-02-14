#!/usr/bin/env python3

#
# This file is part of LitePCIe.
#
# Copyright (c) 2015-2020 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import os
import argparse

from migen import *

from litex_boards.platforms import kc705

from litex.soc.cores.clock import S7MMCM
from litex.soc.interconnect.csr import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *

from litepcie.phy.s7pciephy import S7PCIEPHY
from litepcie.core import LitePCIeEndpoint, LitePCIeMSI
from litepcie.frontend.dma import LitePCIeDMA
from litepcie.frontend.wishbone import LitePCIeWishboneBridge
from litepcie.software import generate_litepcie_software

# CRG ----------------------------------------------------------------------------------------------

class _CRG(Module):
    def __init__(self, platform, sys_clk_freq):
        self.clock_domains.cd_sys = ClockDomain()

        # # #

        # PLL
        self.submodules.pll = pll = S7MMCM(speedgrade=-2)
        pll.register_clkin(platform.request("clk200"), 200e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)

# LitePCIeSoC --------------------------------------------------------------------------------------

class LitePCIeSoC(SoCMini):
    configs = {
        # Gen2  data_width, sys_clk_freq
        "gen2:x1": (64,   int(125e6)),
        "gen2:x4": (128,  int(200e6)),
        "gen2:x8": (128,  int(200e6)),
    }
    def __init__(self, platform, speed="gen2", nlanes=4):
        data_width, sys_clk_freq = self.configs[speed + ":x{}".format(nlanes)]

        # SoCMini ----------------------------------------------------------------------------------
        SoCMini.__init__(self, platform, sys_clk_freq,
            csr_data_width = 32,
            ident          = "LitePCIe example design on KC705 ({}:x{})".format(speed, nlanes))

        # CRG --------------------------------------------------------------------------------------
        self.submodules.crg = _CRG(platform, sys_clk_freq)

        # UARTBone ---------------------------------------------------------------------------------
        self.add_uartbone()

        # PCIe -------------------------------------------------------------------------------------
        # PHY
        self.submodules.pcie_phy = S7PCIEPHY(platform, platform.request("pcie_x" + str(nlanes)),
            data_width = data_width,
            bar0_size  = 0x20000,
        )

        # Endpoint
        self.submodules.pcie_endpoint = LitePCIeEndpoint(self.pcie_phy,
            endianness           = "big",
            max_pending_requests = 8
        )

        # Wishbone bridge
        self.submodules.pcie_bridge = LitePCIeWishboneBridge(self.pcie_endpoint,
            base_address = self.mem_map["csr"])
        self.add_wb_master(self.pcie_bridge.wishbone)

        # DMA0
        self.submodules.pcie_dma0 = LitePCIeDMA(self.pcie_phy, self.pcie_endpoint,
            with_buffering = True, buffering_depth=1024,
            with_loopback  = True)

        # DMA1
        self.submodules.pcie_dma1 = LitePCIeDMA(self.pcie_phy, self.pcie_endpoint,
            with_buffering = True, buffering_depth=1024,
            with_loopback  = True)

        self.add_constant("DMA_CHANNELS", 2)

        # MSI
        self.submodules.pcie_msi = LitePCIeMSI()
        self.comb += self.pcie_msi.source.connect(self.pcie_phy.msi)
        self.interrupts = {
            "PCIE_DMA0_WRITER":    self.pcie_dma0.writer.irq,
            "PCIE_DMA0_READER":    self.pcie_dma0.reader.irq,
            "PCIE_DMA1_WRITER":    self.pcie_dma1.writer.irq,
            "PCIE_DMA1_READER":    self.pcie_dma1.reader.irq,
        }
        for i, (k, v) in enumerate(sorted(self.interrupts.items())):
            self.comb += self.pcie_msi.irqs[i].eq(v)
            self.add_constant(k + "_INTERRUPT", i)

# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LitePCIe SoC on KC705")
    parser.add_argument("--build",  action="store_true", help="Build bitstream")
    parser.add_argument("--driver", action="store_true", help="Generate LitePCIe driver")
    parser.add_argument("--load",   action="store_true", help="Load bitstream (to SRAM)")
    parser.add_argument("--nlanes", default=4,           help="PCIe lanes: 1, 4 (default) or 8")
    args = parser.parse_args()

    platform = kc705.Platform()
    soc      = LitePCIeSoC(platform, nlanes=int(args.nlanes))
    builder  = Builder(soc, output_dir="build/kc705", csr_csv="csr.csv")
    builder.build(build_name="kc705", run=args.build)

    if args.driver:
        generate_litepcie_software(soc, os.path.join(builder.output_dir, "driver"))

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(os.path.join(builder.gateware_dir, soc.build_name + ".bit"))

if __name__ == "__main__":
    main()
