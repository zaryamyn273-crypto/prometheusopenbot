import asyncio
import time
import logging
from enum import Enum
from typing import Callable, Any, Optional, Dict

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "CLOSED"        # Normal operation: requests pass through
    OPEN = "OPEN"            # Tripped: requests fail fast or use fallback
    HALF_OPEN = "HALF_OPEN"  # Testing recovery: limited trial requests allowed


class CircuitBreaker:
    """
    Production-Grade Asynchronous Circuit Breaker.
    Protects downstream APIs (exchanges, search engines, cloud databases)
    from cascading failures, high latency spikes, and socket exhaustion.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 4,
        recovery_time_sec: float = 30.0,
        half_open_max_trials: int = 2,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_time_sec = recovery_time_sec
        self.half_open_max_trials = half_open_max_trials

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._consecutive_successes: int = 0
        self._last_state_change: float = time.time()
        self._lock = asyncio.Lock()
        self._half_open_trials: int = 0

    @property
    def state(self) -> CircuitState:
        # Check if OPEN state has expired and should transition to HALF_OPEN
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_state_change >= self.recovery_time_sec:
                self._state = CircuitState.HALF_OPEN
                self._half_open_trials = 0
                logger.info(f"CircuitBreaker[{self.name}]: State changed OPEN -> HALF_OPEN (probing)")
        return self._state

    def is_available(self) -> bool:
        """Quick non-blocking check whether requests can be attempted."""
        st = self.state
        if st == CircuitState.CLOSED:
            return True
        if st == CircuitState.HALF_OPEN:
            return self._half_open_trials < self.half_open_max_trials
        return False

    async def record_success(self):
        """Record successful execution."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._consecutive_successes += 1
                if self._consecutive_successes >= self.half_open_max_trials:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._consecutive_successes = 0
                    self._last_state_change = time.time()
                    logger.info(f"CircuitBreaker[{self.name}]: Fully recovered -> CLOSED")
            else:
                self._failure_count = max(0, self._failure_count - 1)

    async def record_failure(self, err: Optional[Exception] = None):
        """Record a failed execution or timeout."""
        async with self._lock:
            self._failure_count += 1
            err_msg = str(err) if err else "Unknown error"
            if self._state == CircuitState.HALF_OPEN:
                # Immediate trip back to OPEN
                self._state = CircuitState.OPEN
                self._last_state_change = time.time()
                self._consecutive_successes = 0
                logger.warning(f"CircuitBreaker[{self.name}]: Probe failed ({err_msg}). Re-tripping -> OPEN ({self.recovery_time_sec}s cooldown)")
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._last_state_change = time.time()
                logger.warning(f"CircuitBreaker[{self.name}]: Threshold {self.failure_threshold} reached ({err_msg}). Tripped -> OPEN ({self.recovery_time_sec}s cooldown)")

    async def call(self, coro_fn: Callable, *args, fallback: Any = None, **kwargs) -> Any:
        """
        Execute a coroutine through the circuit breaker.
        Fails fast if OPEN and returns fallback or raises CircuitOpenError.
        """
        if not self.is_available():
            logger.debug(f"CircuitBreaker[{self.name}]: Short-circuiting call (state={self.state.value})")
            if callable(fallback):
                return await fallback(*args, **kwargs) if asyncio.iscoroutinefunction(fallback) else fallback(*args, **kwargs)
            return fallback

        if self._state == CircuitState.HALF_OPEN:
            self._half_open_trials += 1

        try:
            res = await coro_fn(*args, **kwargs)
            await self.record_success()
            return res
        except Exception as e:
            await self.record_failure(e)
            if fallback is not None:
                if callable(fallback):
                    return await fallback(*args, **kwargs) if asyncio.iscoroutinefunction(fallback) else fallback(*args, **kwargs)
                return fallback
            raise e

    def stats(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "threshold": self.failure_threshold,
            "cooldown_sec": self.recovery_time_sec,
            "time_in_state_sec": round(time.time() - self._last_state_change, 2),
        }


# Global Registry of Managed Circuit Breakers
_MANAGED_CIRCUIT_BREAKERS: Dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str, failure_threshold: int = 4, recovery_time_sec: float = 30.0) -> CircuitBreaker:
    """Obtain or instantiate a named circuit breaker."""
    if name not in _MANAGED_CIRCUIT_BREAKERS:
        _MANAGED_CIRCUIT_BREAKERS[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_time_sec=recovery_time_sec,
        )
    return _MANAGED_CIRCUIT_BREAKERS[name]
