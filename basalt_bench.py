"""Basalt v0.4.1 API benchmark. Python 3.10+, standard library only."""
import argparse
import csv
import json
import random
import time
import uuid
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path


def parse_size(s):
    s = s.strip().lower()
    return int(s[:-1]) * 1024 if s.endswith('k') else int(s)


class API:
    def __init__(self, base, key, timeout):
        self.base = base.rstrip('/').removesuffix('/v1')
        self.key, self.timeout = key, timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def open(self, path, body=None):
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        if self.key:
            headers['Authorization'] = 'Bearer ' + self.key
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
        try:
            return self.opener.open(urllib.request.Request(self.base + path, data=data, headers=headers), timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f'HTTP {e.code} {path}: {e.read().decode("utf-8", "replace")[:1500]}') from e

    def get_json(self, path, body=None):
        with self.open(path, body) as r:
            return json.load(r)

    def tokenize(self, text, model):
        return self.get_json('/tokenize', {'content': text, 'parse_special': False, 'model': model})['tokens']

    def detokenize(self, tokens, model):
        return self.get_json('/detokenize', {'tokens': tokens, 'model': model})['content']


WORDS = ('scheduling simulation logistics operations inventory monitoring resources transport '
         'latency memory bandwidth performance analysis engineering validation testing software '
         'pipeline controller equipment network process event queue allocation reliability '
         'research design optimization experiment statistical data measurement system model '
         'planning warehouse routing vehicle production capacity efficiency maintenance').split()


