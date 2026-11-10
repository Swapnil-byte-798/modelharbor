"""Tenant-scoped admission, provider fallback, caching, and reconciled usage."""

from dataclasses import dataclass
from decimal import Decimal
import json
import re
import secrets
import time
from uuid import uuid4

import httpx

from .runtime import Fault, Store, digest, require, settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients(id TEXT PRIMARY KEY,name TEXT NOT NULL,token_hash TEXT UNIQUE NOT NULL,
 budget INTEGER NOT NULL,spent INTEGER NOT NULL DEFAULT 0,bucket REAL NOT NULL,bucket_at REAL NOT NULL,capacity INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS cache(client_id TEXT NOT NULL REFERENCES clients(id),key TEXT NOT NULL,payload TEXT NOT NULL,
 expires REAL NOT NULL,PRIMARY KEY(client_id,key));
CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,client_id TEXT NOT NULL REFERENCES clients(id),request_key TEXT NOT NULL,
 fingerprint TEXT NOT NULL,state TEXT NOT NULL,reserved INTEGER NOT NULL,payload TEXT,error TEXT,created REAL NOT NULL,
 UNIQUE(client_id,request_key));
CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY AUTOINCREMENT,request_id TEXT NOT NULL REFERENCES requests(id),
 provider TEXT NOT NULL,input_tokens INTEGER,output_tokens INTEGER,accounted_tokens INTEGER NOT NULL,estimated_usd TEXT,complete INTEGER NOT NULL)
