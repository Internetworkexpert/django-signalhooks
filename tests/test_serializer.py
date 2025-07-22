from django.core.serializers import register_serializer
from django.db import connection
from django.test import TestCase
from signalhooks.hooks import SNSSignalHook
from test_fixtures import AnotherChildFactory, ChildFactory, ParentFactory
from expected_responses import *
import base64
import pytest
import json


@pytest.mark.django_db
class TestSetup(TestCase):
    def setUp(self):
        super().setUp()
        connection.disable_constraint_checking()

        register_serializer("json.nested", "signalhooks.serializer.nested")
        self.ac1 = AnotherChildFactory(name="Another Child 1")
        self.ac2 = AnotherChildFactory(name="Another Child 2")
        self.c1 = ChildFactory.create(name="Child", desc="Description for child1")
        self.c1.another_children = self.ac1
        self.c2 = ChildFactory(name="Child2", desc="Description for child2")

        self.parent = ParentFactory(
            name="New Parent", child=self.c1, main_child=self.c2
        )
        self.parent.another_children.add(self.ac1)
        self.parent.another_children.add(self.ac2)

    def _fields_from_sns_msg(self, sns_result):
        """
        Convenience helper that returns the *fields* dict from the
        SNS message attributes produced by SNSSignalHook.
        Works for both list- and dict-style Django JSON serialiser output.
        """
        raw = base64.b64decode(sns_result["Instance"]["StringValue"]).decode("utf-8")
        data = json.loads(raw)
        # Stock Django serialiser returns a list; our tests prefer the first item
        if isinstance(data, list):
            data = data[0]
        return data.get("fields", data)

    def test_serializer_with_no_nested_fields_no_depth(self):
        sns_hook = SNSSignalHook(sns_topic_arn="test_topic", serializer="json.nested")
        result = sns_hook.get_sns_msg_attributes(instance=self.parent, created=True)
        self.assertEqual(
            base64.b64decode(result["Instance"]["StringValue"]).decode("utf-8"),
            json.dumps(NO_NESTED_FIELDS_DEFAULT_DEPTH),
        )

    def test_serializer_with_nested_fields_no_depth(self):
        sns_hook = SNSSignalHook(
            sns_topic_arn="test_topic",
            serializer="json.nested",
            nested_fields=["child"],
        )
        result = sns_hook.get_sns_msg_attributes(instance=self.parent, created=True)
        self.assertEqual(
            base64.b64decode(result["Instance"]["StringValue"]).decode("utf-8"),
            json.dumps(NESTED_FIELDS_DEFAULT_DEPTH),
        )

    def test_serializer_with_nested_fields_depth_1(self):
        sns_hook = SNSSignalHook(
            sns_topic_arn="test_topic",
            serializer="json.nested",
            nested_fields=["child"],
            max_depth=1,
        )
        result = sns_hook.get_sns_msg_attributes(instance=self.parent, created=True)
        self.assertEqual(
            base64.b64decode(result["Instance"]["StringValue"]).decode("utf-8"),
            json.dumps(NESTED_FIELDS_DEPTH_1),
        )

    def test_serializer_with_nested_fields_depth_2(self):
        sns_hook = SNSSignalHook(
            sns_topic_arn="test_topic",
            serializer="json.nested",
            nested_fields=["child", "another_children"],
            max_depth=2,
        )
        result = sns_hook.get_sns_msg_attributes(instance=self.parent, created=True)
        self.assertEqual(
            base64.b64decode(result["Instance"]["StringValue"]).decode("utf-8"),
            json.dumps(NESTED_FIELDS_DEPTH_2),
        )

    def test_serializer_with_array_nested_fields_depth(self):
        sns_hook = SNSSignalHook(
            sns_topic_arn="test_topic",
            serializer="json.nested",
            nested_fields=["another_children"],
        )
        result = sns_hook.get_sns_msg_attributes(instance=self.parent, created=True)
        self.assertEqual(
            base64.b64decode(result["Instance"]["StringValue"]).decode("utf-8"),
            json.dumps(ARRAY_NESTED_FIELDS_DEPTH_1),
        )

    def test_serializer_with_include_fields_only(self):
        """
        When *include_fields* is provided and *exclude_fields* is not,
        only the specified attributes should appear in the payload.
        """
        sns_hook = SNSSignalHook(
            sns_topic_arn="test_topic",
            serializer="json.nested",
            include_fields=["name"],  # keep only 'name'
        )
        result = sns_hook.get_sns_msg_attributes(instance=self.parent, created=True)
        fields = self._fields_from_sns_msg(result)

        # 'name' should be present; other attributes (e.g. 'child', 'main_child') should not
        self.assertEqual(set(fields.keys()), {"name"})

    def test_serializer_with_include_and_exclude_fields(self):
        """
        If a field appears in both *include_fields* and *exclude_fields*,
        the exclusion must win.
        """
        sns_hook = SNSSignalHook(
            sns_topic_arn="test_topic",
            serializer="json.nested",
            include_fields=["name", "desc"],
            exclude_fields=["desc"],  # desc is explicitly removed again
        )
        result = sns_hook.get_sns_msg_attributes(instance=self.c1, created=False)
        fields = self._fields_from_sns_msg(result)

        self.assertIn("name", fields)
        self.assertNotIn("desc", fields)
        # No unintended extras slipped through
        self.assertEqual(set(fields.keys()), {"name"})

    def test_serializer_with_model_level_include_fields(self):
        """
        A model may declare `signalhook_include_fields`; the
        serializer must respect it even when no per-call lists are given.
        """
        # Dynamically add the attribute to the model class
        child_cls = self.c1.__class__
        original_attr = getattr(child_cls, "signalhook_include_fields", None)
        child_cls.signalhook_include_fields = ["name"]

        try:
            sns_hook = SNSSignalHook(
                sns_topic_arn="test_topic",
                serializer="json.nested",
            )
            result = sns_hook.get_sns_msg_attributes(instance=self.c1, created=False)
            fields = self._fields_from_sns_msg(result)

            self.assertEqual(set(fields.keys()), {"name"})
        finally:
            # Clean-up to avoid side-effects on other tests
            if original_attr is None:
                del child_cls.signalhook_include_fields
            else:
                child_cls.signalhook_include_fields = original_attr
