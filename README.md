# Talk to Your Graph (TTYG) Client for GraphDB

This repository provides an example implementation of a Talk to Your Graph (TTYG) client for GraphDB. The client interacts with a GraphDB instance using low-level API calls to handle tool (query method) calls while performing base communication with the OpenAI API itself. 

This mimics the TTYG client built into GraphDB Workbench and is the most flexible approach for integrating TTYG in your own application.

The full story behind the client is described in the [Talk to Your Graph Client for GraphDB blog post](http://ontotext.com/blog/talk-to-your-graph-client/). 

## Features

- Leverages GraphDB and OpenAI to provide a third-party client for Talk to Your Graph
- Communicates with OpenAI Assistants API for natural language understanding and generation.
- Executes tool (query method) calls using GraphDB's low-level TTYG API.
- Configurable via a YAML file.

## Prerequisites

1. **GraphDB instance**: A running GraphDB instance accessible via HTTP(S).
2. **TTYG agent**: Ensure that one or more TTYG agents are already created in GraphDB Workbench. The client and the API it uses do not provide agent management.
3. **OpenAI API key**: A valid OpenAI API key or Azure OpenAI setup. This must be identical to the OpenAI configuration of GraphDB.
4. **Python**: Python 3.13+ installed on your system.

## Setup

### 1. Clone the Repository

```bash
git clone https://github.com/Ontotext-AD/ttyg-client.git
cd ttyg-client
```

### 2. Create a Python Virtual Environment

First, create a [Python virtual environment](https://docs.python.org/3/library/venv.html).

```bash
python -m venv venv
```

Then, activate the environment:

```bash
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure the Client

The `client.yaml` file contains essential configuration parameters for both OpenAI and GraphDB. Edit the file to suit your environment. The file includes the following sections:

#### OpenAI Configuration

```yaml
openai:
  # Set this to your OpenAI API key
  api_key: <your_openai_api_key>

  # Set this to your Azure OpenAI URL if using Azure OpenAI
  api_url:

  # Azure API version
  azure_api_version: 2024-08-01-preview
```

#### GraphDB Configuration

```yaml
graphdb:
  # The base URL of the GraphDB instance
  url: http://localhost:7200

  # GraphDB username to associate with created threads and use for HTTP basic auth
  username: <your_graphdb_username>

  # Set this to use HTTP basic auth (with the above username)
  password:

  # Set this to use a custom HTTP authorization header (for example, GraphDB or OpenID token)
  auth_header:

  # TTYG installation ID
  installation_id: __default__
```

Note that you need to specify a username even if GraphDB is not configured with security. Threads (and thus chats) are associated with the username.

If GraphDB has security enabled you must provide either the password (for using HTTP Basic auth) or an authorization header (for all other authentication types, e.g., an OpenAI Bearer token). 

### 5. Run the Client

```bash
python chat.py <assistant-id> (<thread-id>|new)
```

## Usage

1. **Start the client**: Run the `chat.py` script to initiate communication. Note that you must pass the assistant ID and thread ID (or new to create a new thread) as arguments. If you run the script without arguments, it will show a list of all existing assistants and threads.
2. **Communicate**: Input natural language questions that will be processed by the OpenAI Assistant API and, if needed, translated into GraphDB tool queries that will allow the model to answer the questions.
3. **Inspect responses**: The model will answer the questions by using context or invoking tools.

### Commands

When running the chat, the following `!`-prefixed commands are available:
- `!help`: Displays a list of available commands.
- `!explain`: Shows the tools used to answer the last question.
- `!list`: Lists the available assistants and threads.
- `!assistant <assistant-id>`: Switches to a different assistant.
- `!thread <thread-id>|new`: Switches to a different thread or creates a new thread.
- `!rename <name>`: Renames the current thread.
- `!delete`: Deletes the current thread.

## Caveats

**Thread IDs and Persistence**: Thread IDs (chats) are persisted locally due to limitations of the OpenAI Assistants API. Threads created in the client will not be visible in the GraphDB Workbench and vice versa.

## Development Notes

### Source Code
- **`chat.py`**: Main code and entry point for running the client.
- **`thread_store.py`**: Handles thread management for queries and responses.
- **`config.py`**: Manages configuration loading and parsing.

### Extending the Client

This client can be extended to support more sophisticated interaction patterns. Modify the API integration logic in `chat.py` as needed.

## References

- [Talk to Your Graph Client for GraphDB blog post](http://ontotext.com/blog/talk-to-your-graph-client/)
- [Talk to Your Graph Documentation](https://graphdb.ontotext.com/documentation/10.8/talk-to-graph.html)
- [OpenAI Assistants API Documentation](https://platform.openai.com/docs/assistants/overview)

## License

This project is licensed under the Apache 2.0 License.
