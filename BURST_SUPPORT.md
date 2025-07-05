# AHB Burst Support

This document describes the enhanced AHB burst support in cocotbext-ahb, including the updated monitor and utility classes.

## Overview

The AHB monitor has been updated to properly handle all burst types, not just single transfers. The implementation now includes:

- **Burst-aware monitoring**: Full support for all AHB burst types (SINGLE, INCR, WRAP4, INCR4, WRAP8, INCR8, WRAP16, INCR16)
- **Burst validation**: Protocol compliance checking for burst sequences
- **Burst utilities**: Helper classes for burst generation and validation
- **Extensible design**: Foundation for adding burst support to master and slave

## Key Features

### 1. Enhanced AHB Monitor

The `AHBMonitor` class now tracks burst sequences and validates:
- Burst address sequences (incremental and wrapping)
- Burst parameter consistency (size, write mode)
- Burst length compliance
- Protocol violations

### 2. Extended AHBTxn Class

The `AHBTxn` class now includes burst information:
- `burst`: The burst type (AHBBurst enum)
- `trans`: The transfer type (AHBTrans enum)
- `is_burst_start`: Boolean indicating start of burst
- `is_burst_end`: Boolean indicating end of burst

### 3. AHBBurstUtils Class

Utility class providing static methods for:
- Burst address calculation
- Burst validation
- Burst sequence generation
- Burst transaction creation

### 4. AHBBurstValidator Class

Validator class for tracking active bursts:
- Burst state management
- Runtime validation
- Multiple burst tracking

## Usage Examples

### Basic Monitor Usage

```python
import cocotb
from cocotbext.ahb import AHBMonitor, AHBBus

@cocotb.test()
async def test_burst_monitor(dut):
    # Create AHB bus and monitor
    ahb_bus = AHBBus.from_entity(dut)
    monitor = AHBMonitor(ahb_bus, dut.clk, dut.rst)
    
    # Monitor will automatically detect and validate bursts
    await monitor.wait_for_recv()
    
    # Access burst information from transactions
    for txn in monitor.items:
        if txn.burst != AHBBurst.SINGLE:
            print(f"Burst transaction: {txn.burst.name}")
            print(f"Start: {txn.is_burst_start}, End: {txn.is_burst_end}")
```

### Using AHBBurstUtils

```python
from cocotbext.ahb import AHBBurstUtils, AHBBurst, AHBSize, AHBWrite

# Generate burst sequence
addresses = AHBBurstUtils.generate_burst_sequence(
    start_addr=0x1000,
    burst_type=AHBBurst.INCR4,
    size=AHBSize.WORD
)
print(f"INCR4 addresses: {[hex(addr) for addr in addresses]}")

# Create burst transactions
transactions = AHBBurstUtils.create_burst_transactions(
    start_addr=0x2000,
    burst_type=AHBBurst.WRAP4,
    size=AHBSize.WORD,
    write_mode=AHBWrite.WRITE,
    data=[0x11111111, 0x22222222, 0x33333333, 0x44444444]
)

# Validate burst alignment
is_aligned = AHBBurstUtils.validate_burst_alignment(
    address=0x1000,
    burst_type=AHBBurst.WRAP4,
    size=AHBSize.WORD
)
```

### Using AHBBurstValidator

```python
from cocotbext.ahb import AHBBurstValidator

# Create validator
validator = AHBBurstValidator()

# Start tracking a burst
validator.start_burst(
    burst_id="burst_1",
    start_addr=0x1000,
    burst_type=AHBBurst.INCR4,
    size=AHBSize.WORD,
    write_mode=AHBWrite.READ
)

# Continue burst validation
valid = validator.continue_burst("burst_1", 0x1004)
if not valid:
    print("Burst validation failed!")

# End burst
completed = validator.end_burst("burst_1")
```

## Burst Types Supported

| Burst Type | Description | Length | Address Pattern |
|------------|-------------|---------|-----------------|
| SINGLE     | Single transfer | 1 | N/A |
| INCR       | Incremental (undefined length) | Variable | Linear increment |
| WRAP4      | 4-beat wrapping | 4 | Wrapping boundary |
| INCR4      | 4-beat incremental | 4 | Linear increment |
| WRAP8      | 8-beat wrapping | 8 | Wrapping boundary |
| INCR8      | 8-beat incremental | 8 | Linear increment |
| WRAP16     | 16-beat wrapping | 16 | Wrapping boundary |
| INCR16     | 16-beat incremental | 16 | Linear increment |

## Burst Address Calculation

### Incremental Bursts (INCR, INCR4, INCR8, INCR16)
- Address increments by transfer size for each beat
- No wrapping behavior
- Example: 0x1000, 0x1004, 0x1008, 0x100C (for WORD transfers)

### Wrapping Bursts (WRAP4, WRAP8, WRAP16)
- Address wraps at burst boundary
- Boundary = number of beats × transfer size
- Example WRAP4 WORD: 0x1000, 0x1004, 0x1008, 0x100C, 0x1000, ...

## Protocol Validation

The monitor validates the following AHB protocol rules:

1. **Burst Consistency**: All transfers in a burst must have the same size and direction
2. **Address Alignment**: Burst starting addresses must be properly aligned
3. **Address Sequence**: Addresses must follow the expected pattern for the burst type
4. **Transfer Type**: First transfer is NONSEQ, subsequent transfers are SEQ
5. **Burst Length**: Defined-length bursts must complete with the correct number of beats

## Future Enhancements

The current implementation provides a solid foundation for adding burst support to master and slave components:

### Master Enhancements
- Add burst generation methods to `AHBLiteMaster`
- Support for all burst types in read/write operations
- Configurable burst parameters

### Slave Enhancements
- Burst-aware memory models
- Burst optimization for faster transfers
- Burst-specific error handling

### Example Future API
```python
# Future master burst API
await master.burst_write(
    start_addr=0x1000,
    burst_type=AHBBurst.INCR4,
    size=AHBSize.WORD,
    data=[0x11111111, 0x22222222, 0x33333333, 0x44444444]
)

await master.burst_read(
    start_addr=0x2000,
    burst_type=AHBBurst.WRAP8,
    size=AHBSize.WORD
)
```

## Migration Guide

### From Single-Transfer Code
If you're currently using the monitor with single transfers, no changes are required. The monitor maintains backward compatibility while adding burst support.

### New Features Available
- Access burst information in transaction objects
- Use burst utilities for address calculation
- Validate burst sequences in your testbenches

## Error Handling

The monitor will raise `AssertionError` exceptions for:
- Invalid burst address sequences
- Inconsistent burst parameters
- Protocol violations
- Burst length mismatches

## Performance Considerations

- Burst validation adds minimal overhead to monitoring
- Burst utilities are optimized for common use cases
- Memory usage scales with number of active bursts being tracked