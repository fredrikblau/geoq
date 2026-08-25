# Geoq data

`knowledge/` contains the reviewed, human-readable seed knowledge used to build the local retrieval index.

Each record has this shape:

```json
{
  "id": "qeshm_1",
  "question": "...",
  "answer": "...",
  "category": "...",
  "tags": ["..."]
}
```

Contributions should use stable unique IDs, clear Persian wording, and information that can be verified locally. For changing facts—opening hours, prices, routes, or phone numbers—include a verification date or source in the pull request. Run `pytest` after editing the data.
