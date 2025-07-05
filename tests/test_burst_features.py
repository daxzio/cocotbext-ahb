#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Test file demonstrating the new AHB burst features

try:
    import pytest
except ImportError:
    pytest = None

from cocotbext.ahb import (
    AHBBurstUtils, 
    AHBBurstValidator, 
    AHBBurst, 
    AHBSize, 
    AHBWrite, 
    AHBTrans,
    AHBTxn
)


class TestAHBBurstUtils:
    """Test cases for AHBBurstUtils class."""
    
    def test_burst_length_calculation(self):
        """Test burst length calculation for different burst types."""
        assert AHBBurstUtils.get_burst_length(AHBBurst.SINGLE) == 1
        assert AHBBurstUtils.get_burst_length(AHBBurst.INCR) == 0  # Undefined
        assert AHBBurstUtils.get_burst_length(AHBBurst.WRAP4) == 4
        assert AHBBurstUtils.get_burst_length(AHBBurst.INCR4) == 4
        assert AHBBurstUtils.get_burst_length(AHBBurst.WRAP8) == 8
        assert AHBBurstUtils.get_burst_length(AHBBurst.INCR8) == 8
        assert AHBBurstUtils.get_burst_length(AHBBurst.WRAP16) == 16
        assert AHBBurstUtils.get_burst_length(AHBBurst.INCR16) == 16
    
    def test_wrap_boundary_calculation(self):
        """Test wrap boundary calculation."""
        # WRAP4 with WORD (4 bytes) = 16 bytes boundary
        assert AHBBurstUtils.get_wrap_boundary(AHBBurst.WRAP4, AHBSize.WORD) == 16
        # WRAP8 with HWORD (2 bytes) = 16 bytes boundary
        assert AHBBurstUtils.get_wrap_boundary(AHBBurst.WRAP8, AHBSize.HWORD) == 16
        # WRAP16 with BYTE (1 byte) = 16 bytes boundary
        assert AHBBurstUtils.get_wrap_boundary(AHBBurst.WRAP16, AHBSize.BYTE) == 16
        # Non-wrapping bursts return 0
        assert AHBBurstUtils.get_wrap_boundary(AHBBurst.INCR4, AHBSize.WORD) == 0
    
    def test_incremental_address_calculation(self):
        """Test address calculation for incremental bursts."""
        # INCR4 with WORD size
        addresses = []
        current_addr = 0x1000
        addresses.append(current_addr)
        
        for _ in range(3):  # 3 more beats
            current_addr = AHBBurstUtils.calculate_next_address(
                current_addr, AHBBurst.INCR4, AHBSize.WORD
            )
            addresses.append(current_addr)
        
        expected = [0x1000, 0x1004, 0x1008, 0x100C]
        assert addresses == expected
    
    def test_wrapping_address_calculation(self):
        """Test address calculation for wrapping bursts."""
        # WRAP4 with WORD size starting at boundary
        addresses = []
        current_addr = 0x1000  # 16-byte aligned
        addresses.append(current_addr)
        
        for _ in range(7):  # 7 more beats to show wrapping
            current_addr = AHBBurstUtils.calculate_next_address(
                current_addr, AHBBurst.WRAP4, AHBSize.WORD
            )
            addresses.append(current_addr)
        
        expected = [0x1000, 0x1004, 0x1008, 0x100C, 0x1000, 0x1004, 0x1008, 0x100C]
        assert addresses == expected
    
    def test_burst_alignment_validation(self):
        """Test burst alignment validation."""
        # WRAP4 with WORD - must be 16-byte aligned
        assert AHBBurstUtils.validate_burst_alignment(0x1000, AHBBurst.WRAP4, AHBSize.WORD) == True
        assert AHBBurstUtils.validate_burst_alignment(0x1004, AHBBurst.WRAP4, AHBSize.WORD) == False
        
        # INCR4 with WORD - must be 4-byte aligned
        assert AHBBurstUtils.validate_burst_alignment(0x1004, AHBBurst.INCR4, AHBSize.WORD) == True
        assert AHBBurstUtils.validate_burst_alignment(0x1001, AHBBurst.INCR4, AHBSize.WORD) == False
        
        # SINGLE with BYTE - any alignment
        assert AHBBurstUtils.validate_burst_alignment(0x1001, AHBBurst.SINGLE, AHBSize.BYTE) == True
    
    def test_burst_sequence_generation(self):
        """Test burst sequence generation."""
        # INCR4 sequence
        addresses = AHBBurstUtils.generate_burst_sequence(
            0x2000, AHBBurst.INCR4, AHBSize.WORD
        )
        expected = [0x2000, 0x2004, 0x2008, 0x200C]
        assert addresses == expected
        
        # WRAP4 sequence
        addresses = AHBBurstUtils.generate_burst_sequence(
            0x3000, AHBBurst.WRAP4, AHBSize.HWORD
        )
        expected = [0x3000, 0x3002, 0x3004, 0x3006]
        assert addresses == expected
        
        # INCR with custom length
        addresses = AHBBurstUtils.generate_burst_sequence(
            0x4000, AHBBurst.INCR, AHBSize.WORD, length=3
        )
        expected = [0x4000, 0x4004, 0x4008]
        assert addresses == expected
    
    def test_burst_transaction_creation(self):
        """Test burst transaction creation."""
        transactions = AHBBurstUtils.create_burst_transactions(
            start_addr=0x5000,
            burst_type=AHBBurst.INCR4,
            size=AHBSize.WORD,
            write_mode=AHBWrite.WRITE,
            data=[0x11111111, 0x22222222, 0x33333333, 0x44444444]
        )
        
        assert len(transactions) == 4
        
        # Check first transaction
        assert transactions[0]["haddr"] == 0x5000
        assert transactions[0]["htrans"] == AHBTrans.NONSEQ
        assert transactions[0]["is_burst_start"] == True
        assert transactions[0]["is_burst_end"] == False
        assert transactions[0]["hwdata"] == 0x11111111
        
        # Check middle transaction
        assert transactions[1]["haddr"] == 0x5004
        assert transactions[1]["htrans"] == AHBTrans.SEQ
        assert transactions[1]["is_burst_start"] == False
        assert transactions[1]["is_burst_end"] == False
        
        # Check last transaction
        assert transactions[3]["haddr"] == 0x500C
        assert transactions[3]["htrans"] == AHBTrans.SEQ
        assert transactions[3]["is_burst_start"] == False
        assert transactions[3]["is_burst_end"] == True
        assert transactions[3]["hwdata"] == 0x44444444
    
    def test_burst_info(self):
        """Test burst information retrieval."""
        info = AHBBurstUtils.get_burst_info(AHBBurst.INCR4)
        assert info["name"] == "INCR4"
        assert info["length"] == 4
        assert info["is_incremental"] == True
        assert info["is_wrapping"] == False
        assert info["is_single"] == False
        assert info["is_undefined_length"] == False
        
        info = AHBBurstUtils.get_burst_info(AHBBurst.WRAP8)
        assert info["name"] == "WRAP8"
        assert info["length"] == 8
        assert info["is_incremental"] == False
        assert info["is_wrapping"] == True


