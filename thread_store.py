import os

import yaml


class TTYGThreadStore:
    """
    Provides storage for OpenAI thread IDs.

    The OpenAI API maintains the threads but does not provide an endpoint for listing threads,
    so we need to store the IDs locally if we want to reuse them (continue an existing chat).
    """

    def __init__(self, threads_file):
        self._filename = threads_file
        self._load()

    def list_threads(self, username):
        return self._threads.get(username, [])

    def put_thread(self, username, thread_id):
        if username in self._threads.keys():
            self._threads[username].append(thread_id)
        else:
            self._threads[username] = [thread_id]

        self._save()

    def remove_thread(self, username, thread_id):
        if username in self._threads.keys() and thread_id in self._threads[username]:
            self._threads[username].remove(thread_id)
            self._save()

    def _load(self):
        if os.path.isfile(self._filename):
            with open(self._filename, "r", encoding="utf-8") as f:
                self._threads = yaml.safe_load(f)
        else:
            self._threads = {}

    def _save(self):
        with open(self._filename, "w", encoding="utf-8") as f:
            yaml.dump(self._threads, f)
