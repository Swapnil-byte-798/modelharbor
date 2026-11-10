import json
import os
from fastapi import Depends, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from .runtime import Fault, make_app
from .service import Gateway

app, auth, reviewer = make_app("ModelHarbor")
_gateway = None


def service():
    global _gateway
    if _gateway is None:
        _gateway = Gateway(
            os.path.join(os.environ.get("DATA_DIR", ".data"), "modelharbor.db")
        )
    return _gateway


class ClientInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    budget: int = Field(default=20000, gt=0)


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = "auto"
    messages: list[dict]
    max_tokens: int = Field(default=256, ge=1, le=2000)
    stream: bool = False


@app.post("/admin/clients", dependencies=[Depends(auth)])
def create_client(body: ClientInput):
    return service().create_client(body.name, body.budget)


@app.post("/v1/chat/completions")
def chat(
    body: ChatInput,
    authorization: str = Header(default=""),
    idempotency_key: str = Header(default=""),
):
    if body.model != "auto":
        raise Fault(
            "Use the auto model alias; provider models are configured by the operator."
        )
    if not authorization.startswith("Bearer "):
        raise Fault("Supply the gateway client token.", 401)
    result = service().chat(
        authorization.removeprefix("Bearer "),
        body.messages,
        idempotency_key,
        body.max_tokens,
    )
    if not body.stream:
        return result

    def events():
        chunk = {
            "id": result["id"],
            "object": "chat.completion.chunk",
            "created": result["created"],
            "model": result["model"],
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": result["choices"][0]["message"]["content"],
                    },
                    "finish_reason": None,
                }
            ],
        }
        yield "data: " + json.dumps(chunk) + "\n\n"
        chunk["choices"] = [{"index": 0, "delta": {}, "finish_reason": "stop"}]
        chunk["usage"] = result["usage"]
        yield "data: " + json.dumps(chunk) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"X-Gateway-Stream-Mode": "buffered"},
    )


@app.get("/usage")
def usage(authorization: str = Header(default="")):
    return service().report(authorization.removeprefix("Bearer "))