class TestAHBBurstValidator:
    """Test cases for AHBBurstValidator class."""
    
    def test_burst_lifecycle(self):
        """Test complete burst lifecycle."""
        validator = AHBBurstValidator()
        
        # Start burst
        validator.start_burst(
            "test_burst",
            0x1000,
            AHBBurst.INCR4,
            AHBSize.WORD,
            AHBWrite.READ
        )
        
        assert validator.is_burst_active("test_burst") == True
        
        # Continue burst
        assert validator.continue_burst("test_burst", 0x1004) == True
        assert validator.continue_burst("test_burst", 0x1008) == True
        assert validator.continue_burst("test_burst", 0x100C) == True
        
        # End burst
        assert validator.end_burst("test_burst") == True
        assert validator.is_burst_active("test_burst") == False
    
    def test_burst_validation_errors(self):
        """Test burst validation error cases."""
        validator = AHBBurstValidator()
        
        # Invalid alignment should raise error
        try:
            validator.start_burst(
                "bad_burst",
                0x1001,  # Not aligned for WORD
                AHBBurst.INCR4,
                AHBSize.WORD,
                AHBWrite.READ
            )
            assert False, "Expected ValueError to be raised"
        except ValueError:
            pass  # Expected behavior
        
        # Start valid burst
        validator.start_burst(
            "test_burst",
            0x2000,
            AHBBurst.INCR4,
            AHBSize.WORD,
            AHBWrite.READ
        )
        
        # Invalid address continuation
        assert validator.continue_burst("test_burst", 0x2008) == False  # Should be 0x2004
        
        # Continue with non-existent burst
        assert validator.continue_burst("non_existent", 0x3000) == False
        
        # End non-existent burst
        assert validator.end_burst("non_existent") == False
    
    def test_burst_status_tracking(self):
        """Test burst status tracking."""
        validator = AHBBurstValidator()
        
        validator.start_burst(
            "status_test",
            0x4000,
            AHBBurst.WRAP4,
            AHBSize.HWORD,
            AHBWrite.WRITE
        )
        
        status = validator.get_burst_status("status_test")
        assert status is not None
        assert status["start_addr"] == 0x4000
        assert status["burst_type"] == AHBBurst.WRAP4
        assert status["size"] == AHBSize.HWORD
        assert status["write_mode"] == AHBWrite.WRITE
        assert status["beat_count"] == 1
        assert status["expected_beats"] == 4
        
        # Continue burst and check updated status
        validator.continue_burst("status_test", 0x4002)
        status = validator.get_burst_status("status_test")
        assert status is not None
        assert status["beat_count"] == 2
        assert status["current_addr"] == 0x4002


