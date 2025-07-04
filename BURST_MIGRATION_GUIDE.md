# AHB Burst Mode Migration Guide

## Overview

This guide outlines the migration from single burst mode (`AHBBurst.SINGLE`) to supporting multiple burst modes in the cocotbext-ahb project.

## Current State

The current implementation only supports:
- `AHBBurst.SINGLE` - hardcoded in `_addr_phase` method
- `AHBTrans.NONSEQ` - all transactions are non-sequential
- No burst logic for multi-beat transactions

## Target Burst Modes

The AHB specification defines these burst types (already in `AHBBurst` enum):
- `SINGLE` (0b000) - Single transfer
- `INCR` (0b001) - Incrementing burst of unspecified length
- `WRAP4` (0b010) - 4-beat wrapping burst
- `INCR4` (0b011) - 4-beat incrementing burst  
- `WRAP8` (0b100) - 8-beat wrapping burst
- `INCR8` (0b101) - 8-beat incrementing burst
- `WRAP16` (0b110) - 16-beat wrapping burst
- `INCR16` (0b111) - 16-beat incrementing burst

## Migration Steps

### 1. Update AHB Master API

#### Add burst parameter to methods:
```python
async def write(
    self,
    address: Union[int, Sequence[int]],
    value: Union[int, Sequence[int]],
    size: Optional[Union[int, Sequence[int]]] = None,
    burst: Optional[Union[AHBBurst, Sequence[AHBBurst]]] = AHBBurst.SINGLE,  # NEW
    pip: Optional[bool] = False,
    verbose: Optional[bool] = False,
    sync: Optional[bool] = False,
    format_amba: Optional[bool] = False,
) -> Sequence[dict]:
```

#### Update internal transaction logic:
- Replace hardcoded `AHBBurst.SINGLE` with configurable burst type
- Implement burst address generation (incrementing/wrapping)
- Handle `AHBTrans.SEQ` for continuation beats
- Update `_addr_phase` to accept burst parameter

### 2. Implement Burst Logic

#### Address Generation:
```python
def _generate_burst_addresses(self, base_addr: int, burst_type: AHBBurst, 
                            size: int, beats: int) -> List[int]:
    """Generate addresses for burst transactions"""
    addresses = [base_addr]
    
    if burst_type == AHBBurst.SINGLE:
        return addresses
    
    # Calculate address increment based on transfer size
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
            # Implement wrapping logic
            addresses.append(self._wrap_address(next_addr, base_addr, wrap_boundary))
    
    return addresses
```

#### Transaction Type Logic:
```python
def _generate_burst_trans(self, burst_type: AHBBurst, beats: int) -> List[AHBTrans]:
    """Generate transaction types for burst"""
    if burst_type == AHBBurst.SINGLE or beats == 1:
        return [AHBTrans.NONSEQ]
    
    # First beat is NONSEQ, subsequent beats are SEQ
    trans_types = [AHBTrans.NONSEQ]
    trans_types.extend([AHBTrans.SEQ] * (beats - 1))
    return trans_types
```

### 3. Update Slave Implementation

#### Handle burst transactions:
- Recognize burst sequences (NONSEQ followed by SEQ)
- Maintain burst state across multiple beats
- Handle early termination and error responses during bursts

```python
def _handle_burst_transaction(self, trans: AHBTrans, burst: AHBBurst):
    """Handle burst transaction state"""
    if trans == AHBTrans.NONSEQ:
        # Start new burst
        self._current_burst = burst
        self._burst_beat = 0
    elif trans == AHBTrans.SEQ:
        # Continue burst
        self._burst_beat += 1
```

### 4. Update Monitor

#### Add burst protocol checks:
- Verify burst address sequences
- Check transaction type consistency
- Validate wrapping boundaries

### 5. API Changes

#### Backward Compatibility:
- Default `burst=AHBBurst.SINGLE` maintains existing behavior
- All existing tests continue to work without modification

#### New Usage Examples:
```python
# 4-beat incrementing burst
await master.write(0x1000, [0x11, 0x22, 0x33, 0x44], 
                  size=4, burst=AHBBurst.INCR4)

# 8-beat wrapping burst  
await master.read(0x2000, size=4, burst=AHBBurst.WRAP8)

# Mixed burst types
await master.write([0x1000, 0x2000], [0x11, 0x22], 
                  burst=[AHBBurst.INCR4, AHBBurst.SINGLE])
```

## Implementation Priority

1. **Phase 1**: Update AHB Master API and basic burst logic
2. **Phase 2**: Implement address generation for all burst types  
3. **Phase 3**: Update AHB Slave to handle burst transactions
4. **Phase 4**: Add comprehensive burst tests
5. **Phase 5**: Update monitor for burst protocol checking

## Testing Strategy

1. **Unit Tests**: Test address generation for each burst type
2. **Integration Tests**: Test master-slave burst communication
3. **Protocol Tests**: Verify AHB specification compliance
4. **Regression Tests**: Ensure existing functionality unchanged

## Benefits

- Full AHB specification compliance
- Improved performance for bulk transfers
- Better modeling of real-world AHB usage
- Enhanced test coverage for burst scenarios

## Breaking Changes

None - the migration maintains backward compatibility by defaulting to single burst mode.

## Files to Modify

1. `cocotbext/ahb/ahb_master.py` - Main burst implementation
2. `cocotbext/ahb/ahb_slave.py` - Slave burst handling
3. `cocotbext/ahb/ahb_monitor.py` - Burst protocol checks
4. `tests/` - Add burst test cases
5. `README.md` - Update documentation

This migration will transform the project from supporting only single transfers to full AHB burst capability while maintaining backward compatibility.