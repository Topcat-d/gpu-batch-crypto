"""SPDX-License-Identifier: Apache-2.0. Fresh public-runtime benchmark matrix.
Every output is checked; validation and input generation are outside timing.
CPU is a single-thread cryptography/OpenSSL + hashlib baseline with cached keys.
"""
import argparse
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import time
from datetime import datetime,timezone
from pathlib import Path
import cryptography
from cryptography.hazmat.backends.openssl.backend import backend as openssl
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec,utils
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from batchcrypto import Runtime,Record,ORDER,generate_p256_key

ROOT=Path(__file__).resolve().parents[1]
def command(args):return subprocess.check_output(args,cwd=ROOT,text=True,stderr=subprocess.STDOUT).strip()
def cpu_model():
    if os.name=='nt':
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as k:return winreg.QueryValueEx(k,'ProcessorNameString')[0].strip()
    return platform.processor()
def main():
    p=argparse.ArgumentParser();p.add_argument('--library',required=True);p.add_argument('--build-dir',default='build');p.add_argument('--device',type=int,default=0);p.add_argument('--iterations',type=int,default=3);p.add_argument('--output',required=True)
    p.add_argument('--sizes',default='16,512,1024,4096,16384,65536,262144,1048576');p.add_argument('--batches',default='1,8,64,256');a=p.parse_args()
    if a.iterations<2:p.error('at least two measured iterations required')
    sizes=list(map(int,a.sizes.split(',')));batches=list(map(int,a.batches.split(',')))
    if any(not 0<=s<=1048576 for s in sizes) or any(not 1<=n<=4096 for n in batches):p.error('size/batch outside API bounds')
    commit=command(['git','rev-parse','HEAD'])
    if command(['git','diff','--name-only','HEAD']):raise RuntimeError('commit tracked source changes before benchmarking')
    tracked=command(['git','ls-files']).splitlines()
    source_hashes={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in tracked if f.endswith(('.py','.cu','.cuh','.h')) or f in ('CMakeLists.txt','pyproject.toml')}
    cache=Path(a.build_dir,'CMakeCache.txt').read_text()
    compiler=re.search(r'CMAKE_CUDA_COMPILER:FILEPATH=(.+)',cache)
    cuda_version=command([compiler[1].strip(),'--version']) if compiler else 'unavailable'
    config=[]
    for f in Path(a.build_dir,'CMakeFiles').glob('*/CMake*Compiler.cmake'):
        config.extend(re.findall(r'set\(CMAKE_(?:CXX|CUDA)_COMPILER_(?:ID|VERSION) [^\n]+',f.read_text()))
    aes_key=os.urandom(32);sk=generate_p256_key();cpu_aes=AESGCM(aes_key);cpu_signer=ec.derive_private_key(int.from_bytes(sk,'big'),ec.SECP256R1())
    def cpu_sign(ds):
        result=[]
        for digest in ds:
            r,s=utils.decode_dss_signature(cpu_signer.sign(digest,ec.ECDSA(utils.Prehashed(hashes.SHA256()),deterministic_signing=True)))
            result.append(r.to_bytes(32,'big')+min(s,ORDER-s).to_bytes(32,'big'))
        return result
    rows=[];nonce_counter=0
    with Runtime(a.library,a.device) as rt:
        rt.load_key(0,aes_key);rt.load_key(1,sk,'p256')
        cells=[(op,size,n) for op in ('aes256gcm_seal','aes256gcm_open','sha256') for size in sizes for n in batches]+[('p256_sign',32,n) for n in sorted(set(batches+[1024,4096]))]
        for op,size,n in cells:
            work=n*((2*size+16+12) if op.startswith('aes') else size+32)
            if work>64*1024*1024:
                rows.append({'operation':op,'payload_bytes':size,'batch':n,'status':'unsupported','reason':'64 MiB working-data limit'});continue
            timings={'cpu':[],'cuda':[]};checked=0
            for trial in range(a.iterations+1):
                data=[os.urandom(size) for _ in range(n)]
                records=[Record((nonce_counter+i).to_bytes(12,'big'),m,b'benchmark-v1') for i,m in enumerate(data)];nonce_counter+=n
                if op=='aes256gcm_seal':
                    cpu=lambda:[cpu_aes.encrypt(r.nonce,r.data,r.aad) for r in records];gpu=lambda:rt.seal(0,records)
                elif op=='aes256gcm_open':
                    sealed=[Record(r.nonce,cpu_aes.encrypt(r.nonce,r.data,r.aad),r.aad) for r in records]
                    cpu=lambda:[cpu_aes.decrypt(r.nonce,r.data,r.aad) for r in sealed];gpu=lambda:rt.open(0,sealed)
                elif op=='sha256':cpu=lambda:[hashlib.sha256(m).digest() for m in data];gpu=lambda:rt.sha256(data)
                else:cpu=lambda:cpu_sign(data);gpu=lambda:rt.sign(1,data)
                results={}
                # Alternate order to reduce systematic warm-cache/order bias.
                order=(('cpu',cpu),('cuda',gpu)) if trial%2 else (('cuda',gpu),('cpu',cpu))
                for name,fn in order:
                    start=time.perf_counter_ns();results[name]=fn();elapsed=(time.perf_counter_ns()-start)/1e9
                    if trial:timings[name].append(elapsed)
                if results['cuda']!=results['cpu']:raise RuntimeError(f'correctness mismatch: {op}/{size}/{n}')
                if rt.last_report['completed']!=n or rt.last_report['errors']:raise RuntimeError('accounting failure')
                if trial:checked+=n
            for name,times in timings.items():
                total=sum(times);row={'operation':op,'backend':name,'payload_bytes':size,'aad_bytes':12 if op.startswith('aes') else 0,'batch':n,'iterations':a.iterations,'total_operations':n*a.iterations,'total_seconds':total,'batch_seconds':times,'median_batch_ms':statistics.median(times)*1000,'ops_per_second':n*a.iterations/total,'plaintext_bytes_per_second':n*a.iterations*size/total if op.startswith('aes') else None,'input_bytes_per_second':n*a.iterations*size/total,'correctness':'all measured outputs match independent CPU result','outputs_checked':checked,'status':'ok'};rows.append(row)
            print(f'{op} bytes={size} batch={n} checked={checked}',flush=True)
        stats=rt.stats()
    metadata={'commit':commit,'tracked_source_clean':True,'source_sha256':source_hashes,'timestamp_utc':datetime.now(timezone.utc).isoformat(),'gpu':command(['nvidia-smi',f'--id={a.device}','--query-gpu=name,driver_version,memory.total','--format=csv,noheader']),'device':a.device,'cuda_compiler':cuda_version,'compiler_configuration':config,'architectures':re.findall(r'CMAKE_CUDA_ARCHITECTURES:[^=]+=(.+)',cache),'build_configuration':'Release','cpu':cpu_model(),'platform':platform.platform(),'python':platform.python_version(),'cryptography':cryptography.__version__,'openssl':openssl.openssl_version_text(),'library_version':'0.1.0-preview','library_sha256':hashlib.sha256(Path(a.library).read_bytes()).hexdigest(),'timing_scope':'synchronous API calls; CUDA includes Python packing, host/device transfers, stream synchronization, output copies and temporary-buffer clearing; excludes key import, data generation and oracle comparisons; buffers reused after warmup','cpu_scope':'single Python thread; cached cryptography/OpenSSL AES and P-256 keys, hashlib SHA-256; not a tuned multi-core native CPU engine','warmup_calls_per_cell':1,'latency_note':'batch completion times under saturation; not request p99 or an arrival-process experiment','runtime_stats':stats}
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    Path(a.output).write_text(json.dumps({'metadata':metadata,'rows':rows},indent=2)+'\n')

if __name__=='__main__':main()