class TestAHBTxn:
    """Test cases for enhanced AHBTxn class."""
    
    def test_txn_burst_fields(self):
        """Test AHBTxn with burst fields."""
        txn = AHBTxn(
            addr=0x1000,
            size=AHBSize.WORD,
            mode=AHBWrite.READ,
            burst=AHBBurst.INCR4,
            trans=AHBTrans.NONSEQ,
            is_burst_start=True,
            is_burst_end=False
        )
        
        assert txn.addr == 0x1000
        assert txn.burst == AHBBurst.INCR4
        assert txn.trans == AHBTrans.NONSEQ
        assert txn.is_burst_start == True
        assert txn.is_burst_end == False
    
    def test_txn_string_representation(self):
        """Test AHBTxn string representation includes burst info."""
        txn = AHBTxn(
            addr=0x2000,
            size=AHBSize.WORD,
            mode=AHBWrite.WRITE,
            burst=AHBBurst.WRAP4,
            trans=AHBTrans.SEQ,
            is_burst_start=False,
            is_burst_end=True,
            wdata=0x12345678
        )
        
        txn_str = str(txn)
        assert "WRAP4" in txn_str
        assert "SEQ" in txn_str
        assert "Continue End" in txn_str
    
    def test_txn_equality_with_burst(self):
        """Test AHBTxn equality comparison includes burst fields."""
        txn1 = AHBTxn(
            addr=0x1000,
            burst=AHBBurst.INCR4,
            trans=AHBTrans.NONSEQ,
            is_burst_start=True,
            is_burst_end=False
        )
        
        txn2 = AHBTxn(
            addr=0x1000,
            burst=AHBBurst.INCR4,
            trans=AHBTrans.NONSEQ,
            is_burst_start=True,
            is_burst_end=False
        )
        
        txn3 = AHBTxn(
            addr=0x1000,
            burst=AHBBurst.WRAP4,  # Different burst type
            trans=AHBTrans.NONSEQ,
            is_burst_start=True,
            is_burst_end=False
        )
        
        assert txn1 == txn2
        assert txn1 != txn3


if __name__ == "__main__":
    # Run tests manually for demonstration
    print("Testing AHB Burst Features...")
    
    # Test burst utils
    print("\n1. Testing burst sequence generation:")
    addresses = AHBBurstUtils.generate_burst_sequence(0x1000, AHBBurst.INCR4, AHBSize.WORD)
    print(f"INCR4 sequence: {[hex(addr) for addr in addresses]}")
    
    addresses = AHBBurstUtils.generate_burst_sequence(0x2000, AHBBurst.WRAP4, AHBSize.WORD)
    print(f"WRAP4 sequence: {[hex(addr) for addr in addresses]}")
    
    # Test burst validator
    print("\n2. Testing burst validator:")
    validator = AHBBurstValidator()
    validator.start_burst("test", 0x3000, AHBBurst.INCR4, AHBSize.WORD, AHBWrite.READ)
    print(f"Burst started: {validator.is_burst_active('test')}")
    
    valid = validator.continue_burst("test", 0x3004)
    print(f"Continue burst valid: {valid}")
    
    status = validator.get_burst_status("test")
    if status:
        print(f"Beat count: {status['beat_count']}")
    
    # Test transaction creation
    print("\n3. Testing transaction creation:")
    transactions = AHBBurstUtils.create_burst_transactions(
        0x4000, AHBBurst.INCR4, AHBSize.WORD, AHBWrite.WRITE,
        data=[0x11111111, 0x22222222, 0x33333333, 0x44444444]
    )
    
    for i, txn in enumerate(transactions):
        print(f"Transaction {i}: addr=0x{txn['haddr']:08X}, "
              f"trans={txn['htrans'].name}, data=0x{txn['hwdata']:08X}")
    
    print("\nAll tests completed successfully!")