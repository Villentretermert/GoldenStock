"""Inspect actual bindings: some Compose versions print ':0' for EXPOSE-only ports."""
import json
import subprocess


def inspect(service):
    container=subprocess.check_output(['docker','compose','ps','-q',service],text=True).strip()
    if not container: raise RuntimeError(f'{service} is not running')
    # Inspect output includes configuration; keep it in memory and never print it.
    return json.loads(subprocess.check_output(['docker','inspect',container],text=True))[0]


def main():
    for service in ('db','worker','monitor'):
        data=inspect(service)
        if any((data['HostConfig'].get('PortBindings') or {}).values()):
            raise RuntimeError(f'{service} publishes a host port')
        if service=='worker':
            networks=list(data['NetworkSettings']['Networks'])
            if len(networks)!=1 or not networks[0].endswith('_private'):
                raise RuntimeError('File worker must stay on the private network')
        if service=='monitor' and data['Mounts']:
            raise RuntimeError('Monitor must not mount uploaded files or host directories')
    published = inspect('web')['HostConfig'].get('PortBindings') or {}
    if set(published) != {'8080/tcp'} or not published['8080/tcp'] or any(
            binding.get('HostIp') not in ('127.0.0.1','::1') for binding in published['8080/tcp']):
        raise RuntimeError('Web backend must publish only its loopback port')
    inference = subprocess.check_output(['docker','compose','--profile','ai','ps','-q','inference'],text=True).strip()
    if inference:
        data = json.loads(subprocess.check_output(['docker','inspect',inference],text=True))[0]
        networks = list(data['NetworkSettings']['Networks'])
        if any((data['HostConfig'].get('PortBindings') or {}).values()) or len(networks)!=1 or not networks[0].endswith('_private'):
            raise RuntimeError('Inference must stay private')
    print('Container isolation PASS: loopback web, private file worker and inference, no monitor data mounts or host ports.')


if __name__=='__main__': main()
