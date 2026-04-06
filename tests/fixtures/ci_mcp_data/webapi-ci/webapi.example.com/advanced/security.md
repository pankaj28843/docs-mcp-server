# Security

Implement authentication and authorization.

## API Keys

```python
from webapi.security import APIKeyHeader

api_key = APIKeyHeader(name="X-API-Key")

@app.get("/protected")
def protected(key: str = Depends(api_key)):
    return {"status": "authenticated"}
```
