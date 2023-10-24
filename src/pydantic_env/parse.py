from typing import Any, Dict, Generic, List, Optional, Type, TypeVar

from pydantic import BaseModel


def _is_schema(obj: Any):
    """
    Check is an arbitrary object is a pydantic model/config (sub)schema.
    """
    try:
        return issubclass(obj, BaseModel)
    except TypeError:
        return False


def _path_to_var_name(path: List[str]):
    """
    Convert a config schema path to an environment variable name.
    """
    return "_".join([segment.upper() for segment in path])


def _normalize_var_prefix(var_prefix: str):
    """
    Minimally modify an environment variable prefix so tha it ends with a '_'.
    """
    if var_prefix.endswith("_"):
        return var_prefix
    else:
        return f"{var_prefix}_"


def _strip_var_prefix(prefix: str, prefixed_key: str):
    """
    Strip the common prefix off of an environment variable.
    """
    normalized_prefix = _normalize_var_prefix(prefix)
    return prefixed_key[len(normalized_prefix) :]


def _preprocess_var_dict(prefix: Optional[str], var_dict: Dict[str, Optional[str]]):
    """
    Pre-process a dictionary of variables
    """
    non_empty = {k: v for k, v in var_dict.items() if v is not None}

    preprocessed = non_empty
    if prefix is not None:
        normalized_prefix = _normalize_var_prefix(prefix)
        # Remove anything not prefixed by the prefix
        prefixed = {
            k: v for k, v in non_empty.items() if k.startswith(normalized_prefix)
        }
        # Strip the prefix away
        preprocessed = {_strip_var_prefix(prefix, k): v for k, v in prefixed.items()}

    return preprocessed


T = TypeVar("T", bound=BaseModel)


