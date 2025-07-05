#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File              : ahb_burst_utils.py
# License           : MIT license <Check LICENSE>
# Author            : Anderson I. da Silva (aignacio) <anderson@aignacio.com>
# Date              : 01.10.2024
# Last Modified Date: 01.10.2024

from typing import List, Tuple, Dict, Optional
from .ahb_types import AHBBurst, AHBSize, AHBTrans, AHBWrite


class AHBBurstUtils:
    """Utility class for AHB burst operations."""
    
    @staticmethod
    def get_burst_length(burst_type: AHBBurst) -> int:
        """Get the expected number of beats for a burst type.
        
        Args:
            burst_type: The burst type
            
        Returns:
            Number of beats (0 for undefined length INCR)
        """
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
    
    @staticmethod
    def get_wrap_boundary(burst_type: AHBBurst, size: AHBSize) -> int:
        """Get the wrap boundary for wrapping bursts.
        
        Args:
            burst_type: The burst type
            size: Transfer size
            
        Returns:
            Wrap boundary in bytes
        """
        if burst_type not in [AHBBurst.WRAP4, AHBBurst.WRAP8, AHBBurst.WRAP16]:
            return 0
        
        byte_size = 2 ** size.value
        
        if burst_type == AHBBurst.WRAP4:
            return 4 * byte_size
        elif burst_type == AHBBurst.WRAP8:
            return 8 * byte_size
        else:  # WRAP16
            return 16 * byte_size
    
    @staticmethod
    def calculate_next_address(current_addr: int, burst_type: AHBBurst, size: AHBSize) -> int:
        """Calculate the next address in a burst sequence.
        
        Args:
            current_addr: Current address
            burst_type: Type of burst
            size: Transfer size
            
        Returns:
            Next address in the burst sequence
        """
        byte_size = 2 ** size.value
        
        if burst_type == AHBBurst.SINGLE:
            return current_addr
        elif burst_type == AHBBurst.INCR or burst_type in [AHBBurst.INCR4, AHBBurst.INCR8, AHBBurst.INCR16]:
            # Incremental bursts
            return current_addr + byte_size
        elif burst_type in [AHBBurst.WRAP4, AHBBurst.WRAP8, AHBBurst.WRAP16]:
            # Wrapping bursts
            wrap_boundary = AHBBurstUtils.get_wrap_boundary(burst_type, size)
            aligned_start = (current_addr // wrap_boundary) * wrap_boundary
            next_addr = current_addr + byte_size
            
            if next_addr >= aligned_start + wrap_boundary:
                next_addr = aligned_start
            return next_addr
        
        return current_addr
    
    @staticmethod
    def validate_burst_address(expected_addr: int, actual_addr: int, burst_type: AHBBurst) -> bool:
        """Validate that the burst address follows the expected pattern.
        
        Args:
            expected_addr: Expected address
            actual_addr: Actual address
            burst_type: Type of burst
            
        Returns:
            True if address is valid for the burst type
        """
        if burst_type == AHBBurst.INCR:
            # INCR bursts can have any addressing pattern
            return True
        return expected_addr == actual_addr
    
    @staticmethod
    def validate_burst_alignment(address: int, burst_type: AHBBurst, size: AHBSize) -> bool:
        """Validate that the burst starting address is properly aligned.
        
        Args:
            address: Starting address
            burst_type: Type of burst
            size: Transfer size
            
        Returns:
            True if address is properly aligned
        """
        if burst_type == AHBBurst.SINGLE or burst_type == AHBBurst.INCR:
            # Single transfers and undefined length INCR only need transfer size alignment
            return (address % (2 ** size.value)) == 0
        
        # For defined length bursts, check boundary alignment
        wrap_boundary = AHBBurstUtils.get_wrap_boundary(burst_type, size)
        if wrap_boundary > 0:
            return (address % wrap_boundary) == 0
        
        # For INCR4/8/16, check transfer size alignment
        return (address % (2 ** size.value)) == 0
    
    @staticmethod
    def generate_burst_sequence(
        start_addr: int,
        burst_type: AHBBurst,
        size: AHBSize,
        length: Optional[int] = None
    ) -> List[int]:
        """Generate a sequence of addresses for a burst.
        
        Args:
            start_addr: Starting address
            burst_type: Type of burst
            size: Transfer size
            length: Length for undefined bursts (optional)
            
        Returns:
            List of addresses in the burst sequence
        """
        if burst_type == AHBBurst.SINGLE:
            return [start_addr]
        
        burst_length = AHBBurstUtils.get_burst_length(burst_type)
        if burst_length == 0:  # INCR burst
            if length is None:
                raise ValueError("Length must be specified for INCR bursts")
            burst_length = length
        
        addresses = [start_addr]
        current_addr = start_addr
        
        for _ in range(burst_length - 1):
            current_addr = AHBBurstUtils.calculate_next_address(current_addr, burst_type, size)
            addresses.append(current_addr)
        
        return addresses
    
    @staticmethod
    def create_burst_transactions(
        start_addr: int,
        burst_type: AHBBurst,
        size: AHBSize,
        write_mode: AHBWrite,
        data: Optional[List[int]] = None,
        length: Optional[int] = None
    ) -> List[Dict]:
        """Create a list of transaction dictionaries for a burst.
        
        Args:
            start_addr: Starting address
            burst_type: Type of burst
            size: Transfer size
            write_mode: Read or write mode
            data: Data values for write transactions
            length: Length for undefined bursts (optional)
            
        Returns:
            List of transaction dictionaries
        """
        addresses = AHBBurstUtils.generate_burst_sequence(start_addr, burst_type, size, length)
        
        if data is None:
            data = [0] * len(addresses)
        elif len(data) != len(addresses):
            raise ValueError(f"Data length ({len(data)}) doesn't match burst length ({len(addresses)})")
        
        transactions = []
        for i, (addr, value) in enumerate(zip(addresses, data)):
            trans_type = AHBTrans.NONSEQ if i == 0 else AHBTrans.SEQ
            
            transaction = {
                "haddr": addr,
                "hsize": size,
                "hwrite": write_mode,
                "htrans": trans_type,
                "hburst": burst_type,
                "hwdata": value if write_mode == AHBWrite.WRITE else 0,
                "is_burst_start": i == 0,
                "is_burst_end": i == len(addresses) - 1
            }
            transactions.append(transaction)
        
        return transactions
    
    @staticmethod
    def get_burst_info(burst_type: AHBBurst) -> Dict:
        """Get information about a burst type.
        
        Args:
            burst_type: The burst type
            
        Returns:
            Dictionary with burst information
        """
        return {
            "name": burst_type.name,
            "value": burst_type.value,
            "length": AHBBurstUtils.get_burst_length(burst_type),
            "is_wrapping": burst_type in [AHBBurst.WRAP4, AHBBurst.WRAP8, AHBBurst.WRAP16],
            "is_incremental": burst_type in [AHBBurst.INCR, AHBBurst.INCR4, AHBBurst.INCR8, AHBBurst.INCR16],
            "is_single": burst_type == AHBBurst.SINGLE,
            "is_undefined_length": burst_type == AHBBurst.INCR
        }


class AHBBurstValidator:
    """Validator class for AHB burst operations."""
    
    def __init__(self):
        self.active_bursts = {}
    
    def start_burst(self, burst_id: str, start_addr: int, burst_type: AHBBurst, size: AHBSize, write_mode: AHBWrite):
        """Start tracking a new burst.
        
        Args:
            burst_id: Unique identifier for the burst
            start_addr: Starting address
            burst_type: Type of burst
            size: Transfer size
            write_mode: Read or write mode
        """
        if not AHBBurstUtils.validate_burst_alignment(start_addr, burst_type, size):
            raise ValueError(f"Invalid burst alignment for address 0x{start_addr:08X}")
        
        self.active_bursts[burst_id] = {
            "start_addr": start_addr,
            "current_addr": start_addr,
            "burst_type": burst_type,
            "size": size,
            "write_mode": write_mode,
            "beat_count": 1,
            "expected_beats": AHBBurstUtils.get_burst_length(burst_type)
        }
    
    def continue_burst(self, burst_id: str, addr: int) -> bool:
        """Continue a burst with validation.
        
        Args:
            burst_id: Unique identifier for the burst
            addr: Current address
            
        Returns:
            True if the burst continuation is valid
        """
        if burst_id not in self.active_bursts:
            return False
        
        burst = self.active_bursts[burst_id]
        expected_addr = AHBBurstUtils.calculate_next_address(
            burst["current_addr"], burst["burst_type"], burst["size"]
        )
        
        if not AHBBurstUtils.validate_burst_address(expected_addr, addr, burst["burst_type"]):
            return False
        
        burst["current_addr"] = addr
        burst["beat_count"] += 1
        
        # Check if we've exceeded expected beats
        if burst["expected_beats"] > 0 and burst["beat_count"] > burst["expected_beats"]:
            return False
        
        return True
    
    def end_burst(self, burst_id: str) -> bool:
        """End a burst with validation.
        
        Args:
            burst_id: Unique identifier for the burst
            
        Returns:
            True if the burst ended correctly
        """
        if burst_id not in self.active_bursts:
            return False
        
        burst = self.active_bursts[burst_id]
        valid = True
        
        # Check if we completed the expected number of beats
        if burst["expected_beats"] > 0 and burst["beat_count"] != burst["expected_beats"]:
            valid = False
        
        del self.active_bursts[burst_id]
        return valid
    
    def is_burst_active(self, burst_id: str) -> bool:
        """Check if a burst is currently active.
        
        Args:
            burst_id: Unique identifier for the burst
            
        Returns:
            True if the burst is active
        """
        return burst_id in self.active_bursts
    
    def get_burst_status(self, burst_id: str) -> Optional[Dict]:
        """Get the status of an active burst.
        
        Args:
            burst_id: Unique identifier for the burst
            
        Returns:
            Dictionary with burst status or None if not active
        """
        return self.active_bursts.get(burst_id)