# pydantic-env

Type-safe config with pydantic.

## Overview

`pydantic-env` is a library for type-safe loading of config values.

## Usage

### Tutorial: Define a config parser, config sources, and load config

Let's say we want to load some configuration encoded (for organizational purposes) as a nested data structure into our application. We want to be able to source data defaults from a [dotenv](https://github.com/theskumar/python-dotenv) file checked into version control and override any of those with environment variables, or another local dotenv file with some secrets in it. That's what `pydantic-env` is for.

For this tutorial we'll pretend we're working on an application called `google-gateway` which abstracts access to a google api for our company.

#### Define a schema

To define the shape of our configuration (and the static type with which it will be passed around the application) we'll use a nested pydantic model. In `google-gateway` we'll pretend that we're configuring the server host, logging level, and google api key.

> `src/google_gateway/config/schema.py`:

```python
from pydantic import BaseModel


# Google-specific config
class Google(BaseModel):
    key: str = Field(min_length=24, max_length=24)


# Application api integration configuration
class Api(BaseModel):
    google: Google


# Application logging configuration
class Logging(BaseModel):
    level: str = 'info'


# Application server configuration
class Server(BaseModel):
    host: str = '127.0.0.1'
    port: int = 8080


# The configuration schema for the whole application
class Schema(BaseModel):
  api: Api
  logging: Logging
  server: Server
```

#### A look under the hood

We'll have this application attempt to load its configuration from a file of default values: `.env.default`. We'll also set up a git-ignored file in the repo that allows the user to locally override some of the values without having to screw with the environment: `.env`. Then, finally, we'll supersede any of those values with values extracted from the environment.

`pydantic-env` uses the intermediate data structure that it calls a 'var dict' to standardize the way it sources data from different sources. This is simply a python `dict` in which all the keys are expected to be in `CAPS_CASE`. After converting the data in any environment variable source into a var dict, `pydantic-env` will use the structure of the schema to set some expectations for itself about what keys it expects from the var dict.

The mapping of schema paths to var dict keys is simple, and follows the pattern that dot (`.`) delimiters in paths are converted to underscores (`_`) and everything is capsed. For example, `api.google.key` will be mapped to `API_GOOGLE_KEY`. Note that because path segments can contain underscores before this conversion is made, ambiguity is possible, but `pydantic-env` will throw an error if it discovers that this is the case.

`pydantic-env` can also be configured to expect that all the keys in a var dict source should be prefixed with a common prefix. This is to help make sure that application-specific config does not conflict with anything else in a shell environment that one may be loading config from.

#### Instantiate a config parser

`pydantic-env` exports a class which does all this heavy lifting for us: `ConfigParser`. In our toy example, we might create instantiate this class like this:

> `src/google_gateway/config/parsers.py`

```python
from pydantic_env import ConfigParser


_VAR_DICT_PREFIX = "GG"


config_parser = ConfigParser()
```

This parser will expect all our config variables to be prefixed with `GG`, to avoid other environment variables bleeding into the application.

#### Load config

Finally, we can go about loading config by using the instance method `ConfigParser.parse`:

> `src/google_gateway/config/loaders.py`:

```python
import os
from typing import Dict, Optional

from dotenv import dotenv_values

from google_gateway.config.schema import Config
from google_gateway.config.parsers import parser


# The path to the default dotenv file. This contains harmless defaults for configuration values and is committed to git. 
_DEFAULT_PATH = ".env.default"

# The path to a local dotenv file. This is not committed into git and can be used by developers to configure their local development environment.
_LOCAL_PATH = ".env"

def _load_dotenv(path: str):
    """
    Load a raw dictionary of environment variables from a (dotenv) file.
    """
    if not os.path.isfile(path):
        _logger.warning(
            f"⚠ Attempted to load configuration from `{path}` but no such file exists; "
            "defaulting to an empty var dict for this source."
        )
        return {}

    return dotenv_values(path)


def _load_shell():
    return os.environ


def load():
    """
    Load typed config from the filesystem and the shell environment.
    """
    default = _load_dotenv(DEFAULT_PATH)

    local: Dict[str, Optional[str]] = {}
    try:
        local = load_var_dict(LOCAL_PATH)
    except RuntimeError:
        # We're ok with this not being present
        pass

    shell = _load_shell()

    # Note the precedence of sources here. If source A is loaded after source B, then
    # variables from source A will overwrite those from source B. Also note that the
    # config isn't parsed until all these variable sources have been loaded, so any
    # individual variable source can be incomplete as long as they cover the set of
    # variables listed in the schema when considered all together.
    var_dict: Dict[str, Optional[str]] = {
        **default,
        **local,
        **shell,
    }

    return parser.parse(var_dict)
```

Finally, we can use the `load` function to load our config:

> `src/google_gateway/config/core.py`

```python
from google_gateway.config.loaders import load


config = load()
```

The config will be an instance of `google_gateway.config.schema.Schema`!

#### Set-up config sources

If we have the file `.env.default`:

```bash
GG_API_GOOGLE_KEY='fake'
GG_LOGGING_LEVEL='debug'
GG_SERVER_HOST='127.0.0.1'
GG_SERVER_PORT='9000'
```

And we have the file `.env`:

```bash
GG_API_GOOGLE_KEY='ak.n7643DSasd83lkjgkmnn7643DSasd83lkjgkmn'
```

We finally set the environment variable `GG_SERVER_ADDRESS=0.0.0.0`.

#### Test the config

Given all the work in the previous sections, the following test will pass:

```python
from google_gateway.config.schema import Api, Google, Logging, Schema, Server
from google_gateway.config.core import config as actual_config


def test_config():
    # Sourced from .env
    google = Google(key='ak.n7643DSasd83lkjgkmnn7643DSasd83lkjgkmn')
    api = Api(google=google)
    # Sourced from .env.default
    logging = Logging(level='debug')
    # Sourced from .env.default and the environment
    server = Server(host='0.0.0.0', port=9000)
    expected_config = Schema(api=api, logging=logging, server=server)

    assert actual_config == expected_config
```

## Alternatives

- [typed-config](https://github.com/bwindsor/typed-config)
- [pydantic-config](https://github.com/jordantshaw/pydantic-config)
