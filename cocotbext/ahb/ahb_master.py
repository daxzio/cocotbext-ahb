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

from .ahb_types import (
    AHBTrans,
    AHBWrite,
    AHBSize,
    AHBResp,
    AHBBurst,
    AHBPipelineMode,
)
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

    def _master_drive_signals(self) -> List[str]:
        """Signals driven by the master (required + present optional)."""
        skip = {"hready", "hresp", "hrdata", "hexokay"}
        names = list(self.bus._signals)
        if hasattr(self.bus, "_optional_signals"):
            names.extend(self.bus._optional_signals)
        return [s for s in names if s not in skip]

    def _init_bus(self) -> None:
        """Initialize the bus with default value."""
        for signal in self._master_drive_signals():
            sig = getattr(self.bus, signal, None)
            if sig is None:
                continue
            try:
                sig.setimmediatevalue(self._get_def(len(sig)))
            except AttributeError:
                pass

    def _reset_bus(self) -> None:
        """Initialize the bus with default value."""
        for signal in self._master_drive_signals():
            sig = getattr(self.bus, signal, None)
            if sig is None:
                continue
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
    def _resolve_pipeline_mode(
        pip: Optional[bool],
        mode: Optional[AHBPipelineMode],
    ) -> AHBPipelineMode:
        if mode is not None:
            return mode
        if pip is True:
            return AHBPipelineMode.PIPELINED
        return AHBPipelineMode.PACED

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

    def _addr_phase(
        self,
        addr: int,
        size: int,
        mode: AHBWrite,
        trans: AHBTrans,
        exclusive: bool = False,
    ):
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
            self.bus.hburst.value = AHBBurst.SINGLE
        if self.bus.hmastlock_exist:
            self.bus.hmastlock.value = 0
        if self.bus.hprot_exist:
            self.bus.hprot.value = 0
        if self.bus.hnonsec_exist:
            self.bus.hnonsec.value = 1
        if self.bus.hmaster_exist:
            self.bus.hmaster.value = 0
        if self.bus.hexcl_exist:
            self.bus.hexcl.value = 1 if exclusive else 0

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
        exclusive: Sequence[bool] = (),
        pip: bool = False,
        verbose: bool = False,
        sync: bool = False,
    ) -> Sequence[dict]:
        """Drives the AHB transaction into the bus."""
        response = []
        first_txn = True

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

        if not exclusive:
            exclusive = [False for _ in range(len(address))]
        elif len(exclusive) != len(address):
            raise Exception(
                f"Exclusive length ({len(exclusive)}) differs from address length ({len(address)})"
            )

        while index < len(address):
            txn_addr, txn_data, txn_size, txn_mode, txn_trans, txn_id, txn_excl = (
                address[index],
                value[index],
                size[index],
                mode[index],
                trans[index],
                id_ahb[index],
                exclusive[index],
            )
            if index == len(address) - 1:
                self._reset_bus()
            else:
                self._addr_phase(txn_addr, txn_size, txn_mode, txn_trans, txn_excl)
                if txn_id != "BUBBLE":
                    if not isinstance(txn_addr, LogicArray):
                        op = "write" if txn_mode == 1 else "read"
                        if verbose is True:
                            self.log.info(
                                f"AHB {op} txn:\n"
                                f"\tID = {txn_id}\n"
                                f"\tADDR = 0x{txn_addr:x}\n"
                                f"\tDATA = 0x{value[index + 1]:x}\n"
                                f"\tSIZE = {txn_size} byte[s]"
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
                resp_entry = {
                    "resp": AHBResp(int(self.bus.hresp.value)),
                    "data": hex(self.bus.hrdata.value),
                }
                if self.bus.hexokay_exist:
                    resp_entry["hexokay"] = int(self.bus.hexokay.value)
                response += [resp_entry]
            if restart:  # As we withdrawn the last txn, let's restart
                first_txn = True
                restart = False

        self._reset_bus()
        return response

    async def _wait_slave_signals(self, timeout_counter: int = 0) -> int:
        """Wait until slave response signals are resolvable."""
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
        return timeout_counter

    async def _wait_hready(self, timeout_counter: int = 0) -> int:
        """Wait until the slave asserts HREADY."""
        while self.bus.hready.value != 1:
            timeout_counter += 1
            if timeout_counter == self.timeout:
                raise Exception(
                    f"Timeout value of {timeout_counter}"
                    f" clock cycles has been reached!"
                )
            await RisingEdge(self.clk)
        return timeout_counter

    def _response_entry(self) -> dict:
        resp_entry = {
            "resp": AHBResp(int(self.bus.hresp.value)),
            "data": hex(self.bus.hrdata.value),
        }
        if self.bus.hexokay_exist and self.bus.hexokay.value.is_resolvable:
            resp_entry["hexokay"] = int(self.bus.hexokay.value)
        return resp_entry

    async def _send_txn_cpu_like(
        self,
        address: Sequence[int],
        value: Sequence[int],
        size: Sequence[int],
        mode: Sequence[AHBWrite],
        trans: Sequence[AHBTrans],
        exclusive: Sequence[bool] = (),
        verbose: bool = False,
        sync: bool = False,
    ) -> Sequence[dict]:
        """Drive one beat at a time: addr (+ write data) together, wait for HREADY."""
        response = []
        n = len(address)

        if sync:
            await RisingEdge(self.clk)

        if not exclusive:
            exclusive = [False for _ in range(n)]
        elif len(exclusive) != n:
            raise Exception(
                f"Exclusive length ({len(exclusive)}) differs from address length ({n})"
            )

        for index in range(n):
            txn_addr = address[index]
            txn_data = value[index]
            txn_size = size[index]
            txn_mode = mode[index]
            txn_trans = trans[index]
            txn_excl = exclusive[index]

            if isinstance(txn_addr, LogicArray):
                raise ValueError("CPU_LIKE mode does not support LogicArray addresses")

            self._addr_phase(txn_addr, txn_size, txn_mode, txn_trans, txn_excl)
            if txn_mode == AHBWrite.WRITE:
                self.bus.hwdata.value = txn_data
            if self.bus.hready_in_exist:
                self.bus.hready_in.value = 1

            if verbose:
                op = "write" if txn_mode == AHBWrite.WRITE else "read"
                self.log.info(
                    f"AHB {op} txn (CPU_LIKE):\n"
                    f"\tID = {index}\n"
                    f"\tADDR = 0x{txn_addr:x}\n"
                    f"\tDATA = 0x{txn_data:x}\n"
                    f"\tSIZE = {txn_size} byte[s]"
                )

            await RisingEdge(self.clk)

            timeout_counter = await self._wait_slave_signals()
            timeout_counter = await self._wait_hready(timeout_counter)
            response.append(self._response_entry())

        self._reset_bus()
        return response

    async def write(
        self,
        address: Union[int, Sequence[int]],
        value: Union[int, Sequence[int]],
        size: Optional[Union[int, Sequence[int]]] = None,
        exclusive: Optional[Union[bool, Sequence[bool]]] = False,
        pip: Optional[bool] = False,
        mode: Optional[AHBPipelineMode] = None,
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

        if not isinstance(value, list):
            value = [value]

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

        if format_amba is True:
            value = self._fmt_amba(address, size, value)

        pipeline_mode = self._resolve_pipeline_mode(pip, mode)
        if not isinstance(exclusive, list):
            t_exclusive = [exclusive for _ in range(len(address))]
        else:
            t_exclusive = exclusive

        if pipeline_mode == AHBPipelineMode.CPU_LIKE:
            t_trans = [AHBTrans.NONSEQ for _ in range(len(address))]
            t_mode = [AHBWrite.WRITE for _ in range(len(address))]
            return await self._send_txn_cpu_like(
                address,
                value,
                size,
                t_mode,
                t_trans,
                t_exclusive,
                verbose,
                sync,
            )

        pip = pipeline_mode == AHBPipelineMode.PIPELINED

        t_address = copy.deepcopy(address)
        t_value = copy.deepcopy(value)
        t_size = copy.deepcopy(size)

        width = len(self.bus.haddr)
        t_address = self._create_vector(t_address, width, "address_ph", pip)
        width = len(self.bus.hwdata)
        t_value = self._create_vector(t_value, width, "data_ph", pip)
        width = len(self.bus.hsize)
        t_size = self._create_vector(t_size, width, "address_ph", pip)
        t_mode = [AHBWrite.WRITE for _ in range(len(t_address))]
        width = len(self.bus.hwrite)
        t_mode = self._create_vector(t_mode, width, "address_ph", pip)
        t_trans = [AHBTrans.NONSEQ for _ in range(len(t_address))]
        width = len(self.bus.htrans)
        t_trans = self._create_vector(t_trans, width, "address_ph", pip)
        width = 1
        t_exclusive = self._create_vector(t_exclusive, width, "address_ph", pip)

        return await self._send_txn(
            t_address,
            t_value,
            t_size,
            t_mode,
            t_trans,
            t_exclusive,
            pip,
            verbose,
            sync,
        )

    async def read(
        self,
        address: Union[int, Sequence[int]],
        size: Optional[Union[int, Sequence[int]]] = None,
        exclusive: Optional[Union[bool, Sequence[bool]]] = False,
        pip: Optional[bool] = False,
        mode: Optional[AHBPipelineMode] = None,
        verbose: Optional[bool] = False,
        sync: Optional[bool] = False,
    ) -> Sequence[dict]:
        """Read data from the AHB bus."""

        if not isinstance(address, list):
            address = [address]

        if size is None:
            size = [self.bus._data_width // 8 for _ in range(len(address))]
        else:
            if not isinstance(size, list):
                size = [size]

            for sz in size:
                AHBLiteMaster._check_size(sz, len(self.bus.hwdata) // 8)

        if len(address) != len(size):
            raise Exception(
                f"Address length ({len(address)}) is"
                f"different from size length ({len(size)})"
            )

        pipeline_mode = self._resolve_pipeline_mode(pip, mode)
        if not isinstance(exclusive, list):
            t_exclusive = [exclusive for _ in range(len(address))]
        else:
            t_exclusive = exclusive

        if pipeline_mode == AHBPipelineMode.CPU_LIKE:
            t_trans = [AHBTrans.NONSEQ for _ in range(len(address))]
            t_mode = [AHBWrite.READ for _ in range(len(address))]
            t_value = [0 for _ in range(len(address))]
            return await self._send_txn_cpu_like(
                address,
                t_value,
                size,
                t_mode,
                t_trans,
                t_exclusive,
                verbose,
                sync,
            )

        pip = pipeline_mode == AHBPipelineMode.PIPELINED

        t_address = copy.deepcopy(address)
        t_value = [0x00 for i in range(len(address))]
        t_size = copy.deepcopy(size)

        width = len(self.bus.haddr)
        t_address = self._create_vector(t_address, width, "address_ph", pip)
        width = len(self.bus.hwdata)
        t_value = self._create_vector(t_value, width, "data_ph", pip)
        width = len(self.bus.hsize)
        t_size = self._create_vector(t_size, width, "address_ph", pip)
        t_mode = [AHBWrite.READ for _ in range(len(t_address))]
        width = len(self.bus.hwrite)
        t_mode = self._create_vector(t_mode, width, "address_ph", pip)
        t_trans = [AHBTrans.NONSEQ for _ in range(len(t_address))]
        width = len(self.bus.htrans)
        t_trans = self._create_vector(t_trans, width, "address_ph", pip)
        width = 1
        t_exclusive = self._create_vector(t_exclusive, width, "address_ph", pip)

        return await self._send_txn(
            t_address,
            t_value,
            t_size,
            t_mode,
            t_trans,
            t_exclusive,
            pip,
            verbose,
            sync,
        )

    async def custom(
        self,
        address: Union[int, Sequence[int]],
        value: Union[int, Sequence[int]],
        mode: Union[int, Sequence[int]],
        size: Optional[Union[int, Sequence[int]]] = None,
        exclusive: Optional[Union[bool, Sequence[bool]]] = False,
        pip: Optional[bool] = True,
        pipeline_mode: Optional[AHBPipelineMode] = None,
        verbose: Optional[bool] = False,
        sync: Optional[bool] = False,
        format_amba: Optional[bool] = False,
    ) -> Sequence[dict]:
        """Back-to-Back operation"""

        if not isinstance(address, list):
            address = [address]
        if not isinstance(size, list):
            size = [size] if size is not None else None
        if not isinstance(value, list):
            value = [value]
        if not isinstance(mode, list):
            mode = [mode]

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

        if format_amba is True:
            value = self._fmt_amba(address, size, value)

        resolved_mode = self._resolve_pipeline_mode(pip, pipeline_mode)
        if not isinstance(exclusive, list):
            t_exclusive = [exclusive for _ in range(len(address))]
        else:
            t_exclusive = exclusive

        t_mode = [AHBWrite(m) for m in mode]

        if resolved_mode == AHBPipelineMode.CPU_LIKE:
            t_trans = [AHBTrans.NONSEQ for _ in range(len(address))]
            return await self._send_txn_cpu_like(
                address,
                value,
                size,
                t_mode,
                t_trans,
                t_exclusive,
                verbose,
                sync,
            )

        pip = resolved_mode == AHBPipelineMode.PIPELINED

        t_address = copy.deepcopy(address)
        t_value = copy.deepcopy(value)
        t_size = copy.deepcopy(size)

        width = len(self.bus.haddr)
        t_address = self._create_vector(t_address, width, "address_ph", pip)
        width = len(self.bus.hwdata)
        t_value = self._create_vector(t_value, width, "data_ph", pip)
        width = len(self.bus.hsize)
        t_size = self._create_vector(t_size, width, "address_ph", pip)
        width = len(self.bus.hwrite)
        t_mode = self._create_vector(t_mode, width, "address_ph", pip)
        t_trans = [AHBTrans.SEQ for _ in range(len(t_address))]
        t_trans[0] = AHBTrans.NONSEQ
        width = len(self.bus.htrans)
        t_trans = self._create_vector(t_trans, width, "address_ph", pip)
        width = 1
        t_exclusive = self._create_vector(t_exclusive, width, "address_ph", pip)

        return await self._send_txn(
            t_address,
            t_value,
            t_size,
            t_mode,
            t_trans,
            t_exclusive,
            pip,
            verbose,
            sync,
        )

    async def read_excl(
        self,
        address: Union[int, Sequence[int]],
        size: Optional[Union[int, Sequence[int]]] = None,
        **kwargs,
    ) -> Sequence[dict]:
        """Exclusive read (HEXCL asserted in address phase)."""
        return await self.read(address, size=size, exclusive=True, **kwargs)

    async def write_excl(
        self,
        address: Union[int, Sequence[int]],
        value: Union[int, Sequence[int]],
        size: Optional[Union[int, Sequence[int]]] = None,
        **kwargs,
    ) -> Sequence[dict]:
        """Exclusive write (HEXCL asserted in address phase)."""
        return await self.write(address, value, size=size, exclusive=True, **kwargs)


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
