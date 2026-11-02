"""Network-free reference validator / fixture interoperability bridge."""
import argparse
import json
import sys
from pathlib import Path
from .canonical import loads,dumps,sha256,seal
from .validate import validate
from .archive import decode


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=['validate','canonical','seal','archive'])
    args=parser.parse_args()
    try:
        raw=sys.stdin.buffer.read(32*1024*1024+1)
        if len(raw)>32*1024*1024:raise ValueError('INPUT_LIMIT')
        value=decode(raw) if args.operation=='archive' else loads(raw)
        if args.operation in {'validate','archive'}: result=validate(value)
        elif args.operation=='seal':result=seal(value)
        else:result={'canonical_utf8':dumps(value).decode(),'sha256':sha256(value)}
        print(json.dumps({'ok':True,'result':result},ensure_ascii=False))
    except (ValueError,TypeError,RecursionError) as error:
        print(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False));sys.exit(1)

if __name__=='__main__': main()
