"""One controller, many observers. A stale browser tab must not keep the rig."""
import pytest

from hsc.rig.lease import ControlLease, LeaseError


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_first_claim_wins_and_second_is_refused():
    lease = ControlLease()
    assert lease.claim("a") is True
    assert lease.claim("b") is False
    assert lease.holder == "a"


def test_reclaim_by_the_holder_is_allowed():
    lease = ControlLease()
    lease.claim("a")
    assert lease.claim("a") is True


def test_release_frees_the_rig():
    lease = ControlLease()
    lease.claim("a")
    assert lease.release("a") is True
    assert lease.holder is None
    assert lease.claim("b") is True


def test_a_non_holder_cannot_release():
    lease = ControlLease()
    lease.claim("a")
    assert lease.release("b") is False
    assert lease.holder == "a"


def test_lease_expires_without_a_heartbeat():
    clock = Clock()
    lease = ControlLease(ttl_s=30.0, clock=clock)
    lease.claim("a")
    clock.now = 31.0
    assert lease.holder is None
    assert lease.claim("b") is True


def test_heartbeat_keeps_it():
    clock = Clock()
    lease = ControlLease(ttl_s=30.0, clock=clock)
    lease.claim("a")
    clock.now = 20.0
    assert lease.heartbeat("a") is True
    clock.now = 45.0
    assert lease.holder == "a"


def test_heartbeat_from_a_non_holder_is_refused():
    lease = ControlLease()
    lease.claim("a")
    assert lease.heartbeat("b") is False


def test_require_raises_for_a_non_holder():
    lease = ControlLease()
    lease.claim("a")
    with pytest.raises(LeaseError, match="held by a"):
        lease.require("b")
    lease.require("a")          # no raise


def test_require_raises_when_nobody_holds_it():
    with pytest.raises(LeaseError, match="no client holds"):
        ControlLease().require("a")


def test_handover_transfers_without_a_gap():
    lease = ControlLease()
    lease.claim("a")
    assert lease.handover("a", "b") is True
    assert lease.holder == "b"
    assert lease.handover("a", "c") is False
