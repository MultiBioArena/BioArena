"""Install only Bio Arena user services; render and verify before enabling."""
import argparse
import os
from pathlib import Path
import subprocess


def quoted(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--enable',action='store_true');args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];generated=root/'output/service-units';generated.mkdir(parents=True,exist_ok=True)
    destination=Path.home()/'.config/systemd/user';destination.mkdir(parents=True,exist_ok=True)
    python=quoted(root/'.venv/bin/python');cwd=str(root).replace('%','%%')
    common=f'WorkingDirectory={cwd}\nEnvironment=OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1\n'
    units={}
    def service(name,description,command,extra='',oneshot=False):
        units[name]=f'# Bio Arena managed root: {root}\n[Unit]\nDescription={description}\nStartLimitIntervalSec=600\nStartLimitBurst=3\n\n[Service]\nType={"oneshot" if oneshot else "simple"}\n'+common+f'ExecStart={command}\n'+extra+'\n[Install]\nWantedBy=default.target\n'
    service('bio-arena.service','Bio Arena persistent paper simulation',f'{python} {quoted(root/"scripts/serve_resilient.py")}',
            'Restart=on-failure\nRestartPreventExitStatus=2\nRestartSec=10\nTimeoutStopSec=30\nKillMode=mixed\n')
    service('bio-arena-monitor.service','Bio Arena local health and learning reports',f'{python} {quoted(root/"scripts/monitor_paper.py")} --watch','Restart=on-failure\nRestartSec=15\n')
    service('bio-arena-market.service','Bio Arena read-only market display',f'{quoted(root/".venv/bin/uvicorn")} bio_arena.market_board:app --host 0.0.0.0 --port 8142',
            'Restart=on-failure\nRestartSec=15\n')
    service('bio-arena-archive.service','Bio Arena verified cold-run archives',f'{python} {quoted(root/"scripts/archive_runs.py")} --prune-verified',oneshot=True)
    service('bio-arena-comparison.service','Bio Arena independent-seed paper comparison',f'{python} {quoted(root/"scripts/scheduled_comparison.py")}',
            'Nice=10\nCPUQuota=100%\nTimeoutStartSec=2700\n',oneshot=True)
    flow_config=root/'.private/capital-flows.json'
    if flow_config.exists():
        service('bio-arena-flows.service','Bio Arena read-only configured ERC-20 scanning',
                f'{python} {quoted(root/"scripts/scan_capital_flows.py")} --config {quoted(flow_config)} '
                f'--database {quoted(root/".private/capital-flows.sqlite")} --output {quoted(root/".private/capital-flow-status.json")} --span 1000',
                'TimeoutStartSec=180\nUMask=0077\n',oneshot=True)
        units['bio-arena-flows.timer']=f'# Bio Arena managed root: {root}\n[Unit]\nDescription=Bio Arena confirmed transfer polling\n[Timer]\nOnBootSec=30\nOnUnitInactiveSec=30\n[Install]\nWantedBy=timers.target\n'
    desktop=root/'scripts/fomo_login_desktop.py'
    if desktop.exists():
        service('bio-arena-desktop@.service','Bio Arena persistent account browser',f'{python} {quoted(desktop)} --account %i',
            'Restart=on-failure\nRestartSec=30\nTimeoutStopSec=45\nKillMode=mixed\n')
    for kind,calendar in [('archive','daily'),('comparison','*-*-* 00,06,12,18:00:00')]:
        units[f'bio-arena-{kind}.timer']=f'# Bio Arena managed root: {root}\n[Unit]\nDescription=Bio Arena {kind} schedule\n[Timer]\nOnCalendar={calendar}\nPersistent=true\nRandomizedDelaySec=120\n[Install]\nWantedBy=timers.target\n'
    for name,text in units.items():
        target=destination/name
        if target.exists() and f'# Bio Arena managed root: {root}' not in target.read_text():raise ValueError('An unrelated service already uses this name')
        (generated/name).write_text(text)
    subprocess.run(['systemd-analyze','--user','verify',*[str(generated/name) for name in units]],check=True)
    for name in units:
        target=destination/name
        if target.is_symlink():target.unlink()
        elif target.exists():raise ValueError('Refusing to replace a manually installed unit file')
        target.symlink_to(generated/name)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    if args.enable:
        names=[n for n in units if n.endswith('.timer') or n in ('bio-arena.service','bio-arena-monitor.service','bio-arena-market.service')]
        if desktop.exists():names += [f'bio-arena-desktop@{i}.service' for i in (1,2,3)]
        subprocess.run(['systemctl','--user','enable',*names],check=True)
    print('Bio Arena units verified and installed. Starting services is a separate controlled transition.')


if __name__=='__main__':main()
