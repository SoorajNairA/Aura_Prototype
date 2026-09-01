from __future__ import annotations
import json
import pytest
from aura.infrastructure.llm.vertex import VertexAuthenticationError,VertexPlannerProvider,VertexResponseError,VertexSafetyError,VertexTimeoutError
from aura.planner.live import LivePlanner
from aura.planner.schemas import ProjectRequest

class Response:
 def __init__(self,status=200,data=None,headers=None,text=""):
  self.status_code=status;self._data=data;self.headers=headers or {};self.text=text
 def json(self):return self._data
class Session:
 def __init__(self,*responses):self.responses=list(responses);self.calls=[]
 def post(self,url,**kwargs):self.calls.append((url,kwargs));value=self.responses.pop(0);return value() if callable(value) else value
def envelope(text,finish="STOP",usage=None):return {"candidates":[{"finishReason":finish,"content":{"parts":[{"text":text}]}}],"usageMetadata":usage or {}}

def test_vertex_request_uses_global_publisher_endpoint_and_schema():
 session=Session(Response(data=envelope('{"ok":true}')));provider=VertexPlannerProvider("project","global","gemini-test",session=session)
 provider.generate_structured([{"role":"user","content":"plan"}],system_prompt="bounded",response_schema={"type":"OBJECT"})
 url,request=session.calls[0];assert "projects/project/locations/global/publishers/google/models/gemini-test:generateContent" in url
 assert request["json"]["generationConfig"]["responseMimeType"]=="application/json" and request["json"]["generationConfig"]["responseSchema"]=={"type":"OBJECT"}

def test_vertex_usage_metadata_and_diagnostics_are_normalized():
 provider=VertexPlannerProvider("p","global","m",session=Session(Response(data=envelope('{"ok":true}',usage={"promptTokenCount":10,"candidatesTokenCount":4,"totalTokenCount":14}))))
 result=provider.generate_structured([{"role":"user","content":"x"}]);assert (result.input_tokens,result.output_tokens,result.total_tokens)==(10,4,14);assert provider.get_diagnostics()["backend"]=="vertex"

def test_vertex_transient_retry_is_bounded():
 delays=[];session=Session(Response(503,headers={"Retry-After":"0"}),Response(data=envelope('{"ok":true}')));provider=VertexPlannerProvider("p","global","m",max_retries=1,session=session,sleep=delays.append)
 assert provider.generate([{"role":"user","content":"x"}])=='{"ok":true}' and len(session.calls)==2

def test_vertex_auth_timeout_malformed_and_safety_errors():
 for response,error in ((Response(403,text="denied"),VertexAuthenticationError),(Response(data={"bad":True}),VertexResponseError),(Response(data=envelope("{}","SAFETY")),VertexSafetyError),(Response(data=envelope("not json")),VertexResponseError)):
  with pytest.raises(error):VertexPlannerProvider("p","global","m",session=Session(response)).generate([{"role":"user","content":"x"}])
 class ReadTimeout(Exception):pass
 with pytest.raises(VertexTimeoutError):VertexPlannerProvider("p","global","m",session=Session(lambda:(_ for _ in ()).throw(ReadTimeout()))).generate([{"role":"user","content":"x"}])

def test_live_planner_repairs_one_schema_invalid_vertex_result():
 valid=json.dumps({"projectName":"Fan","objective":"Build a temperature controlled fan","requirements":["Low voltage"],"assumptions":[],"components":["controller","sensor","fan","driver"]})
 provider=VertexPlannerProvider("p","global","m",session=Session(Response(data=envelope('{"wrong":true}')),Response(data=envelope(valid))))
 outcome=LivePlanner(provider,2).plan(ProjectRequest("Fan","Build a temperature controlled fan",("Low voltage",)))
 assert outcome.mode=="live_model" and outcome.repair_attempts==1 and not outcome.first_pass_valid

def test_vertex_configuration_rejects_missing_values():
 with pytest.raises(ValueError):VertexPlannerProvider("","global","model")
 class Missing(VertexPlannerProvider):
  def _authorized_session(self):raise VertexAuthenticationError("Run ADC login")
 assert not Missing("p","global","m").is_available()
