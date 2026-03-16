import unittest

from graphiti_core.nodes import EpisodeType

from engine.data_ingestion import normalize_episode_body, normalize_episode_type


class DataIngestionTests(unittest.TestCase):
    def test_json_payload_is_normalized_to_text(self):
        body = normalize_episode_body(
            '{"user":{"name":"Alice"},"skills":["python","ml"]}',
            "json",
        )

        self.assertIn("user.name is Alice", body)
        self.assertIn("skills[0] is python", body)
        self.assertIn("skills[1] is ml", body)

    def test_invalid_type_falls_back_to_text(self):
        self.assertEqual(normalize_episode_body("plain text", "unknown"), "plain text")
        self.assertEqual(normalize_episode_type("unknown"), EpisodeType.text)


if __name__ == "__main__":
    unittest.main()
