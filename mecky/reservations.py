"""Typed reservation boundary. A real provider can replace this adapter later."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ReservationResult:
    trace_id: str
    status: str
    reservation_id: str | None = None
    available_slots: tuple[str, ...] = ()
    error: str | None = None


class ReservationGateway(Protocol):
    def get_reservation_availability(self, *, date: str, party_size: int, trace_id: str, timeout_seconds: float = 8) -> ReservationResult: ...
    def create_reservation(self, *, date: str, time: str, party_size: int, guest_name: str, trace_id: str, timeout_seconds: float = 8) -> ReservationResult: ...
    def modify_reservation(self, *, reservation_id: str, date: str, time: str, trace_id: str, timeout_seconds: float = 8) -> ReservationResult: ...
    def cancel_reservation(self, *, reservation_id: str, trace_id: str, timeout_seconds: float = 8) -> ReservationResult: ...


class UnconnectedReservationGateway:
    """Explicit failure state: the demo may link to booking, never claim a slot."""
    def get_reservation_availability(self, *, date: str, party_size: int, trace_id: str, timeout_seconds: float = 8) -> ReservationResult:
        return ReservationResult(trace_id, "UNAVAILABLE", error="PROVIDER_NOT_CONNECTED")

    def create_reservation(self, *, date: str, time: str, party_size: int, guest_name: str, trace_id: str, timeout_seconds: float = 8) -> ReservationResult:
        return ReservationResult(trace_id, "UNAVAILABLE", error="PROVIDER_NOT_CONNECTED")

    def modify_reservation(self, *, reservation_id: str, date: str, time: str, trace_id: str, timeout_seconds: float = 8) -> ReservationResult:
        return ReservationResult(trace_id, "UNAVAILABLE", error="PROVIDER_NOT_CONNECTED")

    def cancel_reservation(self, *, reservation_id: str, trace_id: str, timeout_seconds: float = 8) -> ReservationResult:
        return ReservationResult(trace_id, "UNAVAILABLE", error="PROVIDER_NOT_CONNECTED")


gateway: ReservationGateway = UnconnectedReservationGateway()
