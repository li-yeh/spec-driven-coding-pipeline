# Technical Specification: Thread-Safe Token Bucket Rate Limiter

## 1. Overview
Implement a lightweight, thread-safe **Token Bucket Rate Limiter** in Python (`token_bucket.py`) using only the Python standard library (`threading`, `time`, `typing`).

The component controls the rate at which operations are permitted by refilling tokens continuously at a fixed rate up to a maximum burst capacity.

---

## 2. Module & Public API

Create `token_bucket.py` exposing a class `TokenBucket`:

```python
from collections.abc import Callable
import time


class TokenBucket:
    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        *,
        initial_tokens: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None: ...

    @property
    def capacity(self) -> float: ...

    @property
    def refill_rate(self) -> float: ...

    @property
    def available_tokens(self) -> float: ...

    def try_acquire(self, tokens: float = 1.0) -> bool: ...

    def acquire(self, tokens: float = 1.0, timeout: float | None = None) -> bool: ...
```

---

## 3. Functional Requirements

### 3.1 Initialization & Validation
1. `capacity` must be finite and strictly greater than `0` (`capacity > 0`); otherwise raise `ValueError`.
2. `refill_rate` (tokens per second) must be finite and strictly greater than `0` (`refill_rate > 0`); otherwise raise `ValueError`.
3. `initial_tokens`:
   - Defaults to `capacity` when `None`.
   - Must be finite and satisfy `0 <= initial_tokens <= capacity`; otherwise raise `ValueError`.
4. Reject `NaN` and `inf` / `-inf` for all numeric parameters (`math.isfinite`).
5. `clock` defaults to `time.monotonic` and is used for all time calculations so unit tests can inject a deterministic fake clock.

### 3.2 Continuous Refill Semantics
- On every state inspection or acquisition, refill tokens lazily based on elapsed time:
  `delta = max(0.0, clock() - last_refill_time)`
  `tokens = min(capacity, current_tokens + delta * refill_rate)`
- Handle non-monotonic or stalled custom clocks defensively (never subtract tokens if `clock() < last_refill_time`).
- `available_tokens` must return the refilled token count at the moment of access in a thread-safe manner.

### 3.3 Non-Blocking Acquisition: `try_acquire(tokens=1.0)`
- Validate `tokens`: must be finite and satisfy `0 < tokens <= capacity`; otherwise raise `ValueError`.
- Refill tokens, then:
  - If `available >= tokens`: deduct `tokens` atomically and return `True`.
  - Otherwise: leave token balance unchanged and return `False`.

### 3.4 Blocking Acquisition: `acquire(tokens=1.0, timeout=None)`
- Validate `tokens`: must be finite and satisfy `0 < tokens <= capacity`; otherwise raise `ValueError`.
- Validate `timeout`: if not `None`, must be finite and `>= 0`; otherwise raise `ValueError`.
- Behavior:
  - If enough tokens are available immediately, deduct and return `True`.
  - If `timeout == 0`, behave identically to `try_acquire(tokens)`.
  - Otherwise, wait until enough tokens accumulate (or until `timeout` expires using `clock`).
  - Avoid busy-waiting: sleep/wait using a `threading.Condition` for the estimated remaining wait time `(needed / refill_rate)`, capped by the remaining timeout.
  - If the deadline expires before `tokens` can be acquired, return `False` without deducting tokens.

---

## 4. Concurrency & Edge-Case Requirements

1. **Thread Safety**: Concurrent calls to `try_acquire`, `acquire`, and `available_tokens` from multiple threads must never over-issue tokens or corrupt internal state.
2. **No Oversubscription**: Under heavy contention (e.g., 20 worker threads racing for tokens from a bucket with `capacity=10`, low refill rate), the total granted tokens within a tight time window must never exceed `capacity + elapsed * refill_rate`.
3. **Request Exceeding Capacity**: Calling `try_acquire(capacity + 1)` or `acquire(capacity + 1)` must raise `ValueError` immediately rather than blocking forever.
4. **Zero / Negative / NaN Requests**: Calling `try_acquire(0)`, `try_acquire(-1)`, `acquire(float("nan"))`, or `acquire(1, timeout=-0.1)` must raise `ValueError`.
5. **Floating-Point Tolerance**: Ensure exact-boundary refills (e.g., `capacity=10, refill_rate=2.0`, advancing fake clock by `5.0` seconds) reliably refill to `10.0` without getting stuck slightly below `capacity`.

---

## 5. Verification Criteria

Provide or run a `pytest` suite (`test_token_bucket.py` or temporary verification under `_ai_tmp/`) covering:
- Parameter validation (`capacity`, `refill_rate`, `initial_tokens`, `tokens`, `timeout`, `NaN`, `inf`).
- Deterministic refill with an injected fake clock (partial refill, cap at `capacity`, backwards clock safety).
- `try_acquire` success and failure paths without side effects on failure.
- `acquire` blocking wait success and timeout expiration (`timeout=0` and small positive `timeout`).
- Multi-threaded stress test verifying strict upper bound on granted tokens.
