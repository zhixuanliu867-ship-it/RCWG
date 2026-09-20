"""Windows operation entry; WSL only orchestrates/executes, never obtains tokens."""
import argparse,os,subprocess
def main():
    if os.name!='nt':raise SystemExit('Windows entry required')
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','live'])
    p.add_argument('--prepared',required=True);p.add_argument('--host-binding');p.add_argument('--approval')
    p.add_argument('--offline-acceptance');p.add_argument('--windows-acceptance');p.add_argument('--ack-paid-model-requests',action='store_true');a=p.parse_args()
    cmd=['wsl.exe','-d','Ubuntu','--cd','/home/zhixuan/projects/RCWG','--exec','/home/zhixuan/.local/bin/uv',
         'run','--offline','--frozen','--python','3.12.14','python','-m','rcwg_api']
    if a.phase=='prepare':
        if not a.host_binding:p.error('--host-binding required')
        cmd+=['prepare-windows-user','--host-binding',a.host_binding,'--output',a.prepared]
    else:
        if not all([a.approval,a.offline_acceptance,a.windows_acceptance,a.ack_paid_model_requests]):p.error('explicit approval and both acceptance paths required')
        cmd+=['live','--prepared',a.prepared,'--approval',a.approval,'--offline-acceptance',a.offline_acceptance,
              '--windows-acceptance',a.windows_acceptance,'--ack-paid-model-requests']
    return subprocess.run(cmd,check=False).returncode
if __name__=='__main__':raise SystemExit(main())
