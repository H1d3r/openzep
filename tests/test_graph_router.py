import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from graphiti_core.nodes import EpisodeType
from graphiti_core.utils.bulk_utils import RawEpisode

from models.graph import GraphAddBatchRequest
from routers.graph import _add_episode_bulk_resilient


def _raw_episode(name: str) -> RawEpisode:
    return RawEpisode(
        name=name,
        content=f"{name} content",
        source_description="test",
        source=EpisodeType.text,
        reference_time=datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc),
    )


class GraphRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_bulk_fallback_splits_batch_after_rate_limit(self):
        graphiti = AsyncMock()

        async def bulk_side_effect(raw_episodes, **kwargs):
            if len(raw_episodes) > 1:
                raise RuntimeError("429 rate limit exceeded")
            return None

        graphiti.add_episode_bulk.side_effect = bulk_side_effect
        body = GraphAddBatchRequest(graph_id="graph-test", episodes=[])
        raw_episodes = [_raw_episode("ep1"), _raw_episode("ep2")]

        with patch("routers.graph.asyncio.sleep", new=AsyncMock()):
            await _add_episode_bulk_resilient(graphiti, body, raw_episodes, ontology=None)

        self.assertEqual(graphiti.add_episode_bulk.await_count, 4)
        graphiti.add_episode.assert_not_awaited()

    async def test_bulk_fallback_uses_single_episode_write_for_last_item(self):
        graphiti = AsyncMock()
        graphiti.add_episode_bulk.side_effect = RuntimeError("429 rate limit exceeded")
        body = GraphAddBatchRequest(graph_id="graph-test", episodes=[])
        raw_episodes = [_raw_episode("ep1")]

        with patch("routers.graph.asyncio.sleep", new=AsyncMock()):
            await _add_episode_bulk_resilient(graphiti, body, raw_episodes, ontology=None)

        self.assertEqual(graphiti.add_episode_bulk.await_count, 2)
        graphiti.add_episode.assert_awaited_once()
        self.assertEqual(graphiti.add_episode.await_args.kwargs["name"], "ep1")


if __name__ == "__main__":
    unittest.main()
