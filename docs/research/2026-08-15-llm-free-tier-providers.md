# Free-tier LLM API providers — research note (verified 2026-08-15)

Purpose: choose a runtime LLM provider chain for the Airport Investment Agent (Python, tool calling, JSON output, zero cost).

| Provider | Free-tier models | RPM / RPD / TPM / TPD | Tools + JSON | Context (free) | OpenAI-compat | Signup | Reliability notes |
|---|---|---|---|---|---|---|---|
| **Google Gemini (AI Studio)** | Gemini 3.x Flash / Flash-Lite, 2.5 Flash/Flash-Lite (2.5 Pro now paid) | ~10 RPM / 1,500 RPD / 250K TPM (3.x Flash); ~15 RPM (3.5 Flash/Lite). No TPD | Yes — best function calling + `responseSchema` | 1M | Yes: `generativelanguage.googleapis.com/v1beta/openai/` | Instant key, no card | Google cut quotas 50–80% Dec 2025; numbers no longer in docs — check AI Studio dashboard |
| **Groq** | `openai/gpt-oss-120b`, `gpt-oss-20b`, `qwen/qwen3.6-27b` (Llama 3.x deprecated Jun 2026) | 30 RPM / 1K RPD / 8K TPM / 200K TPD | Yes, all models; JSON mode | 131K | Yes: `api.groq.com/openai/v1` | Instant, no card | **TPM (8–12K) is the binding limit**; free catalog churns |
| **NVIDIA NIM (build.nvidia.com)** | 100+ (DeepSeek V3.2, Kimi K2.5, GLM, Llama 4, Qwen 3.5) | 40 RPM; token caps reportedly removed | Yes on most instruct models (verify per model) | 128K–1M | Yes: `integrate.api.nvidia.com/v1` | Instant, no card | Latency variable; per-model tool support inconsistent |
| **Cerebras** | `gpt-oss-120b`, `gemma-4-31b` | 5 RPM / 30K TPM / 1M TPD | Yes, strict schema mode | 65K | Yes | Instant | Now a $5/30-day trial, not standing free tier |
| **SambaNova** | DeepSeek-V3.1, Llama-3.3-70B, gpt-oss-120b | 20 RPM / **20 RPD** | Yes | varies | Yes | Instant | 20 req/day → last resort only |
| **OpenRouter `:free`** | ~15 rotating | 20 RPM / 50 RPD (1,000 RPD after $10 credits) | Yes on many; `openrouter/free` router | 128K–1M | Native | Instant | Catalog rotates; upstream flakiness |
| **Cloudflare Workers AI** | 50+ open models | 10,000 Neurons/day (~1,300 responses) | Yes | varies | Yes | CF account | Neurons burn fast on big models |
| **Mistral** | Broad | unpublished, ~1 RPM reported | Yes | 128K | Yes | Phone verify | Smoke-test only |
| **Hugging Face** | routed | $0.10/month credit | depends | varies | Yes | Instant | Not a real free tier |
| **Together AI** | — | No free tier | — | — | — | — | Excluded |
| **GitHub Models** | — | **Retired 30 Jul 2026** | — | — | — | — | Excluded |
| **Anthropic** | — | No permanent free tier (small trial credit) | — | — | — | — | Paid only |

## Recommended chain
1. **Primary: Gemini 3.x Flash** (OpenAI-compat endpoint). 250K TPM absorbs agent tool loops; 1,500 RPD is the most generous daily allowance; best tool-calling/structured output; 1M context.
2. **Fallback 1: Groq `openai/gpt-oss-120b`** (or `qwen/qwen3.6-27b`). Fast burst absorber on Gemini 429s. Never pin deprecated Llama names.
3. **Fallback 2: NVIDIA NIM.** 40 RPM, effectively no token cap — the deep tail. Validate tool calling per model.
4. Optional: OpenRouter `openrouter/free`; Cerebras (trial).

**Unification: LiteLLM `Router` in-process** with declarative `fallbacks`, cooldowns, param normalization. Raw `openai` SDK w/ base_url works but you hand-roll retries and per-provider JSON-schema quirks (Gemini compat rejects some keywords; Cerebras needs `additionalProperties:false`).

## Design implications
- Model names come from config, never hardcoded; health-check on startup.
- Budget for ~10 RPM primary: keep tool loops short (≤4 LLM calls/answer), cache tool results, keep tool schemas compact.
- Deterministic path must be fully usable with LLM unavailable (graceful degradation).

## Unverified
Gemini exact limits (third-party trackers); Mistral limits; NIM "no token cap"; per-model tool support on NIM/Cloudflare.

Sources: console.groq.com/docs/rate-limits · ai.google.dev/gemini-api/docs/rate-limits · openrouter.ai/docs/api-reference/limits · inference-docs.cerebras.ai/support/rate-limits · docs.sambanova.ai/docs/en/models/rate-limits · developers.cloudflare.com/workers-ai/platform/pricing · github.blog/changelog/2026-07-30-github-models-is-now-retired · docs.litellm.ai/docs/proxy/reliability
