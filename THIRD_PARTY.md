# Third-party code and design references

No source file is copied verbatim from an upstream project in the initial
implementation.

| Upstream | License | Use in this repository |
|---|---|---|
| [LangGraph Graph API](https://github.com/langchain-ai/langgraph) | MIT | Runtime dependency; custom model/tool graph is implemented locally. |
| [vLLM `bench serve`](https://github.com/vllm-project/vllm/blob/main/vllm/benchmarks/serve.py) | Apache-2.0 | Design reference for seeded open-loop Poisson/Gamma arrivals. The local generator is independently implemented for end-to-end agent requests. |
| [vLLM OpenTelemetry example](https://github.com/vllm-project/vllm/tree/main/examples/observability/opentelemetry) | Apache-2.0 | Configuration reference for OTLP trace propagation. |
| [Qwen3 function calling](https://github.com/QwenLM/Qwen3/blob/main/docs/source/framework/function_call.md) | Apache-2.0 | Command and API reference for the deferred vLLM backend. |
| [cAdvisor](https://github.com/google/cadvisor) | Apache-2.0 | Optional Linux container metrics service in Docker Compose. |
| [Ayo](https://github.com/ttaliacc/Ayo) | MIT | Architecture reference only; no code imported. |
| [ParrotServe](https://github.com/microsoft/ParrotServe) | MIT | Architecture reference only; deliberately not imported or deployed. |

Before adapting upstream source in the future, add the exact commit, source
path, local destination, and relevant copyright notice here.
