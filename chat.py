#!/usr/bin/env python3

"""
A simple client for GraphDB's Talk to Your Graph (TTYG).

The client leverages GraphDB's low-level TTYG to handle tool (query method) calls,
and the OpenAI Assistants API for natural language understanding and generating answers.
"""

import json
# noinspection PyUnresolvedReferences
# pylint: disable-next=unused-import
import readline
import sys
import time
from datetime import datetime
from textwrap import indent
from typing import override

import openai
import requests
from colorama import Fore
from colorama import Style
from colorama import init as colorama_init
from openai import OpenAI
from openai.lib.azure import AzureOpenAI
from openai.lib.streaming import AssistantEventHandler
from openai.types.beta.assistant import Assistant
from openai.types.beta.thread import Thread
from openai.types.beta.threads import TextContentBlock
from openai.types.beta.threads.runs.tool_calls_step_details import ToolCallsStepDetails
from requests.auth import AuthBase

from config import TTYGConfig
from thread_store import TTYGThreadStore

# Character limit for printing tool output
TOOL_OUTPUT_PRINT_LIMIT = 1000

# Metadata fields in threads
THREAD_METADATA_NAME = "name"
THREAD_METADATA_INSTALLATION_ID = "graphdb.installationId"
THREAD_METADATA_USERNAME = "graphdb.username"
THREAD_METADATA_UPDATED_AT = "graphdb.updatedAt"


class TTYGEventHandler(AssistantEventHandler):
    """Handles OpenAI streaming API events."""

    def __init__(self, config: TTYGConfig, client: OpenAI):
        super().__init__()
        self._config = config
        self._client = client

    @override
    def on_event(self, event):
        """Called automatically for various events."""
        if event.event == "thread.run.requires_action":
            # Event is emitted when the model wants to call a tool
            self._handle_requires_action(event.data)

    @override
    def on_text_delta(self, delta, snapshot):
        """Called automatically to print parts of a streaming response."""
        TTYGClient.print_assistant_message_delta(delta.value)

    @override
    def on_text_done(self, text):
        """Called automatically when all of a response has been received."""
        print()
        TTYGClient.print_message_boundary()

    def _handle_requires_action(self, data):
        """Process all tool calls."""

        tool_outputs = []

        for tool in data.required_action.submit_tool_outputs.tool_calls:
            tool_name = tool.function.name
            tool_args = tool.function.arguments
            try:
                output = self._call_tool(data.assistant_id, tool_name, tool_args)
            except ValueError as ve:
                output = ve.args[0]

            TTYGClient.print_tool_output(tool_name, output)

            if output is not None:
                tool_outputs.append({"tool_call_id": tool.id, "output": output})

        self._submit_tool_outputs(tool_outputs)

    def _submit_tool_outputs(self, tool_outputs):
        """Submit all tool outputs at the same time."""
        with self._client.beta.threads.runs.submit_tool_outputs_stream(
                tool_outputs=tool_outputs,
                run_id=self.current_run.id,
                thread_id=self.current_run.thread_id,
                event_handler=TTYGEventHandler(self._config, self._client)) as stream:
            stream.until_done()

    def _call_tool(self, assistant_id, tool_name, tool_args):
        """Call a single tool (TTYG query method) via the GraphDB REST API."""
        auth = None
        if self._config.graphdb_auth_header is not None:
            auth = GraphDBCustomAuth(self._config.graphdb_auth_header)
        elif self._config.graphdb_password is not None:
            auth = (self._config.graphdb_username, self._config.graphdb_password)

        try:
            response = requests.post(
                f"{self._config.graphdb_url}/rest/ttyg/agents/{assistant_id}/{tool_name}",
                data=tool_args,
                headers={"content-type": "text/plain;charset=UTF-8", "accept": "text/plain;charset=UTF-8"},
                auth=auth,
                timeout=60)
            if response.status_code == 200:
                return response.text
            TTYGClient.print_error(f">>> HTTP error: {response.status_code}")
        except requests.exceptions.ConnectionError as e:
            TTYGClient.print_error(f">>> Connection error: {e}")

        return f"Fatal error calling tool {tool_name}. Do not retry and inform the user."


