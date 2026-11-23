import argparse
from pathlib import Path
import uvicorn
from .model import AgentModel
from .api import create_app
from .search import SearchProvider


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description='Run the local live meeting copilot')
    parser.add_argument('--env',type=Path,default=root/'.env')
    parser.add_argument('--data',type=Path,default=root/'runs/copilot-local')
    parser.add_argument('--history-db',type=Path)
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--search-key',type=Path,help='Optional Bocha key file (never sent to the browser)')
    args=parser.parse_args()
    model=AgentModel(args.env if args.env.is_file() else None)
    search=SearchProvider(args.search_key) if args.search_key else None
    app=create_app(args.data,root/'demo/public/scenario-cross.json',model,args.history_db,search)
    uvicorn.run(app,host='127.0.0.1',port=args.port)


if __name__=='__main__':main()
