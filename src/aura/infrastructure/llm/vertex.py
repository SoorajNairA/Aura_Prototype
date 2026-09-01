from __future__ import annotations

import json
import time
from typing import Any,Callable

from .provider import ModelGenerationResult

class VertexProviderError(RuntimeError): pass
class VertexAuthenticationError(VertexProviderError): pass
class VertexTimeoutError(VertexProviderError): pass
class VertexSafetyError(VertexProviderError): pass
class VertexResponseError(VertexProviderError): pass

class VertexPlannerProvider:
    """Managed Vertex publisher-model adapter using local ADC and normalized results."""
    SCOPE="https://www.googleapis.com/auth/cloud-platform"
    TRANSIENT={408,429,500,502,503,504}

    def __init__(self,project:str,location:str,model:str,timeout_seconds:float=25,max_retries:int=1,*,session:Any|None=None,sleep:Callable[[float],None]=time.sleep)->None:
        self.project=project.strip();self.location=location.strip();self.model=model.strip();self.timeout_seconds=timeout_seconds;self.max_retries=max(0,min(max_retries,2));self._session=session;self._sleep=sleep;self.last_result:ModelGenerationResult|None=None
        if not all((self.project,self.location,self.model)): raise ValueError("Vertex project, location, and model are required")

    @property
    def endpoint(self)->str:
        host="aiplatform.googleapis.com" if self.location=="global" else f"{self.location}-aiplatform.googleapis.com"
        return f"https://{host}/v1/projects/{self.project}/locations/{self.location}/publishers/google/models/{self.model}:generateContent"

    def _authorized_session(self):
        if self._session is not None:return self._session
        try:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            credentials,adc_project=google.auth.default(scopes=[self.SCOPE])
            if not self.project and adc_project:self.project=adc_project
            self._session=AuthorizedSession(credentials);return self._session
        except Exception as exc:
            raise VertexAuthenticationError("Google Application Default Credentials are unavailable. Run: gcloud auth application-default login") from exc

    def request_payload(self,messages:list[dict[str,str]],system_prompt:str|None,max_tokens:int,response_schema:dict[str,Any]|None=None)->dict[str,Any]:
        contents=[{"role":"model" if item["role"]=="assistant" else "user","parts":[{"text":item["content"]}]} for item in messages]
        generation:dict[str,Any]={"temperature":0.1,"maxOutputTokens":max_tokens,"responseMimeType":"application/json"}
        generation["thinkingConfig"]={"thinkingLevel":"MINIMAL" if "flash" in self.model else "LOW"}
        if response_schema:generation["responseSchema"]=response_schema
        payload={"contents":contents,"generationConfig":generation}
        if system_prompt:payload["systemInstruction"]={"parts":[{"text":system_prompt}]}
        return payload

    def generate_structured(self,messages:list[dict[str,str]],*,system_prompt:str|None=None,max_tokens:int=1200,response_schema:dict[str,Any]|None=None)->ModelGenerationResult:
        payload=self.request_payload(messages,system_prompt,max_tokens,response_schema);session=self._authorized_session();response=None
        for attempt in range(self.max_retries+1):
            try: response=session.post(self.endpoint,json=payload,timeout=self.timeout_seconds)
            except Exception as exc:
                if exc.__class__.__name__.lower().endswith("timeout"): raise VertexTimeoutError(f"Vertex request exceeded {self.timeout_seconds:g}s") from exc
                if attempt<self.max_retries:self._sleep(.25*(attempt+1));continue
                raise VertexProviderError(f"Vertex network request failed: {exc}") from exc
            if response.status_code in self.TRANSIENT and attempt<self.max_retries:
                retry=float(response.headers.get("Retry-After",.25));self._sleep(min(max(retry,0),2));continue
            break
        assert response is not None
        if response.status_code in {401,403}: raise VertexAuthenticationError(f"Vertex rejected ADC/IAM access ({response.status_code}). Required permission: aiplatform.endpoints.predict")
        if response.status_code>=400: raise VertexProviderError(f"Vertex request failed ({response.status_code}): {response.text[:500]}")
        try:data=response.json();candidate=data["candidates"][0];finish=candidate.get("finishReason","")
        except Exception as exc: raise VertexResponseError("Vertex returned a malformed response envelope") from exc
        if finish in {"SAFETY","BLOCKLIST","PROHIBITED_CONTENT","SPII"}: raise VertexSafetyError(f"Vertex blocked the response: {finish}")
        try:text="".join(part.get("text","") for part in candidate["content"]["parts"]);json.loads(text)
        except Exception as exc: raise VertexResponseError("Vertex did not return valid structured JSON") from exc
        usage=data.get("usageMetadata",{});result=ModelGenerationResult(text,int(usage["promptTokenCount"]) if "promptTokenCount" in usage else None,int(usage["candidatesTokenCount"]) if "candidatesTokenCount" in usage else None,int(usage["totalTokenCount"]) if "totalTokenCount" in usage else None,self.model,{"finishReason":finish})
        self.last_result=result;return result

    def generate(self,messages:list[dict[str,str]],*,system_prompt:str|None=None,max_tokens:int=512)->str:
        return self.generate_structured(messages,system_prompt=system_prompt,max_tokens=max_tokens).text
    def stream_generate(self,*args,**kwargs): yield self.generate(*args,**kwargs)
    def is_available(self)->bool:
        try:self._authorized_session();return True
        except VertexAuthenticationError:return False
    def get_diagnostics(self)->dict[str,Any]:
        return {"backend":"vertex","project":self.project,"location":self.location,"model":self.model,"structuredOutput":True,"streaming":False}
