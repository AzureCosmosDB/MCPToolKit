# Datasets

This repository includes the evaluation code used by Harness-1, but it does not
bundle large retrieval corpora or private Chroma indexes.

## Public Ready-To-Run Path: BrowseComp+

BrowseComp+ is the recommended public smoke/evaluation dataset for this release.
The evaluator expects the public BrowseComp+ query/answer files and qrels on
disk, plus a Chroma collection containing the corresponding BrowseComp+ corpus
chunks.

### 1. Download BrowseComp+

Clone the public BrowseComp+ release and follow its instructions to obtain the
decrypted query/answer file:

```bash
git clone https://github.com/texttron/BrowseComp-Plus external/BrowseComp-Plus
```

After setup, you should have files equivalent to:

```text
external/BrowseComp-Plus/topics-qrels/queries.tsv
external/BrowseComp-Plus/topics-qrels/qrel_golds.txt
external/BrowseComp-Plus/topics-qrels/qrel_evidence.txt
external/BrowseComp-Plus/data/browsecomp_plus_decrypted.jsonl
```

### 2. Configure local paths

Copy `.env.example` to `.env.local` and point these variables at the downloaded
files:

```bash
BROWSECOMPPLUS_QUERIES_PATH=external/BrowseComp-Plus/topics-qrels/queries.tsv
BROWSECOMPPLUS_QRELS_GOLD_PATH=external/BrowseComp-Plus/topics-qrels/qrel_golds.txt
BROWSECOMPPLUS_QRELS_EVIDENCE_PATH=external/BrowseComp-Plus/topics-qrels/qrel_evidence.txt
BROWSECOMPPLUS_ANSWERS_PATH=external/BrowseComp-Plus/data/browsecomp_plus_decrypted.jsonl
```

### 3. Build or provide the BrowseComp+ retrieval collection

The search harness retrieves from Chroma. For BrowseComp+, create a Chroma
collection named `browsecomp_plus_test` containing the BrowseComp+ corpus chunks,
with document IDs matching the qrel document IDs. Configure your Chroma access in
`.env.local`:

```bash
CHROMA_API_KEY=...
CHROMA_DATABASE=...
```

At minimum, each indexed chunk should preserve:

- the document/chunk ID used in the qrels,
- text content,
- any metadata your Chroma deployment requires for retrieval.

The evaluator looks up the collection name from the dataset class, so keeping
the collection name `browsecomp_plus_test` is the least surprising path.

### 4. Run a BrowseComp+ Harness-1 eval

Set your checkpoint path privately in the environment, then run:

```bash
set -a && source .env.local && set +a

PYTHONPATH=. uv run python inference/evaluate_harness1.py \
  --dataset browsecompplus \
  --split test \
  --collection-split test \
  --max-turns 40 \
  --temperature 1.0 \
  --checkpoints harness1="$HARNESS1_TINKER_CHECKPOINT" \
  --output tmp/eval_harness1_browsecompplus.json
```

The released Hugging Face checkpoint can be used for model loading and serving,
but the full search evaluation still requires a configured retrieval backend and
the Harness-1 tool environment.

## Other In-Domain Corpora

The `web`, `sec`, and `patents` in-domain corpora used in the paper are not
distributed here as public ready-made datasets/indexes. To reproduce those
settings, construct the corresponding data and Chroma collections yourself. We
recommend using the Context-1 data-generation repository as the reference
pipeline:

https://github.com/chroma-core/context-1-data-gen

Once your corpora are indexed in Chroma with compatible collection names and
document IDs, the same Harness-1 evaluation scripts can target those datasets.
