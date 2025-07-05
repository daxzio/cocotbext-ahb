#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File              : ahb_monitor.py
# License           : MIT license <Check LICENSE>
# Author            : Anderson I. da Silva (aignacio) <anderson@aignacio.com>
# Date              : 27.10.2023
# Last Modified Date: 01.10.2024
import cocotb
import logging
import random
import copy
import struct
import datetime

from .ahb_types import AHBTrans, AHBWrite, AHBSize, AHBResp, AHBBurst
from .ahb_bus import AHBBus
from .version import __version__

from cocotb.triggers import RisingEdge, FallingEdge
from cocotb.handle import SimHandleBase
from cocotb.types import LogicArray
from cocotb_bus.monitors import Monitor
from typing import Optional, Union, Generator, List, Any
from .memory import Memory


class AHBMonitor(Monitor):
    def __init__(
        self, bus: AHBBus, clock: str, reset: str, prefix: str = None, **kwargs: Any
    ) -> None:
        self.name = prefix if prefix is not None else bus.entity._name + "_ahb_monitor"
        self.clk = clock
        self.rst = reset
        self.bus = bus

        # Burst tracking state
        self.burst_state = {
            "active": False,
            "type": AHBBurst.SINGLE,
            "size": AHBSize.WORD,
            "start_addr": 0,
            "current_addr": 0,
            "beat_count": 0,
            "expected_beats": 0,
            "write_mode": False,
            "transactions": []
        }

        # We extend from Monitor base class because we don't need to recreate
        # the internal bus property as it already exists from AHBBus
        Monitor.__init__(self, **kwargs)

        self.log.info(f"AHB ({self.name}) Monitor")
        self.log.info("cocotbext-ahb version %s", __version__)
        self.log.info(
            f"Copyright (c) {datetime.datetime.now().year} Anderson Ignacio da Silva"
        )
        self.log.info("https://github.com/aignacio/cocotbext-ahb")

    def _get_burst_length(self, burst_type: AHBBurst) -> int:
        """Get the expected number of beats for a burst type."""
        burst_lengths = {
            AHBBurst.SINGLE: 1,
            AHBBurst.INCR: 0,  # Undefined length
            AHBBurst.WRAP4: 4,
            AHBBurst.INCR4: 4,
            AHBBurst.WRAP8: 8,
            AHBBurst.INCR8: 8,
            AHBBurst.WRAP16: 16,
            AHBBurst.INCR16: 16,
        }
        return burst_lengths.get(burst_type, 1)

    def _get_next_burst_addr(self, current_addr: int, burst_type: AHBBurst, size: AHBSize) -> int:
        """Calculate the next address in a burst sequence."""
        byte_size = 2 ** size.value
        
        if burst_type == AHBBurst.SINGLE:
            return current_addr
        elif burst_type == AHBBurst.INCR or burst_type in [AHBBurst.INCR4, AHBBurst.INCR8, AHBBurst.INCR16]:
            # Incremental bursts
            return current_addr + byte_size
        elif burst_type in [AHBBurst.WRAP4, AHBBurst.WRAP8, AHBBurst.WRAP16]:
            # Wrapping bursts
            if burst_type == AHBBurst.WRAP4:
                wrap_boundary = 4 * byte_size
            elif burst_type == AHBBurst.WRAP8:
                wrap_boundary = 8 * byte_size
            else:  # WRAP16
                wrap_boundary = 16 * byte_size
            
            # Calculate wrapped address
            aligned_start = (current_addr // wrap_boundary) * wrap_boundary
            next_addr = current_addr + byte_size
            if next_addr >= aligned_start + wrap_boundary:
                next_addr = aligned_start
            return next_addr
        
        return current_addr

    def _validate_burst_address(self, expected_addr: int, actual_addr: int, burst_type: AHBBurst) -> bool:
        """Validate that the burst address follows the expected pattern."""
        if burst_type == AHBBurst.INCR:
            # INCR bursts can have any addressing pattern
            return True
        return expected_addr == actual_addr

    def _start_burst(self, txn_data: dict) -> None:
        """Initialize a new burst sequence."""
        burst_type = AHBBurst(txn_data.get("hburst", AHBBurst.SINGLE))
        
        self.burst_state = {
            "active": True,
            "type": burst_type,
            "size": AHBSize(txn_data["hsize"]),
            "start_addr": txn_data["haddr"],
            "current_addr": txn_data["haddr"],
            "beat_count": 1,
            "expected_beats": self._get_burst_length(burst_type),
            "write_mode": bool(txn_data["hwrite"]),
            "transactions": []
        }

    def _continue_burst(self, txn_data: dict) -> bool:
        """Continue an existing burst sequence."""
        if not self.burst_state["active"]:
            return False
        
        current_addr = txn_data["haddr"]
        expected_addr = self._get_next_burst_addr(
            self.burst_state["current_addr"], 
            self.burst_state["type"], 
            self.burst_state["size"]
        )
        
        # Validate burst address
        if not self._validate_burst_address(expected_addr, current_addr, self.burst_state["type"]):
            raise AssertionError(
                f"[{self.bus.name}/{self.name}] AHB PROTOCOL VIOLATION: "
                f"Invalid burst address sequence. Expected: 0x{expected_addr:08X}, "
                f"Got: 0x{current_addr:08X}, Burst Type: {self.burst_state['type']}"
            )
        
        # Validate consistent burst parameters
        if (AHBSize(txn_data["hsize"]) != self.burst_state["size"] or
            bool(txn_data["hwrite"]) != self.burst_state["write_mode"]):
            raise AssertionError(
                f"[{self.bus.name}/{self.name}] AHB PROTOCOL VIOLATION: "
                f"Burst parameters must remain constant throughout the burst"
            )
        
        self.burst_state["current_addr"] = current_addr
        self.burst_state["beat_count"] += 1
        
        # Check if we've exceeded expected beats for defined length bursts
        if (self.burst_state["expected_beats"] > 0 and 
            self.burst_state["beat_count"] > self.burst_state["expected_beats"]):
            raise AssertionError(
                f"[{self.bus.name}/{self.name}] AHB PROTOCOL VIOLATION: "
                f"Burst exceeded expected length of {self.burst_state['expected_beats']} beats"
            )
        
        return True

    def _end_burst(self) -> List[dict]:
        """End the current burst and return all transactions."""
        if not self.burst_state["active"]:
            return []
        
        transactions = self.burst_state["transactions"].copy()
        
        # Validate burst completion for defined length bursts
        if (self.burst_state["expected_beats"] > 0 and 
            self.burst_state["beat_count"] != self.burst_state["expected_beats"]):
            self.log.warning(
                f"Burst ended early. Expected {self.burst_state['expected_beats']} beats, "
                f"got {self.burst_state['beat_count']} beats"
            )
        
        self.burst_state["active"] = False
        return transactions

    async def _monitor_recv(self):
        """Watch the pins and reconstruct transactions."""

        slave_error_prev = 0
        first_txn = {}
        first_st = {}
        first_st["phase"] = "none"
        first_st["write_first_cycle"] = True

        second_txn = {}
        second_st = {}
        second_st["phase"] = "none"
        second_st["write_first_cycle"] = True

        while True:
            await FallingEdge(self.clk)

            # Check that address phase signals of the second txn are stable while slave is not available
            if (second_st["phase"] == "addr") and (self.bus.hready.value == 0):
                self._check_signals(second_txn)

            if first_st["phase"] == "data":
                # Previous cycle we started a txn and slave was ready, but now if it is a write lets
                # check the hwdata whether it is stable or not as the slave is not available anymore
                if self.bus.hready.value == 0:
                    # Copy the latest hresp to ensure slave follow 2-cycle response
                    slave_error_prev = copy.deepcopy(self.bus.hresp.value)

                    if (first_txn["hwrite"] == 1) and (
                        first_st["write_first_cycle"] is True
                    ):
                        first_txn["hwdata"] = copy.deepcopy(self.bus.hwdata.value)
                        first_st["write_first_cycle"] = False
                    elif (first_txn["hwrite"] == 1) and (
                        first_st["write_first_cycle"] is False
                    ):
                        if self.bus.hwdata.value == first_txn["hwdata"]:
                            pass
                        else:
                            raise AssertionError(
                                f"[{self.bus.name}/{self.name}] AHB PROTOCOL VIOLATION: Master.hwdata signal should not change before slave.hready == 1"
                            )

                # Previous cycle we started a txn and slave was ready, and now it is still ready
                # As address and data phase were both completed, push the txn to the next method
                elif self.bus.hready.value == 1:
                    # Check whether the slave response follow the AMBA AHB spec
                    # with 2-cycle delay
                    if (self.bus.hresp.value != AHBResp.OKAY) and (
                        slave_error_prev == 0
                    ):
                        raise AssertionError(
                            f"[{self.bus.name}/{self.name}] AHB PROTOCOL VIOLATION: Slave is not following the 2-cyle error response \
                                    - ARM IHI 0033B.b (ID102715) - Section 5.1.3"
                        )

                    first_txn["response"] = copy.deepcopy(self.bus.hresp.value)
                    first_txn["hrdata"] = copy.deepcopy(self.bus.hrdata.value)
                    first_txn["hwdata"] = copy.deepcopy(self.bus.hwdata.value)

                    # Get burst type if available
                    burst_type = AHBBurst.SINGLE
                    if self.bus.hburst_exist:
                        burst_type = AHBBurst(first_txn.get("hburst", AHBBurst.SINGLE))

                    txn = AHBTxn(
                        int(first_txn["haddr"]),
                        AHBSize(first_txn["hsize"]),
                        AHBWrite(first_txn["hwrite"]),
                        AHBResp(first_txn["response"]),
                        int(first_txn["hwdata"]),
                        int(first_txn["hrdata"]),
                        burst_type,
                        AHBTrans(first_txn["htrans"]),
                        is_burst_start=first_txn["htrans"] == AHBTrans.NONSEQ,
                        is_burst_end=not self.burst_state["active"] or first_txn["htrans"] != AHBTrans.SEQ
                    )

                    # Handle burst tracking
                    if first_txn["htrans"] == AHBTrans.NONSEQ:
                        # Start of new burst or single transfer
                        if self.burst_state["active"]:
                            # End previous burst if it was active
                            self._end_burst()
                        
                        if burst_type != AHBBurst.SINGLE:
                            self._start_burst(first_txn)
                    elif first_txn["htrans"] == AHBTrans.SEQ:
                        # Continuation of burst
                        if not self._continue_burst(first_txn):
                            raise AssertionError(
                                f"[{self.bus.name}/{self.name}] AHB PROTOCOL VIOLATION: "
                                f"SEQ transfer without active burst"
                            )

                    # Add transaction to burst if active
                    if self.burst_state["active"]:
                        self.burst_state["transactions"].append(txn)
                    
                    # Send transaction to monitor
                    self._recv(txn)

                    # Restart the txn status
                    first_st["phase"] = "none"
                    first_st["write_first_cycle"] = True
                    slave_error_prev = 0

                    # Clean second txn
                    second_st["phase"] = "none"
                    second_st["write_first_cycle"] = True

            if (self._check_valid_txn() is True) and (first_st["phase"] == "none"):
                first_st["phase"] = "data" if self.bus.hready.value == 1 else "addr"

                first_txn["hsel"] = (
                    copy.deepcopy(self.bus.hsel.value) if self.bus.hsel_exist else 0
                )
                first_txn["haddr"] = copy.deepcopy(self.bus.haddr.value)
                first_txn["htrans"] = copy.deepcopy(self.bus.htrans.value)
                first_txn["hsize"] = copy.deepcopy(self.bus.hsize.value)
                first_txn["hwrite"] = copy.deepcopy(self.bus.hwrite.value)
                
                # Capture burst information if available
                if self.bus.hburst_exist:
                    first_txn["hburst"] = copy.deepcopy(self.bus.hburst.value)
                else:
                    first_txn["hburst"] = AHBBurst.SINGLE

            # We only enter in the if below if the last txn did not complete and the master issued a new txn
            elif (self._check_valid_txn() is True) and (first_st["phase"] == "data"):
                second_st["phase"] = "addr"

                second_txn["hsel"] = (
                    copy.deepcopy(self.bus.hsel.value) if self.bus.hsel_exist else 0
                )
                second_txn["haddr"] = copy.deepcopy(self.bus.haddr.value)
                second_txn["htrans"] = copy.deepcopy(self.bus.htrans.value)
                second_txn["hsize"] = copy.deepcopy(self.bus.hsize.value)
                second_txn["hwrite"] = copy.deepcopy(self.bus.hwrite.value)
                
                # Capture burst information if available
                if self.bus.hburst_exist:
                    second_txn["hburst"] = copy.deepcopy(self.bus.hburst.value)
                else:
                    second_txn["hburst"] = AHBBurst.SINGLE

            if first_st["phase"] == "addr":
                self._check_signals(first_txn)

                if self.bus.hready.value == 0:
                    raise AssertionError(
                        f"[{self.bus.name}/{self.name}] AHB PROTOCOL VIOLATION:"
                        "A slave cannot request that the address phase is extended"
                        "and therefore all slaves must be capable of sampling the address during this time"
                        " - ARM IHI 0033B.b (ID102715) - Section 1.3"
                    )
                else:
                    first_st["phase"] = "data"

    def _check_inputs(self) -> bool:
        """Check any of the master signals are resolvable (i.e not 'z')"""
        signals = {
            "htrans": self.bus.htrans,
            "hwrite": self.bus.hwrite,
            "haddr": self.bus.haddr,
            "hsize": self.bus.hsize,
        }

        if self.bus.hsel_exist:
            signals["hsel"] = self.bus.hsel

        if self.bus.hready_in_exist:
            signals["hready_in"] = self.bus.hready_in

        for var, val in signals.items():
            if val.value.is_resolvable is False:
                # self.log.warn(f"{var} is not resolvable")
                return False
        return True

    def _check_valid_txn(self) -> bool:
        if self._check_inputs():
            htrans_st = (AHBTrans(self.bus.htrans.value) != AHBTrans.IDLE) and (
                AHBTrans(self.bus.htrans.value) != AHBTrans.BUSY
            )

            if self.bus.hsel_exist:  # Decoder to slave
                if self.bus.hready_in_exist:
                    if (
                        (self.bus.hsel.value == 1)
                        and (self.bus.hready_in.value == 1)
                        and htrans_st
                    ):
                        return True
                    else:
                        return False
                else:
                    if (self.bus.hsel.value == 1) and htrans_st:
                        return True
                    else:
                        return False
            else:
                if htrans_st:  # In this case it is just a master
                    return True
                else:
                    return False
        else:
            return False

    def _check_signals(self, stable):
        """Check any of the master signals are resolvable (i.e not 'z')"""
        if self.bus.hsel_exist:
            current = {
                "hsel": self.bus.hsel,
                "htrans": self.bus.htrans,
                "hwrite": self.bus.hwrite,
                "haddr": self.bus.haddr,
                "hsize": self.bus.hsize,
            }
        else:
            current = {
                "htrans": self.bus.htrans,
                "hwrite": self.bus.hwrite,
                "haddr": self.bus.haddr,
                "hsize": self.bus.hsize,
            }

        for signal in current:
            if current[signal].value.is_resolvable is not True:
                raise AssertionError(f"Signal master.{signal} is not resolvable!")
            if current[signal].value != stable[signal]:
                if (signal == "htrans") and (self.bus.hresp.value == AHBResp.ERROR):
                    pass
                else:
                    raise AssertionError(
                        f"[{self.bus.name}/{self.name}] AHB PROTOCOL VIOLATION: Master.{signal} signal should not change before slave.hready == 1"
                    )


class AHBTxn:
    def __init__(
        self,
        addr: int = 0x00,
        size: AHBSize = AHBSize.BYTE,
        mode: AHBWrite = AHBWrite.READ,
        resp: AHBResp = AHBResp.OKAY,
        wdata: int = 0x00,
        rdata: int = 0x00,
        burst: AHBBurst = AHBBurst.SINGLE,
        trans: AHBTrans = AHBTrans.NONSEQ,
        is_burst_start: bool = False,
        is_burst_end: bool = True,
    ):
        self.addr = addr
        self.size = size
        self.mode = mode
        self.resp = resp
        self.wdata = wdata
        self.rdata = rdata
        self.burst = burst
        self.trans = trans
        self.is_burst_start = is_burst_start
        self.is_burst_end = is_burst_end

    def __str__(self):
        burst_info = f"Burst: {self.burst.name}"
        if self.burst != AHBBurst.SINGLE:
            burst_info += f" ({'Start' if self.is_burst_start else 'Continue'}"
            burst_info += f"{' End' if self.is_burst_end else ''})"
        
        return (
            f"AHB Txn Details:\n"
            f"  Address: 0x{self.addr:08X}\n"
            f"  Size: {2**self.size} bytes (0x{self.size:03X})\n"
            f"  Mode: {'Write' if self.mode == 1 else 'Read'} (0x{self.mode:01X})\n"
            f"  Response: {'OKAY' if self.resp == 0 else 'ERROR'} (0x{self.resp:02X})\n"
            f"  Write Data: 0x{self.wdata:08X}\n"
            f"  Read Data: 0x{self.rdata:08X}\n"
            f"  Transfer: {self.trans.name}\n"
            f"  {burst_info}\n"
        )

    def __eq__(self, other):
        # We have to override the default python comparison method for this class
        # because the Scoreboard class will compare the txns
        if isinstance(other, AHBTxn):
            return (
                self.addr == other.addr
                and self.size == other.size
                and self.mode == other.mode
                and self.resp == other.resp
                and self.wdata == other.wdata
                and self.rdata == other.rdata
                and self.burst == other.burst
                and self.trans == other.trans
                and self.is_burst_start == other.is_burst_start
                and self.is_burst_end == other.is_burst_end
            )
        return False
