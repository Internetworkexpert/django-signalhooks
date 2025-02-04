import logging

from django.db import models
from django.db import transaction
from django.db.models.signals import pre_save
from django.core.serializers import serialize
from signalhooks import signals

logger = logging.getLogger(__name__)


class NotifiableModelChangeMixin(models.Model):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._old_instance = None
        pre_save.connect(NotifiableModelChangeMixin.save_old_instance, self.__class__)

    @staticmethod
    def save_old_instance(sender, instance, **kwargs):
        old_instance = None
        if not instance._state.adding:
            old_instance = serialize("json", [sender.objects.get(id=instance.id)])[1:-1]
        else:
            logger.warning("The instance is being created, there's no old_instance")
        instance._old_instance = old_instance

    class Meta:
        abstract = True


class NotifiableContentSerializer:
    @transaction.atomic
    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        signals.post_update.send(
            sender=instance.__class__, instance=instance, raw=None, created=False
        )
        return instance