# pylint: disable-next=too-few-public-methods
class GraphDBCustomAuth(AuthBase):
    """Provides custom Authorization header for GraphDB API calls."""

    def __init__(self, authorization):
        self._authorization = authorization

    def __call__(self, r):
        r.headers["Authorization"] = self._authorization
        return r


class TTYGClient:
    """
    Talk to Your Graph client.

    Instantiate the class and call `run_chat` to use the client.
    """

    def __init__(self, config_file, threads_file):
        colorama_init()

        self._config = TTYGConfig(config_file)
        self._thread_store = TTYGThreadStore(threads_file)

        key = self._config.openai_apikey
        url = self._config.openai_url
        if url is not None and "azure.com" in url:
            self._client = AzureOpenAI(api_key=key, azure_endpoint=url,
                                       api_version=self._config.openai_azure_api_version)
        else:
            self._client = OpenAI(api_key=key)

    def run_chat(self, req_assistant_id, req_thread_id) -> None:
        """
        Run the chat interaction - the user will be prompted to enter questions
        and will receive responses, until they terminate the conversation.

        The user can also switch assistants and threads via !-prefixed commands.
        """
        assistant = self._init_assistant(req_assistant_id)
        if assistant is None:
            return

        thread = self._init_thread(req_thread_id)
        if thread is None:
            return

        TTYGClient.print_welcome_prompt()

        while True:
            msg = input("> ").strip()

            if msg == "":
                break

            if msg.startswith("!"):
                cmd_args = msg.split(maxsplit=1)
                cmd = cmd_args[0]
                arg = cmd_args[1] if len(cmd_args) > 1 else None
                if cmd == "!help":
                    self.print_help()
                elif cmd == "!explain":
                    if TTYGClient._check_thread(thread):
                        self._explain(thread.id)
                elif cmd == "!list":
                    self.print_assistants_and_threads()
                elif cmd == "!delete":
                    if TTYGClient._check_thread(thread):
                        self._delete_thread(thread.id)
                        thread = None
                elif cmd == "!rename":
                    if arg is None:
                        TTYGClient.print_error(">>> !rename requires a name argument")
                    else:
                        if TTYGClient._check_thread(thread):
                            self._rename_thread(thread.id, arg)
                elif cmd == "!assistant":
                    if arg is None:
                        TTYGClient.print_error(
                            ">>> !assistant requires an assistant ID argument")
                    else:
                        new_assistant = self._init_assistant(arg)
                        if new_assistant is not None:
                            assistant = new_assistant
                elif cmd == "!thread":
                    if arg is None:
                        TTYGClient.print_error(">>> !thread requires a thread ID argument")
                    else:
                        new_thread = self._init_thread(arg)
                        if new_thread is not None:
                            thread = new_thread
                else:
                    TTYGClient.print_error(f">>> Unknown command: {msg}")
            else:
                if TTYGClient._check_thread(thread):
                    TTYGClient.print_message_boundary()
                    self._ask(assistant.id, thread.id, msg)

    def _ask(self, assistant_id, thread_id, message) -> None:
        """Ask a question and print the result"""
        self._client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=message
        )

        handler = TTYGEventHandler(self._config, self._client)
        with self._client.beta.threads.runs.stream(
                thread_id=thread_id,
                assistant_id=assistant_id,
                event_handler=handler
        ) as stream:
            stream.until_done()

        self._update_thread_time(thread_id)

    def _explain(self, thread_id) -> None:
        """Print what tools were called to answer the last thing asked."""
        tool_calls = None
        runs = self._client.beta.threads.runs.list(thread_id, limit=1, order="desc")
        if len(runs.data) > 0:
            tool_calls = []
            run = runs.data[0]
            steps = self._client.beta.threads.runs.steps.list(run.id, thread_id=thread_id)
            for step in steps.data:
                if isinstance(step.step_details, ToolCallsStepDetails):
                    tool_calls.extend(step.step_details.tool_calls)

        if tool_calls is None:
            TTYGClient.print_info(">>> Nothing asked yet.")
        elif len(tool_calls) == 0:
            TTYGClient.print_info(">>> Answered directly without calling any tools")
        else:
            for tc in tool_calls:
                tool_name = tc.function.name
                tool_args = tc.function.arguments
                TTYGClient.print_info(f">>> Called tool: {tool_name}")
                TTYGClient.print_info(indent(tool_args, prefix="    "))

    def _installation_id_matches(self, installation_id) -> bool:
        """
        Return `True` if the provided installation ID matches the configured ID
        or is the default ID.
        """
        return installation_id in ("__default__", self._config.graphdb_installation_id)

    def _init_thread(self, req_thread_id) -> Thread | None:
        """
        Retrieve an existing thread by ID or create a new thread if the given thread ID is "new".
        If the thread is an existing thread, the last 3 question/responses will be printed.

        :returns: the created or retrieved thread
        """
        try:
            if req_thread_id == "new":
                thread = self._create_thread()
                TTYGClient.print_success(f">>> Created thread: {thread.id}")
                self._thread_store.put_thread(self._config.graphdb_username, thread.id)
            else:
                thread = self._retrieve_thread(req_thread_id)
                if thread is not None:
                    TTYGClient.print_success(
                        f">>> Using existing thread: {TTYGClient._get_thread_description(thread)}")
                    self._print_thread_history(thread.id, 3)

            return thread
        except openai.APIStatusError as e:
            TTYGClient.print_error(f">>> {e.message}")
            return None

    def _init_assistant(self, req_assistant_id) -> Assistant | None:
        """
        Retrieve an existing assistant and check if it is available to the configured
        TTYG installation ID.

        If the assistant does not exist or is not available, `None` is returned,
        and error messages are printed to the user.
        """
        try:
            assistant = self._client.beta.assistants.retrieve(req_assistant_id)
        except openai.APIStatusError as e:
            TTYGClient.print_error(f">>> {e.message}")
            return None

        installation_id = TTYGClient._get_assistant_installation_id(assistant)
        if not self._installation_id_matches(installation_id):
            TTYGClient.print_error(
                ">>> Assistant not associated with the configured TTYG installation ID.")
            return None

        TTYGClient.print_success(
            f">>> Using assistant: {TTYGClient._get_assistant_description(assistant)}")

        return assistant

    def _create_thread(self) -> Thread:
        """
        Create a new thread compatible with threads created via the TTYG UI.

        Note that threads created by TTYG in GraphDB Workbench will not be seen by this client
        and vice versa.
        """
        return self._client.beta.threads.create(metadata={
            THREAD_METADATA_NAME:
                f"[Unnamed chat@{datetime.now().replace(microsecond=0).isoformat()}]",
            THREAD_METADATA_INSTALLATION_ID: self._config.graphdb_installation_id,
            THREAD_METADATA_USERNAME: self._config.graphdb_username
        })

    def _retrieve_thread(self, thread_id) -> Thread | None:
        """
        Retrieve an existing thread with the given ID.

        Threads that exist but are not accessible (wrong installation ID or username)
        will not be returned.

        :returns: a `Thread` or `None` if the thread does not exist or is inaccessible.
        """
        try:
            thread = self._client.beta.threads.retrieve(thread_id)
            if not self._installation_id_matches(
                    TTYGClient._metadata_value(thread.metadata, THREAD_METADATA_INSTALLATION_ID)):
                TTYGClient.print_error(
                    ">>> Thread not associated with the configured TTYG installation ID.")
                return None
            if (TTYGClient._metadata_value(thread.metadata, THREAD_METADATA_USERNAME)
                    != self._config.graphdb_username):
                TTYGClient.print_error(
                    ">>> Thread not associated with the configured GraphDB username.")
                return None
            return thread
        except openai.APIStatusError as e:
            TTYGClient.print_error(f">>> {e.message}")
            return None

    def _rename_thread(self, thread_id, name) -> None:
        """Rename the thread identified by the supplied ID."""
        try:
            self._client.beta.threads.update(thread_id=thread_id, metadata={THREAD_METADATA_NAME: name})
        except openai.APIStatusError as e:
            TTYGClient.print_error(f">>> {e.message}")

    def _update_thread_time(self, thread_id) -> None:
        """Sets the last update time of the thread in the metadata."""
        try:
            self._client.beta.threads.update(thread_id=thread_id,
                                             metadata={THREAD_METADATA_UPDATED_AT: str(int(time.time()))})
        except openai.APIStatusError as e:
            TTYGClient.print_error(f">>> {e.message}")

    def _delete_thread(self, thread_id) -> None:
        """
        Delete the thread with the given ID from the OpenAI server and the local thread ID storage.
        """
        self._client.beta.threads.delete(thread_id)
        self._thread_store.remove_thread(self._config.graphdb_username, thread_id)
        TTYGClient.print_success(f">>> Thread {thread_id} was deleted.")

    def _print_thread_history(self, thread_id, limit) -> None:
        """Print the last `limit` user messages from thread history and their responses"""

        # Fetch the newest messages, somewhat over the desired limit.
        # The messages will be sorted be newest first.
        messages_data = self._client.beta.threads.messages.list(thread_id,
                                                                limit=3 * limit,
                                                                order="desc").data

        # Extract up to <limit> user messages and the responses they have
        found_user_messages = 0
        messages = []
        for msg in messages_data:
            if msg.role == "user":
                found_user_messages += 1
            contents = []
            for con in msg.content:
                if isinstance(con, TextContentBlock):
                    contents.append(con.text.value)
            messages.append((msg.role, contents))
            if found_user_messages == limit:
                break

        # Print the collected messages reversing the order so older messages come first
        for msg in reversed(messages):
            if msg[0] == "user":
                for content in msg[1]:
                    TTYGClient.print_user_message(content)
            else:
                for content in msg[1]:
                    TTYGClient.print_assistant_message(content)

    def print_assistants_and_threads(self) -> None:
        """Print the available TTYG assistants."""
        assistants = self._client.beta.assistants.list(limit=100).data
        if len(assistants) > 0:
            TTYGClient.print_info(">>> The available assistants are:")
            print()
            for ass in assistants:
                installation_id = TTYGClient._get_assistant_installation_id(ass)
                # Filtering by the TTYG installation ID ensures this client sees
                # only the intended assistants.
                if self._installation_id_matches(installation_id):
                    print(f"\t{TTYGClient._get_assistant_description(ass)}")
        else:
            TTYGClient.print_info(">>> There are no assistants available.")
            TTYGClient.print_info(">>> Please create a TTYG agent in GraphDB Workbench.")

        print()

        threads = []
        for thread_id in self._thread_store.list_threads(self._config.graphdb_username):
            thread = self._retrieve_thread(thread_id)
            if thread is not None:
                threads.append(thread)
        if len(threads) > 0:
            TTYGClient.print_info(">>> The persisted threads are:")
            print()
            for thread in threads:
                print(f"\t{TTYGClient._get_thread_description(thread)}")
        else:
            TTYGClient.print_info(">>> There are no persisted threads.")

    @staticmethod
    def _check_thread(thread) -> bool:
        """
        Return `True` if the thread is not `None` (i.e., not already deleted).
        If the thread is `None` an error will be printed to the user.
        """
        if thread is None:
            TTYGClient.print_error(
                ">>> Thread was deleted, switch to another thread to chat/operate on thread.")
            return False
        return True

    @staticmethod
    def _metadata_value(metadata: object, field_name, default_value=None) -> str | None:
        if metadata is not None:
            return metadata.get(field_name, default_value)
        return default_value

    @staticmethod
    def _get_assistant_installation_id(assistant) -> str | None:
        """Retrieve the TTYG installation ID from the assistant metadata."""
        base_metadata = TTYGClient._metadata_value(assistant.metadata, "graphdb.ttyg")
        if base_metadata is not None:
            return json.loads(base_metadata).get("installationId")
        return None

    @staticmethod
    def _get_thread_description(thread) -> str:
        """Return a simple description of the thread composed of the thread ID and name."""
        return f"{thread.id} ({TTYGClient._get_thread_name(thread)})"

    @staticmethod
    def _get_thread_name(thread) -> str:
        # The names of threads are stored in the metadata, but it's not a requirement to have a name
        return TTYGClient._metadata_value(thread.metadata, THREAD_METADATA_NAME, "<no name>")

    @staticmethod
    def _get_assistant_description(assistant) -> str:
        """Return a simple description of the assistant composed of the assistant ID and name."""
        return f"{assistant.id} ({assistant.name})"

    @staticmethod
    def shorten_print_arg(arg, limit):
        """
        Shorten the string representation of an object to fit into a limited number
        of characters. Objects whose string representation is longer than the limit
        will be truncated to the limit and a note about truncation will be added.
        """
        string = str(arg)
        if len(string) > limit:
            return (string[:limit]
                    + f"{Fore.RED}... (output truncated at {limit:,}){Style.RESET_ALL}")
        return arg

    @staticmethod
    def print_assistant_message(msg):
        TTYGClient.print_assistant_message_delta(msg)
        print()
        TTYGClient.print_message_boundary()

    @staticmethod
    def print_assistant_message_delta(delta):
        print(delta, end="", flush=True)

    @staticmethod
    def print_user_message(msg):
        print(f"> {msg}")
        TTYGClient.print_message_boundary()

    @staticmethod
    def print_message_boundary():
        TTYGClient.print_color(Fore.YELLOW, "...")

    @staticmethod
    def print_color(color, text):
        """Print text in color"""
        print(f"{color}{text}{Style.RESET_ALL}")

    @staticmethod
    def print_error(text):
        TTYGClient.print_color(Fore.RED, text)

    @staticmethod
    def print_info(text):
        TTYGClient.print_color(Fore.CYAN, text)

    @staticmethod
    def print_success(text):
        TTYGClient.print_color(Fore.YELLOW, text)

    @staticmethod
    def print_tool_output(tool_name, tool_output):
        TTYGClient.print_success(
            f">>>>>> Called {tool_name}, result ({len(tool_output):,} characters):")
        TTYGClient.print_success(
            indent(TTYGClient.shorten_print_arg(tool_output, TOOL_OUTPUT_PRINT_LIMIT), "    "))
        print()

    @staticmethod
    def print_help():
        print("\t!help                      - display the list of commands")
        print("\t!explain                   - show the tools used to answer the last question")
        print("\t!list                      - show the available assistants and threads")
        print("\t!assistant <assistant-id>  - switch to a different assistant")
        print("\t!thread <thread-id>|new    - switch to a different thread")
        print("\t!rename <name>             - rename the current thread")
        print("\t!delete                    - delete the current thread")
        print()

    @staticmethod
    def print_welcome_prompt():
        TTYGClient.print_info(
            ">>> Start conversation by asking something. Press Enter (empty input) to quit.")
        TTYGClient.print_info(
            ">>> Type !help and press Enter to get a list of !-prefixed commands.")

    @staticmethod
    def print_usage():
        print("GraphDB Talk to Your Graph Client")
        print("Usage: chat.py <assistant-id> (<thread-id>|new)")
        print()
        print("You can provide an existing thread ID, "
              "or the special value 'new' to create a new thread.")
        print()


def main():
    ttyg = TTYGClient("client.yaml", "threads.yaml")

    if len(sys.argv) != 3:
        TTYGClient.print_usage()
        ttyg.print_assistants_and_threads()
        sys.exit(1)
    else:
        try:
            ttyg.run_chat(sys.argv[1], sys.argv[2])
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
