"""Register the built-in settlement gate on an explicit station registry."""

from runtime.station07_settlement_gate import station07_settlement_gate
from runtime.station_engine import StationRegistry
from sovereign_runtime import SovereignRuntime


def register_station07(
    runtime: SovereignRuntime, registry: StationRegistry
) -> None:
    registry.replace(7, station07_settlement_gate(runtime))
