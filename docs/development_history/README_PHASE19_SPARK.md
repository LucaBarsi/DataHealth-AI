# DataHealth AI — Phase 19: Local Spark FHIR ETL

A small, optional PySpark proof of concept using *synthetic FHIR Bundle JSON* and an isolated Parquet output directory. All source code, schema names, and documentation are in English.

## Safety and scope

- **Educational prototype only. No real patient information or clinical validation.**
- Does not change `data/gold/datahealth.db`, your original `data/processed` pipeline, the Streamlit demo, or the Power BI CSVs.
- Uses the full FHIR `Bundle.entry[].resource` array, not just the first Bundle.
- Selects only essential structured fields. No names, addresses, phone numbers, or free-text document bodies are exported.
- Raw Bundle file count is not a patient count. Row totals from raw files may differ from the existing SQL Gold Layer because earlier transformation and deduplication rules differ.
- Do **not** commit or upload the raw synthetic data or generated Parquet files to your public GitHub repository without an explicit release review.

## Install / verify

From the project root on Windows PowerShell, using your existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip show pyspark
```

Expected version: `4.3.0` (Java JDK 21 and Python 3.12 already checked).

## Install these package files

Copy **`src/spark_etl.py`** into the project's `src/` folder and **`tests/test_spark_etl.py`** into `tests/`. Keep your existing files intact. You can copy this README into the project root as well.

## Run self-contained integration tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_spark_etl.py" -v
```

The tests create **invented JSON fixtures** in temporary directories. They do not read or alter your 114 real local Synthea bundle files.

## Execute the full ETL

```powershell
.\.venv\Scripts\python.exe -m src.spark_etl run --input "data/raw/synthea_sample_data_fhir_latest" --output "data/spark_demo" --report "reports/spark/phase19_summary.json"
```

Outputs: separate `data/spark_demo/silver/fhir_resources/` (one Parquet directory) and `data/spark_demo/gold/` (five aggregated Parquet directories), plus `reports/spark/phase19_summary.json`. Spark writes directories containing one or more `.parquet` part-files. The default `.mode('overwrite')` replaces **only this separate demo output**, so use a dedicated output path.

## Check outputs

```powershell
Get-Content "reports/spark/phase19_summary.json"
Get-ChildItem "data/spark_demo/gold" -Directory
```

The report includes bundle count, resource row count, counts by FHIR type, and minimal structural status; there is **no medically meaningful validation**.

## Windows troubleshooting

- The warning about absent `winutils.exe` may be harmless for local Spark reads and writes. If an operation actually fails, provide the **full traceback**; do not download `winutils.exe` from an untrusted website.
- `pyspark` warns about pandas 3.x with some pandas integrations. This script uses native Spark SQL, not pandas UDFs.
- Run all commands from the folder that contains `src`, `tests`, and `data`.
- Keep `JAVA_HOME` pointed to JDK 21; restart VS Code after modifying environment variables.

## Technical notes

The pipeline reads each complete JSON file with Spark's `text(..., wholetext=True)`, parses a deliberately restricted FHIR schema with `from_json`, flattens `entry[].resource`, creates a normalized Silver DataFrame, and computes five Gold aggregations via DataFrame `groupBy`, `count`, and date-format operations. Spark parquet writers generate the outputs. It does **not** replicate all rules of the existing Python/SQLite transformations; it is a demonstration of a complementary batch processing engine.
