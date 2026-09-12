import time
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class StageTimer:
    """Microsecond-accurate timer for discrete pipeline execution stages."""
    stage_times: Dict[str, float] = field(default_factory=dict)
    _active_stage: Optional[str] = None
    _stage_start: float = field(default_factory=time.perf_counter)
    turn_start: float = field(default_factory=time.perf_counter)

    def start_stage(self, stage_name: str):
        now = time.perf_counter()
        if self._active_stage is not None:
            elapsed_ms = (now - self._stage_start) * 1000.0
            self.stage_times[self._active_stage] = round(
                self.stage_times.get(self._active_stage, 0.0) + elapsed_ms, 2
            )
        self._active_stage = stage_name
        self._stage_start = now

    def stop_stage(self):
        now = time.perf_counter()
        if self._active_stage is not None:
            elapsed_ms = (now - self._stage_start) * 1000.0
            self.stage_times[self._active_stage] = round(
                self.stage_times.get(self._active_stage, 0.0) + elapsed_ms, 2
            )
            self._active_stage = None

    @property
    def total_ms(self) -> float:
        return round((time.perf_counter() - self.turn_start) * 1000.0, 2)

    def to_dict(self) -> Dict[str, Any]:
        self.stop_stage()
        return {
            "stages_ms": dict(self.stage_times),
            "total_turn_ms": self.total_ms,
        }


class PerformanceTelemetry:
    """Global lightweight in-memory metrics aggregator."""
    _total_turns: int = 0
    _total_ms_accumulated: float = 0.0
    _fast_path_hits: int = 0
    _llm_turns: int = 0
    _tool_calls_executed: int = 0

    @classmethod
    def record_turn(cls, duration_ms: float, is_fast_path: bool = False, tool_count: int = 0):
        cls._total_turns += 1
        cls._total_ms_accumulated += duration_ms
        if is_fast_path:
            cls._fast_path_hits += 1
        else:
            cls._llm_turns += 1
        cls._tool_calls_executed += tool_count

    @classmethod
    def summary(cls) -> Dict[str, Any]:
        avg_latency = round(
            cls._total_ms_accumulated / max(1, cls._total_turns), 2
        ) if cls._total_turns else 0.0
        return {
            "total_turns": cls._total_turns,
            "fast_path_turns": cls._fast_path_hits,
            "llm_turns": cls._llm_turns,
            "tool_calls": cls._tool_calls_executed,
            "avg_latency_ms": avg_latency,
        }
