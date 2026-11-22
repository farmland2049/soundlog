"""Run the installed Codex CLI for one Soundlog button action."""

import json
from pathlib import Path
import shutil
import subprocess

from . import product_view


def pending_questions(pipeline):
    return sum(
        not (request.parent / 'answer.json').exists()
        for request in (pipeline.home / 'questions').glob('question-*/request.json')
    )


def run_codex(pipeline, prompt):
    candidates = [shutil.which('codex'), Path.home() / '.local/bin/codex']
    executable = next((path for item in candidates if item and (path := shutil.which(str(item)))), None)
    if executable is None:
        raise RuntimeError('找不到本机 Codex CLI')

    with (pipeline.home / 'agent-cli.log').open('ab') as log:
        result = subprocess.run(
            [executable, '-a', 'never', 'exec', '--sandbox', 'workspace-write', '--json', '-'],
            cwd=pipeline.root, input=prompt, text=True, stdout=log, stderr=subprocess.STDOUT,
        )
    if result.returncode:
        raise RuntimeError(f'Codex CLI 退出码 {result.returncode}。详见 agent-cli.log')


def verify_completion(pipeline, prior_state):
    with pipeline.lock():
        current = pipeline.state()
        if current['state'] != 'idle' or pipeline.inventory() or pending_questions(pipeline):
            raise RuntimeError('Agent 已退出，管线仍有待处理工作')
        published = current.get('lastBundle')
        if not published:
            return current
        catalog = product_view.delivery_days(pipeline.delivery)
        previous_days = prior_state.get('deliveryDays')
        expected = {date: bundle for date, bundle in catalog.items()
                    if previous_days is not None and previous_days.get(date) != bundle}
        previous_bundle = prior_state.get('lastBundle')
        if published != previous_bundle or prior_state['state'] == 'awaiting_enrichment':
            receipt = json.loads((pipeline.delivery/published/'receipt.json').read_text())
            if receipt['state'] != 'completed' or receipt['bundle'] != published or not receipt['days']:
                raise ValueError('本批日交付回执无效')
            for date in receipt['days']:
                if catalog.get(date) != published:
                    raise ValueError(f'{date} 的目录未指向本批交付包')
                expected[date] = published
        if prior_state['state'] == 'awaiting_enrichment':
            for date, bundle in (previous_days or {}).items():
                if bundle == previous_bundle:
                    if date not in catalog:
                        raise ValueError(f'{date} 的交付已从目录缺失')
                    expected[date] = catalog[date]
        # Verify existing bindings before carrying old activities forward.
        product_view.results(pipeline)
        missing = product_view.missing_delivery_days(pipeline, expected)
        if missing:
            product_view.publish_reviewed_scenes(pipeline, missing)
            product_view.results(pipeline)
            missing = product_view.missing_delivery_days(pipeline, expected)
            if missing:
                raise RuntimeError('成果页未覆盖本批日期：' + '、'.join(sorted(missing)))
        return current
