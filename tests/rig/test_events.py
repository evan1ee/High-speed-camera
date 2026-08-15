"""Fan-out of rig events to every connected client, controller or observer."""
import queue

from hsc.rig.events import EventBus


def test_every_subscriber_receives_a_published_event():
    bus = EventBus()
    a, b = bus.subscribe(), bus.subscribe()
    bus.publish("status", text="Capturing")
    assert a.get_nowait().kind == "status"
    assert b.get_nowait().payload == {"text": "Capturing"}


def test_unsubscribed_queue_stops_receiving():
    bus = EventBus()
    a = bus.subscribe()
    bus.unsubscribe(a)
    bus.publish("status", text="x")
    with_raises = queue.Empty
    try:
        a.get_nowait()
        assert False, "expected no event"
    except with_raises:
        pass


def test_unsubscribing_an_unknown_queue_is_a_no_op():
    """A double-unsubscribe (or a queue this bus never issued) must not raise."""
    bus = EventBus()
    stray = queue.Queue()
    bus.unsubscribe(stray)          # never subscribed -- no error
    a = bus.subscribe()
    bus.unsubscribe(a)
    bus.unsubscribe(a)              # already removed -- no error


def test_a_full_subscriber_queue_drops_instead_of_blocking():
    """A slow observer must never stall the grab thread."""
    bus = EventBus(maxsize=2)
    slow = bus.subscribe()
    for i in range(5):
        bus.publish("log", text=str(i))
    assert slow.qsize() == 2


def test_history_returns_recent_events_for_a_late_joiner():
    bus = EventBus()
    bus.publish("log", text="one")
    bus.publish("log", text="two")
    assert [e.payload["text"] for e in bus.history(10)] == ["one", "two"]
    assert len(bus.history(1)) == 1
