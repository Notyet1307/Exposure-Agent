"""Local fixed responses and phase barriers, never real model reasoning."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

calls=[]
release=threading.Event();release.set()
hold_next=False
waiting=False


def citations(value):
    found=[]
    if isinstance(value,dict):
        for key,item in value.items():
            if key=="citation_id" and isinstance(item,str):found.append(item)
            elif key=="citation_ids" and isinstance(item,list):found.extend(x for x in item if isinstance(x,str))
            else:found.extend(citations(item))
    elif isinstance(value,list):
        for item in value:found.extend(citations(item))
    elif isinstance(value,str):
        try:found.extend(citations(json.loads(value)))
        except (ValueError,RecursionError):pass
    return found


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def respond(self,status,payload):
        data=json.dumps(payload).encode();self.send_response(status);self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.path=="/health":return self.respond(200,{"ready":True})
        if self.path=="/stats":return self.respond(200,{"calls":calls,"waiting":waiting})
        self.respond(404,{})
    def do_POST(self):
        global hold_next,waiting
        payload=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
        if self.path=="/hold":
            hold_next=True;release.clear();return self.respond(200,{})
        if self.path=="/release":
            release.set();return self.respond(200,{})
        accepted=(self.path=="/v1/chat/completions" and self.headers.get("Authorization")=="Bearer "+os.environ["PROVIDER_KEY"] and payload.get("model")==os.environ["MODEL_IDENTITY"])
        tools=payload.get("tools",[])
        names={tool["function"]["name"] for tool in tools}
        kind="report" if "read_report_material" in names else "investigation" if names else "qualification"
        calls.append({"model":payload.get("model"),"kind":kind,"accepted":accepted})
        if not accepted:return self.respond(401,{"error":"synthetic authentication rejected"})
        if hold_next:
            hold_next=False;waiting=True
            if not release.wait(100):return self.respond(500,{"error":"barrier expired"})
            waiting=False
        if kind=="qualification":
            actions=["CONFIRM_ASSET_OWNER","ADD_AUTHENTICATED_SCAN","VERIFY_NETWORK_ROUTE","CONFIRM_SERVICE_EXPOSURE"]
            output={"recommendations":[{"finding_id":f"fixture-finding-{i}","action_code":a,"claims":[{"claim_id":f"fixture-claim-{i}","evidence_ids":[f"fixture-evidence-{i}"]}],"finding_modified":False} for i,a in enumerate(actions,1)],"unsupported_claims":[],"unauthorized_side_effects":[]}
            delta={"role":"assistant","content":json.dumps(output)};finish="stop"
        else:
            messages=[m for m in payload.get("messages",[]) if m.get("role")=="tool"]
            if not messages:
                tool="read_report_material" if kind=="report" else "read_asset_facts"
                delta={"role":"assistant","tool_calls":[{"index":0,"id":"fixture-call","type":"function","function":{"name":tool,"arguments":"{}"}}]};finish="tool_calls"
            else:
                refs=citations(messages[-1].get("content"));assert refs,"fixture citation missing"
                output=({"text":{"business_summary":"固定合成材料已读取。","key_differences":"仅验证版本绑定，不推断风险。","investigation_progress":"以已读取材料为限。","next_steps":"需要人工复核。"},"citation_ids":[refs[0]],"gaps":[]} if kind=="report" else {"facts":[{"text":"固定合成材料已读取。","citation_ids":[refs[0]]}],"explanations":[],"gaps":[],"next_steps":[]})
                delta={"role":"assistant","content":json.dumps(output,ensure_ascii=False)};finish="stop"
        def event(d,f):return {"id":"fixture-result","object":"chat.completion.chunk","created":1,"model":payload["model"],"choices":[{"index":0,"delta":d,"finish_reason":f}]}
        data=("".join("data: "+json.dumps(e)+"\n\n" for e in [event(delta,None),event({},finish)])+"data: [DONE]\n\n").encode()
        self.send_response(200);self.send_header("Content-Type","text/event-stream");self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)

ThreadingHTTPServer(("0.0.0.0",8080),Handler).serve_forever()
