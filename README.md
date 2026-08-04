# Tariff errors search (profile extract + compare)

Self-contained project: **Gemini** authors **extraction profiles** (YAML); **Python** extracts both workbooks to **TariffLine** JSONL and diffs OLD vs NEW.

**Full explanation (purpose, steps, code map):** [`docs/FULL_GUIDE.md`](docs/FULL_GUIDE.md)

## Layout

```text
tariff-errors-search/          ← CODE (Colab: /content/tariff-errors-search/)
  pipeline.py         # profile + OLD/NEW xlsx → extract → compare (one step)
  extract.py          # workbook + profile → JSONL only
  compare.py          # OLD/NEW JSONL → report.xlsx
  tariff_compare/paths.py   # DATA_ROOT on Google Drive (config, input, output)

Google Drive DATA folder:     ← edit DATA_ROOT in tariff_compare/paths.py
  config/profiles/    # Gem YAML
  input/old rate/     # OLD .xlsx
  input/new rate/     # NEW .xlsx
  output/             # compare_…/report.xlsx
```

**Google Colab:** see [`docs/COLAB.md`](docs/COLAB.md). Run with:

```python
exec(open("/content/tariff-errors-search/pipeline.py").read())
```

## Quick start

```powershell
cd tariff-errors-search
pip install -r requirements.txt

# 1) Gem profile → config/profiles/my_template.yaml
# 2) OLD/NEW .xlsx → input/old rate/ and input/new rate/
# 3) One interactive run:
python pipeline.py
```

Open **`output/compare_<old>__vs__<new>/report.xlsx`**.

Step-by-step for your files: **`docs/WHAT_YOU_DO.md`**.

## CLI

```powershell
python pipeline.py `
  --profile config/profiles/scm_global_air_factsheet.yaml `
  --old "input/old rate/old.xlsx" `
  --new "input/new rate/new.xlsx" `
  --run-name siemens_compare
```

Gem: **`docs/GEM_PROFILE_PROMPT.md`**. Full workflow: **`docs/PIPELINE.md`**.
