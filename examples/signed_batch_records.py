"""SPDX-License-Identifier: Apache-2.0. Independent signed record batch."""
import argparse
import hashlib
import json
from batchcrypto import Runtime,generate_p256_key,verify_p256

def main():
    p=argparse.ArgumentParser();p.add_argument('--library',required=True);p.add_argument('--device',type=int,default=0);a=p.parse_args()
    records=[json.dumps({'record_id':i,'message':f'example-{i}'},sort_keys=True,separators=(',',':')).encode() for i in range(32)]
    with Runtime(a.library,a.device) as rt:
        rt.load_key(0,generate_p256_key(),'p256');public,epoch=rt.public_key(0)
        digests=rt.sha256(records);signatures=rt.sign(0,digests)
        for record,digest,sig in zip(records,digests,signatures):
            if digest!=hashlib.sha256(record).digest() or not verify_p256(public,digest,sig):raise RuntimeError('batch verification failed')
        print(json.dumps({'records':len(records),'all_verified':True,'key_epoch':epoch,'stats':rt.stats()},indent=2))

if __name__=='__main__':main()
