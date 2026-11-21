# DataHealth AI — Visual Identity

## Brand idea

**Data that connects. Insights you can trace.**

The visual identity highlights interoperability, provenance, and responsible clinical-data exploration. It is a local educational prototype that uses **synthetic patient records only**, not a diagnostic application.

## Color tokens

| Token | Color | Purpose |
|---|---|---|
| Night Navy | `#081120` | Primary canvas |
| Deep Slate | `#111E33` | Surface / sidebar |
| Sea Glass | `#4ADAC5` | Primary actions and highlights |
| Clinical Blue | `#78A9FF` | Secondary accent |
| Ice White | `#EBF4FF` | Primary text |
| Mist Blue | `#A2B7CD` | Secondary text |

## Typography and accessibility

Use the platform sans-serif stack without downloading custom fonts. Prioritize clear hierarchy, high contrast, and responsive layouts. Keep essential warnings as readable text, not icon-only labels.

## Interface principles

1. **Patient-scoped:** Always show the selected synthetic patient's name and retain their UUID for SQL/RAG lookups.
2. **Evidence-first:** Source metadata and unmodified evidence must remain accessible from every answer.
3. **Conservative language:** Citation ID validity must never be presented as clinical or factual validation.
4. **Separation of concerns:** Visual styling in `assets/datahealth.css` and `.streamlit/config.toml`; SQL/RAG and citation policies remain in existing Python modules.
5. **Local-only:** Keep the server bound to `127.0.0.1`. Never expose the demonstration to a public network or upload real medical records.

## Key files

- `app.py`: branded interface and chat experience
- `assets/datahealth.css`: layout and component styling
- `.streamlit/config.toml`: base Streamlit theme
- `src/ui_backend.py`: unchanged patient-scoped backend

## Known limitations

The design has no authentication or authorization model for real patient access. Styling does not affect or fix the remaining fact-level errors found in Phase 8.1. Continue to evaluate claim support and patient isolation before deploying any expanded prototype.
