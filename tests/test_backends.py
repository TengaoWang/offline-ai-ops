import unittest

from llm import client, config


class BackendAdapterTest(unittest.TestCase):
    def setUp(self):
        self.saved = config.BACKEND, config.EMBED_BACKEND, client._post_url

    def tearDown(self):
        config.BACKEND, config.EMBED_BACKEND, client._post_url = self.saved

    def test_ollama_chat_mapping(self):
        config.BACKEND = "ollama"
        called = []
        client._post_url = lambda base, path, body: called.append((base, path, body)) or {"message": {"content": "ok"}}
        self.assertEqual(client.chat([{"role": "user", "content": "q"}]), "ok")
        self.assertEqual(called[0][1], "/api/chat")

    def test_llama_cpp_chat_mapping(self):
        config.BACKEND = "llama.cpp"
        called = []
        client._post_url = lambda base, path, body: called.append((base, path, body)) or {
            "choices": [{"message": {"content": '{"ok":true}'}}]}
        result = client.chat([{"role": "user", "content": "q"}], schema={"type": "object"})
        self.assertEqual(result, '{"ok":true}')
        self.assertEqual(called[0][1], "/v1/chat/completions")
        self.assertEqual(called[0][2]["response_format"]["type"], "json_schema")

    def test_llama_cpp_embedding_order(self):
        config.EMBED_BACKEND = "llama.cpp"
        client._post_url = lambda *a, **k: {"data": [{"index": 1, "embedding": [0, 1]},
                                                       {"index": 0, "embedding": [1, 0]}]}
        self.assertEqual(client.embed(["a", "b"], "embed"), [[1, 0], [0, 1]])


if __name__ == "__main__":
    unittest.main()