"""


def mask_pii(text):
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", text)
    text = re.sub(r"(?<!\d)(?:\d[ -]?){12}(?!\d)", "[IDENTIFIER]", text)
    return re.sub(r"(?<!\w)(?:\+\d{1,3}[ -]?)?(?:\d[ -]?){10}(?!\d)", "[PHONE]", text)


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str
    input_price: Decimal | None = None
    output_price: Decimal | None = None


class Provider:
    def __init__(self, config: ProviderConfig, transport=None):
        self.config = config
        self.transport = transport

    def complete(self, messages, max_tokens):
        key = settings().get(
            "GROQ_API_KEY" if self.config.name == "groq" else "OPENAI_API_KEY", ""
        )
        if not key:
            raise Fault(f"The {self.config.name} provider key is not configured.", 503)
        base = (
            "https://api.groq.com/openai/v1"
            if self.config.name == "groq"
            else "https://api.openai.com/v1"
        )
        try:
            with httpx.Client(transport=self.transport, timeout=25) as client:
                response = client.post(
                    base + "/chat/completions",
                    headers={"Authorization": "Bearer " + key},
                    json={
                        "model": self.config.model,
                        "messages": messages,
                        "max_completion_tokens": max_tokens,
                        "temperature": 0,
                    },
                )
            if response.status_code != 200:
                raise Fault(
                    f"Provider returned HTTP {response.status_code}.",
                    502
                    if response.status_code >= 500 or response.status_code == 429
                    else 400,
                )
            value = response.json()
            content = value["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Missing text")
            usage = value.get("usage", {})
            return {
                "text": content,
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
            }
        except Fault:
            raise
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            raise Fault(
                "Provider request failed or returned invalid output.", 502
            ) from None


class Gateway:
    def __init__(self, path=".data/modelharbor.db", providers=None, clock=time.time):
        self.store = Store(path, SCHEMA)
        self.clock = clock
        self.providers = providers or [
            Provider(ProviderConfig("groq", "openai/gpt-oss-20b")),
            Provider(ProviderConfig("openai", "gpt-4.1-mini")),
        ]
        self.failures = {}
        self.open_until = {}

    def create_client(self, name, budget=20000, capacity=5):
        name = require(name, "Client name", 100)
        if not isinstance(budget, int) or budget <= 0 or not 1 <= capacity <= 100:
            raise Fault("Use a positive token budget and a capacity from 1 to 100.")
        token = secrets.token_urlsafe(32)
        identifier = str(uuid4())
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO clients(id,name,token_hash,budget,bucket,bucket_at,capacity) VALUES(?,?,?,?,?,?,?)",
                (
                    identifier,
                    name,
                    digest(token),
                    budget,
                    capacity,
                    self.clock(),
                    capacity,
                ),
            )
        return {"id": identifier, "client_token": token, "budget_tokens": budget}

    def client(self, token):
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM clients WHERE token_hash=?", (digest(token),)
            ).fetchone()
            if row is None:
                raise Fault("Invalid gateway client token.", 401)
            return dict(row)

    def chat(self, token, messages, request_key, max_tokens=256):
        client = self.client(token)
        request_key = require(request_key, "Request key", 100)
        if (
            not isinstance(messages, list)
            or not 1 <= len(messages) <= 20
            or not 1 <= max_tokens <= 2000
        ):
            raise Fault("Use 1-20 messages and 1-2000 output tokens.")
        clean = []
        for message in messages:
            if (
                not isinstance(message, dict)
                or set(message) != {"role", "content"}
                or message["role"] not in {"user", "assistant", "system"}
            ):
                raise Fault("Each message needs a supported role and text content.")
            content = require(message["content"], "Message", 12000)
            if re.search(
                r"ignore\s+(previous|system)|reveal.*(api key|secret)", content, re.I
            ):
                raise Fault("The input triggered the configured instruction guard.")
            clean.append({"role": message["role"], "content": mask_pii(content)})
        fingerprint = digest(
            [
                messages,
                max_tokens,
                [provider.config.model for provider in self.providers],
            ]
        )
        now = self.clock()
        identifier = str(uuid4())
        # UTF-8 bytes plus framing and the output allowance are a conservative admission estimate.
        reservation = len(json.dumps(clean).encode()) + 512 + max_tokens
        cache_key = fingerprint
        with self.store.transaction() as connection:
            old = connection.execute(
                "SELECT * FROM requests WHERE client_id=? AND request_key=?",
                (client["id"], request_key),
            ).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise Fault("Request key is bound to a different payload.", 409)
                if old["state"] == "done":
                    return json.loads(old["payload"])
                raise Fault(
                    "The original request is in progress or failed; inspect its usage before a new attempt.",
                    409,
                )
            client = dict(
                connection.execute(
                    "SELECT * FROM clients WHERE id=?", (client["id"],)
                ).fetchone()
            )
            available = min(
                float(client["capacity"]),
                client["bucket"] + max(0, now - client["bucket_at"]),
            )
            if available < 1:
                raise Fault("Client rate limit exceeded.", 429)
            cached = connection.execute(
                "SELECT payload FROM cache WHERE client_id=? AND key=? AND expires>?",
                (client["id"], cache_key, now),
            ).fetchone()
            reserve = 0 if cached else reservation * len(self.providers)
            if client["spent"] + reserve > client["budget"]:
                raise Fault("Client token budget would be exceeded.", 429)
            connection.execute(
                "UPDATE clients SET spent=spent+?,bucket=?,bucket_at=? WHERE id=?",
                (reserve, available - 1, now, client["id"]),
            )
            connection.execute(
                "INSERT INTO requests VALUES(?,?,?,?,?,?,NULL,NULL,?)",
                (
                    identifier,
                    client["id"],
                    request_key,
                    fingerprint,
                    "running",
                    reserve,
                    now,
                ),
            )
            if cached:
                result = json.loads(cached["payload"])
                result["gateway"] = {**result["gateway"], "cache_hit": True}
                connection.execute(
                    "UPDATE requests SET state='done',payload=? WHERE id=?",
                    (json.dumps(result), identifier),
                )
                return result
        accounted = 0
        attempts = []
        result = None
        last_error = None
        for provider in self.providers:
            name = provider.config.name
            if self.open_until.get(name, 0) > now:
                continue
            try:
                output = provider.complete(clean, max_tokens)
                input_tokens = output.get("input_tokens")
                output_tokens = output.get("output_tokens")
                complete = all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                    for value in [input_tokens, output_tokens]
                )
                charged = input_tokens + output_tokens if complete else reservation
                accounted += charged
                price = None
                if (
                    complete
                    and provider.config.input_price is not None
                    and provider.config.output_price is not None
                ):
                    price = str(
                        (
                            Decimal(input_tokens) * provider.config.input_price
                            + Decimal(output_tokens) * provider.config.output_price
                        )
                        / Decimal(1_000_000)
                    )
                attempts.append(
                    (name, input_tokens, output_tokens, charged, price, int(complete))
                )
                self.failures[name] = 0
                result = {
                    "id": "chatcmpl-" + identifier,
                    "object": "chat.completion",
                    "created": int(now),
                    "model": provider.config.model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": output["text"]},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": input_tokens,
                        "completion_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens
                        if complete
                        else None,
                    },
                    "gateway": {
                        "cache_hit": False,
                        "provider": name,
                        "usage_complete": complete,
                        "attempts": len(attempts),
                        "estimated_usd": price,
                    },
                }
                break
            except Fault as error:
                last_error = error
                if error.status == 503:
                    continue
                accounted += reservation
                attempts.append((name, None, None, reservation, None, 0))
                self.failures[name] = self.failures.get(name, 0) + 1
                if self.failures[name] >= 3:
                    self.open_until[name] = now + 30
                if error.status == 400:
                    break
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE clients SET spent=MAX(0,spent-?+?) WHERE id=?",
                (reserve, accounted, client["id"]),
            )
            for attempt in attempts:
                connection.execute(
                    "INSERT INTO usage(request_id,provider,input_tokens,output_tokens,accounted_tokens,estimated_usd,complete) VALUES(?,?,?,?,?,?,?)",
                    (identifier, *attempt),
                )
            if result:
                result["gateway"]["accounted_tokens_all_attempts"] = accounted
                connection.execute(
                    "UPDATE requests SET state='done',payload=? WHERE id=?",
                    (json.dumps(result), identifier),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO cache VALUES(?,?,?,?)",
                    (client["id"], cache_key, json.dumps(result), now + 300),
                )
            else:
                connection.execute(
                    "UPDATE requests SET state='failed',error=? WHERE id=?",
                    ("Provider attempts did not produce a result", identifier),
                )
        if result is None:
            raise Fault(
                str(last_error) if last_error else "No provider was available.", 502
            )
        return result

    def report(self, token):
        client = self.client(token)
        with self.store.transaction() as connection:
            usage = [
                dict(row)
                for row in connection.execute(
                    "SELECT u.provider,u.input_tokens,u.output_tokens,u.accounted_tokens,u.estimated_usd,u.complete FROM usage u JOIN requests r ON u.request_id=r.id WHERE r.client_id=?",
                    (client["id"],),
                )
            ]
        return {
            "client": client["name"],
            "budget_tokens": client["budget"],
            "accounted_tokens": client["spent"],
            "attempts": usage,
        }
