# DataHealth AI — Power BI Integration

This optional portfolio module turns the synthetic SQLite Gold Layer into **privacy-minimized, aggregate CSV datasets** suitable for Power BI Desktop.

## Install

No extra Python packages required (standard library only).

At the project root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_power_bi_export.py" -v
.\.venv\Scripts\python.exe -m src.export_power_bi --database "data/gold/datahealth.db" --output "reports/power_bi/source_csv"
```

Follow `docs/power_bi_dashboard_guide.md` for Power BI setup, visual layout, DAX measures, and interpretation cautions.

**Synthetic data only.** This module is not for clinical use. It does not upload data or connect to Power BI Service. Do not commit the local `reports/` outputs.