class ConfigParser(Generic[T]):
    """
    ConfigParser for parsing configuration from a dictionary of environment variables.

    Attributes:
    - schema: Pydantic model/schema used for validation.
    - var_prefix: Prefix used to filter environment variables.

    Example:
    ```
    import os

    from pydantic import BaseModel

    class DatabaseConfig(BaseModel):
        port: int

        # Aliased fields will be derived from var dict variables according to their alias
        # but they will be accessible in-memory with the actual field name
        address: str = Field(alias='host')

    class AppConfig(BaseModel):
        debug: bool

        # Config can be nested
        database: DatabaseConfig

        # Unions do not work yet
        # deployment: Union[Literal['dev'], Literal['prod']]

    # Config parsers can specify a prefix to expect from environment variables
    config_parser = ConfigParser(AppConfig, "MYAPP")

    # Config can be parsed from any dictionary source, such as:
    # - the environment
    # - dotenv files
    validated_config = config_parser.parse({
        **os.environ
    })

    print(validated_config)
    # If the environment consisted of:
    # MYAPP_DEBUG=True
    # MYAPP_DATABASE_HOST=localhost
    # MYAPP_DATABASE_PORT=9999
    # DEBUG=False
    #
    # the output would be:
    # AppConfig(
    #   debug=True, database=DatabaseConfig(host='localhost', port=9999)
    # )
    ```
    """

    schema: Type[T]
    """
    """

    var_prefix: Optional[str]
    """
    """

    def __init__(self, schema: Type[T], var_prefix: Optional[str]):
        self.schema = schema
        self.var_prefix = var_prefix

    def _paths(
        self, sub_schema: Optional[Type[BaseModel]], path_prefix: List[str] = []
    ):
        """
        Obtain all path strings for a config schema.
        """
        if sub_schema is None:
            sub_schema = self.schema

        paths: List[List[str]] = []
        for key, value in sub_schema.model_fields.items():
            # Check to see if this is an aliased field and update it if so
            if value.alias is not None:
                key = value.alias
            prefixed_key = path_prefix + [key]
            annotation = value.annotation
            if _is_schema(annotation):
                paths.extend(self._paths(annotation, prefixed_key))
            else:
                paths.append(prefixed_key)

        return paths

    def var_name_to_path_table(self):
        """
        Create a map between environment variable names and schema paths.

        Example:
        ```
        from pydantic import BaseModel

        class DatabaseConfig(BaseModel):
            host: str
            port: int

        class AppConfig(BaseModel):
            debug: bool
            database: DatabaseConfig

        config_parser = ConfigParser(AppConfig, "MYAPP")
        lookup_table = config_parser.var_name_to_path_table()
        print(lookup_table)
        # Output:
        # {
        #   'MYAPP_DEBUG': ['debug'],
        #   'MYAPP_DATABASE_HOST': ['database', 'host'],
        #   'MYAPP_DATABASE_PORT': ['database', 'port']
        # }
        ```
        """
        paths = self._paths(None)

        pairs = [(_path_to_var_name(path), path) for path in paths]
        var_names = [var_name for var_name, _ in pairs]

        duplicate_indices = [
            i for i, var_name in enumerate(var_names) if var_names.count(var_name) > 1
        ]
        if len(duplicate_indices) > 0:
            unique_duplicated_var_names = set(var_names[i] for i in duplicate_indices)

            message_components = [
                "Cannot load config; ambiguous environment variable names based on"
                + "schema paths."
            ]
            for duplicated_var_name in unique_duplicated_var_names:
                schema_paths = [
                    path for var_name, path in pairs if var_name == duplicated_var_name
                ]
                message_components.append(
                    f"Paths `{schema_paths}` all resolve to the environment variable "
                    + f"`{duplicated_var_name}`"
                )

            message = "\n".join(message_components)
            raise RuntimeError(message)

        return {k: v for k, v in pairs}

    def _var_dict_to_proto_config(self, var_dict: Dict[str, str]):
        """
        Take a var dict and a path lookup and reformat the values in the var dict
        so that they sit in a nested dictionary that can be supplied to a schema
        validator.

        Such a nested dictionary is referred to as "proto config".
        """
        path_lookup = self.var_name_to_path_table()

        root: Dict[str, Any] = {}

        for var_name, value in var_dict.items():
            if var_name not in path_lookup:
                message = f"""Extra var `{var_name}` found in var dict; expected one of
                {list(path_lookup.keys())}
                """
                raise RuntimeError(message)

            path = path_lookup[var_name]
            path_length = len(path)

            curr_level = root
            for depth, segment in enumerate(path):
                if depth < path_length - 1:
                    if curr_level.get(segment) is None:
                        curr_level[segment] = {}
                    curr_level = curr_level[segment]
                else:
                    curr_level[segment] = value

        return root

    def parse(self, var_dict: Dict[str, Optional[str]]) -> T:
        """
        Parse and validate configuration from a dictionary of environment variables.

        Args:
        - var_dict (Dict[str, Optional[str]]): Dictionary of environment variables.

        Returns:
        - Any: Validated configuration.

        Example, building a schema:
        ```
        from pydantic import BaseModel, SecretStr

        class Database(BaseModel):
            host: str
            port: int
            password: SecretStr

        class Config(BaseModel):
            debug: bool
            database: Database
        ```

        Example, parsing prefixed environment variables:
        ```
        from pydantic_env import ConfigParser

        from .schema import Config


        # Parse a var dict with prefixed var names
        parser = ConfigParser(Config, "MYAPP")
        config = parser.parse({
            'MYAPP_DEBUG': 'True',
            'MYAPP_DATABASE_HOST': 'localhost',
            'MYAPP_DATABASE_PORT': '5432',
            'MYAPP_DATABASE_PASSWORD': 'password123'
        })

        print(config)
        # Output:
        # Config(
        #    debug=True,
        #    database=Database(
        #        host='localhost',
        #        port=5432,
        #        password=SecretStr('**********')
        #    )
        # )
        ```

        Example, parsing unprefixed environment variables:
        ```
        from pydantic_env import ConfigParser

        from .schema import Config


        # Parsing unprefixed environment variables
        parser = ConfigParser(Config, None)
        config = parser.parse({
            'DEBUG': 'True',
            'DATABASE_HOST': 'localhost',
            'DATABASE_PORT': '5432',
            'DATABASE_PASSWORD': 'password123'
        })

        print(config)
        # Output:
        # Config(
        #    debug=True,
        #    database=Database(
        #        host='localhost',
        #        port=5432,
        #        password=SecretStr('**********')
        #    )
        # )
        ```
        """
        preprocessed = _preprocess_var_dict(self.var_prefix, var_dict)
        proto_config = self._var_dict_to_proto_config(preprocessed)
        return self.schema.model_validate(proto_config)


def parse(
    schema: Type[T], var_prefix: Optional[str], var_dict: Dict[str, Optional[str]]
) -> T:
    """
    Utility function to parse and validate configuration from environment variables.
    """
    parser = ConfigParser(schema, var_prefix)
    return parser.parse(var_dict)
