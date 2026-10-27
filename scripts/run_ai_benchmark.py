"""Capture synthetic results and host VRAM while the isolated provider runs."""
import json
import subprocess
import time
from pathlib import Path


def memory():
    output=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,memory.free','--format=csv,noheader,nounits'],text=True,timeout=5)
    return [int(v.strip()) for v in output.splitlines()[0].split(',')]


root=Path(__file__).resolve().parents[1]
before=memory();samples=[]
with (root/'.build-ai-benchmark.jsonl').open('w',encoding='utf-8') as results:
    process=subprocess.Popen(['wsl','-d','Ubuntu','--','docker','compose','exec','-T','worker','python','-'],stdin=subprocess.PIPE,stdout=results,stderr=subprocess.PIPE,text=True)
    process.stdin.write((root/'scripts/check_inference.py').read_text(encoding='utf-8'));process.stdin.close()
    while process.poll() is None:
        samples.append(memory());time.sleep(.5)
    error=process.stderr.read()
    if process.returncode: raise RuntimeError('Benchmark process failed: '+error[:300])
after=memory()
report=dict(baseline_used_mib=before[0],peak_used_mib=max(s[0] for s in samples),minimum_free_mib=min(s[1] for s in samples),after_used_mib=after[0],sample_count=len(samples),scope='Host GPU includes other applications; sampled, not a hard VRAM guarantee')
(root/'.build-ai-gpu.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
print((root/'.build-ai-benchmark.jsonl').read_text(encoding='utf-8'))
