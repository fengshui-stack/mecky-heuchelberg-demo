import os
import uvicorn
from .bootstrap import main as bootstrap

def main():
    bootstrap()
    uvicorn.run("mecky.api:app",host="0.0.0.0",port=int(os.getenv("PORT","8000")))

if __name__=="__main__": main()
