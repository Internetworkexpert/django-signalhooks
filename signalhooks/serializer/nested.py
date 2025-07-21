from django.core.serializers.json import Serializer as JsonSerializer
from django.db.models.fields.related import ForeignKey
from django.utils.encoding import is_protected_type


class Serializer(JsonSerializer):
    def __init__(self):
        super().__init__()
        self._max_depth = 0
        self._level = 0
        self._nested_fields = []
        self._exclude_fields: set[str] = set()
        self._include_fields: set[str] = set()
        self._current = None

    def _init_options(self):
        """
        Extract our custom parameters, stores them in the instance
        and calls super()._init_options().
        """
        self._max_depth = self.options.pop("max_depth", 0)
        self._nested_fields = self.options.pop("nested_fields", [])
        self._exclude_fields = set(self.options.pop("exclude_fields", []))
        self._include_fields = set(self.options.pop("include_fields", []))
        super()._init_options()

    def _is_serialized(self, field, obj=None) -> bool:
        """
        Return True if we should emit this *field* on *obj*.

        1) If field.name or field.attname in any exclude set → False
        2) If either include set is non-empty and field not in include → False
        3) Otherwise → True
        """
        # build the two “names” we might match on
        names = {field.name, getattr(field, "attname", field.name)}

        # 1) check excludes
        if names & self._exclude_fields:
            return False
        if obj is not None:
            model_excl = set(getattr(obj.__class__, "signalhook_exclude_fields", ()))
            if names & model_excl:
                return False

        # 2) check includes (only if there's something to include)
        global_inc = self._include_fields
        model_inc = set(getattr(obj.__class__, "signalhook_include_fields", ()))
        if global_inc or model_inc:
            if not names & (global_inc | model_inc):
                return False

        # 3) otherwise okay
        return True

    def handle_field(self, obj, field):
        if not self._is_serialized(field, obj):
            return
        super().handle_field(obj, field)

    def handle_fk_field(self, obj, field):
        """
        Decides if we need to call custom or default serialization based on _nested_fields
        and max_depth.
        """
        if not self._is_serialized(field, obj):
            return

        if self._level > self._max_depth or field.name not in self._nested_fields:
            value = super()._value_from_field(obj, field)
        else:
            value = self._value_from_field(obj, field)
        self._current[field.name] = value

    def handle_m2m_field(self, obj, field):
        """
        We override this method to check if the ManyToMany attribute is required to be serialized or not.
        We call custom serialization if needed.
        """
        if not self._is_serialized(field, obj):
            return

        if field.remote_field.through._meta.auto_created:
            if field.name not in self._nested_fields or self._level > self._max_depth:

                def m2m_value(val):
                    return self._value_from_field(val, val._meta.pk)

            else:

                def m2m_value(val):
                    return self.m2m_full_object(val)

            self._current[field.name] = [
                m2m_value(rel) for rel in getattr(obj, field.name).iterator()
            ]

    def m2m_full_object(self, obj):
        """
        Serializes a full object instance that belongs to a ManyToMany relationship.
        """
        self._level += 1
        aux = self._current
        value = self.serialize_fk(obj)
        self._current = aux
        self._level -= 1
        return value

    def _value_from_field(self, obj, field):
        """
        This method overrides the default behaviour for ForeingKey and
        returns full object if needed. The rest of the behaviour remains the same.
        """
        if isinstance(field, ForeignKey) and getattr(obj, field.name, None):
            self._level += 1
            aux = self._current
            value = self.serialize_fk(getattr(obj, field.name))
            self._current = aux
            self._level -= 1
            return value

        value = field.value_from_object(obj)
        if is_protected_type(value):
            return value
        return field.value_to_string(obj)

    def serialize_fk(self, o):
        """
        Overrides default serialization to call the new methods for ForeingKey and m2m.
        """
        self.start_object(o)
        concrete = o._meta.concrete_model

        # regular fields
        for field in concrete._meta.local_fields:
            if not field.serialize or not self._is_serialized(field, o):
                continue

            # simple vs FK
            if field.remote_field is None:
                if (
                    self.selected_fields is None
                    or field.attname in self.selected_fields
                ):
                    self.handle_field(o, field)
            else:
                if (
                    self.selected_fields is None
                    or field.attname[:-3] in self.selected_fields
                ):
                    self.handle_fk_field(o, field)

        # m2m relations
        for field in concrete._meta.local_many_to_many:
            if (
                field.serialize
                and (
                    self.selected_fields is None
                    or field.attname in self.selected_fields
                )
                and self._is_serialized(field, o)
            ):
                self.handle_m2m_field(o, field)

        return self.get_dump_object(o)
