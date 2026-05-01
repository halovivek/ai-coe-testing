# LLM & RAG Quality Assurance — Testing Methodology

**Pillar:** AI Quality · **Version:** 1.0  
**Applicable systems:** LLM-powered features · RAG pipelines · Agentic AI products

---

## Why LLM testing is different

Traditional software testing validates deterministic outputs. LLMs produce probabilistic, context-sensitive responses that can drift, hallucinate, produce biased content, or fail silently in ways that pass all existing test metrics. Standard automation frameworks are blind to these failure modes.

This methodology defines a structured, repeatable approach to evaluating LLM and RAG systems across five quality dimensions.

---

## Five quality dimensions

### 1. Factual accuracy & hallucination detection

**What can go wrong:** The model confidently states incorrect facts, fabricates citations, or confuses entities.

**Test approach:**
- Build a golden dataset of questions with verified ground-truth answers
- Compute factual accuracy using exact match + semantic similarity (ROUGE-L, BERTScore)
- Run adversarial prompts designed to trigger confabulation
- Track hallucination rate per model version and per knowledge domain

**Tools:** DeepEval · Trulens · PromptFoo  
**Acceptance threshold:** Hallucination rate < 3% on production query distribution

```python
from deepeval import evaluate
from deepeval.metrics import HallucinationMetric
from deepeval.test_case import LLMTestCase

test_case = LLMTestCase(
    input="What is the RBI's repo rate as of Q1 2025?",
    actual_output=llm_response,
    context=["The RBI maintained repo rate at 6.5% in Q1 2025"]
)

metric = HallucinationMetric(threshold=0.3)
evaluate([test_case], [metric])
```

---

### 2. RAG retrieval quality

**What can go wrong:** The retriever surfaces irrelevant chunks, misses critical context, or over-retrieves noise.

**Test approach:**
- Evaluate retrieval precision and recall against labelled query-context pairs
- Test chunk boundary effects — questions spanning multiple chunks
- Measure context utilization: does the LLM use retrieved context or ignore it?
- Validate citation accuracy in responses that reference source documents

**Metrics:**
- Context Precision: fraction of retrieved chunks that are relevant
- Context Recall: fraction of relevant information that was retrieved
- Answer Relevancy: semantic similarity of answer to the question

**Tools:** Trulens RAG Triad · Ragas · LlamaIndex evaluation

---

### 3. Semantic consistency & response stability

**What can go wrong:** Semantically identical questions yield contradictory or inconsistent answers across runs.

**Test approach:**
- Generate paraphrase sets (5–10 variants per question) and compare response semantics
- Run identical prompts N=20 times; measure variance in critical facts
- Test for position bias: does answer quality degrade when context is reordered?
- Validate that model conclusions are stable under mild prompt perturbations

**Acceptance threshold:** Semantic similarity (cosine) > 0.85 across paraphrase variants

---

### 4. Bias, fairness & toxicity

**What can go wrong:** Model outputs exhibit demographic bias, produce harmful content, or treat user groups inequitably.

**Test approach:**
- Counterfactual testing: replace protected attributes (gender, religion, ethnicity) and compare outputs
- Run model on bias benchmark datasets (WinoBias, BBQ, BOLD)
- Toxicity detection on all outputs using automated classifiers (Perspective API)
- Audit outputs for regulatory sensitivity: PII leakage, financial advice without disclaimer, medical claims

**Tools:** Fairlearn · Giskard · What-If Tool · IBM AI Fairness 360  
**Regulatory alignment:** EU AI Act (High-Risk AI) · GDPR Article 22 · RBI AI governance guidelines

---

### 5. Agentic safety & control

**What can go wrong:** An AI agent takes unintended actions, loops infinitely, or violates scope boundaries when given tool access.

**Test approach:**
- Define action-space constraints and test boundary violations explicitly
- Inject adversarial system prompts to test prompt injection resistance
- Validate that agents request human confirmation before irreversible actions
- Test graceful degradation when tools are unavailable or return errors
- Measure goal completion rate vs. unintended side-effect rate

**Tools:** PromptFoo red-teaming · Custom agent harness · LangSmith tracing

---

## Testing pipeline integration

```yaml
# .github/workflows/llm-quality-gate.yml
name: LLM Quality Gate

on: [pull_request]

jobs:
  llm-eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Run hallucination evaluation
        run: |
          python -m pytest tests/llm/test_hallucination.py \
            --threshold 0.03 \
            --dataset tests/data/golden_qa.jsonl

      - name: Run RAG quality metrics
        run: |
          python -m pytest tests/llm/test_rag_quality.py \
            --context-precision-min 0.80 \
            --context-recall-min 0.75

      - name: Run bias audit
        run: |
          python tests/llm/bias_audit.py \
            --fail-on-score-below 0.85

      - name: Publish eval report
        uses: actions/upload-artifact@v4
        with:
          name: llm-eval-report
          path: reports/llm-quality-*.html
```

---

## LLM quality scorecard

| Dimension | Metric | Target | Blocker |
|-----------|--------|--------|---------|
| Hallucination | Hallucination rate | < 3% | > 8% |
| RAG | Context Precision | > 80% | < 60% |
| RAG | Context Recall | > 75% | < 55% |
| Consistency | Paraphrase similarity | > 0.85 | < 0.70 |
| Safety | Toxicity rate | < 0.1% | > 1% |
| Bias | Fairness score | > 0.85 | < 0.70 |
| Agentic | Goal completion | > 90% | < 75% |

---

## Recommended toolchain

| Tool | Use case | License |
|------|----------|---------|
| DeepEval | LLM unit testing framework | MIT |
| Trulens | RAG quality & feedback | Apache 2.0 |
| PromptFoo | Prompt evaluation & red-teaming | MIT |
| Giskard | Bias & vulnerability scanning | Apache 2.0 |
| Ragas | RAG-specific evaluation | MIT |
| Evidently | LLM monitoring in production | Apache 2.0 |

---

## Further reading

- [NIST AI Risk Management Framework](https://www.nist.gov/system/files/documents/2023/01/26/AI%20RMF%201.0.pdf)
- [EU AI Act — High Risk AI requirements](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52021PC0206)
- [Google's Responsible AI practices](https://ai.google/responsibility/responsible-ai-practices/)
- [Anthropic Constitutional AI](https://www.anthropic.com/research/constitutional-ai-harmlessness-from-ai-feedback)

---

*Maintained by the AI CoE for Testing · Feedback via GitHub Issues*
