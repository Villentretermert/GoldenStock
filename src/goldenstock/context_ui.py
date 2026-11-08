"""Render added context separately from the primary numeric evidence."""
def context_cards(window, job_id):
    from goldenstock.ui import e
    if 'context' not in window:
        return ''
    body='<h3>Added nearby context</h3><p>These are separate source excerpts, not confirmed facts. Check that their period and scale apply to the selected values.</p>'
    if not window['context']:
        body+='<p>No additional context fits this window, or the nearby text is already included.</p>'
    for entry in window['context']:
        body+=f'<article class="card"><p>Original page {entry["page"]} · {e(entry["role"])} · {e(entry["method"])}</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{e(entry["text"])}</pre><p>'
        for index, source in enumerate(entry['sources'],1):
            a,b=source['source_range']
            body+=f'<a href="/normalize/{e(job_id)}/{source["item_index"]}">Context source {index} · characters {a+1}–{b}</a> '
        body+='</p></article>'
    if window.get('context_omitted'):
        body+=f'<p>{window["context_omitted"]} nearby excerpts exceeded the context budget. Inspect the original for missing context.</p>'
    return body
