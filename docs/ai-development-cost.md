# AI development cost report

[← Project home](../README.md) · [Guides](README.md)

We built a tool to limit screen time. Then we gave several AIs what appears to be unlimited screen time to build it. **The parenting budget has never looked so modest.**

## Historical snapshot

- **Snapshot date:** 2026-11-22
- **Repository:** [HAL Gaming Control](https://github.com/mhalak/hal-gaming-control)
- **Baseline `main` commit:** [`7f661142333bb148c3c55bdcb591da41c6b4f552`](https://github.com/mhalak/hal-gaming-control/commit/7f661142333bb148c3c55bdcb591da41c6b4f552)
- **Basis:** Hermes/Paperclip agent usage and estimates supplied by the project team, combined with a separate historical ChatGPT development estimate.
- **Cost basis:** approximate **API-equivalent USD** values from the project's working estimate; **not actual subscription spending or a verified bill**.

## Model usage

Input includes fresh input, cache reads and cache writes where these were available in the underlying Hermes data. The GPT-6 line combines the estimated ChatGPT work with GPT-6 Astra activity recorded by Hermes.

| Model | Input tokens | Output tokens | Total tokens | Estimated API-equivalent cost (USD) |
| --- | ---: | ---: | ---: | ---: |
| GPT-6 (including Astra) | 68,900,000 | 6,071,000 | 74,971,000 | $866.55 |
| Claude Sonnet 5 | 142,500,000 | 536,000 | 143,036,000 | $58.01 |
| Claude Sonnet 5.5 | 178,842,300 | 1,585,000 | 180,427,300 | $65.99 |
| GPT-5.6 Sol | 28,135,000 | 169,000 | 28,304,000 | $21.24 |
| GPT-5.6 Terra | 1,184,000 | 124,000 | 1,308,000 | $3.86 |
| GPT-6.1 Terra | 12,066,000 | 85,000 | 12,151,000 | $3.47 |
| **TOTAL (allocated by model)** | **431,627,300** | **8,570,000** | **440,197,300** | **$1,019.12** |

## How to read these numbers

This is a historical **estimate**, not precise metering of all development or a billed cost. Hermes supplied model-level measurements for Paperclip agents and delegated subagents, plus a less certain estimate for one main chat. The ChatGPT share is independently estimated at **54 million input + 6 million output tokens** (60 million total) and is folded into the GPT-6 row; it is **not added a second time**. It was calculated as 60% of a deliberately conservative 100-million-token upper-bound estimate. Model names reflect the labels in the source report, not independently verified API model identifiers.

The prior working cost calculation used model-specific price assumptions and caching discounts. Because the detailed cache-by-model ledger and exact pricing assumptions are not captured here, the **USD column preserves that prior estimate and is not independently reproducible from the aggregate input/output columns alone**. In particular, cached input may be cheaper than fresh input. Real costs under ChatGPT/Codex/Claude subscriptions are different from API-equivalent estimates, and image generation and other tools are not fully represented.

The source report's overall input total was about **30.9 million tokens higher** than the individually attributed model rows. That **unallocated discrepancy is excluded** from this table and its cost total rather than assigned to a model without evidence. The estimate may also contain some overlap between chat sessions and agent work.

**Future snapshots:** append a dated section or update this snapshot with per-model measured input, cached input, output, a tariff/source, and the corresponding `main` commit. Never silently treat an estimate as a measured bill.

*Powered by HAL Systems. The kids get gaming limits; the robots apparently got a blank cheque.*
