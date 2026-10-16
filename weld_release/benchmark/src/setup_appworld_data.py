"""Unpack the official bundled AppWorld data locally using its installed package.

Run with the separate AppWorld Python 3.12 environment. Never deletes or replaces
an existing data directory. This is offline and uses the official package codec.
"""
from pathlib import Path
import json

def main():
    root=Path(__file__).resolve().parents[1]
    target=(root/'local_only/appworld_workspace').resolve()
    target.relative_to(root.resolve())
    data=target/'data'
    if data.exists():
        required=[data/'tasks/22cc237_1/ground_truth/private_data.json',data/'tasks/b0a8eae_1/ground_truth/private_data.json']
        if all(p.exists() for p in required):
            print(json.dumps({'status':'EXISTING_DATA_READY','data':str(data)}));return
        raise RuntimeError('Existing incomplete data directory retained; inspect it before choosing a new release directory.')
    from appworld.common.constants import PASSWORD,SALT
    from appworld.common.utils import unpack_bundle
    bundle=root/'source_bundles/appworld-data-0.1.0.bundle'
    if not bundle.is_file():raise FileNotFoundError(bundle)
    target.mkdir(parents=True,exist_ok=True)
    unpack_bundle(bundle_file_path=str(bundle),base_directory=str(target),password=PASSWORD,salt=SALT)
    if not (data/'tasks/22cc237_1/ground_truth/private_data.json').exists():raise RuntimeError('Official task data missing after unpacking')
    print(json.dumps({'status':'UNPACKED','data':str(data)}))

if __name__=='__main__':main()
