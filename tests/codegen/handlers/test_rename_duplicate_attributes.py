from unittest import mock

from docx4j_xsdata.codegen.handlers import RenameDuplicateAttributes
from docx4j_xsdata.codegen.utils import ClassUtils
from docx4j_xsdata.utils.testing import ClassFactory, FactoryTestCase


class RenameDuplicateAttributesTests(FactoryTestCase):
    def setUp(self) -> None:
        super().setUp()

        self.processor = RenameDuplicateAttributes()

    @mock.patch.object(ClassUtils, "rename_duplicate_attributes")
    def test_process(self, mock_rename_duplicate_attributes) -> None:
        target = ClassFactory.create()
        self.processor.process(target)

        mock_rename_duplicate_attributes.assert_called_once_with(target)
