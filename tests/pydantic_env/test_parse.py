import pytest
from pydantic import BaseModel
from pydantic_env import ConfigParser


@pytest.fixture
def SubSchema():
    class SubSchema(BaseModel):
        sub_field: int

    return SubSchema


@pytest.fixture
def Schema(SubSchema):
    class Schema(BaseModel):
        field1: str
        field2: int
        sub_config: SubSchema

    return Schema


class TestConfigParser:
    class TestPaths:
        def test_can_parse_paths(self, Schema):
            parser = ConfigParser(Schema, "PREFIX")
            expected_paths = [["field1"], ["field2"], ["sub_config", "sub_field"]]
            assert parser._paths(None) == expected_paths

    class TestVarNameToPathTable:
        def test_produces_the_expected_table(self, Schema):
            parser = ConfigParser(Schema, "PREFIX")
            expected_table = {
                "FIELD1": ["field1"],
                "FIELD2": ["field2"],
                "SUB_CONFIG_SUB_FIELD": ["sub_config", "sub_field"],
            }
            assert parser.var_name_to_path_table() == expected_table

    class TestParse:
        def test_successfully_parses_prefixed_var_dicts(self, Schema):
            parser = ConfigParser(Schema, "PREFIX")
            var_dict = {
                "PREFIX_FIELD1": "some_value",
                "PREFIX_FIELD2": "42",
                "PREFIX_SUB_CONFIG_SUB_FIELD": "1",
            }
            parsed_config = parser.parse(var_dict)
            assert parsed_config.model_dump() == {
                "field1": "some_value",
                "field2": 42,
                "sub_config": {"sub_field": 1},
            }

        def test_throws_errors_for_missing_fields(self, Schema):
            parser = ConfigParser(Schema, "PREFIX")
            var_dict = {
                "PREFIX_FIELD1": "some_value",
            }
            with pytest.raises(Exception):
                parser.parse(var_dict)

        def test_throws_errors_for_extra_fields(self, Schema):
            parser = ConfigParser(Schema, "PREFIX")
            var_dict = {
                "PREFIX_FIELD1": "some_value",
                "PREFIX_FIELD2": "42",
                "PREFIX_SUB_CONFIG_SUB_FIELD": "1",
                "PREFIX_EXTRA": "extra_value",
            }
            with pytest.raises(Exception):
                parser.parse(var_dict)

        def test_successfully_parses_unprefixed_var_dicts(self, Schema):
            parser = ConfigParser(Schema, None)
            var_dict = {
                "FIELD1": "some_value",
                "FIELD2": "42",
                "SUB_CONFIG_SUB_FIELD": "1",
            }
            parsed_config = parser.parse(var_dict)
            assert parsed_config.model_dump() == {
                "field1": "some_value",
                "field2": 42,
                "sub_config": {"sub_field": 1},
            }
