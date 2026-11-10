from pathlib import Path
import tempfile
from .runtime import run_cli
from .service import Gateway, ProviderConfig


class FixtureProvider:
    config = ProviderConfig("fixture", "fixture-response")

    def complete(self, messages, max_tokens):
        return {
            "text": "Explicit provider-contract fixture",
            "input_tokens": 15,
            "output_tokens": 5,
        }


def demo():
    with tempfile.TemporaryDirectory() as directory:
        gateway = Gateway(Path(directory) / "demo.db", providers=[FixtureProvider()])
        client = gateway.create_client("demo")
        first = gateway.chat(
            client["client_token"],
            [{"role": "user", "content": "Explain caching"}],
            "demo-1",
        )
        second = gateway.chat(
            client["client_token"],
            [{"role": "user", "content": "Explain caching"}],
            "demo-2",
        )
        return {
            "mode": "injected_fixture_provider",
            "first": first,
            "cached": second,
            "live_provider_tested": False,
        }


def main():
    run_cli("modelharbor", demo, ("GROQ_API_KEY", "OPENAI_API_KEY"))
