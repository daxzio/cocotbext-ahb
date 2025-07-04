#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File              : ahb_master.py
# License           : MIT license <Check LICENSE>
# Author            : Anderson I. da Silva (aignacio) <anderson@aignacio.com>
# Date              : 08.10.2023
# Last Modified Date: 27.12.2024
import logging
import cocotb
import copy
import datetime

from .ahb_types import AHBTrans, AHBWrite, AHBSize, AHBResp, AHBBurst
from .ahb_bus import AHBBus
from .version import __version__

from cocotb.triggers import RisingEdge
from typing import Optional, Sequence, Union, List
from cocotb.types import LogicArray


class AHBLiteMaster:
    def __init__(
        self,
        bus: AHBBus,
        clock: str,
        reset: str,
        timeout: int = 100,
        def_val: Union[int, str] = 0,  # Can be set to "Z",
        name: str = "ahb_lite",
        **kwargs,
    ):
        self.bus = bus
        self.clk = clock
        self.rst = reset
        self.timeout = timeout
        self.def_val = def_val
        self.log = logging.getLogger(
            f"cocotb.{name}.{bus._name}." f"{bus._entity._name}"
        )
        self._init_bus()
        self.log.info(f"AHB ({name}) master")
        self.log.info("cocotbext-ahb version %s", __version__)
        self.log.info(
            f"Copyright (c) {datetime.datetime.now().year} Anderson Ignacio da Silva"
        )
        self.log.info("https://github.com/aignacio/cocotbext-ahb")

    def _init_bus(self) -> None:
        """Initialize the bus with default value."""
        for signal in self.bus._signals:
            if signal not in ["hready", "hresp", "hrdata"]:
                sig = getattr(self.bus, signal)
                try:
                    sig.setimmediatevalue(self._get_def(len(sig)))
                except AttributeError:
                    pass

    def _reset_bus(self) -> None:
        """Initialize the bus with default value."""
        for signal in self.bus._signals:
            if signal not in ["hready", "hresp", "hrdata"]:
                sig = getattr(self.bus, signal)
                try:
                    sig.value = self._get_def(len(sig))
                except AttributeError:
                    pass

    def _get_def(self, width: int = 1) -> LogicArray:
        """Return a handle obj with the default value"""
        return LogicArray([self.def_val for _ in range(width)])

    def _convert_size(self, value) -> Union[AHBTrans, LogicArray]:
        """Convert byte size into hsize."""

        if isinstance(value, LogicArray):
            return value

        for hsize in AHBSize:
            if (2**hsize.value) == value:
                return hsize
        raise ValueError(f"No hsize value found for {value} number of bytes")

    @staticmethod
    def _check_size(size: int, data_bus_width: int) -> None:
        """Check that the provided transfer size is valid."""
        if size > data_bus_width:
            raise ValueError(
                "Size of the transfer ({} B)"
                " provided is larger than the bus width "
                "({} B)".format(size, data_bus_width)
            )
        elif size <= 0 or (size & (size - 1)) != 0:
            raise ValueError(f"Error -> {size} - Size must" f"be a positive power of 2")

    def _get_burst_length(self, burst_type: AHBBurst) -> int:
        """Get the number of beats for a burst type."""
        burst_lengths = {
            AHBBurst.SINGLE: 1,
            AHBBurst.INCR: 1,  # Unspecified length, using 1 as default
            AHBBurst.WRAP4: 4,
            AHBBurst.INCR4: 4,
            AHBBurst.WRAP8: 8,
            AHBBurst.INCR8: 8,
            AHBBurst.WRAP16: 16,
            AHBBurst.INCR16: 16,
        }
        return burst_lengths.get(burst_type, 1)

    def _get_wrap_boundary(self, burst_type: AHBBurst, size: int) -> int:
        """Get the wrap boundary for wrapping bursts."""
        if burst_type == AHBBurst.WRAP4:
            return 4 * size
        elif burst_type == AHBBurst.WRAP8:
            return 8 * size
        elif burst_type == AHBBurst.WRAP16:
            return 16 * size
        return size

    def _wrap_address(self, address: int, base_addr: int, wrap_boundary: int) -> int:
        """Calculate wrapped address for wrapping bursts."""
        # Find the aligned boundary
        aligned_base = (base_addr // wrap_boundary) * wrap_boundary
        offset = address - aligned_base
        return aligned_base + (offset % wrap_boundary)

    def _generate_burst_addresses(self, base_addr: int, burst_type: AHBBurst, 
                                size: int, beats: int) -> List[int]:
        """Generate addresses for burst transactions."""
        if burst_type == AHBBurst.SINGLE or beats == 1:
            return [base_addr]
        
        addresses = [base_addr]
        increment = size
        
        if burst_type in [AHBBurst.INCR, AHBBurst.INCR4, AHBBurst.INCR8, AHBBurst.INCR16]:
            # Incrementing burst
            for i in range(1, beats):
                addresses.append(base_addr + (i * increment))
        
        elif burst_type in [AHBBurst.WRAP4, AHBBurst.WRAP8, AHBBurst.WRAP16]:
            # Wrapping burst
            wrap_boundary = self._get_wrap_boundary(burst_type, size)
            for i in range(1, beats):
                next_addr = base_addr + (i * increment)
                addresses.append(self._wrap_address(next_addr, base_addr, wrap_boundary))
        
        return addresses

    def _generate_burst_trans(self, burst_type: AHBBurst, beats: int) -> List[AHBTrans]:
        """Generate transaction types for burst."""
        if burst_type == AHBBurst.SINGLE or beats == 1:
            return [AHBTrans.NONSEQ]
        
        # First beat is NONSEQ, subsequent beats are SEQ
        trans_types = [AHBTrans.NONSEQ]
        trans_types.extend([AHBTrans.SEQ] * (beats - 1))
        return trans_types

    def _expand_burst_transaction(self, address: List[int], value: List[int], 
                                size: List[int], burst: List[AHBBurst]) -> tuple:
        """Expand burst transactions into individual beats."""
        expanded_addr = []
        expanded_value = []
        expanded_size = []
        expanded_burst = []
        expanded_trans = []
        
        for addr, val, sz, burst_type in zip(address, value, size, burst):
            beats = self._get_burst_length(burst_type)
            burst_addrs = self._generate_burst_addresses(addr, burst_type, sz, beats)
            burst_trans = self._generate_burst_trans(burst_type, beats)
            
            # Expand addresses
            expanded_addr.extend(burst_addrs)
            
            # For writes, replicate the value for each beat
            # For reads, value is ignored but we still need placeholders
            expanded_value.extend([val] * beats)
            
            # Size and burst type are same for all beats
            expanded_size.extend([sz] * beats)
            expanded_burst.extend([burst_type] * beats)
            expanded_trans.extend(burst_trans)
        
        return expanded_addr, expanded_value, expanded_size, expanded_burst, expanded_trans

    def _fmt_amba(
        self, address: Sequence[int], size: Sequence[int], value: Sequence[int]
    ) -> Sequence[int]:
        """Format the write data to follow AMBA by shifting / masking data."""
        new_val = []
        offset = (self.bus.data_width // 8) - 1
        for addr, sz, val in zip(address, size, value):
            if sz != (self.bus.data_width // 8):
                data = 0
                if sz == 4:
                    data = (val & 0xFFFFFFFF) << ((addr & offset) * 8)
                elif sz == 2:
                    data = (val & 0xFFFF) << ((addr & offset) * 8)
                elif sz == 1:
                    data = (val & 0xFF) << ((addr & offset) * 8)
                new_val.append(data & (2**self.bus.data_width - 1))
            else:
                new_val.append(val)
        return new_val

    def _addr_phase(self, addr: int, size: int, mode: AHBWrite, trans: AHBTrans, burst: AHBBurst = AHBBurst.SINGLE):
        """Drive the AHB signals of the address phase."""
        self.bus.haddr.value = addr
        self.bus.htrans.value = trans
        self.bus.hsize.value = self._convert_size(size)
        self.bus.hwrite.value = mode

        # Optional signals
        if self.bus.hsel_exist:
            self.bus.hsel.value = 1
        if self.bus.hready_in_exist:
            self.bus.hready_in.value = 1
        if self.bus.hburst_exist:
            self.bus.hburst.value = burst

    def _create_vector(
        self, vec: Sequence[int], width: int, phase: str, pip: Optional[bool] = False
    ) -> Sequence[int]:
        """Create a list to be driven during address/data phase."""
        vec_out = []
        if pip:
            # Format address/data to send in pipeline
            # Address
            # |   ADDRESS 0  | ADDRESS 1 | ... | default value |
            # Data
            # |  default val |   DATA 0  | ... |    DATA N     |

            if phase == "address_ph":
                vec_out = vec
                vec_out.append(self._get_def(width))
            elif phase == "data_ph":
                vec_out = vec
                vec_out.insert(0, self._get_def(width))
        else:
            # Format address/data to send in non-pipeline
            # Address
            # |   ADDRESS 0  | default value |   ADDRESS 1   | default value |
            # Data
            # |  default val |     DATA 0    | default value |    DATA 1     |

            if phase == "address_ph":
                for i in vec:
                    vec_out.append(i)
                    vec_out.append(self._get_def(width))
            elif phase == "data_ph":
                for i in vec:
                    vec_out.append(self._get_def(width))
                    vec_out.append(i)
        return vec_out

    async def _send_txn(
        self,
        address: Sequence[int],
        value: Sequence[int],
        size: Sequence[int],
        mode: Sequence[AHBWrite],
        trans: Sequence[AHBTrans],
        burst: Optional[Sequence[AHBBurst]] = None,
        pip: bool = False,
        verbose: bool = False,
        sync: bool = False,
    ) -> Sequence[dict]:
        """Drives the AHB transaction into the bus."""
        response = []
        first_txn = True

        if burst is None:
            burst = [AHBBurst.SINGLE] * len(address)

        index = 0
        restart = False

        # If sync, wait for one clock cycle before it starts
        # useful when leaving out of reset
        if sync:
            await RisingEdge(self.clk)

        if pip is not True:
            # If pip is True, create a list with "BUBBLE" between each number
            id_ahb = []
            for i in range(len(address)):
                id_ahb.append(i)  # Append the number
                id_ahb.append("BUBBLE")  # Append "BUBBLE"
        else:
            # If pip is False, just create a simple list of sequential numbers
            id_ahb = list(range(len(address)))

        while index < len(address):
            txn_addr, txn_data, txn_size, txn_mode, txn_trans, txn_burst, txn_id = (
                address[index],
                value[index],
                size[index],
                mode[index],
                trans[index],
                burst[index],
                id_ahb[index],
            )
            if index == len(address) - 1:
                self._reset_bus()
            else:
                self._addr_phase(txn_addr, txn_size, txn_mode, txn_trans, txn_burst)
                if txn_id != "BUBBLE":
                    if not isinstance(txn_addr, LogicArray):
                        op = "write" if txn_mode == 1 else "read"
                        if verbose is True:
                            burst_info = f" (burst: {txn_burst.name})" if txn_burst != AHBBurst.SINGLE else ""
                            self.log.info(
                                f"AHB {op} txn:\n"
                                f"\tID = {txn_id}\n"
                                f"\tADDR = 0x{txn_addr:x}\n"
                                f"\tDATA = 0x{value[index + 1]:x}\n"
                                f"\tSIZE = {txn_size} byte[s]{burst_info}"
                            )
            self.bus.hwdata.value = txn_data
            if self.bus.hready_in_exist:
                self.bus.hready_in.value = 1

            await RisingEdge(self.clk)

            # First check if the slave signals are resolvable
            timeout_counter = 0
            while any(
                [
                    not self.bus.hready.value.is_resolvable,
                    not self.bus.hresp.value.is_resolvable,
                    not self.bus.hrdata.value.is_resolvable,
                ]
            ):
                timeout_counter += 1
                if timeout_counter == self.timeout:
                    raise Exception(
                        f"Timeout value of {timeout_counter}"
                        f" clock cycles has been reached because AHB.SLAVE"
                        f"signals are not resolvable!\n"
                        f"hready: {self.bus.hready.value.is_resolvable}\n"
                        f"hrdata: {self.bus.hrdata.value.is_resolvable}\n"
                        f"hresp: {self.bus.hresp.value.is_resolvable}\n"
                    )
                await RisingEdge(self.clk)

            index += 1

            # Wait till a response is available from the slave
            while self.bus.hready.value != 1:
                if self.bus.hresp == AHBResp.ERROR:
                    if self.bus.htrans.value.is_resolvable:
                        if self.bus.htrans.value == AHBTrans.NONSEQ:
                            index -= 1  # Redo the txn
                            self.bus.htrans.value = (
                                AHBTrans.IDLE
                            )  # Withdrawn the req. in case of error
                            restart = True
                timeout_counter += 1
                if timeout_counter == self.timeout:
                    raise Exception(
                        f"Timeout value of {timeout_counter}"
                        f" clock cycles has been reached!"
                    )
                await RisingEdge(self.clk)

            if first_txn:
                first_txn = False
            else:
                # if Non-Pipeline, don't sample hresp in the next cc, wait
                # always one more
                if not pip:
                    first_txn = True
                response += [
                    {
                        "resp": AHBResp(int(self.bus.hresp.value)),
                        "data": hex(self.bus.hrdata.value),
                    }
                ]
            if restart:  # As we withdrawn the last txn, let's restart
                first_txn = True
                restart = False

        self._reset_bus()
        return response

    async def write(
        self,
        address: Union[int, Sequence[int]],
        value: Union[int, Sequence[int]],
        size: Optional[Union[int, Sequence[int]]] = None,
        burst: Optional[Union[AHBBurst, Sequence[AHBBurst]]] = AHBBurst.SINGLE,
        pip: Optional[bool] = False,
        verbose: Optional[bool] = False,
        sync: Optional[bool] = False,
        format_amba: Optional[bool] = False,
    ) -> Sequence[dict]:
        """Write data in the AHB bus."""

        if not isinstance(address, list):
            address = [address]

        if size is None:
            size = [self.bus._data_width // 8 for _ in range(len(address))]
        else:
            if not isinstance(size, list):
                size = [size]
            for sz in size:
                AHBLiteMaster._check_size(sz, len(self.bus.hwdata) // 8)

        # Convert all inputs into lists, if not already
        if not isinstance(value, list):
            value = [value]

        if not isinstance(burst, list):
            burst = [burst] * len(address)

        # First check if the input sizes are correct
        if len(address) != len(value):
            raise Exception(
                f"Address length ({len(address)}) is"
                f"different from data length ({len(value)})"
            )

        if len(address) != len(size):
            raise Exception(
                f"Address length ({len(address)}) is"
                f"different from size length ({len(size)})"
            )

        if len(address) != len(burst):
            raise Exception(
                f"Address length ({len(address)}) is"
                f"different from burst length ({len(burst)})"
            )

        # Expand burst transactions into individual beats
        exp_addr, exp_value, exp_size, exp_burst, exp_trans = self._expand_burst_transaction(
            address, value, size, burst
        )

        if format_amba is True:
            exp_value = self._fmt_amba(exp_addr, exp_size, exp_value)

        # Need to copy data as we'll have to shift address/value
        t_address = copy.deepcopy(exp_addr)
        t_value = copy.deepcopy(exp_value)
        t_size = copy.deepcopy(exp_size)
        t_burst = copy.deepcopy(exp_burst)
        t_trans = copy.deepcopy(exp_trans)

        width = len(self.bus.haddr)
        t_address = self._create_vector(t_address, width, "address_ph", pip)
        width = len(self.bus.hwdata)
        t_value = self._create_vector(t_value, width, "data_ph", pip)
        width = len(self.bus.hsize)
        t_size = self._create_vector(t_size, width, "address_ph", pip)
        width = len(self.bus.htrans)
        t_trans = self._create_vector(t_trans, width, "address_ph", pip)
        # Default signaling for burst
        width = len(self.bus.hburst) if self.bus.hburst_exist else 3
        t_burst = self._create_vector(t_burst, width, "address_ph", pip)
        # Default signaling for mode
        t_mode = [AHBWrite.WRITE for _ in range(len(t_address))]
        width = len(self.bus.hwrite)
        t_mode = self._create_vector(t_mode, width, "address_ph", pip)

        return await self._send_txn(
            t_address, t_value, t_size, t_mode, t_trans, t_burst, pip, verbose, sync
        )

    async def read(
        self,
        address: Union[int, Sequence[int]],
        size: Optional[Union[int, Sequence[int]]] = None,
        burst: Optional[Union[AHBBurst, Sequence[AHBBurst]]] = AHBBurst.SINGLE,
        pip: Optional[bool] = False,
        verbose: Optional[bool] = False,
        sync: Optional[bool] = False,
    ) -> Sequence[dict]:
        """Read data from the AHB bus."""

        if not isinstance(address, list):
            address = [address]

        if size is None:
            size = [self.bus._data_width // 8 for _ in range(len(address))]
        else:
            # Convert all inputs into lists, if not already
            if not isinstance(size, list):
                size = [size]

            for sz in size:
                AHBLiteMaster._check_size(sz, len(self.bus.hwdata) // 8)

        if not isinstance(burst, list):
            burst = [burst] * len(address)

        # First check if the input sizes are correct
        if len(address) != len(size):
            raise Exception(
                f"Address length ({len(address)}) is"
                f"different from size length ({len(size)})"
            )

        if len(address) != len(burst):
            raise Exception(
                f"Address length ({len(address)}) is"
                f"different from burst length ({len(burst)})"
            )

        # Create placeholder values for read transactions
        t_value = [0x00 for i in range(len(address))]
        
        # Expand burst transactions into individual beats
        exp_addr, exp_value, exp_size, exp_burst, exp_trans = self._expand_burst_transaction(
            address, t_value, size, burst
        )

        # Need to copy data as we'll have to shift address/size
        t_address = copy.deepcopy(exp_addr)
        t_value = copy.deepcopy(exp_value)
        t_size = copy.deepcopy(exp_size)
        t_burst = copy.deepcopy(exp_burst)
        t_trans = copy.deepcopy(exp_trans)

        width = len(self.bus.haddr)
        t_address = self._create_vector(t_address, width, "address_ph", pip)
        width = len(self.bus.hwdata)
        t_value = self._create_vector(t_value, width, "data_ph", pip)
        width = len(self.bus.hsize)
        t_size = self._create_vector(t_size, width, "address_ph", pip)
        width = len(self.bus.htrans)
        t_trans = self._create_vector(t_trans, width, "address_ph", pip)
        # Default signaling for burst
        width = len(self.bus.hburst) if self.bus.hburst_exist else 3
        t_burst = self._create_vector(t_burst, width, "address_ph", pip)
        # Default signaling for mode
        t_mode = [AHBWrite.READ for _ in range(len(t_address))]
        width = len(self.bus.hwrite)
        t_mode = self._create_vector(t_mode, width, "address_ph", pip)

        return await self._send_txn(
            t_address, t_value, t_size, t_mode, t_trans, t_burst, pip, verbose, sync
        )

    async def custom(
        self,
        address: Union[int, Sequence[int]],
        value: Union[int, Sequence[int]],
        mode: Union[int, Sequence[int]],
        size: Optional[Union[int, Sequence[int]]] = None,
        burst: Optional[Union[AHBBurst, Sequence[AHBBurst]]] = AHBBurst.SINGLE,
        pip: Optional[bool] = True,
        verbose: Optional[bool] = False,
        sync: Optional[bool] = False,
        format_amba: Optional[bool] = False,
    ) -> Sequence[dict]:
        """Back-to-Back operation"""

        if len(address) != len(value):
            raise Exception(
                f"Length address {len(address)} is diff from"
                f" length value {len(value)}!"
            )

        if size is None:
            size = [self.bus._data_width // 8 for _ in range(len(address))]
        else:
            if len(address) != len(mode):
                raise Exception(
                    f"Length address {len(address)} is diff from"
                    f" length mode {len(mode)}!"
                )
            for sz in size:
                AHBLiteMaster._check_size(sz, len(self.bus.hwdata) // 8)

        # Convert all inputs into lists, if not already
        if not isinstance(address, list):
            address = [address]
        if not isinstance(size, list):
            size = [size]
        if not isinstance(value, list):
            value = [value]
        if not isinstance(mode, list):
            mode = [mode]
        if not isinstance(burst, list):
            burst = [burst] * len(address)

        if len(address) != len(burst):
            raise Exception(
                f"Address length ({len(address)}) is"
                f"different from burst length ({len(burst)})"
            )

        # Expand burst transactions into individual beats
        exp_addr, exp_value, exp_size, exp_burst, exp_trans = self._expand_burst_transaction(
            address, value, size, burst
        )

        if format_amba is True:
            exp_value = self._fmt_amba(exp_addr, exp_size, exp_value)

        # Need to copy data as we'll have to shift address/size
        t_address = copy.deepcopy(exp_addr)
        t_value = copy.deepcopy(exp_value)
        t_size = copy.deepcopy(exp_size)
        t_burst = copy.deepcopy(exp_burst)
        t_trans = copy.deepcopy(exp_trans)

        # Expand mode to match burst expansion
        exp_mode = []
        for m, b in zip(mode, burst):
            beats = self._get_burst_length(b)
            exp_mode.extend([m] * beats)
        t_mode = copy.deepcopy(exp_mode)

        width = len(self.bus.haddr)
        t_address = self._create_vector(t_address, width, "address_ph", pip)
        width = len(self.bus.hwdata)
        t_value = self._create_vector(t_value, width, "data_ph", pip)
        width = len(self.bus.hsize)
        t_size = self._create_vector(t_size, width, "address_ph", pip)
        width = len(self.bus.hwrite)
        t_mode = self._create_vector(t_mode, width, "address_ph", pip)
        width = len(self.bus.htrans)
        t_trans = self._create_vector(t_trans, width, "address_ph", pip)
        # Default signaling for burst
        width = len(self.bus.hburst) if self.bus.hburst_exist else 3
        t_burst = self._create_vector(t_burst, width, "address_ph", pip)

        return await self._send_txn(
            t_address, t_value, t_size, t_mode, t_trans, t_burst, pip, verbose, sync
        )


class AHBMaster(AHBLiteMaster):
    def __init__(
        self,
        bus: AHBBus,
        clock: str,
        reset: str,
        timeout: int = 100,
        def_val: Union[int, str] = "Z",
        **kwargs,
    ):
        super().__init__(bus, clock, reset, timeout, def_val, "ahb_full", **kwargs)
