import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from engine.context_assembly import ContextBlockConfig, assemble_context_block


class _FakeLLMClient:
    async def generate_response(self, messages, response_model=None):
        return {"summary": "Alice is a CS student who likes robotics and currently has login issues."}


class _FakeGraphiti:
    def __init__(self, edges):
        self.driver = object()
        self.llm_client = _FakeLLMClient()
        self._edges = edges

    async def search(self, query, group_ids, num_results):
        return list(self._edges)[:num_results]


class ContextAssemblyTests(unittest.IsolatedAsyncioTestCase):
    @patch("engine.context_assembly.EntityNode.get_by_group_ids", new_callable=AsyncMock)
    async def test_assemble_context_block_includes_summary_dates_and_filters_invalid(self, mock_get_nodes):
        now = datetime.now(timezone.utc)
        mock_get_nodes.return_value = [
            SimpleNamespace(name="Alice", summary="Computer science student"),
        ]
        edges = [
            SimpleNamespace(
                uuid="fact-1",
                fact="Alice studies at Peking University",
                created_at=now,
                valid_at=now - timedelta(days=5),
                invalid_at=None,
                expired_at=None,
                score=0.92,
            ),
            SimpleNamespace(
                uuid="fact-2",
                fact="Alice had a temporary dorm access issue",
                created_at=now - timedelta(days=1),
                valid_at=now - timedelta(days=3),
                invalid_at=now - timedelta(hours=1),
                expired_at=None,
                score=0.85,
            ),
        ]

        block = await assemble_context_block(
            graphiti=_FakeGraphiti(edges),
            user_id="alice",
            group_ids=["session-1"],
            config=ContextBlockConfig(max_facts=5),
        )

        self.assertIn("<USER_SUMMARY>", block.context)
        self.assertIn("<FACTS>", block.context)
        self.assertIn("Alice studies at Peking University", block.context)
        self.assertIn("present", block.context)
        self.assertEqual(block.user_summary.startswith("Alice is a CS student"), True)
        self.assertEqual([fact.uuid for fact in block.facts], ["fact-1"])

    @patch("engine.context_assembly.EntityNode.get_by_group_ids", new_callable=AsyncMock)
    async def test_token_budget_trims_fact_list(self, mock_get_nodes):
        mock_get_nodes.return_value = []
        edges = [
            SimpleNamespace(
                uuid=f"fact-{index}",
                fact="X" * 80,
                created_at=datetime.now(timezone.utc),
                valid_at=None,
                invalid_at=None,
                expired_at=None,
                score=1.0 - index * 0.1,
            )
            for index in range(3)
        ]

        block = await assemble_context_block(
            graphiti=_FakeGraphiti(edges),
            user_id="alice",
            group_ids=["session-1"],
            config=ContextBlockConfig(
                max_tokens=25,
                max_facts=3,
                include_summary=False,
            ),
        )

        self.assertEqual(len(block.facts), 1)
        self.assertIn("<FACTS>", block.context)


if __name__ == "__main__":
    unittest.main()
