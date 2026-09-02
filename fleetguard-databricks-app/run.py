import os
import uvicorn

if __name__ == "__main__":
    # Databricks Apps provides the port via the DATABRICKS_APP_PORT env var
    port = int(os.environ.get("DATABRICKS_APP_PORT", 8000))
    
    # Run the FastAPI app
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)
