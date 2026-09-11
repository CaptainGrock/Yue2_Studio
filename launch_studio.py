"""Start the workspace's local YuE2 Studio without reinstalling the package."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from yue2_studio.server import main

if __name__=='__main__':
    main()
