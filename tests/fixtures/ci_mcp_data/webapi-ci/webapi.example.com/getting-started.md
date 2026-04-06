# Getting Started

WebAPI is a framework for building APIs.

## Installation

```bash
pip install webapi
```

## Quick Example

```python
from webapi import WebAPI

app = WebAPI()

@app.get("/")
def root():
    return {"message": "Hello"}
```
