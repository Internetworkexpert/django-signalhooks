import pytest
from types import SimpleNamespace

import signalhooks.models as models_module

from tests.models import Child
from signalhooks.models import NotifiableModelChangeMixin, NotifiableContentSerializer
from signalhooks import signals


class DummyState:
    def __init__(self, adding: bool):
        self.adding = adding


class DummyInstance:
    def __init__(self, id, adding: bool):
        self.id = id
        self._state = DummyState(adding)
        self._old_instance = "__unset__"


class DummySender:
    class objects:
        @staticmethod
        def get(id):
            # Return a simple object; only its serialization matters
            return SimpleNamespace(id=id, foo="bar")


@pytest.mark.parametrize(
    "adding, expected_old",
    [
        (True, None),  # new instances should log and leave old_instance None
        (False, "old"),  # existing instances get serialized payload
    ],
)
def test_save_old_instance(monkeypatch, caplog, adding, expected_old):
    inst = DummyInstance(id=42, adding=adding)

    # Stub the serialize function in signalhooks.models to avoid real ORM calls
    monkeypatch.setattr(models_module, "serialize", lambda fmt, objs: "[old]")

    # Call the mixin's save_old_instance
    NotifiableModelChangeMixin.save_old_instance(sender=DummySender, instance=inst)

    if adding:
        # New instances: warning and None
        assert inst._old_instance is None
        assert "there's no old_instance" in caplog.text
    else:
        # Existing: [old] -> old
        assert inst._old_instance == expected_old


@pytest.mark.django_db
def test_content_serializer_update_and_signal(monkeypatch):
    # Create a real Child in the test DB
    child = Child.objects.create(name="first", desc="hello")

    # Spy on the post_update signal
    captured = {}

    def fake_send(sender, instance, raw, created):
        captured["args"] = (sender, instance, raw, created)

    monkeypatch.setattr(signals.post_update, "send", fake_send)

    # Dummy base that actually updates and saves the instance
    class DummyBase:
        def update(self, instance, validated_data):
            for key, val in validated_data.items():
                setattr(instance, key, val)
            instance.save()
            return instance

    # Compose our serializer: MRO ensures NotifiableContentSerializer.update calls DummyBase.update
    class MySerializer(NotifiableContentSerializer, DummyBase):
        pass

    ser = MySerializer()

    # Perform the update
    updated = ser.update(child, {"desc": "updated-text"})

    # The return value should be the saved instance
    assert updated.pk == child.pk

    # And the change should persist
    child.refresh_from_db()
    assert child.desc == "updated-text"

    # Ensure the signal was emitted with the right values
    assert captured["args"] == (
        Child,  # sender
        child,  # instance
        None,  # raw
        False,  # created=False
    )