def build_prompt(api, model, target, seed, workload):
    rng = random.Random(seed)
    # A different prefix per request minimizes KV-prefix reuse, not expert-cache reuse.
    prefix = f'Benchmark sample {seed:016x}.\n'
    task = ('\n\nWrite a detailed technical report in English about designing and validating '
            'a reliable scheduling simulation. Explain architecture, algorithms, failure modes, '
            'testing, and practical tradeoffs in continuous natural prose. Aim for at least '
            '4000 words; do not conclude prematurely.') if workload == 'prose' else (
            '\n\nWrite a long Python implementation of a scheduling simulator, including '
            'classes, event handlers, validation, tests, and detailed comments. Continue '
            'with implementation details rather than a summary.')
    # Build varied synthetic English records, then trim with the model's own tokenizer.
    n = max(32, target // 18)
    while True:
        records = []
        for i in range(n):
            a, b, c, d = rng.sample(WORDS, 4)
            records.append(f'Record {i}: The {a} team reviewed {b} and {c}; the {d} result was {rng.randrange(100,9999)}.\n')
        ids = api.tokenize(''.join(records), model)
        if len(ids) >= target:
            break
        n *= 2
    # Leave headroom for the template and the task's own tokens.
    budget = max(1, target - len(api.tokenize(prefix + task, model)) - 32)
    body = prefix + api.detokenize(ids[:budget], model) + task
    count = len(api.tokenize(body, model))
    return body, count


def benchmark(api, model, prompt, input_count, max_out, seed, temperature):
    payload = {'model': model, 'messages': [{'role': 'user', 'content': prompt}],
               'stream': True, 'stream_options': {'include_usage': True},
               'max_tokens': max_out, 'temperature': temperature, 'seed': seed % 2147483647,
               'reasoning_effort': 'none', 'enable_thinking': False}
    usage, timings, finish, text, reasoning = {}, {}, None, [], []
    first = last = None
    request_id = ''
    t0 = time.perf_counter()
    with api.open('/v1/chat/completions', payload) as response:
        request_id = response.headers.get('X-Request-Id', '')
        for line in response:
            line = line.decode('utf-8').strip()
            if not line.startswith('data:'):
                continue
            data = line[5:].strip()
            if data == '[DONE]':
                break
            obj = json.loads(data)
            if obj.get('error'):
                raise RuntimeError(str(obj['error']))
            if obj.get('usage'):
                usage.update(obj['usage'])
            if isinstance(obj.get('timings'), dict):
                timings.update(obj['timings'])
            for choice in obj.get('choices') or []:
                delta = choice.get('delta') or {}
                c = delta.get('content') or ''
                r = delta.get('reasoning_content') or delta.get('reasoning') or ''
                if isinstance(c, str) and isinstance(r, str) and (c or r):
                    now = time.perf_counter()
                    if first is None:
                        first = now
                        print(f'  First token: {first-t0:.3f} s', flush=True)
                    last = now
                    text.append(c)
                    reasoning.append(r)
                if choice.get('finish_reason'):
                    finish = choice['finish_reason']
    end = time.perf_counter()
    if first is None:
        raise RuntimeError('No text/reasoning received in SSE stream')
    pcount = usage.get('prompt_tokens')
    ocount = usage.get('completion_tokens')
    psource = 'API usage' if pcount is not None else 'tokenized user text (template excluded)'
    osource = 'API usage' if ocount is not None else 'retokenized output (estimate)'
    if pcount is None:
        pcount = input_count
    if ocount is None:
        ocount = sum(len(api.tokenize(''.join(part), model)) for part in (reasoning, text) if any(part))
    cached = (usage.get('prompt_tokens_details') or {}).get('cached_tokens')
    if cached is None:
        cached = usage.get('cached_tokens')
    ttft, decode = first-t0, last-first
    # API-observed estimates: TTFT includes queue, HTTP and tokenization;
    # last-first excludes the first output token, not necessarily one token per SSE chunk.
    return {'prompt_tokens': pcount, 'output_tokens': ocount, 'cached_tokens': cached,
            'ttft_s': round(ttft, 4), 'prefill_effective_tps': round(pcount/ttft, 2) if ttft else '',
            'decode_s': round(decode, 4), 'decode_stream_tps': round((ocount-1)/decode, 2) if decode>0 and ocount>1 else '',
            'total_s': round(end-t0, 4), 'end_to_end_output_tps': round(ocount/(end-t0), 2),
            'finish_reason': finish, 'prompt_count_source': psource, 'output_count_source': osource,
            'request_id': request_id, 'server_timings': json.dumps(timings, ensure_ascii=False),
            'raw_usage': json.dumps(usage, ensure_ascii=False)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', default='http://127.0.0.1:18511')
    p.add_argument('--api-key', default='')
    p.add_argument('--model', default=None)
    p.add_argument('--sizes', default='1k,8k,32k,64k,128k,256k,480k')
    p.add_argument('--output', type=int, default=512, help='maximum generated tokens per request')
    p.add_argument('--context', type=parse_size, default=524288)
    p.add_argument('--repeat', type=int, default=1)
    p.add_argument('--timeout', type=float, default=3600, help='socket timeout in seconds')
    p.add_argument('--temperature', type=float, default=0.7)
    p.add_argument('--workload', choices=['prose','code'], default='prose')
    p.add_argument('--no-warmup', action='store_true')
    p.add_argument('--csv', type=Path, default=None)
    args = p.parse_args()
    sizes = [parse_size(x) for x in args.sizes.split(',')]
    if args.output < 2 or args.repeat < 1 or any(n < 128 or n + args.output + 128 > args.context for n in sizes):
        p.error('Each size must be >=128 and leave room for output + 128 template tokens; output>=2, repeat>=1')
    api = API(args.base, args.api_key, args.timeout)
    models = api.get_json('/v1/models')['data']
    model = args.model or models[0]['id']
    print(f'Server: {api.base}\nModel: {model}\nWorkload: {args.workload}\nThinking: off; requests: serial', flush=True)
    if not args.no_warmup:
        print('Warm-up (excluded from CSV)', flush=True)
        seed = uuid.uuid4().int & ((1<<63)-1)
        prompt, count = build_prompt(api, model, 1024, seed, args.workload)
        benchmark(api, model, prompt, count, 64, seed, args.temperature)
    path = args.csv or Path(f'basalt_bench_{datetime.now():%Y%m%d_%H%M%S}.csv')
    rows = []
    for size in sizes:
        for run in range(1, args.repeat+1):
            seed = uuid.uuid4().int & ((1<<63)-1)
            print(f'\nTarget {size:,} tokens | run {run}/{args.repeat} | preparing prompt', flush=True)
            try:
                prompt, count = build_prompt(api, model, size, seed, args.workload)
                print(f'  User prompt: {count:,} tokens; sending request...', flush=True)
                row = benchmark(api, model, prompt, count, args.output, seed, args.temperature)
                row = {'target_tokens':size, 'run':run, 'seed':seed, 'model':model, 'workload':args.workload, **row}
                rows.append(row)
                print(f"  Prompt={row['prompt_tokens']:,}  Output={row['output_tokens']:,}  Cached={row['cached_tokens']}  Finish={row['finish_reason']}")
                print(f"  Prefill(effective)={row['prefill_effective_tps']} t/s  Decode(stream)={row['decode_stream_tps']} t/s  Total={row['total_s']} s", flush=True)
                if row['cached_tokens'] and row['cached_tokens'] > 32:
                    print('  WARNING: cached prefix detected; not a clean full-prefill result.')
                if row['output_tokens'] < args.output * .8:
                    print('  NOTE: short output; decode result may be noisy.')
                with path.open('w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                    writer.writeheader(); writer.writerows(rows)
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                print(f'  FAILED: {e}\n  Stopping sweep to avoid continuing after a failed request.', flush=True)
                if rows:
                    print(f'Partial results: {path.resolve()}')
                return 1
    print('\nSummary (client-observed rates)')
    print(f'{"Prompt":>10} {"Output":>8} {"TTFT(s)":>10} {"Prefill t/s":>13} {"Decode t/s":>13} {"Total(s)":>10}')
    for r in rows:
        print(f"{r['prompt_tokens']:>10} {r['output_tokens']:>8} {r['ttft_s']:>10} {r['prefill_effective_tps']:>13} {r['decode_stream_tps']:>13} {r['total_s']:>10}")
    print(f'CSV: {path.resolve()}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nInterrupted. Completed rows already saved.')
        raise SystemExit(130)
