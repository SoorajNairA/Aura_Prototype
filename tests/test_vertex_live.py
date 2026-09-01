from __future__ import annotations
import os
import pytest
from aura.infrastructure.llm.vertex import VertexPlannerProvider
from aura.planner.live import LivePlanner
from aura.planner.schemas import ProjectRequest
from aura.verification.service import VerificationService
from tests.test_goal5_generalization import CORPUS

pytestmark=pytest.mark.vertex_live

@pytest.mark.skipif(os.getenv("AURA_RUN_VERTEX_LIVE")!="1",reason="Set AURA_RUN_VERTEX_LIVE=1 to incur Vertex requests")
def test_selected_vertex_model_satisfies_goal5_corpus_live():
 project=os.environ["AURA_GCP_PROJECT"];model=os.getenv("AURA_VERTEX_MODEL","gemini-3.1-flash-lite");provider=VertexPlannerProvider(project,"global",model,20,1)
 for benchmark in CORPUS:
  outcome=LivePlanner(provider,20).plan(ProjectRequest(benchmark["id"],benchmark["objective"],("Use low voltage",)));assert outcome.mode=="live_model" and outcome.first_pass_valid
  assert VerificationService().verify(outcome.plan).accepted;assert set(benchmark["concepts"])<={item.id for item in outcome.plan.components}
