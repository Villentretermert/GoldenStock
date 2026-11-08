"""Shared resource decisions for tasks, batches and blind experiments."""
import json


def device_choice(base,*,group=False):
    from goldenstock.ui import form
    scope='all queued and waiting parts' if group else 'this task'
    return ('<div class="notice" id="device-choice"><h2>Choose how to continue</h2>'
        '<p>The GPU run could not proceed with a verified 3 GiB reserve. '
        'CPU is slower and uses system memory. No automatic switch has occurred.</p>'
        f'<p>Your choice applies to {scope}. Completed and running parts stay unchanged.</p>'
        +form(base+'/use-cpu','Run on CPU')+form(base+'/check-gpu','Check GPU again')+'</div>')


def execution_cards(executions):
    from goldenstock.ui import e
    body=''
    for row in executions:
        body+=(f'<details class="card"><summary>Attempt {row["attempt"]} · '
            f'{e(row.get("requested_device","unknown").upper())} · {e(row["state"])} · '
            f'{e(row.get("seconds","unknown"))} seconds</summary>'
            '<p>Time covers admission, loading, inference and cleanup; queue wait is excluded. '
            'Memory samples are observations, not an exclusive GPU reservation.</p>'
            '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+e(json.dumps(row,indent=2))+'</pre></details>')
    return body
